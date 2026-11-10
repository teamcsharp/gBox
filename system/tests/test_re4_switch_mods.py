"""RE4 Switch live mods (gbox.mercs.titles.re4_switch_mods) on a fake guest memory: the health caps, one-hit kills,
the clock ops and time per kill, and the live sidebar / bot logic rows."""
import struct

import pytest

from gbox.mercs.titles import re4_switch as D
from gbox.mercs.titles import re4_switch_mods as M

BASE = 0x3CA7C04000
CLOCK = BASE + 0x1274B90
G1, G2, BIG = 0x5D50001000, 0x5D50002000, 0x5D50003000


class Ad:
    def __init__(self):
        self.mem = bytearray()
        self.at = {}
        self.writes = []

    def put(self, addr, data):
        self.at[addr] = bytearray(data)

    def read_memory(self, addr, n):
        for a, d in self.at.items():
            if a <= addr and addr + n <= a + len(d):
                return bytes(d[addr - a:addr - a + n])
        raise ValueError("unmapped")

    def write_memory(self, addr, data):
        for a, d in self.at.items():
            if a <= addr and addr + len(data) <= a + len(d):
                d[addr - a:addr - a + len(data)] = data
                self.writes.append((addr, bytes(data)))
                return
        raise ValueError("unmapped")


def unit(ad, addr, hp, top, cls=0xAE7050):
    raw = bytearray(D.UNIT_SIZE)
    struct.pack_into("<Q", raw, 0, BASE + cls)
    struct.pack_into("<H", raw, D.U_HP, hp)
    struct.pack_into("<H", raw, D.U_HP_MAX, top)
    ad.put(addr, raw)


def hp(ad, addr):
    return struct.unpack("<H", ad.read_memory(addr + D.U_HP, 2))[0]


def snap(ad, clock=True):
    enemies = []
    for addr in (G1, G2, BIG):
        if addr in ad.at:
            raw = ad.at[addr]
            enemies.append({"ptr": addr, "class": struct.unpack_from("<Q", raw, 0)[0] - BASE,
                            "hp": struct.unpack_from("<H", raw, D.U_HP)[0],
                            "hp_max": struct.unpack_from("<H", raw, D.U_HP_MAX)[0]})
    return {"module_base": BASE, "clock_addr": CLOCK if clock else None, "enemies": enemies, "player": None}


@pytest.fixture
def ad():
    M.ORIG.clear()
    a = Ad()
    unit(a, G1, 400, 400)
    unit(a, G2, 120, 400)
    unit(a, BIG, 3500, 3500)
    a.put(CLOCK, struct.pack("<f", 90.0))
    return a


def test_enemy_health_lowers_every_living_ganado_to_the_share_and_never_raises(ad):
    out = M.run(ad, "enemy_health", 0.25, snap=snap(ad))
    assert out["verified"] and out["capped"] == 3, "120 of 400 is still above a quarter"
    assert (hp(ad, G1), hp(ad, G2), hp(ad, BIG)) == (100, 100, 875)
    unit(ad, G1, 400, 400)                              # a new spawn in the slot
    assert M.maintain(ad, snap(ad))["capped"] == 1 and hp(ad, G1) == 100


def test_one_hit_floors_at_one_and_the_dead_stay_dead(ad):
    unit(ad, G2, 0, 400)
    M.run(ad, "one_hit", on=True, snap=snap(ad))
    assert (hp(ad, G1), hp(ad, G2), hp(ad, BIG)) == (1, 0, 1)


def test_other_classes_and_foreign_objects_are_never_written(ad):
    unit(ad, G1, 1000, 1000, cls=0xAED470)              # a set object (lamp, prop)
    unit(ad, G2, 400, 0)                                 # no maximum: not a Ganado's health
    M.run(ad, "enemy_health", 0.1, snap=snap(ad))
    assert hp(ad, G1) == 1000 and hp(ad, G2) == 400 and hp(ad, BIG) == 350


def test_enemy_health_one_is_the_games_own_and_off(ad):
    M.run(ad, "enemy_health", 0.5, snap=snap(ad))
    M.run(ad, "enemy_health", 1.0, snap=snap(ad))
    unit(ad, G1, 400, 400)
    assert M.maintain(ad, snap(ad)) == {} and hp(ad, G1) == 400
    with pytest.raises(ValueError):
        M.run(ad, "enemy_health", 0.0)


