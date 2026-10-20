"""Autoplay from the operator's recorded play (gbox.imitate) and the autoplay tool's modes, chaining and pad chord."""
import random
import threading
from types import SimpleNamespace

import pytest

from gbox import imitate, padstate


def pad(at, events=(), stick=None, i=[0]):
    i[0] += 1
    return {"id": i[0], "kind": "pad", "at": at,
            "payload": {"events": [{"key": k, "down": d} for k, d in events], "stick": stick or {"x": 0, "y": 0},
                        "rstick": {"x": 0, "y": 0}}}


def test_held_timeline_names_buttons_for_each_emulator():
    ev = [pad(1.0, [("b", True)], {"x": 0.9, "y": 0}), pad(1.1, [("b", False), ("up", True)]),
          {"id": 99, "kind": "mod_action", "at": 1.2, "payload": {}}]
    assert imitate.held_timeline(ev, "retroarch", "dreamcast") == [(1.0, frozenset({"b", "lright"})), (1.1, frozenset({"up"}))]
    # Dolphin on Windows: GameCube keyboard names (Xbox A = RetroPad b = GC A), main stick = arrows, D-pad = t/g/f/h
    assert imitate.held_timeline(ev, "dolphin", "gamecube") == [(1.0, frozenset({"a", "right"})), (1.1, frozenset({"t"}))]


def test_replay_plan_keeps_timing_from_boot_and_caps_idle_gaps():
    tl = [(103.0, frozenset({"start"})), (103.2, frozenset()), (200.0, frozenset({"a"})), (200.1, frozenset({"a"})),
          (200.3, frozenset())]
    plan = imitate.replay_plan(tl, 100.0, idle_cap=20)
    assert plan[0] == (3.0, [{"key": "start", "down": True}])
    assert plan[1] == (3.2, [{"key": "start", "down": False}])
    assert plan[2][0] == pytest.approx(23.2)                  # 96.8 s away from the pad played as 20 s
    assert [r for _, rows in plan for r in rows][-1] == {"key": "a", "down": False}
    assert len(plan) == 4                                      # an unchanged report sends nothing


def test_replay_plan_releases_before_pressing_and_lets_go_at_the_end():
    plan = imitate.replay_plan([(1.0, frozenset({"lleft"})), (1.5, frozenset({"lright"}))], 0.0)
    assert plan[1][1] == [{"key": "lleft", "down": False}, {"key": "lright", "down": True}]
    assert plan[-1][1] == [{"key": "lright", "down": False}]


def test_pick_run_prefers_the_newest_real_run_on_the_same_emulator():
    runs = [{"id": "poke", "adapter": "dolphin", "updated": 9, "events": {"pad": 30}},
            {"id": "old", "adapter": "dolphin", "updated": 1, "events": {"pad": 900}},
            {"id": "ra", "adapter": "retroarch", "updated": 5, "events": {"pad": 900}},
            {"id": "new", "adapter": "dolphin", "updated": 3, "events": {"pad": 500}}]
    assert imitate.pick_run(runs, "dolphin")["id"] == "new"
    assert imitate.pick_run(runs, "retroarch")["id"] == "ra"
    assert imitate.pick_run(runs, "mame")["id"] == "ra"         # no run on this emulator: the newest real run
    assert imitate.pick_run(runs, "dolphin", "poke")["id"] == "poke"
    assert imitate.pick_run([runs[0]], "dolphin") is None


def test_bursts_split_on_idle_and_cut_long_holds_into_moves():
    f = frozenset
    tl = [(0.0, f({"x"})), (0.1, f()), (0.2, f({"x"})), (0.3, f()),       # 0.1 s apart: one burst (a double tap)
          (1.0, f({"lright"})), (1.5, f({"lright", "x", "start"})), (3.2, f({"lright"})), (3.3, f())]
    out = imitate.bursts(tl)
    assert [start for start, _ in out] == [0.0, 1.0, 3.2]
    assert out[0][1] == [(0.0, f({"x"})), (0.1, f()), (0.2, f({"x"})), (0.3, f())]
    assert out[1][1] == [(0.0, f({"lright"})), (0.5, f({"lright", "x"})), (2.2, f())]   # start never learned; cut at 2 s
    assert out[2][1] == [(0.0, f({"lright"})), (0.1, f())]


