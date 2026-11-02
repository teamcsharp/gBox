"""The PSO 2D map feed assembles a RAM-derived map model from telemetry + the crystal + the live
stage-flag read, and the structured map directives validate the operator's clicks. See
docs/pso-map-directives.md and gbox/pso_map.py / gbox/pso_directive.py."""
import base64
import json

import pytest

from gbox import pso_map as M, pso_directive as D


# ----------------------------------------------------------------------------- stage flags
def test_flag_set_msb_first():
    group = bytes([0x80, 0x00] + [0] * 30)          # bit 0 set (MSB of byte 0)
    assert M.flag_set(group, 0) is True
    assert M.flag_set(group, 1) is False
    group = bytes([0x00, 0x40] + [0] * 30)          # byte 1, mask 0x40 -> index 8 + (bit 1) = 9
    assert M.flag_set(group, 9) is True
    assert M.flag_set(group, 8) is False
    assert M.flag_set(group, 300) is None           # out of range
    assert M.flag_set(b"", 0) is None               # short group


# ----------------------------------------------------------------------------- players from steering
def test_players_from_steering_leader_and_swarm():
    steering = json.dumps({"events": [{"players": {
        "1": {"after": {"x": -231.5, "z": 120.7, "y": 25.2, "hp": 33, "room": 10, "heading_deg": 175.9}},
        "2": {"before": {"x": -282.6, "z": 234.4, "hp": 38, "room": 10}},
    }}]})
    players = M.players_from_steering(steering)
    by_slot = {p["slot"]: p for p in players}
    assert by_slot[1]["role"] == "leader" and by_slot[1]["x"] == -231.5 and by_slot[1]["heading"] == 175.9
    assert by_slot[2]["role"] == "swarm" and by_slot[2]["z"] == 234.4
    assert M.players_from_steering("not json") == []
    assert M.players_from_steering(json.dumps({"events": []})) == []


# ----------------------------------------------------------------------------- the live nav block
def test_merge_pso_block_objects_split():
    model = {k: [] for k in ("switches", "doors", "warps")}
    model.update(players=[], enemies=[], path=[], exit=None)
    block = {"area": {"episode": 1, "floor": 1, "room": 5, "fingerprint": "fp"},
             "players": [{"slot": 1, "role": "leader", "x": 1.0, "z": 2.0}],
             "enemies": [{"id": "e1", "x": 3.0, "z": 4.0, "cls": "TObjEneBm3", "class": "Booma", "alive": True}],
             "path": [[1, 2], [3, 4]], "target": {"x": 3.0, "z": 4.0, "kind": "goto"},
             "objective": "reach the door",
             "objects": [
                 {"id": "sw1", "kind": "switch", "x": 5.0, "z": 6.0, "flag_index": 12, "state": "pressed", "opens": "door1"},
                 {"id": "door1", "kind": "door", "x": 7.0, "z": 8.0, "type": "TObjDoor", "flag_index": 13, "state": "locked", "to_room": 6},
                 {"id": "w1", "kind": "warp", "x": 9.0, "z": 10.0, "warp_kind": "area_warp", "to": "floor_2"},
                 {"id": "x1", "kind": "exit", "x": 11.0, "z": 12.0, "warp_kind": "teleporter"},
             ]}
    M.merge_pso_block(model, block)
    assert model["episode"] == 1 and model["floor"] == 1 and model["fingerprint"] == "fp"
    assert model["switches"][0]["pressed"] is True and model["switches"][0]["opens"] == "door1"
    assert model["doors"][0]["open"] is False and model["doors"][0]["to_room"] == 6
    assert model["warps"][0]["kind"] == "area_warp" and model["warps"][0]["to"] == "floor_2"
    assert model["exit"] == {"x": 11.0, "z": 12.0, "kind": "teleporter"}
    assert model["objective"] == "reach the door"
    assert model["path"] == [[1, 2], [3, 4]]


