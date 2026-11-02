"""Collision-surface extraction + operator map directive parsing (pure)."""
from gbox import pso_map as M


def _state():
    players = {1: {"ptr": "80D01000", "class": "TObjPlayer", "entity_id": 0, "kind": "player",
                   "x": 0., "y": 0., "z": 0., "room": 10, "heading_deg": 0., "hp": 40, "hp_max": 40},
               2: {"ptr": "80D02000", "class": "TObjPlayer", "entity_id": 1, "kind": "player",
                   "x": 3., "y": 0., "z": 0., "room": 10, "heading_deg": 0., "hp": 40, "hp_max": 40}}
    ents = list(players.values()) + [
        {"class": "TObjDoorKey", "kind": "gate", "x": 5., "z": 0., "room": 10, "flag_index": 7},
        {"class": "TObjAreaWarpForest", "kind": "object", "x": 50., "z": 60., "room": 10}]
    return {"verified": True, "phase": 14, "episode": 1, "floor": 1, "geometry_verified": True,
            "geometry_identity": "area1", "players": players, "player": players[1], "entities": ents,
            "difficulty": 0, "collision_grid": {"size": 12.0, "floor": [[0, 0], [1, 0], [0, 1], [-1, 0]],
                                                 "walls": [], "heights": [[0, 0, 0.0]], "max_step": .75, "max_slope": .75}}


def test_extract_surface_publishes_cells_bounds_gates_and_warps():
    s = M.extract_surface(_state(), _state()["players"][1])
    assert s["cell_count"] == 4 and [0, 0] in s["cells"]
    assert s["size"] == 12.0 and s["episode"] == 1 and s["floor"] == 1 and s["room"] == 10
    assert s["bounds"] == {"min_x": -12.0, "min_z": 0.0, "max_x": 24.0, "max_z": 24.0}
    assert any(g["class"] == "TObjDoorKey" and g["flag"] == 7 and g["kind"] == "switch" for g in s["gates"])
    assert any(w["class"] == "TObjAreaWarpForest" for w in s["warps"])
    assert isinstance(s["fingerprint"], str) and s["fingerprint"]


def test_extract_surface_requires_verified_geometry_and_a_grid():
    st = _state()
    st["geometry_verified"] = False
    assert M.extract_surface(st, st["players"][1]) is None
    st2 = _state()
    st2["collision_grid"] = {"size": 12.0, "floor": []}
    assert M.extract_surface(st2, st2["players"][1]) is None


def test_parse_directive_validates_each_op():
    assert M.parse_directive({"op": "goto", "x": -120., "z": 70., "id": "c1"}) == {
        "op": "goto", "id": "c1", "x": -120., "z": 70.}
    assert M.parse_directive({"op": "goto", "x": "nope", "z": 0}) is None
    assert M.parse_directive({"op": "press", "flag": 7}) == {"op": "press", "id": None, "flag": 7}
    assert M.parse_directive({"op": "press", "flag": 999}) is None
    assert M.parse_directive({"op": "attack", "ptr": "80DB1234"})["ptr"] == "80DB1234"
    assert M.parse_directive({"op": "clear"}) == {"op": "clear", "id": None}
    assert M.parse_directive({"op": "dance"}) is None
    assert M.parse_directive("nope") is None


def test_parse_directive_carries_optional_scope():
    d = M.parse_directive({"op": "goto", "x": 1., "z": 2., "episode": 1, "floor": 3, "room": 10})
    assert d["episode"] == 1 and d["floor"] == 3 and d["room"] == 10


def test_directive_in_scope_matches_live_state():
    st = _state()
    assert M.directive_in_scope({"op": "goto", "episode": 1, "floor": 1, "room": 10}, st) is True
    assert M.directive_in_scope({"op": "goto", "floor": 2}, st) is False          # wrong floor
    assert M.directive_in_scope({"op": "goto", "room": 99}, st) is False          # wrong room (P1 in 10)
    assert M.directive_in_scope({"op": "goto"}, st) is True                       # no scope = always in scope
    assert M.directive_in_scope(None, st) is False