def test_learn_counts_moves_follow_ups_and_gaps():
    f = frozenset
    tl = []
    for t in (0.0, 1.0, 2.0):                                   # x, then down+b, three times
        tl += [(t, f({"x"})), (t + 0.1, f()), (t + 0.5, f({"down", "b"})), (t + 0.7, f())]
    m = imitate.learn(tl)
    assert m["total"] == 6 and len(m["bursts"]) == 2
    assert [b["n"] for b in m["bursts"]] == [3, 3]
    assert m["follows"] == {"0": {1: 3}, "1": {0: 2}}
    assert m["gaps"] == [0.4, 0.3, 0.4, 0.3, 0.4]


def test_style_follows_the_operators_order_and_play_style_lets_go():
    m = {"bursts": [{"steps": [[0, ["x"]], [0.1, []]], "n": 1}, {"steps": [[0, ["lright"]], [0.2, ["lright", "a"]], [0.3, []]], "n": 1}],
         "follows": {"0": {"1": 5}, "1": {"0": 5}}, "gaps": [0.1], "total": 2}
    st = imitate.Style(m, random.Random(1))
    sent, slept = [], []
    n = imitate.play_style(st, send=sent.append, stopped=lambda: False, sleep=slept.append, limit=4)
    assert n == 4
    held = set()
    for rows in sent:
        for r in rows:
            held.add(r["key"]) if r["down"] else held.discard(r["key"])
    assert held == set()                                        # nothing left held
    assert all(r["key"] not in imitate.NO_LEARN for rows in sent for r in rows)


def test_play_plan_skips_what_already_passed_and_stops_on_takeover():
    now = [0.0]
    clock = lambda: now[0]
    def sleep(s): now[0] += max(s, 0.01)
    plan = [(1.0, ["a"]), (2.0, ["b"]), (5.0, ["c"])]
    sent = []
    out = imitate.play_plan(plan, send=sent.append, stopped=lambda: now[0] > 2, clock=clock, sleep=sleep, offset=1.5)
    assert sent == [["b"]] and out["completed"] is False


def test_chord_starts_without_counting_as_a_touch(monkeypatch):
    sid = "s-chord"
    padstate.PLAYER_TOUCH.pop(sid, None)
    fire, ch = padstate.chord_step(sid, set(), {"select"}, False, False)
    assert not fire and not ch and padstate.PLAYER_TOUCH[sid]   # Select alone is a touch (hands control back)
    padstate.PLAYER_TOUCH[sid] = 0
    fire, ch = padstate.chord_step(sid, {"select"}, {"select", "b"}, False, ch)
    assert fire and ch and padstate.PLAYER_TOUCH[sid] == 0       # Select+A: the chord, not a touch
    fire, ch = padstate.chord_step(sid, {"select", "b"}, {"select"}, False, ch)
    assert not fire and ch and padstate.PLAYER_TOUCH[sid] == 0   # letting go of the chord isn't a touch either
    fire, ch = padstate.chord_step(sid, {"select"}, set(), False, ch)
    assert not ch and padstate.PLAYER_TOUCH[sid] == 0
    fire, ch = padstate.chord_step(sid, set(), {"x"}, False, ch)
    assert not fire and padstate.touched_after(sid, 1)         # real play afterwards is a touch


# --- the autoplay tool ---

class FakeDriver:
    runs = []

    def __init__(self, *a, **k):
        self.stopped, self.trace = False, []

    def run_mission(self, m, **k):
        FakeDriver.runs.append(m["name"])
        return {"ok": True}


