"""RE4 Switch: the bow (and the grenades) fired fire_rate x faster (re4_switch_mods._motion_rate; the operator
2026-11-10 #9508 "fire the bow 20x faster"), and its arrows kept (_keep_arrows) - on synthetic guest memory. The
offsets are static (main.bin against the GameCube decompilation); nothing here is a claim about a live round."""
import struct

import pytest

from gbox.mercs.titles import re4_switch as D
from gbox.mercs.titles import re4_switch_mods as M
from gbox.mercs.titles import re4_weapons as W

BASE = 0x3CA7C04000
PLAYER, WEP, OBJ, ITEMS, BOW_ITEM = 0x5D50100000, 0x5D50200000, 0x5D50300000, 0x5D50400000, 0x5D50500000


class Ad:
    def __init__(self):
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


def f32(ad, addr):
    return struct.unpack("<f", ad.read_memory(addr, 4))[0]


def world(routine=(0, 6, 2, 1), speed=1.0, obj_speed=1.0):
    ad = Ad()
    unit = bytearray(D.UNIT_SIZE)
    unit[W.P_ROUTINE:W.P_ROUTINE + 4] = bytes(routine)
    struct.pack_into("<f", unit, W.P_MOTION_SPEED, speed)
    struct.pack_into("<Q", unit, D.PL_WEP, WEP)
    ad.put(PLAYER, unit)
    wep = bytearray(0x60)
    struct.pack_into("<Q", wep, D.WEP_OBJ, OBJ)
    ad.put(WEP, wep)
    obj = bytearray(0x500)
    struct.pack_into("<f", obj, W.OBJ_MOTION_SPEED, obj_speed)
    ad.put(OBJ, obj)
    return ad


def snap(cls=0x1C):
    return {"module_base": BASE, "weapon_class": cls, "enemies": [],
            "player": {"ptr": PLAYER, "pos": (0.0, 0.0, 0.0), "rot": 0.0}}


def set_routine(ad, routine):
    ad.at[PLAYER][W.P_ROUTINE:W.P_ROUTINE + 4] = bytes(routine)


def test_the_bows_weapon_routine_plays_x_the_fire_rate_and_goes_back_after():
    ad = world()
    st = {"fire_rate": 20.0}
    assert M._motion_rate(ad, snap(), st) == 2
    assert f32(ad, PLAYER + W.P_MOTION_SPEED) == 20.0 and f32(ad, OBJ + W.OBJ_MOTION_SPEED) == 20.0
    assert st["motion_rate"]["kind"] == "bow"
    n = len(ad.writes)
    assert M._motion_rate(ad, snap(), st) == 0 and len(ad.writes) == n, "ours already: nothing written again"
    struct.pack_into("<f", ad.at[PLAYER], W.P_MOTION_SPEED, 1.0)       # the next shot's motion set it back
    assert M._motion_rate(ad, snap(), st) == 1 and f32(ad, PLAYER + W.P_MOTION_SPEED) == 20.0
    set_routine(ad, (0, 1, 0, 0))                                      # the bow put away: walking
    M._motion_rate(ad, snap(), st)
    assert f32(ad, PLAYER + W.P_MOTION_SPEED) == 1.0 and f32(ad, OBJ + W.OBJ_MOTION_SPEED) == 1.0
    assert st["motion_rate"] is None and st["motion_rate_restores"] == 1


def test_a_gun_or_no_fire_rate_leaves_every_motion_alone():
    for cls, mult in ((0x05, 20.0), (0x1C, 1.0)):
        ad = world()
        M._motion_rate(ad, snap(cls), {"fire_rate": mult})
        assert not ad.writes, (cls, mult)


def test_a_speed_the_game_set_since_is_never_overwritten_on_the_way_out():
    ad = world()
    st = {"fire_rate": 10.0}
    M._motion_rate(ad, snap(), st)
    struct.pack_into("<f", ad.at[PLAYER], W.P_MOTION_SPEED, 0.5)       # the game's own (a hit's slow motion)
    set_routine(ad, (0, 1, 0, 0))
    M._motion_rate(ad, snap(), st)
    assert f32(ad, PLAYER + W.P_MOTION_SPEED) == 0.5
    assert f32(ad, OBJ + W.OBJ_MOTION_SPEED) == 1.0


