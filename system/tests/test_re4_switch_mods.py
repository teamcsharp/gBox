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


def test_the_huds_countdown_is_written_in_its_own_frames_never_over_its_state(ad):
    """The snapshot's clock is now the game's CountDown (clock_source "countdown": state u32 at the address, frames at
    30 a second at +8). A write in seconds onto the state word would kill the clock; the time goes into the frames."""
    cd = BASE + D.COUNTDOWN
    ad.put(cd, struct.pack("<IbbbxffI", 1, 1, 30, 0, 2700.0, 2700.0, 0))   # 1:30 running
    s = dict(snap(ad), clock_addr=cd, clock_source="countdown")
    out = M.run(ad, "add_time", seconds=30, snap=s)
    assert out["verified"] and out["before"] == 90.0 and out["after"] == 120.0
    assert struct.unpack("<I", ad.read_memory(cd, 4))[0] == 1, "the clock's state word is untouched"
    assert struct.unpack("<f", ad.read_memory(cd + D.CD_FRAME, 4))[0] == 3600.0
    assert M.status(ad, s)["clock"]["value"] == 120.0


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


def _held_gun(ad, iid=0x24, levels=0x2000, loaded=0, empty=True):
    """The item manager's equipped item: a gun of the fake weapon table, its magazine as given."""
    from gbox.mercs.titles import re4_weapons as W
    item = 0x5D60000000
    ad.put(BASE + W.ITEM_MGR + W.M_EQUIPPED, struct.pack("<QH", item, iid) + bytes(6))
    ad.put(item, struct.pack("<HHBBHHBBBB", iid, 1, 1, 0, levels, (loaded << 3) | int(empty), 0, 0, 0, 1))
    ad.put(BASE + W.GAME_OBJ + W.G_EMPTY, b"\x01")
    return W, item


def test_infinite_ammo_keeps_the_magazine_full_and_never_writes_the_capacity_table(ad):
    """Live 2026-11-10: the capacity table's infinite value (0x8000) came out as an EMPTY gun from the round's start
    (the magazine is capacity << 19 in a 32-bit word). Now the gun in hand is refilled to its capacity instead."""
    W = _weapon_tables(ad)
    W, item = _held_gun(ad)
    table = ad.read_memory(BASE + W.WEAPON_TBL, W.WEAPON_N * W.WEAPON_SZ)
    out = M.run(ad, "infinite_ammo", on=True, snap=snap(ad))
    assert out["refilled"] == 1
    it = W.decode_item(ad.read_memory(item, W.ITEM_SZ))
    assert it["loaded"] == 6 and not it["empty"] and ad.read_memory(BASE + W.GAME_OBJ + W.G_EMPTY, 1) == b"\x00"
    assert ad.read_memory(BASE + W.WEAPON_TBL, W.WEAPON_N * W.WEAPON_SZ) == table, "the table is never touched"
    ad.write_memory(item + 8, struct.pack("<H", 2 << 3))                  # two shots left
    assert M.maintain(ad, snap(ad))["mag_refills"] == 1
    assert W.decode_item(ad.read_memory(item, W.ITEM_SZ))["loaded"] == 6
    assert "mag_refills" not in M.maintain(ad, snap(ad)), "full: nothing written"


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
    s["player"]["rot"] = 3.14159                                          # turned round: the run to the goal
    assert {"lup", D.RUN_BTN} <= b.tick(s, now=1.5)["hold"], "the run holds LOW_LIFE_RUN_S"


class _Walls:
    """A stage mesh whose open floor is only the lines within `open_deg` of +x (everything else a wall)."""
    def __init__(self, open_deg=None):
        self.open_deg = open_deg

    def clear_segment(self, a, b):
        import math
        if self.open_deg is None:
            return False
        h = math.degrees(math.atan2(b[0] - a[0], b[2] - a[2]))
        return abs(h - 90.0) <= self.open_deg


