"""RE4: a Ganado's hold is a QTE, and its status bit is cleared rather than mashed.

The operator, 2026-11-12: "the bot is still failing QTE events ... make sure that they always succeed and that the bot
is fully reactive to QTE events no matter what, and they never fail." Status_flg is u32[4] at player + PG_STATUS and a
hold is word 1 & 0x8000 (re4_switch.STA_PL_CATCHED); the game's own mash frees him through that same flag, so clearing
it ends the hold whatever the input timing.
"""
import struct

from gbox.mercs.titles import re4_switch as D
from gbox.mercs.titles import re4_switch_mods as M

PTR = 0x10000000                      # inside ptr_ok's range


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


def world(status_words):
    ad = Ad()
    ad.put(PTR + D.PG_STATUS, struct.pack("<4I", *status_words))
    return ad, {"player": {"ptr": PTR}}


def test_a_hold_is_cleared_and_nothing_else_in_the_word_changes():
    ad, snap = world((0xDEADBEEF, 0x8001, 0x1234, 0x5678))          # word 1: caught (0x8000) plus a held 0x0001
    assert M._unstick(ad, snap) == 1
    now = struct.unpack("<I", ad.read_memory(PTR + D.PG_STATUS + 4, 4))[0]
    assert not now & D.STA_PL_CATCHED[1], "the caught bit is gone: he is not held any more"
    assert now == 0x0001, "the rest of the word is untouched"
    assert struct.unpack("<I", ad.read_memory(PTR + D.PG_STATUS, 4))[0] == 0xDEADBEEF
    assert struct.unpack("<I", ad.read_memory(PTR + D.PG_STATUS + 8, 4))[0] == 0x1234


def test_an_unheld_player_is_left_alone():
    ad, snap = world((1, 2, 3, 4))
    assert M._unstick(ad, snap) == 0 and not ad.writes


def test_no_player_pointer_writes_nothing():
    ad, _ = world((0, 0x8000, 0, 0))
    assert M._unstick(ad, {}) == 0 and M._unstick(ad, {"player": {"ptr": 5}}) == 0
    assert not ad.writes
