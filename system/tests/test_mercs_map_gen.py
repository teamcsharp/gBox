"""#9528: the unified Mercenaries map (scripts/mercs_map_gen.py) from the committed RE4/RE5 tables."""
import json
import sys
from pathlib import Path

SYSTEM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SYSTEM / "scripts"))
sys.path.insert(0, str(SYSTEM))

import mercs_map_gen as G  # noqa: E402

R400 = G.DATA / "re4_switch_room_map" / "r400.json"
R404 = G.DATA / "re4_switch_room_map" / "r404.json"
S400 = G.DATA / "re5_switch_room_map" / "s400.json"


def test_re4_stage_shape_and_measured_counts():
    m = G.build_stage("re4", R404)
    src = json.loads(R404.read_text())
    assert m["format"] == G.FORMAT and m["stage"] == "Waterworld" and m["units"] == "mm"
    assert len(m["walls"]) == len(src["walls"])
    assert {w["kind"] for w in m["walls"]} <= {"solid", "blocker", "walked"}
    assert m["floor"]["polygons"] and m["floor"]["area_m2"] > 100
    assert m["spawns"]["positions"] == "not determined"
    assert all(d["kind"] in ("vault", "ladder") for d in m["doorways"])
    assert m["gaps"] and m["derivation"]["cover"]


def test_floor_rectangles_cover_exactly_the_mask():
    from gbox.mercs.core import room_map as core
    rm = core.from_json(json.loads(R404.read_text()))
    rects = G.floor_rectangles(rm)
    cells = sum(round((r[2] - r[0]) / rm.cell) * round((r[3] - r[1]) / rm.cell) for r in rects)
    mask = sum(rm.floor_at(rm.ox + (c + .5) * rm.cell, rm.oz + (r + .5) * rm.cell)
               for r in range(rm.rows) for c in range(rm.cols))
    assert cells == mask


def test_route_graph_connects_and_routes():
    m = G.build_stage("re4", R404)
    g = m["routes"]
    assert g["nodes"] and g["edges"]
    a = next(iter(g["nodes"]))
    comp, todo = {a}, [a]
    adj = {}
    for u, v, _ in g["edges"]:
        adj.setdefault(u, []).append(v)
        adj.setdefault(v, []).append(u)
    while todo:
        for v in adj.get(todo.pop(), ()):
            if v not in comp:
                comp.add(v)
                todo.append(v)
    far = max(comp, key=lambda n: abs(g["nodes"][n]["pos"][0] - g["nodes"][a]["pos"][0]))
    path, length = G.route(g, a, far)
    assert path[0] == a and path[-1] == far and length >= 0
    assert G.route(g, a, "nowhere") is None


def test_re5_walked_walls_become_doorways_and_re6_is_a_gap():
    m = G.build_stage("re5", S400)
    src = json.loads(S400.read_text())
    assert len(m["doorways"]) == sum(1 for w in src["walls"] if w[6] == 2)
    assert "re6" in G.GAPS and "not determined" in " ".join(G.GAPS["re6"])


def test_wrong_format_refused(tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text(json.dumps({"format": "other/1"}))
    try:
        G.build_stage("re4", bad)
    except ValueError:
        return
    raise AssertionError("accepted a foreign format")


def test_svg_is_text_with_walls():
    m = G.build_stage("re4", R404)
    s = G.svg(m)
    assert s.startswith("<svg") and s.count("<line") >= len(m["walls"])