def test_the_escape_runs_along_open_floor_not_into_the_wall():
    """Live 2026-11-10: "just walking into walls in RE4" - the low-life run had gone straight away, into a wall."""
    import math
    b = D.Bot(stats={}, director=False)
    p = {"pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 300, "hp_max": 1680, "ptr": 1}
    live = b._live(p, [{"pos": (0.0, 0.0, 1500.0), "hp": 400, "ptr": 9}])        # straight away is -z: walled
    goal = b._escape_goal(p, live, {"nav": _Walls(open_deg=20)})
    assert goal is not None and abs(math.degrees(math.atan2(goal[0], goal[2])) - 90.0) <= 20.0
    assert b.stats["escape_lines_walled"] >= 1
    assert b._escape_goal(p, live, {"nav": _Walls(None)}) is None and b.stats["escapes_walled_in"] == 1


def test_a_new_boot_keeps_the_operators_settings_but_not_the_counts(ad):
    M.run(ad, "one_hit", on=True, snap=snap(ad))
    M.maintain(ad, snap(ad))
    s = snap(ad)
    s["module_base"] = BASE + 0x100000
    M.maintain(ad, s)
    st = M.ORIG[id(ad)]
    assert st["one_hit"] is True and st["boot"].startswith(hex(BASE + 0x100000))
    assert st.get("capped_total", 0) <= 3, "the counts start again on the new boot"


def test_a_new_emulator_process_is_a_new_boot_at_the_same_address(ad):
    """Eden loads RE4 at the same address every boot: the base alone made every later boot "already applied"."""
    class P:
        pid = 100
    ad.proc = P()
    first = M._boot(ad, BASE)
    ad.proc = type("P2", (), {"pid": 200})()
    assert M._boot(ad, BASE) != first


def test_a_collected_adapters_state_is_never_handed_to_a_new_one(ad):
    M.run(ad, "one_hit", on=True, snap=snap(ad))
    st = M._state(ad)
    st["pre_round_boot"] = "stale"

    class Other:
        pass
    other = Other()
    M.ORIG[id(other)] = st                                           # as if the old adapter's id came back
    assert "pre_round_boot" not in M._state(other)


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
    first = struct.unpack("<f", ad.read_memory(ptr + D.U_YAW, 4))[0]
    assert first == pytest.approx(M.AIM_WRITE_MAX_STEP, abs=1e-6), "a smooth step, not a 1.25 rad teleport"
    for _ in range(60):
        M.maintain(ad, s)
    assert abs(struct.unpack("<f", ad.read_memory(ptr + D.U_YAW, 4))[0] - 1.25) < 1e-3, "it converges"
    D.AIM_REQUEST.update(at=_t.monotonic() - 5)
    assert "aim_writes" not in M.maintain(ad, s), "a stale request is not written"


def test_the_aim_lock_ignores_a_micro_correction(ad):
    """The operator 2026-11-11: the aim jerked every tick - a request inside the deadband leaves the facing alone."""
    import time as _t
    ptr = 0x5D50100000
    raw = bytearray(D.UNIT_SIZE)
    struct.pack_into("<f", raw, D.U_YAW, 0.5)
    ad.put(ptr, raw)
    M.run(ad, "aim_lock", on=True)
    D.AIM_REQUEST.update(ptr=ptr, yaw=0.5 + M.AIM_WRITE_DEADBAND / 2, at=_t.monotonic())
    s = snap(ad)
    s["player"] = {"ptr": ptr, "pos": (0, 0, 0), "rot": 0.0}
    assert "aim_writes" not in M.maintain(ad, s), "under the deadband: no write"
    assert struct.unpack("<f", ad.read_memory(ptr + D.U_YAW, 4))[0] == 0.5



def test_settings_outlive_the_session(ad, tmp_path, monkeypatch):
    """MercMode plays one RE4 round per boot: a setting made in one session is there in the next one."""
    monkeypatch.setattr(M, "SETTINGS_FILE", tmp_path / "re4-mods.json")
    M.run(ad, "one_hit", on=True, snap=snap(ad))
    M.run(ad, "fire_rate", 5, snap=snap(ad))
    M.ORIG.clear()
    st = M._state(ad)
    assert st["one_hit"] is True and st["fire_rate"] == 5.0


def test_pre_round_puts_the_saved_settings_into_the_boot_once(ad, tmp_path, monkeypatch):
    monkeypatch.setattr(M, "SETTINGS_FILE", tmp_path / "re4-mods.json")
    _weapon_tables(ad)
    gap = D.FIRE_GAP_S
    try:
        M.run(ad, "fire_rate", 20, snap=snap(ad))
        M.ORIG.clear()
        monkeypatch.setattr(D, "module_base", lambda m: BASE)
        out = M.pre_round(ad)
        assert out["fire_tables"] == 2 and out["boot"].startswith(hex(BASE))
        assert M.pre_round(ad)["skipped"] == "already put into this boot"
        assert M.status(ad)["pre_round"]["fire_tables"] == 2
    finally:
        D.FIRE_GAP_S = gap


# --- the random weapon in his hand (data writes once the round is live; no code) -----------------------------------
ITEM = 0x5D60000000
PLAYER = 0x5D70000000
TEXT_END = 0x656000                         # main's text segment: module 0 .. here (rodata from 0x656000)


def _armoury(ad, held=0x27, character=0, levels=0x2114):
    """A weapon table with real ids and classes (re4_weapons.CLASS_OF), the item manager holding `held`, the game
    object through its pointer variable."""
    from gbox.mercs.titles import re4_weapons as W
    ids = sorted(W.CLASS_OF)[:W.WEAPON_N]
    caps = {0x37: (3, 4, 5, 6, 8, 10, W.CAP_INFINITE), 0x2D: (7, 9, 12, 14, 17, 20, 100)}
    rows = b"".join(struct.pack("<HBBBBH7H", i, 0, W.CLASS_OF[i], 1 if i == 0x6B else 0, 0, 0x04,
                                *caps.get(i, (5, 6, 7, 8, 9, 10, 0))) for i in ids)
    rows += bytes(W.WEAPON_N * W.WEAPON_SZ - len(rows))
    ad.put(BASE + W.WEAPON_TBL, rows)
    ad.put(BASE + W.GAME_PTR_VAR, struct.pack("<Q", BASE + W.GAME_OBJ))
    g = BASE + W.GAME_OBJ
    blob = bytearray(16)
    blob[W.G_CLASS - 0x5030:W.G_CLASS - 0x5030 + 6] = bytes([W.CLASS_OF.get(held, 0x13), 0, 0, 4, 1, 2])
    blob[W.G_CHARACTER - 0x5030] = character
    blob[W.G_RELOAD - 0x5030] = 1
    ad.put(g + 0x5030, blob)
    ad.put(BASE + W.ITEM_MGR + W.M_EQUIPPED, struct.pack("<QH", ITEM, held) + bytes(6))
    ad.put(ITEM, struct.pack("<HHBBHHBBBB", held, 1, 1, 0, levels, 9 << 3, 0, 0, 0, 1))
    return W


def _round(phase="playing", control=True, clock=True, player=True):
    game = {"phase": phase, "in_control": control and phase == "playing", "clock_running": clock}
    return {"module_base": BASE, "clock_addr": None, "enemies": [], "game": game,
            "player": {"ptr": PLAYER} if player else None}


def _hand(ad, W):
    it = W.decode_item(ad.read_memory(ITEM, W.ITEM_SZ))
    held = struct.unpack("<H", ad.read_memory(BASE + W.ITEM_MGR + W.M_EQUIPPED_ID, 2))[0]
    g = BASE + W.GAME_OBJ
    return it, held, ad.read_memory(g + W.G_CLASS, 6), ad.read_memory(g + W.G_RELOAD, 1)[0]


def test_the_random_weapon_goes_in_his_hand_once_the_round_is_live(ad):
    W = _armoury(ad)
    M._state(ad)["random_weapon"] = True
    for phase in ("none", "intro"):                     # the stage load and the intro card: never written
        assert "weapon_given" not in M.maintain(ad, _round(phase, control=False, clock=False))
    assert M.maintain(ad, _round("playing", clock=False)) == {}, "his clock not running yet"
    assert not ad.writes
    assert M.maintain(ad, _round())["weapon_given"] == 1
    it, held, cls, reload = _hand(ad, W)
    lv = W.max_levels(it["id"])
    assert it["id"] in W.HIGH_POWER and it["id"] != 0x27 and held == it["id"]
    assert it["levels_raw"] == lv["packed"] and not it["empty"] and it["loaded"] > 0
    assert cls == bytes([W.CLASS_OF[it["id"]], 0, 0, lv["firepower"], lv["firing_speed"], lv["capacity"]])
    assert reload == lv["reload"]
    first = it["id"]
    n = len(ad.writes)
    assert "weapon_given" not in M.maintain(ad, _round()) and len(ad.writes) == n, "once a round"
    M.maintain(ad, _round("dead", control=False, clock=False))
    M.maintain(ad, _round("intro", control=False))     # Continue: the game's next round
    assert M.maintain(ad, _round())["weapon_given"] == 1
    assert _hand(ad, W)[0]["id"] != first, "a fresh draw, never the last round's"
    assert M.status(ad)["weapon_given"]["round"] == 2 and M.status(ad)["random_weapon_route"] == "in_hand"


def test_the_playbook_mods_panel_never_sums_a_record(monkeypatch, ad):
    """Live 2026-11-10: the RE4 bot stood there not fighting; the playbook's mission had died with
    ``unsupported operand type(s) for +: 'int' and 'dict'`` because maintain() published a per-round weapon record and
    ``re4switch_bot._maintain_mods`` summed every value. Counters add; records are shown."""
    from gbox import re4switch_bot as B
    from gbox.mercs.titles import re4_switch_mods as M
    monkeypatch.setattr(M, "maintain", lambda a, s: {"weapon_given": 1, "fire_tables": 2,
                                                     "weapon_round": {"round": 3, "name": "Killer7"}})
    stats = {}
    B._maintain_mods(ad, {}, stats)
    assert stats["mods_weapon_given"] == 1 and stats["mods_fire_tables"] == 2
    assert stats["mods_weapon_round"] == {"round": 3, "name": "Killer7"}, "a record is kept as it is, never summed"
    B._maintain_mods(ad, {}, stats)
    assert stats["mods_weapon_given"] == 2, "counters keep adding"


def test_a_random_weapon_is_any_campaign_weapon_with_magnums_and_shotguns_emphasised(ad):
    """The operator 2026-11-10: "the bot firing relentlessly with any weapon type magnum or shotgun with rapid fire";
    2026-11-11: "randomize the weapon being used between rounds between all of the weapons available in the campaign
    at random emphasizing magnums and shotguns". Every round a campaign weapon in his hand, PRIMARY_SHARE of the draws
    a magnum or a shotgun (a magnum MAGNUM_SHARE of those), the rest the other campaign weapons; the fire_rate tables
    written in the same round. A results -> playing round is a new round too (only an intro used to count)."""
    W = _weapon_tables(ad)
    _armoury(ad)                                        # (the real weapon rows back over the fire-rate test's)
    st = M._state(ad)
    st["random_weapon"], st["fire_rate"] = True, 20.0
    gap = D.FIRE_GAP_S
    try:
        draws = []
        for k in range(40):
            assert "weapon_given" not in M.maintain(ad, _round("results", control=False, clock=False))
            out = M.maintain(ad, _round())
            assert out.get("weapon_given") == 1 and out["fire_tables"] == 2, "the tables with the gun"
            assert all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in out.values()), \
                "every maintain value is a counter: the playbook sums them (int + dict killed a live RE4 mission)"
            it, held, _cls, _rel = _hand(ad, W)
            assert it["id"] in W.HIGH_POWER and held == it["id"], "a campaign weapon in his hand"
            assert W.max_levels(it["id"]) is not None
            draws.append(it["id"])
        primary = [i for i in draws if i in M.PRIMARY]
        assert set(primary) & set(M.MAGNUMS) and set(primary) & set(M.SHOTGUNS), "both families come up"
        assert len(primary) >= 25, "magnums/shotguns emphasised (PRIMARY_SHARE 0.8 over 40 draws)"
        assert set(draws) - set(M.PRIMARY), "and the rest of the campaign weapons come up too"
        assert len(draws) == 40 and st["weapon_rounds"][-1]["round"] == 40, "every round, not four a session"
        assert st["rf_tables_round"] == 2 and st["rf_applied_round"] == 40, "the tables with the last round's gun"
        assert st["fire_tables_total"] == 80
        row = struct.unpack("<5f", ad.read_memory(BASE + W.FIRE_RATE_TBL + 2 * 20, 20))
        assert row == (W.RAPID_FIRE_FLOOR,) * 5, "the 20x tables (14 frames / 20 is under the gate: the floor)"
        assert st["weapon_rounds"][-1]["weapon"] == W.name(draws[-1])
        s = M.status(ad)
        assert s["fire_tables_round"] == 2 and s["magnum_share"] == 0.8
        assert len(s["weapon_rounds"]) == 12, "the last rounds' telemetry"
        assert set(s["weapon_primary"]) == {W.name(i) for i in M.PRIMARY}
        assert D.FIRE_GAP_S == max(M.FIRE_GAP_MIN_S, gap / 20), "the trigger taps paced to the 20x"
    finally:
        D.FIRE_GAP_S = gap
        M.run(ad, "fire_rate", 1, snap={"module_base": BASE})


