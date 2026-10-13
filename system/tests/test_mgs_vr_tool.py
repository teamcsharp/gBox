"""Metal Gear Solid: VR Missions live tool (#1082 "mark current mission as complete", #1085).

Synthetic RAM is laid out like the real game: a stage overlay at 0x800C4350 holding the vr.c manager's clear routine
and the result screen's clear-flag store (the instruction words are copied from vr_sud03's overlay 24428.bin), a GV
actor list with the manager in level 5, and the fixed executable globals.  Owned-disc tests (skipped elsewhere) scan
every stage overlay on the US disc and replay the real pcsx_rearmed save states of a Level 03 run."""
import os
import struct
from pathlib import Path

import pytest

from gbox import agent, mgs_vr_tool as T, mgs_vr_unlock as U

TITLE = "Metal Gear Solid - VR Missions (USA)"
CLEAR_ROUTINE = bytes.fromhex("""21288000 0e80033c 02000224 0b80043c b02b62ac e4c1828c 0010033c 25104300 e4c182ac
                                 0b01a290""".replace(" ", "").replace("\n", ""))
FLAG_STORE = struct.pack("<6I", 0x3C02800E, 0x24522C20, 0x0C024183, 0x02402821, 0x0C0240C0, 0x00002021)
FLAG_LOAD = struct.pack("<2I", 0x0C02416B, 0x02402821)
HANDLER, ACT, STATE = 0x800D87A8, 0x800D87A8 + 0x10D0, 0x800E2BB0
STORE_AT, LOAD_AT, GRID = 0x800DC2A8, 0x800DC334, 0x800E2C20
NAME_AT, ACTOR = 0x800E2384, 0x801408F4


class FakePsx:
    """pcsx_rearmed main RAM as RetroArch exposes it: offsets 0..0x1FFFFF."""

    def __init__(self):
        self.ram = bytearray(0x200000)
        self.writes = []

    def put(self, a, data):
        self.ram[a & 0x1FFFFF:(a & 0x1FFFFF) + len(data)] = data

    def get(self, a, n):
        return bytes(self.ram[a & 0x1FFFFF:(a & 0x1FFFFF) + n])

    def read_memory(self, a, n):
        assert 0 <= a < 0x200000
        return bytes(self.ram[a:a + n])

    def write_memory(self, a, data):
        assert 0 <= a < 0x200000
        self.ram[a:a + len(data)] = data
        self.writes.append((a, bytes(data)))
        return {"written": len(data)}


def mission(stage=b"vr_sud03", state=1, player=(-1548, 1122, -682), goal=(7000, 1000, -9000)):
    ad = FakePsx()
    ad.put(T.STAGE_NAME, stage.ljust(8, b"\0"))
    ad.put(T.GAME_STATUS, struct.pack("<I", 0x08024010))
    ad.put(T.PLAYER_POS, struct.pack("<3h", *player))
    ad.put(HANDLER, CLEAR_ROUTINE)
    ad.put(STORE_AT, FLAG_STORE)
    ad.put(LOAD_AT, FLAG_LOAD)
    ad.put(NAME_AT, b"vr.c\0")
    ad.put(STATE, struct.pack("<I", state))
    for lv in range(T.ACTOR_LEVEL_COUNT):                 # empty levels: head -> tail sentinel (act 0) -> 0
        head = T.ACTOR_LEVELS + lv * T.ACTOR_LEVEL_SIZE
        ad.put(head + 4, struct.pack("<I", head + 0x20))
    head5 = T.ACTOR_LEVELS + 5 * T.ACTOR_LEVEL_SIZE
    other = 0x80141000                                     # an unrelated actor first in the list
    ad.put(head5 + 4, struct.pack("<I", other))
    ad.put(other, struct.pack("<6I", head5, ACTOR, 0x800C9000, 0, 0, 0x800E0000))
    ad.put(0x800E0000, b"goal.c\0")
    ad.put(ACTOR, struct.pack("<6I", other, head5 + 0x20, ACT, ACT + 0x780, 0, NAME_AT))
    ad.put(ACTOR + 0x24, struct.pack("<3h", *goal))
    return ad


