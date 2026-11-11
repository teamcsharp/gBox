"""Learning from a recorded play session: gameplay-memory pad events become a mission the bot can replay.

The archive's real shape is used (`{"kind": "pad", "at": ..., "payload": {"events": [...], "stick": {...}, "rstick": {...}}}`), and the
mission it produces is fed through the same `imitate.learn` the plane's autoplay uses - so this test covers the join that was missing,
not a re-implementation of it.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from gbox import imitate, pso_learn_play as LP                       # noqa: E402

GID = "436e0bb84d5337d1"


def pad(at: float, keys=(), stick=(0.0, 0.0), rstick=(0.0, 0.0)) -> dict:
    return {"kind": "pad", "at": at, "payload": {
        "events": [{"key": k, "down": True} for k in keys], "stick": {"x": stick[0], "y": stick[1]},
        "rstick": {"x": rstick[0], "y": rstick[1]}}}


def test_timeline_converts_pad_events_and_ignores_the_rest():
    events = [
        {"kind": "mod_action", "at": 10.0, "payload": {}},
        pad(20.0, ("start",)),
        pad(21.0, stick=(0.0, -0.8)),
        pad(22.0, rstick=(-0.5, 0.0)),
        pad(24.0),
    ]
    rows = LP.timeline(events)
    assert rows[0] == (0.0, frozenset({"start"}))                    # seconds are relative to the first pad event
    assert rows[1][1] == frozenset({"up"})                            # stick y -0.8 is up
    assert rows[2][1] == frozenset({"cleft"})                         # right-stick x -0.5 is the C-stick left
    assert rows[3] == (4.0, frozenset())


def test_a_learned_session_becomes_a_mission_with_the_recorded_timing():
    # three presses of START with gaps, then a stick push: the kind of shape a real boot has
    events = [pad(float(t), keys, stick) for t, keys, stick in (
        (100.0, ("start",), (0.0, 0.0)),
        (100.6, (), (0.0, 0.0)),
        (101.4, ("a",), (0.0, 0.0)),
        (102.0, (), (0.0, 0.0)),
        (103.2, (), (0.0, -0.9)),
    )]
    mission, learned = LP.from_events(events, game_id=GID, name="pso-learned-run", run="run-1")
    assert mission["game_id"] == GID
    assert mission["policy"] == "learned-from-operator"
    assert mission["provenance"]["run"] == "run-1"
    assert mission["provenance"]["bursts"] == len(learned["bursts"])
    kinds = [step["op"] for step in mission["steps"]]
    assert "press" in kinds and "wait" in kinds
    presses = [step["key"] for step in mission["steps"] if step["op"] == "press"]
    assert "start" in presses or "a" in presses
    waits = [step["secs"] for step in mission["steps"] if step["op"] == "wait"]
    assert all(w >= 0 for w in waits)


def test_the_mission_is_replayable_by_the_autoplay_step_vocabulary():
    events = [pad(0.0, ("start",)), pad(1.0, ("ddown",)), pad(2.0, ("start",))]
    mission, _learned = LP.from_events(events, game_id=GID, name="pso-learned-mini")
    allowed = {"press", "wait", "navigate", "interact", "fight", "key", "keyup", "keydown", "cancel"}
    assert all(step["op"] in allowed for step in mission["steps"])
    for step in mission["steps"]:
        if step["op"] == "press":
            assert step["key"] and step["n"] >= 1
        if step["op"] == "wait":
            assert 0 <= step["secs"] <= 10


def test_a_run_without_pad_events_is_refused_rather_than_invented():
    with pytest.raises(ValueError):
        LP.from_events([{"kind": "mod_action", "at": 1.0, "payload": {}}], game_id=GID, name="x")


def test_the_learned_style_is_the_plane_learners_own_output():
    events = [pad(float(i), ("start",) if i % 2 == 0 else ()) for i in range(6)]
    rows = LP.timeline(events)
    assert LP.learn(rows) == imitate.learn(rows)


def test_mission_saves_next_to_the_plane_missions(tmp_path):
    events = [pad(0.0, ("start",)), pad(1.0, ("a",))]
    mission, _ = LP.from_events(events, game_id=GID, name="pso-learned-save")
    path = LP.save(mission, tmp_path)
    assert path.is_file() and path.name == "pso-learned-save.json"
    import json
    assert json.loads(path.read_text())["name"] == "pso-learned-save"