def test_the_chosen_weapon_every_round_with_its_exclusive_magazine(ad):
    W = _armoury(ad, held=0x3E, character=3, levels=0x2204)
    st = M._state(ad)
    st["loadout_weapon"] = 0x37                         # the Handcannon: its exclusive capacity is infinite
    assert M.maintain(ad, _round())["weapon_given"] == 1
    it, held, cls, _ = _hand(ad, W)
    assert it["id"] == held == 0x37 and it["levels_raw"] == W.max_levels(0x37)["packed"] and it["loaded"] == 99
    assert st["weapon_given"]["character"] == "HUNK" and st["weapon_given"]["was"] == "Custom TMP"


class _DropsHeldId(Ad):
    """An emulator that takes every write but the item manager's held id (it reads back the old one)."""
    def write_memory(self, addr, data):
        from gbox.mercs.titles import re4_weapons as W
        if addr == BASE + W.ITEM_MGR + W.M_EQUIPPED_ID:
            self.writes.append((addr, bytes(data)))
            return
        super().write_memory(addr, data)


def test_a_swap_that_does_not_read_back_puts_his_own_weapon_back():
    M.ORIG.clear()
    ad = _DropsHeldId()
    W = _armoury(ad)
    before = ad.read_memory(ITEM, W.ITEM_SZ), ad.read_memory(BASE + W.GAME_OBJ + W.G_CLASS, 6)
    M._state(ad)["random_weapon"] = True
    for _ in range(M.ROUND_WEAPON_TRIES + 2):
        assert "weapon_given" not in M.maintain(ad, _round())
    assert (ad.read_memory(ITEM, W.ITEM_SZ), ad.read_memory(BASE + W.GAME_OBJ + W.G_CLASS, 6)) == before
    given = M._state(ad)["weapon_given"]
    assert given["verified"] is False and "put back" in given["reason"]
    item_writes = [a for a, _ in ad.writes if a == ITEM]
    assert len(item_writes) == 2 * M.ROUND_WEAPON_TRIES, "a swap and its undo per try, then left alone"


