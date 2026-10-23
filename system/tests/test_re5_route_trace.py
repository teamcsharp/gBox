import json
import random
import sqlite3
from pathlib import Path

import pytest

from gbox.mercs.route_trace import Recorder, report
from gbox.mercs.titles.re5_nav import NavMesh
from gbox.mercs.titles.re5_ps3 import StagePick


HOURGLASS_TRACE = json.loads((Path(__file__).parent / "fixtures/re5_hourglass_evidence.json").read_text())


def _pickup_trace(tmp_path, samples, bonus_pos=(110., 0., 100.), actor=123):
    height = samples[0][3][1]
    mesh = NavMesh([(-10000., height, -10000.), (10000., height, -10000.), (0., height, 10000.)],
                   [(0, 1, 2)], [[]])
    recorder = Recorder(lambda *a, **k: None, atlas_root=tmp_path, title="BLUS30491", round_id="pickup-replay")
    stats = {}
    for at, timer, kills, position, standing in samples:
        snap = {"player": {"pos": position, "hp": 100}, "nav": mesh, "timer": timer,
                "bonuses": [{"ptr": actor, "pos": bonus_pos, "kind": "time"}] if standing else []}
        if kills is not None:
            snap["kills"] = kills
        recorder.observe(snap, None, stats, at, ["lup"], "before_decision")
    status = recorder.finish(samples[-1][0] + .1, "interrupted", dict(stats), wait_s=5)
    assert not status.get("navigation_atlas_error"), status
    artifact = json.loads(Path(status["navigation_atlas_round"]).read_text())
    with sqlite3.connect(tmp_path / "BLUS30491/atlas.sqlite") as db:
        routes = db.execute("SELECT attempts,completed FROM checkpoint_routes").fetchall()
    return artifact, routes


@pytest.mark.parametrize("window", HOURGLASS_TRACE["windows"], ids=lambda w: hex(w["actor"]))
def test_recorded_hourglass_destruction_delay_creates_one_measured_checkpoint(tmp_path, window):
    # Actual RAM samples: the bonus clock is credited 1.64–2.52 seconds before
    # its actor disappears. Kills immediately AFTER removal must not erase it.
    artifact, routes = _pickup_trace(tmp_path, window["samples"], window["bonus_pos"], window["actor"])
    events = [e for e in artifact["events"] if e["kind"] == "checkpoint_acquired"]
    assert len(events) == 1 and routes == [(1, 1)]
    evidence = events[0]["evidence"]
    removed = next(row[0] for row in window["samples"] if not row[4])
    assert evidence["actor"] == window["actor"]
    assert evidence["actor_removed_at"] == removed
    assert 1.6 < removed - evidence["clock_gain_at"] < 2.6
    assert evidence["clock_gain_s"] > 58 and evidence["player_distance_cm"] <= 250
    assert artifact["review"]["time_bonuses_acquired"] == 1
    assert artifact["review"]["metrics"]["bonuses_taken"] == 1
    assert artifact["review"]["metrics"]["bonus_s"] == evidence["clock_gain_s"]


@pytest.mark.parametrize("gain_first", [True, False])
def test_pickup_correlates_both_ram_event_orders_without_duplicate_credit(tmp_path, gain_first):
    near = [100., 0., 100.]
    samples = [(0., 100., 0, near, True)]
    for t in (.5, 1., 1.5, 2., 2.5, 3.):
        gain = t >= (.5 if gain_first else 2.5)
        standing = t < (2.5 if gain_first else .5)
        samples.append((t, 100.-t+(30. if gain else 0.), 0, near, standing))
    # A later clock gain cannot spend the same actor a second time.
    samples += [(3.5, 157., 0, near, False), (4., 156.5, 0, near, False)]
    artifact, routes = _pickup_trace(tmp_path, samples)
    assert artifact["review"]["time_bonuses_acquired"] == 1 and routes == [(1, 1)]


NEAR, FAR, UPSTAIRS = [100., 0., 100.], [700., 0., 100.], [100., 500., 100.]


