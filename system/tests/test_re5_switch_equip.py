"""RE5 Switch RAM equip (re5_switch_equip): put any inventory slot in hand by writing INV_HAND directly - no D-pad
tap, so a weapon parked on a non-QUICK grid (2/4/6/8/0) is reachable, and the held slot is cleared in one tick.

The module's invoke gate is the same as aim_writer (adapter + mercs_no_modifications), and every write is read back:
a failed read-back leaves verified False so the bot keeps its D-pad fallback. Off in play until a live round shows the
writes hold (no private slot - the same UNVERIFIED contract as the aim lock)."""
import struct

import pytest

from gbox.mercs.titles import re5_switch as R
from gbox.mercs.titles import re5_switch_equip as E

BASE, PLAYER = 0x3CA7C04000, 0x5D30000000
P_INV = PLAYER + R.P_INV


class Guest:
    def __init__(self, sticky=True):
        self.mem, self.sticky, self.writes = {}, sticky, []

    def put(self, a, data):
        for i, b in enumerate(data):
            self.mem[a + i] = b

    def q(self, a, v):
        self.put(a, struct.pack("<Q", v))

    def rd(self, a, n):
        return bytes(self.mem.get(a + i, 0) for i in range(n))

    read_memory = rd

    def write_memory(self, a, data):
        self.writes.append((a, bytes(data)))
        if self.sticky:
            self.put(a, data)


class Session:
    def __init__(self, g):
        self.adapter, self.rd = g, g.rd


def slot(g, k, item, grid=1, hand=0):
    """Write one inventory slot record at index k (id word + grid + hand); id = item | (type << 8)."""
    a = P_INV + R.INV_SLOT * k
    g.put(a + R.INV_ID, struct.pack("<I", item))
    g.put(a + R.INV_GRID, struct.pack("<i", grid))
    g.put(a + R.INV_HAND, struct.pack("<i", hand))


def guest(items=None):
    """A session whose inventory holds the given (k, item, grid, hand) records; player pointer resolved."""
    g = Guest()
    # module_base caches on m and re-checks a signature; avoid it: we call instant_equip with a resolved player
    for k, item, grid, hand in items or []:
        slot(g, k, item, grid, hand)
    return g


def read_hand(g, k):
    return struct.unpack_from("<i", g.rd(P_INV + R.INV_SLOT * k + R.INV_HAND, 4))[0]


def test_equips_a_non_quick_slot_by_writing_its_hand(monkeypatch):
    monkeypatch.setattr(R, "module_base", lambda m: BASE)
    g = guest([(2, 0x1A2B, 2, 0), (5, 0x1A2C, 5, 1)])      # 0x2B on grid 2 (no D-pad), 0x2C held on grid 5
    r = E.instant_equip(Session(g), PLAYER, 0x2B)
    assert r["equipped"] == 0x2B and r["verified"] and r["cleared"] == [5] and r["held_slot"] == 2
    assert read_hand(g, 2) == 1 and read_hand(g, 5) == 0


def test_already_held_is_a_no_op(monkeypatch):
    monkeypatch.setattr(R, "module_base", lambda m: BASE)
    g = guest([(2, 0x1A2B, 2, 1)])
    r = E.instant_equip(Session(g), PLAYER, 0x2B)
    assert r["equipped"] == 0x2B and r["verified"] and r["cleared"] == [] and r["held_slot"] == 2
    assert g.writes == []                                    # nothing written


def test_a_missing_item_does_not_clobber_what_is_in_hand(monkeypatch):
    monkeypatch.setattr(R, "module_base", lambda m: BASE)
    g = guest([(5, 0x1A2C, 5, 1)])                           # 0x2C held
    r = E.instant_equip(Session(g), PLAYER, 0x2B)            # 0x2B not owned
    assert r["equipped"] is None and not r["verified"] and r["cleared"] == []
    assert read_hand(g, 5) == 1                              # the held slot is untouched


def test_item_none_clears_the_held_slot(monkeypatch):
    monkeypatch.setattr(R, "module_base", lambda m: BASE)
    g = guest([(5, 0x1A2C, 5, 1)])
    r = E.instant_equip(Session(g), PLAYER, None)
    assert r["equipped"] is None and r["verified"] and r["cleared"] == [5] and r["held_slot"] is None
    assert read_hand(g, 5) == 0


def test_a_write_that_does_not_hold_is_a_failure(monkeypatch):
    monkeypatch.setattr(R, "module_base", lambda m: BASE)
    g = guest([(2, 0x1A2B, 2, 0)])
    g.sticky = False                                          # the write never lands
    r = E.instant_equip(Session(g), PLAYER, 0x2B)
    assert r["equipped"] == 0x2B and not r["verified"]


def test_no_hook_without_an_adapter_or_with_modifications_off(monkeypatch):
    monkeypatch.setattr(R, "module_base", lambda m: BASE)
    g = guest([(2, 0x1A2B, 2, 0)])
    assert E.instant_equip(object(), PLAYER, 0x2B) is None
    s = Session(g)
    s.mercs_no_modifications = True
    assert E.instant_equip(s, PLAYER, 0x2B) is None
