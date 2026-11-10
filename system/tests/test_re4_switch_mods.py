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


def _weapon_tables(ad):
    from gbox.mercs.titles import re4_weapons as W
    fr = []
    for c in range(W.N_CLASSES):
        fr += [14.0, 12.0, 10.0, 10.0, 10.0] if c == 2 else [21.0, 21.0, 21.0, 21.0, 21.0]
    ad.put(BASE + W.FIRE_RATE_TBL, struct.pack("<%df" % len(fr), *fr))
    ad.put(BASE + W.RIFLE_FIRE_TBL, struct.pack("<10f", *([20.0] * 10)))
    rows = b"".join(struct.pack("<HBBBBH7H", 0x29 if k == 0 else 0x23 + k, 0, 5, 0, 0, 0x1A, 6, 6, 6, 6, 6, 6, 6)
                    for k in range(W.WEAPON_N))
    ad.put(BASE + W.WEAPON_TBL, rows)
    return W


def test_fire_rate_divides_the_frames_between_shots_down_to_the_gate_floor(ad):
    W = _weapon_tables(ad)
    gap = D.FIRE_GAP_S
    try:
        out = M.run(ad, "fire_rate", 20, snap=snap(ad))
        assert out["verified"] and out["tables"] == 2 and D.FIRE_GAP_S == max(M.FIRE_GAP_MIN_S, gap / 20)
        row = struct.unpack("<5f", ad.read_memory(BASE + W.FIRE_RATE_TBL + 2 * 20, 20))
        assert row == (W.RAPID_FIRE_FLOOR,) * 5, "14 frames / 20 is under the gate: the floor"
        M.run(ad, "fire_rate", 1, snap=snap(ad))
        assert struct.unpack("<5f", ad.read_memory(BASE + W.FIRE_RATE_TBL + 2 * 20, 20))[0] == 14.0
        assert D.FIRE_GAP_S == gap
    finally:
        D.FIRE_GAP_S = gap


def test_infinite_ammo_sets_the_games_own_infinite_capacity(ad):
    W = _weapon_tables(ad)
    M.run(ad, "infinite_ammo", on=True, snap=snap(ad))
    caps = struct.unpack("<7H", ad.read_memory(BASE + W.WEAPON_TBL + 8, 14))
    assert caps == (W.CAP_INFINITE,) * 7
    M.run(ad, "infinite_ammo", on=False, snap=snap(ad))
    assert struct.unpack("<7H", ad.read_memory(BASE + W.WEAPON_TBL + 8, 14)) == (6,) * 7


def test_unlimited_life_puts_the_life_back_at_its_maximum(ad):
    """re4_switch.PLAYER_LIFE (measured 2026-11-10: HUNK 1680 -> 1152 -> 96 -> 0): kept at its maximum while on."""
    life = BASE + D.PLAYER_LIFE
    ad.put(life - 2, struct.pack("<3H", 0, 1152, 1680))
    s = snap(ad)
    s["player"] = {"hp": 1152, "hp_max": 1680}
    out = M.run(ad, "unlimited_health", on=True, snap=s)
    assert out["verified"] and out["kept"] == 1 and struct.unpack("<H", ad.read_memory(life, 2))[0] == 1680
    ad.put(life - 2, struct.pack("<3H", 0, 900, 1680))
    s["player"] = {"hp": 900, "hp_max": 1680}
    assert M.maintain(ad, s)["life_kept"] == 1 and M.status(ad)["unlimited_health"] is True
    ad.put(life - 2, struct.pack("<3H", 0, 0, 1680))
    s["player"] = {"hp": 0, "hp_max": 1680}
    assert "life_kept" not in M.maintain(ad, s), "a death stays the game's"


def test_the_life_is_read_from_the_module_with_its_maximum_beside_it():
    class Mem:
        def rd(self, a, n):
            assert a == BASE + D.PLAYER_LIFE - 2 and n == 6
            return struct.pack("<3H", 7, 1152, 1680)
    assert D.player_life(Mem(), BASE) == (1152, 1680)


def test_low_life_turns_and_runs_from_the_nearest():
    b = D.Bot(stats={}, director=False)
    s = {"player": {"pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 300, "hp_max": 1680, "ptr": 1},
         "enemies": [{"pos": (0.0, 0.0, 1500.0), "hp": 400, "ptr": 9}]}
    act = b.tick(s, now=1.0)
    assert act["hold"] == set(D.QUICK_TURN) and b.doing == "retreat" and b.stats["low_life_runs"] == 1
    assert b.tick(s, now=1.5)["hold"] == {"lup", D.RUN_BTN}, "the run holds LOW_LIFE_RUN_S"


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



def _fp_table(ad):
    """The measured firepower rows in a fake module."""
    import struct as _s
    for name, (off, first) in M.FIREPOWER_ROWS.items():
        vals = [first * (1 + 0.1 * i) for i in range(7)]
        ad.put(BASE + off, _s.pack("<7f", *vals))


def test_weapon_power_and_max_level_rewrite_the_firepower_rows(ad):
    _fp_table(ad)
    s = snap(ad)
    out = M.run(ad, "weapon_power", 5, snap=s)
    assert out["verified"] and out["rows"] == len(M.FIREPOWER_ROWS)
    off, first = M.FIREPOWER_ROWS["broken_butterfly"]
    vals = struct.unpack("<7f", ad.read_memory(BASE + off, 28))
    assert abs(vals[0] - first * 5) < 1e-3
    M.run(ad, "max_level", on=True, snap=s)
    vals = struct.unpack("<7f", ad.read_memory(BASE + off, 28))
    assert all(abs(v - first * 1.6 * 5) < 1e-2 for v in vals), "every level at the exclusive value, x5"
    M.run(ad, "weapon_power", 1, snap=s)
    M.run(ad, "max_level", on=False, snap=s)
    vals = struct.unpack("<7f", ad.read_memory(BASE + off, 28))
    assert abs(vals[0] - first) < 1e-3, "back to the game's own"


def test_a_row_that_does_not_match_is_never_written(ad):
    _fp_table(ad)
    off, _ = M.FIREPOWER_ROWS["handgun"]
    ad.put(BASE + off, struct.pack("<7f", *([99.0] * 7)))
    M.run(ad, "weapon_power", 3, snap=snap(ad))
    assert struct.unpack("<7f", ad.read_memory(BASE + off, 28))[0] == 99.0


def test_the_aim_lock_writes_the_bots_aim_onto_the_facing(ad):
    import time as _t
    ptr = 0x5D50100000
    raw = bytearray(D.UNIT_SIZE)
    ad.put(ptr, raw)
    M.run(ad, "aim_lock", on=True)
    D.AIM_REQUEST.update(ptr=ptr, yaw=1.25, at=_t.monotonic())
    s = snap(ad)
    s["player"] = {"ptr": ptr, "pos": (0, 0, 0), "rot": 0.0}
    assert M.maintain(ad, s).get("aim_writes") == 1
    assert abs(struct.unpack("<f", ad.read_memory(ptr + D.U_YAW, 4))[0] - 1.25) < 1e-6
    D.AIM_REQUEST.update(at=_t.monotonic() - 5)
    assert "aim_writes" not in M.maintain(ad, s), "a stale request is not written"