@pytest.mark.parametrize("samples", [
    [(0.,100.,0,NEAR,True), (.5,99.5,0,NEAR,False), (1.,99.,0,NEAR,False)],
    [(0.,100.,0,NEAR,True), (.5,109.5,0,NEAR,False), (1.,109.,1,NEAR,False)],
    [(0.,100.,0,NEAR,True), (.5,129.5,3,NEAR,False), (1.,129.,3,NEAR,False)],
    [(0.,100.,0,NEAR,True), (.5,129.5,0,NEAR,True), (1.,129.,3,NEAR,False), (1.5,128.5,3,NEAR,False)],
    [(0.,100.,None,NEAR,True), (.5,129.5,None,NEAR,False), (1.,129.,None,NEAR,False)],
    [(0.,100.,10,NEAR,True), (.5,129.5,0,NEAR,False), (1.,129.,0,NEAR,False)],
    [(0.,100.,0,FAR,True), (.5,129.5,0,FAR,False), (1.,129.,0,FAR,False)],
    [(0.,100.,0,UPSTAIRS,True), (.5,129.5,0,UPSTAIRS,False), (1.,129.,0,UPSTAIRS,False)],
    [(0.,100.,0,NEAR,True), (.5,129.5,0,NEAR,True), (1.,129.,0,FAR,False), (1.5,128.5,0,FAR,False)],
    [(0.,100.,0,NEAR,True), (.5,129.5,0,NEAR,False), (1.,129.,0,NEAR,True),
     (1.5,128.5,0,NEAR,False), (2.,128.,0,NEAR,False)],
    [(0.,100.,0,NEAR,True), (.5,99.5,0,NEAR,False), (1.,99.,0,NEAR,False),
     (2.,98.,0,NEAR,False), (3.,97.,0,NEAR,False), (4.,126.,0,NEAR,False)],
    [(0.,100.,0,NEAR,True), (.5,129.5,0,NEAR,True), (1.,129.,0,NEAR,True),
     (2.,128.,0,NEAR,True), (3.,127.,0,NEAR,True), (4.,126.,0,NEAR,False), (4.5,125.5,0,NEAR,False)],
], ids=["disappearance_only", "delayed_ten_second_kill_counter", "three_kill_credit", "kill_counter_changes_before_removal", "unknown_kills",
        "counter_reset", "far_actor", "different_floor", "left_before_removal", "actor_flicker",
        "unrelated_late_gain", "expired_gain"])
def test_disappearance_without_correlated_pickup_is_not_learned(tmp_path, samples):
    artifact, routes = _pickup_trace(tmp_path, samples)
    assert artifact["review"]["time_bonuses_acquired"] == 0
    assert routes == [] and not any(e["kind"] == "checkpoint_acquired" for e in artifact["events"])
    assert artifact["review"]["metrics"].get("bonuses_taken", 0) == 0
    assert artifact["review"]["metrics"].get("bonus_s", 0) == 0


def test_trace_retains_mesh_routes_and_stuck_events(tmp_path):
    rows = []
    recorder = Recorder(lambda kind, **kw: rows.append(dict(kind=kind, **kw)))
    mesh = NavMesh([(0., 0., 0.), (1000., 0., 0.), (0., 0., 1000.)], [(0, 1, 2)], [[]])
    snap = {"player": {"pos": (100., 0., 100.), "rot": 0., "hp": 100}, "nav": mesh}

    class Bot:
        def plan(self):
            return {"phase": "pursue", "route": [(200., 0., 200.)]}

    recorder.observe(snap, Bot(), {}, 0., ["lup"], "before_decision")
    recorder.observe(snap, Bot(), {}, .1, ["lup"], "before_decision")
    recorder.observe(snap, Bot(), {"stuck": 1}, .1, ["ldown"], "decision")
    assert [r["kind"] for r in rows] == ["navigation_stage", "navigation_sample", "navigation_event"]
    assert rows[-1]["events"] == {"stuck": 1}
    assert rows[-1]["frame"]["plan"]["route"] == [[200, 0, 200]]
    trace = tmp_path / "run.jsonl"
    trace.write_text("\n".join(json.dumps(r) for r in rows) + '\n{"partial":', encoding="utf-8")
    result = report(trace, tmp_path / "report")
    stage = next(iter(result["stages"].values()))
    assert len(stage["events"]) == 1
    svg = (tmp_path / "report" / stage["map"]).read_text()
    assert '<circle' in svg and '<polyline' in svg and '<title>' in svg


def test_stage_picks_never_repeat_consecutively():
    pick = StagePick(random.Random(7))
    previous = None
    scr = {"where": "select_stage"}
    selected = set()
    for _ in range(50):
        for _ in range(20):
            key = pick.key(scr)
            target = pick.target
            pick.pressed(scr, key)
            if key == "cross":
                assert target != previous
                previous = target
                selected.add(target)
                break
        else:
            raise AssertionError("Stage selection never confirmed")
    assert selected == set(range(8))