# ---------------------------------------------------------------------------------------------- signatures
def test_clear_routine_signature_gives_the_state_word_and_step_offset():
    code = bytes(64) + CLEAR_ROUTINE + bytes(64)
    hits = T.find_clear_handler(code, 0x800D8000)
    assert hits == [{"handler": 0x800D8000 + 64, "state": STATE, "step": 0x10B, "status": T.GAME_STATUS}]
    # the failure routine ORs the same status bit but stores 5: not a clear routine
    fail = bytearray(CLEAR_ROUTINE)
    fail[8:12] = struct.pack("<I", 0x24020005)
    assert T.find_clear_handler(bytes(64) + bytes(fail) + bytes(64), 0x800D8000) == []


def test_flag_store_signature_gives_the_grid_and_both_image_calls():
    code = bytes(32) + FLAG_STORE + bytes(LOAD_AT - STORE_AT - len(FLAG_STORE)) + FLAG_LOAD + bytes(32)
    base = STORE_AT - 32
    assert U.find_flag_store(code, base) == [{"grid": GRID, "store_call": STORE_AT + 8, "load_call": LOAD_AT}]


def test_menu_bits_are_the_select_menu_tables():
    assert len(U.MENU_BITS) == 277
    rows = {r for r, _ in U.MENU_BITS}
    assert rows == {0, 1, 2, 3, 6, 8, 9, 10, 11, 12, 15}
    # sneaking levels 1..15 and the eight weapons x 5 levels share rows 0..3
    assert {b for r, b in U.MENU_BITS if r == 0} == set(range(1, 16)) | {w + l for w in range(21, 92, 10) for l in range(5)}
    grid = U.grid_bytes()
    assert U.count(grid) == 277 and U.menu_open(grid) == 277 and len(grid) == 384


def test_count_follows_the_game_rule_for_the_ten_point_mark():
    grid = U.grid_bytes([(12, 4 * 32 + 12)])
    assert U.count(grid) == 10


# ---------------------------------------------------------------------------------------------- live ops
def test_status_finds_the_manager_and_reads_the_mission():
    ad = mission()
    r = T.run(ad, TITLE, "status")
    assert r["stage"] == "vr_sud03" and r["mission"] and r["family"].startswith("Sneaking")
    assert (r["state"], r["state_name"], r["clear_step"]) == (1, "running", 0)
    assert r["actor"] == f"{ACTOR:#x}" and r["state_address"] == f"{STATE:#x}" and r["clear_routine"] == f"{HANDLER:#x}"
    assert r["goal"] == [7000, 1000, -9000] and not r["at_goal"]
    assert ad.writes == []


def test_complete_runs_the_games_clear_routine_and_verifies():
    ad = mission()
    r = T.run(ad, TITLE, "complete", wait_s=0)
    assert r["completed"] and r["verified"]
    assert struct.unpack("<I", ad.get(STATE, 4))[0] == 2
    assert struct.unpack("<I", ad.get(T.GAME_STATUS, 4))[0] == 0x08024010 | 0x10000000
    assert ad.get(ACTOR + 0x10B, 1) == b"\x01"
    assert {w[0] for w in ad.writes} == {STATE & 0x1FFFFF, T.GAME_STATUS & 0x1FFFFF, (ACTOR + 0x10B) & 0x1FFFFF}
    assert r["after"]["state_name"] == "cleared"


def test_complete_refuses_a_failed_mission_and_reports_an_already_cleared_one():
    ad = mission(state=5)
    r = T.run(ad, TITLE, "complete", wait_s=0)
    assert not r["completed"] and "restart" in r["error"] and ad.writes == []
    ad = mission(state=4)
    ad.put(ACTOR + 0x10B, b"\x08")                           # the result screen of a real clear (state 61 of the run)
    r = T.run(ad, TITLE, "clear", wait_s=0)
    assert r["completed"] and "already" in r["note"] and ad.writes == []