def test_no_swap_without_the_games_state_a_player_or_with_a_grenade_in_hand(ad):
    W = _armoury(ad)
    st = M._state(ad)
    st["random_weapon"] = True
    s = _round()
    s.pop("game")
    M.maintain(ad, s)
    M.maintain(ad, _round(player=False))
    st["hand_saved"] = {"item": ITEM}                   # the bot's grenade swap holds his hand
    M.maintain(ad, _round())
    assert not ad.writes
    st.pop("hand_saved")
    ad.put(ITEM, struct.pack("<HHBBHHBBBB", 0x01, 1, 1, 0, 0, 1 << 3, 0, 0, 0, 1))   # a hand grenade in hand
    ad.write_memory(BASE + W.ITEM_MGR + W.M_EQUIPPED_ID, struct.pack("<H", 0x01))
    ad.writes.clear()
    M.maintain(ad, _round())
    assert not ad.writes and "not a gun" in st["weapon_given"]["reason"]


class _CodeAndData(Ad):
    """The loadout function's patchable words (main.bin's) beside the data the mods write."""
    def __init__(self):
        super().__init__()
        from gbox.mercs.titles import re4_weapons as W
        for slots in W.LOADOUT_SLOTS.values():
            for s in slots:
                for off, _, orig in s["code"]:
                    self.put(BASE + off, struct.pack("<I", orig))


