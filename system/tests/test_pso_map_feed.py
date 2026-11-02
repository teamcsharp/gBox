"""The PSO map feed (gbox/pso_map_feed): assembles a RAM-derived map model from telemetry + the
bot's published collision surface + the crystal index, resolves gate flags live, and writes the
operator's click into pso-directive.json in the format the bot (gbox/pso_map.parse_directive)
consumes. See docs/pso-map-directives.md."""
import json

from gbox import pso_map_feed as F, pso_map as M


# ----------------------------------------------------------------------------- stage flags
def test_flag_set_msb_first():
    group = bytes([0x80, 0x00] + [0] * 30)
    assert F.flag_set(group, 0) is True and F.flag_set(group, 1) is False
    group = bytes([0x00, 0x40] + [0] * 30)
    assert F.flag_set(group, 9) is True and F.flag_set(group, 8) is False
    assert F.flag_set(group, 300) is None and F.flag_set(b"", 0) is None


# ----------------------------------------------------------------------------- players
def test_players_from_steering_and_surface():
    steering = json.dumps({"events": [{"players": {
        "1": {"after": {"x": -231.5, "z": 120.7, "hp": 33, "room": 10, "heading_deg": 175.9}},
        "2": {"before": {"x": -282.6, "z": 234.4, "hp": 38, "room": 10}}}}]})
    by = {p["slot"]: p for p in F.players_from_steering(steering)}
    assert by[1]["role"] == "leader" and by[1]["heading"] == 175.9 and by[2]["role"] == "swarm"
    surf = F.players_from_surface({"1": [1.0, 2.0], "2": [3.0, 4.0]})
    assert {p["slot"]: p["role"] for p in surf} == {1: "leader", 2: "swarm"}


# ----------------------------------------------------------------------------- bounds / crystal index
def test_bounds_list_and_learned_areas():
    assert F.bounds_list({"min_x": -600, "min_z": -560, "max_x": 540, "max_z": 560}) == [-600, -560, 540, 560]
    rooms = {"fp": {"surface": {"episode": 1, "floor": 1, "room": 10, "cell_count": 42,
                                "bounds": {"min_x": 0, "min_z": 0, "max_x": 120, "max_z": 120}, "gates": 2, "warps": 1}}}
    areas = F.learned_areas(rooms)
    assert len(areas) == 1 and areas[0]["cell_count"] == 42 and areas[0]["bounds"] == [0, 0, 120, 120]


# ----------------------------------------------------------------------------- the whole model
def test_build_model_merges_surface_and_reads_gate_flags():
    # gate flag 13 open: byte 13//8=1, mask 0x80>>(13%8=5)=0x04
    group = bytearray(32); group[1] = 0x04
    seen = []

    def peek(sid, addr, n, actor):
        seen.append((addr, n))
        assert addr == F.STAGE_FLAG_BASE + 1 * F.STAGE_GROUP_SIZE and n == F.STAGE_GROUP_SIZE
        return bytes(group).hex()

    surface = {"version": 1, "fingerprint": "abc123", "episode": 1, "floor": 1, "room": 10, "size": 12.0,
               "bounds": {"min_x": -12.0, "min_z": 0.0, "max_x": 24.0, "max_z": 24.0},
               "cells": [[0, 0], [1, 0]], "gates": [{"class": "TObjDoor", "x": 7.0, "z": 0.0, "room": 10, "flag": 13, "kind": "gate"}],
               "warps": [{"class": "TObjAreaWarpForest", "x": 50.0, "z": 60.0, "room": 10}], "players": {"1": [0.0, 0.0]}}
    tel = {"running": True, "age_s": 0.2, "title": "PSO", "stats": {
        "episode": 1, "floor": 1, "map_surface_fingerprint": "abc123",
        "forward_fallback_target": "TObjLazerFenceNorm",
        "map_directive": {"op": "goto", "state": "navigating", "x": 20.0, "z": 10.0},
        "steering_evidence_json": json.dumps({"events": [{"players": {"1": {"after": {"x": 0.0, "z": 0.0, "hp": 40, "room": 10, "heading_deg": 90}}}}]})}}
    model = F.build_model("sess", tel, surface, {}, peek=peek, actor="agent", now=1000.0)
    assert model["schema"] == F.SCHEMA and model["live"] is True and model["size"] == 12.0 and model["room"] == 10
    assert model["cells"] == [[0, 0], [1, 0]] and model["bounds"] == [-12.0, 0.0, 24.0, 24.0]
    assert model["gates"][0]["set"] is True            # read live from the stage-flag group
    assert model["objective"] == "TObjLazerFenceNorm"
    assert model["map_directive"]["state"] == "navigating"
    assert model["players"][0]["slot"] == 1 and seen


def test_build_model_without_surface_still_shows_players():
    tel = {"running": True, "stats": {"episode": 1, "floor": 1, "steering_evidence_json": json.dumps(
        {"events": [{"players": {"1": {"after": {"x": 1.0, "z": 2.0, "hp": 40, "room": 3}}}}]})}}
    model = F.build_model("s", tel, None, {}, peek=None, now=5.0)
    assert model["cells"] == [] and model["players"][0]["x"] == 1.0
    assert model["bounds"] is not None                 # fitted from the player


def test_build_model_empty_is_safe():
    model = F.build_model("s", {}, None, None, peek=None, now=1.0)
    assert model["live"] is False and model["players"] == [] and model["bounds"] is None


# ----------------------------------------------------------------------------- directive file writer
def test_directive_raw_is_accepted_by_the_bot_parser():
    # the written file must parse under the bot's own validator (pso_map.parse_directive)
    goto = F.directive_raw({"op": "goto", "x": -120.0, "z": 70.0, "room": 10, "episode": 1, "floor": 1})
    assert "id" in goto and "ts" in goto and M.parse_directive(goto)["op"] == "goto"
    press = F.directive_raw({"op": "press", "flag": 7})
    assert M.parse_directive(press)["flag"] == 7
    attack = F.directive_raw({"op": "attack", "ptr": "80DB0000"})
    assert M.parse_directive(attack)["ptr"] == "80DB0000"
    assert M.parse_directive(F.directive_raw({"op": "clear"}))["op"] == "clear"
    # a bad directive the endpoint must reject: goto without coords does not parse
    assert M.parse_directive(F.directive_raw({"op": "goto"})) is None


def test_write_and_read_directive_roundtrip(tmp_path):
    raw = F.directive_raw({"op": "goto", "x": 1.0, "z": 2.0})
    F.write_directive(tmp_path, raw)
    assert (tmp_path / "pso-directive.json").is_file()
    assert F.read_directive(tmp_path)["op"] == "goto"


def test_live_root_picks_the_most_recent_run(tmp_path):
    root = tmp_path / "autoplay" / "pso-coop"
    (root / "old").mkdir(parents=True)
    (root / "new").mkdir(parents=True)
    (root / "old" / "pso-knowledge.json").write_text("{}", encoding="utf-8")
    (root / "new" / "pso-knowledge.json").write_text("{}", encoding="utf-8")
    import os, time
    old = time.time() - 1000
    os.utime(root / "old" / "pso-knowledge.json", (old, old))

    class Cfg:
        runtime = tmp_path
    assert F.live_root(Cfg()).name == "new"


def test_load_surface_rejects_bad_fingerprint(tmp_path):
    assert F.load_surface(tmp_path, "../etc/passwd") is None
    assert F.load_surface(tmp_path, "NOTHEX!!") is None
