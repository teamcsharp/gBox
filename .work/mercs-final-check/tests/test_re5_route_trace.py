import json
import random

from gbox.mercs.route_trace import Recorder, report
from gbox.mercs.titles.re5_nav import NavMesh
from gbox.mercs.titles.re5_ps3 import StagePick


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
