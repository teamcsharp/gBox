"""#9528: the bot core consumes the committed gbox.mercs_map/1 stages.

Runs against the two bounded committed samples (docs/research/) and the 11-stage
manifest - no generated output, no game session, no live store.
"""
import json
import sys
from pathlib import Path

SYSTEM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SYSTEM))

from gbox.mercs.core import mercs_map as MM  # noqa: E402

R4 = SYSTEM / "docs" / "research" / "mercs-map-sample-re4-waterworld.json"
R5 = SYSTEM / "docs" / "research" / "mercs-map-sample-re5-ancient-ruins.json"
MANIFEST = SYSTEM / "docs" / "research" / "mercs-map-manifest.json"


def test_re4_sample_loads_and_is_well_formed():
    m = MM.load_map(R4)
    assert m.title == "re4" and m.stage == "Waterworld" and m.data["units"] == "mm"
    walls = m.walls()
    assert walls and all(w["kind"] in ("solid", "blocker", "walked") for w in walls)
    assert all("y0" in w and "y1" in w for w in walls)
    assert m.floor_polygons()
    assert m.doorways() and m.chokepoints() and m.cover()
    assert m.route_nodes() and m.route_edges()
    assert m.places(), "RE4 sample must carry named places"
    assert m.source.get("room_map_sha256")


def test_wall_blocking_respects_measured_height():
    m = MM.load_map(R4)
    w = next(w for w in m.walls() if w["kind"] in MM.BLOCKING_KINDS and w["y1"] - w["y0"] > 100)
    mx, mz = (w["a"][0] + w["b"][0]) / 2, (w["a"][1] + w["b"][1]) / 2
    assert m.wall_blocks(mx, mz, (w["y0"] + w["y1"]) / 2)
    assert not m.wall_blocks(mx, mz, w["y1"] + 5000)  # above the top of the wall
    assert not m.wall_blocks(mx + 100000, mz, (w["y0"] + w["y1"]) / 2)  # far away


def test_floor_containment_from_mask_rectangles():
    m = MM.load_map(R4)
    poly = m.floor_polygons()[0]
    cx = sum(p[0] for p in poly) / len(poly)
    cz = sum(p[1] for p in poly) / len(poly)
    assert m.on_floor(cx, cz)
    bx, bz = m.bounds["x"], m.bounds["z"]
    assert not m.on_floor(bx[0] - 50000, bz[0] - 50000)


def test_chokepoints_are_queryable():
    m = MM.load_map(R4)
    c0 = m.chokepoints()[0]
    near = m.chokepoints_within(c0["pos"][0], c0["pos"][1], within_mm=1.0)
    assert c0 in near
    assert m.chokepoints_within(c0["pos"][0] + 1e9, c0["pos"][1], within_mm=1.0) == []


def test_re4_route_graph_routes_between_named_places():
    m = MM.load_map(R4)
    names = list(m.places())
    assert len(names) >= 2
    a, b = names[0], names[-1]
    got = m.shortest_route(a, b)
    assert got is not None, "named blocks of the measured graph must be connected"
    path, cost = got
    assert len(path) >= 2 and path[0] == m.nearest_node(*m.places()[a])
    assert path[-1] == m.nearest_node(*m.places()[b])
    assert cost > 0
    assert all(n in m.route_nodes() for n in path)
    assert m.shortest_route(a, "no-such-place") is None


def test_re5_sample_loads_with_known_gaps():
    m = MM.load_map(R5)
    assert m.title == "re5" and m.stage == "Ancient Ruins"
    assert m.walls() and m.floor_polygons()
    assert m.route_nodes() and m.route_edges()
    assert m.places() == {}, "RE5 named places are a committed gap, not a bot assumption"
    assert m.wall_blocks(m.walls()[0]["a"][0], m.walls()[0]["a"][1],
                         (m.walls()[0]["y0"] + m.walls()[0]["y1"]) / 2)


def test_manifest_is_the_committed_record_of_11_stages():
    dm = json.loads(MANIFEST.read_text())
    assert dm["format"] == MM.FORMAT and dm["units"] == "mm" and dm["y"] == "up"
    stages = dm["stages"]
    assert len(stages) == 11
    assert {s["title"] for s in stages} == {"re4", "re5"}, "RE6 must be absent: no committed collision table"
    for s in stages:
        assert s["sha256"] and s["canonical_path"].startswith("gbox-data/mercs/maps/")
        assert s["walls"] > 0 and s["floor_polygons"] > 0
    assert dm["samples_committed"] == [str(p.relative_to(SYSTEM.parent)) for p in (R4, R5)]
    # the committed sample must match its own manifest entry
    entry = next(s for s in stages if s["stage"] == "Waterworld")
    m = MM.load_map(R4)
    assert entry["walls"] == len(m.walls())
    assert entry["doorways"] == len(m.doorways())
    assert entry["chokepoints"] == len(m.chokepoints())
