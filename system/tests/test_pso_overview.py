from gbox.pso_knowledge import KnowledgeStore
from gbox.pso_overview import SCHEMA, build_overview, render_svg, shortest_route


def _store(tmp_path):
    s = KnowledgeStore(tmp_path / "k.json")
    s.record_edge("A", 1, "d1", 2)
    s.record_edge("A", 1, "d2", 3)
    s.record_edge("A", 2, "d3", 4)
    s.record_edge("A", 3, "d4", 5)
    s.record_edge("A", 5, "d5", 4)
    s.record_path("A", [1, 2, 4])
    s.remember("fp1", gate="forced_flags", room=2, floor=3, forward_flags=[7, 9])
    s.remember("fp2", gate="forced_flags", room=2, floor=9, forward_flags=[1])
    return s


def test_shortest_route_and_unreachable():
    e = {1: {"a": 2}, 2: {"b": 3}}
    assert shortest_route(e, 1, 3) == [1, 2, 3]
    assert shortest_route(e, 3, 1) == []


def test_overview_layout_gates_route(tmp_path):
    s = _store(tmp_path)
    o = build_overview(s, "A", floor=3)
    assert o["schema"] == SCHEMA and o["start"] == 1 and o["exit"] == 4
    assert o["route"] == [1, 2, 4]
    by = {n["room"]: n for n in o["rooms"]}
    assert by[2]["gate_flags"] == [7, 9]          # floor-9 record filtered out
    assert by[1]["col"] == 0 and by[4]["col"] == 2 and by[2]["on_route"]
    assert not by[5]["on_route"] and len(o["doors"]) == 5
    svg = render_svg(o)
    assert svg.startswith("<svg") and "room 2 flags 7,9" in svg


def test_record_run_keeps_best_and_persists(tmp_path):
    s = _store(tmp_path)
    assert s.record_run("A", 120.0, [1, 3, 5, 4])
    assert not s.record_run("A", 150.0, [1, 2, 4])
    assert s.record_run("A", 90.5, [1, 2, 4])
    assert not s.record_run("A", -1) and not s.record_run("A", True)
    s2 = KnowledgeStore(tmp_path / "k.json")
    o = build_overview(s2, "A")
    assert o["best_s"] == 90.5 and o["runs"] == 3 and o["critical_path"] == [1, 2, 4]