def test_menus_and_other_games_are_refused():
    ad = mission(stage=b"selectvr")
    assert "start a mission" in T.run(ad, TITLE, "status")["note"]
    assert not T.run(ad, TITLE, "complete")["completed"]
    assert "not Metal Gear Solid" in T.run(mission(), "Metal Gear Solid (USA) (Disc 1)", "status")["error"]
    assert "unknown op" in T.run(mission(), TITLE, "teleport")["error"]
    assert T.run(mission(), TITLE, "mark_complete", wait_s=0)["completed"]


def test_unlock_all_fills_the_result_grid_disables_its_vram_read_and_clears():
    ad = mission()
    ad.put(GRID, struct.pack("<I", 1 << 3))                   # a clear the player already has
    r = T.run(ad, TITLE, "unlock_all")
    assert r["unlocked"] and r["complete"]["completed"]
    assert ad.get(STORE_AT + 8, 4) == bytes(4)                # StoreImage call -> nop; LoadImage untouched
    assert ad.get(LOAD_AT, 8) == FLAG_LOAD
    grid = ad.get(GRID, 384)
    assert U.menu_open(grid) == 277 and struct.unpack_from("<I", grid, 0)[0] & 1 << 3
    again = mission()
    again.put(STORE_AT + 8, bytes(4))
    assert "already changed" in T.run(again, TITLE, "unlock_all")["error"]


def test_unlock_all_on_the_menu_explains_and_reports_the_count():
    ad = mission(stage=b"selectvr")
    ad.put(U.SELECT_MIRROR, U.grid_bytes(U.MENU_BITS[:10]))
    r = T.run(ad, TITLE, "unlock_all")
    assert not r["unlocked"] and r["open_entries"] == 10 and "start any mission" in r["error"] and ad.writes == []


# ---------------------------------------------------------------------------------------------- registration + agent
def test_tool_is_registered_with_the_worker():
    from gbox import registry, tools
    assert "mgs_vr" in registry.REGISTRY and "mgs_vr_tool" in tools._load_tool_modules.__defaults__[0]
    inp = registry.REGISTRY["mgs_vr"].In.model_validate({"session_id": "w-1", "op": "complete"})
    assert inp.wait_s == 2.0


def _spec(name):
    return next(t["function"] for t in agent.tool_specs() if t["function"]["name"] == name)


def test_agent_routes_mark_this_mission_complete():
    desc = _spec("mgs_vr")["description"]
    assert "mark this mission complete" in desc and "op=complete" in desc and "op=unlock_all" in desc
    assert "mgs_vr" in agent.WORKER_TOOLS and "mgs_vr" in agent.MODIFIES
    assert agent._modifies_game("mgs_vr", {"op": "complete"}) and not agent._modifies_game("mgs_vr", {"op": "status"})
    line = next(ln for ln in agent.SYSTEM.splitlines() if ln.startswith("- Metal Gear Solid: VR Missions"))
    assert "mark this mission complete" in line and "mgs_vr" in agent.SYSTEM[agent.SYSTEM.index(line):][:400]
    assert "mgs_vr for Metal Gear Solid VR Missions" in agent.SYSTEM


def test_agent_call_dispatches_a_worker_job():
    a = object.__new__(agent.Agent)
    sent = []
    a._job = lambda tool, inp, node=None, limit=900, worker=None: (
        sent.append((tool, inp, worker)) or {"state": "succeeded", "output": {"result": {"completed": True}}})
    assert a.mgs_vr("worker-abc-123", op="complete")["completed"]
    assert sent == [("mgs_vr", {"session_id": "worker-abc-123", "op": "complete"}, "worker-abc")]


def test_dossier_seed_names_the_verified_addresses():
    from gbox import re_seeds
    tf = next(t for t in re_seeds.TITLE_FACTS if t["title_has"] == ["metal gear", "vr missions"])
    names = {f["name"] for f in tf["facts"]}
    assert {"GM_GameStatus", "current stage name", "clearflags grid"} <= names