@pytest.fixture
def ap(monkeypatch, tmp_path):
    from gbox import tools, autoplay as apmod
    FakeDriver.runs = []
    monkeypatch.setattr(apmod, "Driver", FakeDriver)
    sess = [{"session_id": "s1", "game_id": "g1", "started": 0}]
    monkeypatch.setattr(tools.httpx, "get", lambda *a, **k: SimpleNamespace(json=lambda: sess, raise_for_status=lambda: None))
    sent = []
    ad = SimpleNamespace(name="retroarch", supported={"send_input"}, send_input=sent.append, reset=lambda: sent.append("reset"))
    monkeypatch.setitem(tools.SESSIONS, "s1", (ad, {"platform": "dreamcast", "title": "T"}))
    monkeypatch.setattr(tools, "AUTOPLAY", {})
    ctx = SimpleNamespace(server="http://x", headers={"authorization": "Bearer t"}, config=SimpleNamespace(runtime=tmp_path))
    return SimpleNamespace(tools=tools, ctx=ctx, sent=sent, sess=sess)


def test_missions_chain_through_then(ap, monkeypatch):
    t = ap.tools
    monkeypatch.setattr(t, "_missions", lambda game_id=None: [{"name": "m1", "then": "m2"}, {"name": "m2"}])
    r = t.autoplay(t.AutoplayIn(session_id="s1", op="start", mission="m1", mode="mission"), ap.ctx)["result"]
    assert r["started"] == "m1"
    t.AUTOPLAY["s1"]["thread"].join(5)
    assert FakeDriver.runs == ["m1", "m2"]                      # the chain used to stop after the first mission
    assert t.AUTOPLAY["s1"]["ended"]


def test_learned_mode_needs_enough_play_then_plays_it(ap, monkeypatch):
    t = ap.tools
    monkeypatch.setattr(t, "LEARNED", {})
    monkeypatch.setattr(t, "_recorded_play", lambda ctx, gid: [{"id": "r1", "events": {"pad": 50}, "adapter": "retroarch"}])
    few = [pad(1.0, [("x", True)]), pad(1.1, [("x", False)])]
    monkeypatch.setattr(t, "_run_events", lambda ctx, rid: few)
    with pytest.raises(ValueError, match="bursts recorded"):
        t.autoplay(t.AutoplayIn(session_id="s1", op="start", mode="learned"), ap.ctx)
    many = []
    for i in range(30):
        many += [pad(i, [("x", True)], {"x": 0.9, "y": 0}), pad(i + 0.1, [("x", False)])]
    t.LEARNED.clear()
    monkeypatch.setattr(t, "_run_events", lambda ctx, rid: many)
    stop = threading.Event()
    monkeypatch.setattr(t.time, "sleep", lambda s: stop.wait(0.001))
    r = t.autoplay(t.AutoplayIn(session_id="s1", op="start", mode="learned"), ap.ctx)["result"]
    assert r["mode"] == "learned"
    run = t.AUTOPLAY["s1"]
    for _ in range(200):
        if ap.sent:
            break
        stop.wait(0.01)
    run["driver"].stopped = True
    run["thread"].join(5)
    keys = {e["key"] for rows in ap.sent if isinstance(rows, list) for e in rows}
    assert {"x", "lright"} <= keys


def test_auto_mode_at_the_title_screen_replays_the_operators_run(ap, monkeypatch):
    t = ap.tools
    ap.sess[0]["started"] = t.time.time() - 5                   # five seconds after launch
    monkeypatch.setattr(t, "_missions", lambda game_id=None: [])
    monkeypatch.setattr(t, "_recorded_play", lambda ctx, gid: [{"id": "r1", "events": {"pad": 500}, "adapter": "retroarch",
                                                                "started": 100.0, "updated": 1}])
    monkeypatch.setattr(t, "_run_events", lambda ctx, rid: [pad(103.0, [("start", True)]), pad(103.2, [("start", False)])])
    r = t.autoplay(t.AutoplayIn(session_id="s1", op="start"), ap.ctx)["result"]
    assert r["mode"] == "replay"
    t.AUTOPLAY["s1"]["driver"].stopped = True
    t.AUTOPLAY["s1"]["thread"].join(5)


def test_unknown_mode_is_refused(ap):
    t = ap.tools
    with pytest.raises(ValueError, match="mode"):
        t.autoplay(t.AutoplayIn(session_id="s1", op="start", mode="dance"), ap.ctx)
