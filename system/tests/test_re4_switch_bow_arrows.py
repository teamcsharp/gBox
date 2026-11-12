"""RE4 Switch: the bow's arrows never run out (_keep_arrows) - on synthetic guest memory.

Live 2026-11-12, the operator: "rain arrows at enemies defending themselves effortlessly". _keep_arrows refilled only
when 0 < count < top, so a stack that reached 0 stayed at 0 and the bow was dry for the rest of the round - and at
BOW_MOTION_X 40 arrows a second a 30-arrow stack empties in under a second.
"""
import struct

from gbox.mercs.titles import re4_switch as D
from gbox.mercs.titles import re4_switch_mods as M
from gbox.mercs.titles import re4_weapons as W

BASE = 0x3CA7C04000
PLAYER, WEP, OBJ = 0x5D50100000, 0x5D50200000, 0x5D50300000
MGR, ARR = BASE + W.ITEM_MGR, 0x5D50600000


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


def bow_world(equipped=0x52, arrows=20):
    """The player, his weapon object and the item case: slot 0 the arrows, slot 1 the equipped bow."""
    ad = Ad()
    unit = bytearray(D.UNIT_SIZE)
    unit[W.P_ROUTINE:W.P_ROUTINE + 4] = bytes((0, 6, 2, 1))          # the bow's weapon routine
    struct.pack_into("<Q", unit, D.PL_WEP, WEP)
    ad.put(PLAYER, unit)
    wep = bytearray(0x60)
    struct.pack_into("<Q", wep, D.WEP_OBJ, OBJ)
    ad.put(WEP, wep)
    ad.put(OBJ, bytearray(0x40))
    mgr = bytearray(0x40)
    struct.pack_into("<Q", mgr, W.M_EQUIPPED, ARR + W.ITEM_SZ)       # the item in his hand
    struct.pack_into("<H", mgr, W.M_EQUIPPED_ID, equipped)
    struct.pack_into("<Q", mgr, W.M_ITEMS, ARR)
    struct.pack_into("<i", mgr, W.M_SLOTS, 2)
    struct.pack_into("<B", mgr, W.M_OWNER, 0)
    ad.put(MGR, mgr)
    arr = bytearray(2 * W.ITEM_SZ)
    struct.pack_into("<HHBB", arr, 0, W.ARROWS, arrows, 1, 0)         # id, count, in use, owner
    struct.pack_into("<HHBB", arr, W.ITEM_SZ, equipped, 1, 1, 0)      # the bow itself, equipped
    ad.put(ARR, arr)
    return ad


def arrows_at(ad):
    return struct.unpack_from("<H", ad.at[ARR], 2)[0]


def set_arrows(ad, n):
    struct.pack_into("<H", ad.at[ARR], 2, n)


def test_the_bows_arrows_come_back_from_empty():
    ad = bow_world(arrows=20)
    st = {}
    assert M._keep_arrows(ad, BASE, st) == 0, "a full stack needs nothing"
    set_arrows(ad, 0)                                     # the last arrow left: the bow was dry from here on
    assert M._keep_arrows(ad, BASE, st) == 1, "an empty stack is refilled, not left dry"
    assert arrows_at(ad) == 20
    set_arrows(ad, 3)
    assert M._keep_arrows(ad, BASE, st) == 1
    assert arrows_at(ad) == 20


def test_a_gun_in_his_hand_keeps_no_arrows():
    ad = bow_world(equipped=0x29, arrows=0)               # the Handcannon: its magazine is _keep_mag's job
    assert M._keep_arrows(ad, BASE, {}) == 0