def test_pre_round_writes_no_code_and_the_weapon_still_comes(tmp_path, monkeypatch):
    """Regression (2026-11-10, every boot with random_weapon hung at the stage load): the loadout is never code."""
    monkeypatch.setattr(M, "SETTINGS_FILE", tmp_path / "re4-mods.json")
    monkeypatch.setattr(D, "module_base", lambda m: BASE)
    M.ORIG.clear()
    ad = _CodeAndData()
    W = _armoury(ad)
    _weapon_tables(ad)
    _armoury(ad)                                        # (the real weapon rows back over the fire-rate test's)
    code = {a: bytes(d) for a, d in ad.at.items() if a - BASE < TEXT_END}
    gap = D.FIRE_GAP_S
    try:
        M.run(ad, "random_weapon", on=True, snap=_round("none"))
        M.run(ad, "fire_rate", 5, snap=_round("none"))
        M.ORIG.clear()
        ad.writes.clear()
        out = M.pre_round(ad)
        assert out["loadout_route"] == "in_hand" and "LOADOUT_CODE_PATCH" in out["loadout_code"]
        assert out["fire_tables"] == 2
        assert not [a for a, _ in ad.writes if BASE <= a < BASE + TEXT_END], "no write into main's code"
        assert {a: bytes(d) for a, d in ad.at.items() if a - BASE < TEXT_END} == code
        assert M.maintain(ad, _round())["weapon_given"] == 1 and _hand(ad, W)[0]["id"] in W.HIGH_POWER
    finally:
        D.FIRE_GAP_S = gap