def test_clock_add_and_set_are_read_back_and_confirmed_on_the_next_snapshot(ad):
    out = M.run(ad, "add_time", seconds=30, snap=snap(ad))
    assert out["verified"] and out["after"] == 120.0
    M.maintain(ad, snap(ad))
    assert M.status(ad)["clock_holds"] is True
    assert M.run(ad, "set_time", seconds=5, snap=snap(ad))["after"] == 5.0
    assert M.run(ad, "add_time", seconds=-60, snap=snap(ad))["after"] == 1.0, "never under 1 s"


def test_a_clock_its_master_rewrites_is_reported_as_not_holding(ad):
    M.run(ad, "add_time", seconds=30, snap=snap(ad))
    ad.put(CLOCK, struct.pack("<f", 89.0))              # the game wrote its own value back
    M.maintain(ad, snap(ad))
    assert M.status(ad)["clock_holds"] is False


def test_no_clock_no_time_ops(ad):
    out = M.run(ad, "add_time", seconds=30, snap=snap(ad, clock=False))
    assert out["verified"] is False and "clock" in out["reason"]


def test_time_per_kill_from_the_census(ad):
    M.run(ad, "kill_time", on=True, seconds=4)
    M.maintain(ad, snap(ad))
    unit(ad, G1, 0, 400)
    unit(ad, G2, 0, 400)
    assert M.maintain(ad, snap(ad))["kill_time_added"] == 8
    assert struct.unpack("<f", ad.read_memory(CLOCK, 4))[0] == 98.0


def test_life_and_ammo_say_they_are_not_mapped(ad):
    for op in ("unlimited_health", "infinite_ammo"):
        out = M.run(ad, op, snap=snap(ad))
        assert out["verified"] is False and "not mapped" in out["reason"]


def test_a_new_boot_keeps_the_operators_settings_but_not_the_counts(ad):
    M.run(ad, "one_hit", on=True, snap=snap(ad))
    M.maintain(ad, snap(ad))
    s = snap(ad)
    s["module_base"] = BASE + 0x100000
    M.maintain(ad, s)
    st = M.ORIG[id(ad)]
    assert st["one_hit"] is True and st["base"] == BASE + 0x100000 and "capped_total" not in st or st["capped_total"] >= 0


def test_the_live_sidebar_lists_re4s_rows():
    from gbox import merc_live_controls as L
    assert L.SWITCH["270a15eb98dab4d7"] == "re4"
    status = {"one_hit": False, "enemy_health_x": 1.0, "kill_time_on": False}
    rows = {r["id"]: r for r in L.control_inventory("re4", {}, status)}
    assert rows["mod.one_hit"]["available"] and rows["mod.enemy_health"]["min"] == 0.05
    assert L.change_input(rows["mod.enemy_health"], 0.3) == {"op": "enemy_health", "multiplier": 0.3, "on": True}
    assert L.change_input(rows["mod.one_hit"], True) == {"op": "one_hit", "on": True}


def test_bot_logic_has_re4s_dials(tmp_path):
    from gbox.mercs import bot_logic
    view = bot_logic.status("re4", path=tmp_path / "b.json")
    names = {k["name"] for k in view["knobs"]}
    assert {"ENGAGE_RANGE_CM", "RUN_CM", "STAND_MAX_S", "KILL_PACE_S"} <= names
    before = D.ENGAGE_RANGE_CM
    try:
        bot_logic.handle("010099A00BC1E000", {"ENGAGE_RANGE_CM": 9000}, path=tmp_path / "b.json")
        assert D.ENGAGE_RANGE_CM == 9000.0
    finally:
        D.ENGAGE_RANGE_CM = before
    assert bot_logic.weapon_menu(None, "re4")["weapons"] == []


def test_the_tool_routes_re4_switch():
    from gbox import re5_mods_tool as T
    assert T.is_switch_re4({"game_id": "270a15eb98dab4d7"}) and T.is_switch_re4({"map_id": "010099a00bc1e000"})
    assert not T.is_switch_re4({"game_id": "52d15709be0fda1a"})