def test_a_field_that_is_not_a_speed_is_refused_cleanly():
    ad = world(speed=float("nan"), obj_speed=1234.0)
    st = {"fire_rate": 20.0}
    assert M._motion_rate(ad, snap(), st) == 0 and not ad.writes
    assert st["motion_rate_refused"] == 2 and "not a motion speed" in st["motion_rate_refused_last"]
    ad2 = Ad()                                                         # no player unit mapped at all
    assert M._motion_rate(ad2, snap(), {"fire_rate": 20.0}) == 0


def test_the_kind_needs_the_class_and_the_weapon_routine():
    assert W.motion_rate_kind(0x1C, (0, 6, 2, 1)) == "bow"
    assert W.motion_rate_kind(0x1C, (0, 6, 1, 0)) == "bow"             # the set state: the next shot starts fast
    assert W.motion_rate_kind(0x13, (0, 6, 2, 0)) == "hand grenade"
    assert W.motion_rate_kind(0x1C, (0, 1, 0, 0)) is None              # walking
    assert W.motion_rate_kind(0x05, (0, 6, 2, 0)) is None              # a gun: its table paces it
    assert W.motion_rate_kind(None, (0, 6, 2, 0)) is None and W.motion_rate_kind(0x1C, ()) is None


def test_maintain_runs_it_with_the_fire_rate_and_status_reports_it():
    ad = world()
    M.ORIG.clear()
    st = M._state(ad)
    st["fire_rate"] = 20.0
    st["rf_applied_boot"] = st["boot"] = M._boot(ad, BASE)             # (the tables are not mapped in this guest)
    out = M.maintain(ad, snap())
    assert out.get("motion_rate_writes") == 2
    s = M.status(ad)
    assert s["motion_rate_on"] == "bow" and s["motion_rate_writes"] == 2


def arrows_world(counts):
    ad = Ad()
    mgr = bytearray(0x40)
    struct.pack_into("<Q", mgr, W.M_EQUIPPED, BOW_ITEM)
    struct.pack_into("<H", mgr, W.M_EQUIPPED_ID, 0x52)
    struct.pack_into("<Q", mgr, W.M_ITEMS, ITEMS)
    struct.pack_into("<i", mgr, W.M_SLOTS, 4)
    ad.put(BASE + W.ITEM_MGR, mgr)
    items = bytearray(4 * W.ITEM_SZ)
    struct.pack_into("<HHBB", items, 0, 0x52, 1, 1, 0)
    for k, c in enumerate(counts, start=1):
        struct.pack_into("<HHBB", items, k * W.ITEM_SZ, W.ARROWS, c, 1, 0)
    ad.put(ITEMS, items)
    ad.put(BOW_ITEM, bytes(items[:W.ITEM_SZ]))
    return ad


def test_the_arrows_are_kept_at_the_most_each_stack_held():
    ad = arrows_world((20, 10))
    st = {}
    assert M._keep_arrows(ad, BASE, st) == 0                           # full: nothing to do, the tops noted
    struct.pack_into("<H", ad.at[ITEMS], W.ITEM_SZ + 2, 3)            # three left in the first stack
    assert M._keep_arrows(ad, BASE, st) == 1
    assert struct.unpack_from("<H", ad.at[ITEMS], W.ITEM_SZ + 2)[0] == 20
    assert struct.unpack_from("<H", ad.at[ITEMS], 2 * W.ITEM_SZ + 2)[0] == 10


def test_the_bow_can_play_at_forty_times_the_rate():
    """Operator 2026-11-11: "the character with the bow rapid firing arrows at 40 times a second" - the bow's motion
    rate cap is 40x and the trigger gap floor 0.025 s (the playbook's bow tick is BOW_FIGHT_TICK_S = 0.025)."""
    assert M.MOTION_RATE_MAX_X == 40.0 and M.FIRE_RATE_MAX_X == 40.0 and M.FIRE_GAP_MIN_S == 0.025
    ad = world()
    st = {"fire_rate": 40.0}
    assert M._motion_rate(ad, snap(), st) == 2
    assert f32(ad, PLAYER + W.P_MOTION_SPEED) == 40.0 and f32(ad, OBJ + W.OBJ_MOTION_SPEED) == 40.0