def test_the_code_patch_stays_refused_under_nce_even_when_turned_on(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "SETTINGS_FILE", tmp_path / "re4-mods.json")
    monkeypatch.setattr(M, "LOADOUT_CODE_PATCH", True)
    M.ORIG.clear()
    ad = _CodeAndData()
    ad.use_nce = True
    assert "NCE" in M._code_patch_refusal(ad)
    out = M.loadout_weapon(ad, 0x37, snap={"module_base": BASE})
    assert out["route"] == "in_hand" and not [a for a, _ in ad.writes if a - BASE < TEXT_END]
    ad.use_nce = False
    assert M._code_patch_refusal(ad) is None


class _Ladders(_Walls):
    """Every line walled, one ladder down 2 m away (approach at +x) and one 5 m away on the Ganados' side."""
    def __init__(self):
        super().__init__(None)
        self.crossing_rows = {
            4: {"kind": "ladder", "direction": "down", "approach": [2000.0, 0.0, 0.0], "landing": [2000.0, -4000.0, 0.0]},
            5: {"kind": "ladder", "direction": "up", "approach": [500.0, 0.0, 0.0], "landing": [500.0, 4000.0, 0.0]},
            6: {"kind": "ladder", "direction": "down", "approach": [0.0, 0.0, 1800.0], "landing": [0.0, -4000.0, 1800.0]},
        }