# ---------------------------------------------------------------------------------------------- owned disc
BIN = Path(os.environ.get("GBOX_MGS_VR_BIN", r"D:\gBox\cache\modbase\mgs_vr_us\Metal Gear Solid - VR Missions (USA).bin"))
STATES = Path(os.environ.get("GBOX_MGS_VR_STATES", r"D:\gBox\runtime\states\PCSX-ReARMed"))


@pytest.fixture(scope="module")
def stage_dir_bytes():
    if not BIN.is_file():
        pytest.skip("owned VR Missions disc image not on this machine")
    from gbox import psxdisc
    d = psxdisc.RawBin(BIN, writable=False)
    try:
        return d.read("MGS/STAGE.DIR")
    finally:
        d.close()


def test_every_mission_overlay_has_one_clear_routine_and_one_flag_store(stage_dir_bytes):
    names = T.stage_dir(stage_dir_bytes)
    assert len(names) == 105 and "vr_sud03" in names and "selectvr" in names
    missions = [n for n in names if T.is_mission(n) and not n.startswith("photo_")]
    assert len(missions) == 90
    for n in missions:
        ovl = T.stage_overlay(stage_dir_bytes, n)
        assert b"vr.c\0" in ovl, n
        (h,) = T.find_clear_handler(ovl, T.OVERLAY_BASE)
        assert h["step"] == 0x10B, n
        (s,) = U.find_flag_store(ovl, T.OVERLAY_BASE)
        assert T.OVERLAY_BASE < s["store_call"] < s["load_call"], n
    sud03 = T.stage_overlay(stage_dir_bytes, "vr_sud03")
    assert T.find_clear_handler(sud03, T.OVERLAY_BASE)[0]["state"] == STATE
    assert sud03[HANDLER - T.OVERLAY_BASE:][:len(CLEAR_ROUTINE)] == CLEAR_ROUTINE


def test_select_menu_tables_match_the_constants(stage_dir_bytes):
    ovl = T.stage_overlay(stage_dir_bytes, "selectvr")
    at = lambda a, n: ovl[a - T.OVERLAY_BASE:a - T.OVERLAY_BASE + n]  # noqa: E731
    assert (at(0x800D1DF0, 0x48), at(0x800D1E38, 0x48), at(0x800D1F34, 0x48)) == (U._ROWS, U._BASE, U._COUNT)
    assert at(0x800E4D30, 8) == struct.pack("<4h", 160, 224, 12, 16)     # the VRAM RECT of the clear grid


def _state_ram(slot):
    p = STATES / f"Metal Gear Solid - VR Missions (USA).state{slot}"
    if not p.is_file():
        pytest.skip("the Level 03 run's save states are not on this machine")
    from gbox.flycast_state import unpack
    core = unpack(p.read_bytes())
    if not BIN.is_file():
        pytest.skip("owned disc needed to locate RAM in the state")
    from gbox import psxdisc
    d = psxdisc.RawBin(BIN, writable=False)
    try:
        exe = d.read("SLUS_009.57")
    finally:
        d.close()
    probe = exe[0x800 + 0x2000:0x800 + 0x2040]
    base = core.find(probe) - 0x12000
    return bytearray(core[base:base + 0x200000])


def test_real_run_in_mission_then_result_screen():
    """state60: Sneaking No Weapon Level 03 in progress; state61: its LEVEL 03 CLEARED screen."""
    if not (STATES / "Metal Gear Solid - VR Missions (USA).state61").is_file():
        pytest.skip("the Level 03 run's save states are not on this machine")
    ad = FakePsx()
    ad.ram = _state_ram(60)
    r = T.run(ad, TITLE, "status")
    assert (r["stage"], r["state"], r["clear_step"], r["goal"]) == ("vr_sud03", 1, 0, [7000, 1000, -9000])
    done = T.run(ad, TITLE, "complete", wait_s=0)
    assert done["completed"] and done["after"]["state"] == 2
    ad.ram = _state_ram(61)
    r = T.run(ad, TITLE, "status")
    assert r["at_goal"] and r["clear_step"] == 8 and r["state"] == 4    # the game's own clear ran to its last step