# ----------------------------------------------------------------------------- crystal + bounds
def test_crystal_apply_and_learned_areas():
    rooms = {"fp": {"episode": 1, "floor": 1, "room": 5,
                    "surface": {"origin": [0, 0], "cell": 50.0, "cols": 4, "rows": 4, "bounds": [0, 0, 200, 200]},
                    "switches": [{"id": "sw1", "x": 5.0, "z": 6.0, "flag_index": 12}],
                    "doors": [{"id": "d1", "x": 7.0, "z": 8.0, "flag_index": 13}]}}
    model = {k: [] for k in ("switches", "doors", "warps")}
    model.update(surface=None, exit=None)
    M.apply_crystal(model, M.crystal_area(rooms, "fp"))
    assert model["surface"]["cols"] == 4 and model["switches"][0]["id"] == "sw1"
    areas = M.learned_areas(rooms)
    assert len(areas) == 1 and areas[0]["has_surface"] and areas[0]["switches"] == 1
    assert M.bounds_of(model) == [0, 0, 200, 200]


# ----------------------------------------------------------------------------- the whole model
def test_build_model_merges_and_reads_flags():
    # flag_index 12 pressed, 13 not: byte 1 bit (12%8=4)->0x08 set; index 13 -> 0x04 clear
    group = bytearray(32); group[12 // 8] = 0x08
    peeks = []

    def peek(sid, addr, n, actor):
        peeks.append((addr, n))
        assert addr == M.STAGE_FLAG_BASE + 1 * M.STAGE_GROUP_SIZE and n == M.STAGE_GROUP_SIZE
        return bytes(group).hex()

    tel = {"running": True, "age_s": 0.4, "title": "PSO", "stats": {
        "episode": 1, "floor": 1, "forward_room": 5, "forward_fallback_target": "TObjLazerFenceNorm",
        "pso_map": {"area": {"fingerprint": "fp"},
                    "objects": [{"id": "sw1", "kind": "switch", "x": 5.0, "z": 6.0, "flag_index": 12},
                                {"id": "d1", "kind": "door", "x": 7.0, "z": 8.0, "flag_index": 13}]}}}
    model = M.build_model("sess", tel, {}, peek=peek, actor="agent", now=1000.0)
    assert model["schema"] == M.SCHEMA and model["live"] is True and model["floor"] == 1
    assert model["objective"] == "TObjLazerFenceNorm"
    assert model["switches"][0]["pressed"] is True          # read live from the stage-flag group
    assert model["doors"][0]["open"] is False
    assert model["stage_flags"]["read"] is True and peeks   # the bounded read happened


def test_build_model_synthesizes_players_without_block():
    tel = {"running": True, "stats": {"episode": 1, "floor": 1, "steering_evidence_json": json.dumps(
        {"events": [{"players": {"1": {"after": {"x": 1.0, "z": 2.0, "hp": 40, "room": 3}}}}]})}}
    model = M.build_model("s", tel, {}, peek=None, now=5.0)
    assert model["players"] == [{"slot": 1, "role": "leader", "x": 1.0, "z": 2.0, "hp": 40, "room": 3}]


def test_build_model_empty_telemetry_is_safe():
    model = M.build_model("s", {}, None, peek=None, now=1.0)
    assert model["live"] is False and model["players"] == [] and model["bounds"] is None
    assert model["schema"] == M.SCHEMA


def test_surface_bounds_from_grid():
    assert M.surface_bounds({"origin": [10, 20], "cell": 5.0, "cols": 4, "rows": 2}) == [10, 20, 30, 30]


# ----------------------------------------------------------------------------- directives
def test_directive_build_validates():
    assert D.build("goto", {"x": 1.0, "z": 2.0, "floor": 1}) == {"kind": "goto", "x": 1.0, "z": 2.0, "floor": 1, "room": None}
    assert D.build("press", {"switch_id": "sw1"})["switch_id"] == "sw1"
    assert D.build("attack", {"x": 1.0, "z": 2.0})["x"] == 1.0
    assert D.build("clear", {}) == {"kind": "clear"}
    with pytest.raises(ValueError):
        D.build("goto", {"x": 1.0})                         # missing z
    with pytest.raises(ValueError):
        D.build("press", {})                                # neither id nor coords
    with pytest.raises(ValueError):
        D.build("fly", {})                                  # unknown kind
    with pytest.raises(ValueError):
        D.build("goto", {"x": float("inf"), "z": 0.0})      # non-finite


def test_directive_post_latest_newest_wins():
    D.clear("sx")
    a = D.post("sx", "goto", {"x": 1.0, "z": 2.0}, now=100.0)
    b = D.post("sx", "press", {"switch_id": "sw1"}, now=101.0)
    assert b["seq"] > a["seq"]
    assert D.latest("sx", now=101.0)["kind"] == "press"
    assert D.latest("sx", now=101.0 + D.TTL_S + 1) is None   # expired past the newest post's TTL