def test_walled_in_he_takes_the_ladder_down_he_reaches_before_the_ganados():
    b = D.Bot(stats={}, director=False)
    p = {"pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 300, "hp_max": 1680, "ptr": 1}
    live = b._live(p, [{"pos": (0.0, 0.0, 1500.0), "hp": 400, "ptr": 9}])
    assert b._escape_goal(p, live, {"nav": _Ladders()}) == (2000.0, -4000.0, 0.0)   # not the up ladder, not the foe's
    assert b.stats["escape_ladders"] == 1 and "escapes_walled_in" not in b.stats
    far = D.Bot(stats={}, director=False)
    onfloor = {"pos": (0.0, -5000.0, 0.0), "rot": 0.0, "hp": 300, "hp_max": 1680, "ptr": 1}
    assert far._escape_goal(onfloor, far._live(onfloor, []), {"nav": _Ladders()}) is None   # another floor


def test_every_recorded_down_ladder_is_an_escape_from_beside_its_approach():
    """The committed stage data (re4_switch_nav r400/r403/r404): beside each down ladder's approach, walled in, the
    landing is the escape goal. Castle (r402) has no ladder data: not determined, no goal."""
    from gbox.mercs.titles import re4_nav
    seen = {}
    for room in ("r400", "r402", "r403", "r404"):
        nav = re4_nav.load(room)
        if nav is None:
            continue
        nav.clear_segment = lambda a, b: False
        downs = [r for r in nav.crossing_rows.values() if r.get("kind") == "ladder" and r.get("direction") == "down"]
        seen[room] = len(downs)
        for r in downs:
            ap = r["approach"]
            b = D.Bot(stats={}, director=False)
            p = {"pos": (ap[0] + 300.0, ap[1], ap[2]), "rot": 0.0, "hp": 300, "hp_max": 1680, "ptr": 1}
            live = b._live(p, [{"pos": (ap[0] + 4000.0, ap[1], ap[2]), "hp": 400, "ptr": 9}])
            goal = b._escape_goal(p, live, {"nav": nav})
            assert goal is not None and goal[1] == float(r["landing"][1]) or any(
                abs(goal[1] - float(o["landing"][1])) < 1 for o in downs if o is not r), (room, r["source"])
    assert seen.get("r403") == 9 and seen.get("r404") == 8 and seen.get("r402", 0) == 0


def test_fire_tables_are_retried_when_the_first_write_reads_nothing(ad, tmp_path, monkeypatch):
    """Hermes #9560 (ported): maintain marked the boot's 20x tables done with 0 tables written, so the rate never
    landed until a round's own give. The boot is marked only once a table reads back; retries are paced."""
    monkeypatch.setattr(M, "SETTINGS_FILE", tmp_path / "re4-mods.json")
    monkeypatch.setattr(M, "FIRE_RETRY_S", 0.0)
    gap = D.FIRE_GAP_S
    st = M._state(ad)
    st["fire_rate"] = 20.0
    try:
        assert M.maintain(ad, _round("none", control=False, clock=False)).get("fire_tables", 0) == 0
        assert st.get("rf_applied_boot") is None, "nothing read back: the boot is not marked done"
        assert st["fire_tries"] == 1
        _weapon_tables(ad)
        out = M.maintain(ad, _round("none", control=False, clock=False))
        assert out["fire_tables"] > 0 and st["rf_applied_boot"] is not None and st["fire_tries"] == 2
        assert "fire_tables" not in M.maintain(ad, _round("none", control=False, clock=False)), "done for this boot"
    finally:
        D.FIRE_GAP_S = gap
