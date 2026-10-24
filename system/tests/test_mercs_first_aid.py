"""The autobot's infinite First Aid Spray: RE4 heals by a verified hp write when low; RE5 gets a spray record in every
loadout template and replays the game-made inventory record after use. Never immortality, never while dead."""
import struct

import pytest

from gbox import re_mods_tool as RM
from gbox import re5_mods_tool as R5


class FakeRE4(RM.RE4):
    """RE4 over a dict of bytes: only what maintain_first_aid touches (pG and Leon's hp)."""
    PG = 0x80400000

    def __init__(self, hp):
        self.ad = object()
        self.state = RM.STATE.setdefault(id(self.ad), {})
        self.V = RM.R.GC
        self.ram = {}
        self.m = self
        self.put(self.PG + self.V.G_HP, struct.pack(">h", hp))

    def put(self, a, data):
        for i, b in enumerate(data):
            self.ram[a + i] = b

    def rd(self, a, n):
        return bytes(self.ram.get(a + i, 0) for i in range(n))

    def wr(self, a, data):
        self.put(a, data)
        return self.rd(a, len(data)) == data

    def pg(self):
        return self.PG

    def hp(self):
        return struct.unpack(">h", self.rd(self.PG + self.V.G_HP, 2))[0]


def snap(hp, room=0x400, timer=90.0):
    return {"room": room, "hp": hp, "player": {"ptr": 0x80500000}, "timer": timer}


def test_re4_first_aid_heals_only_low_living_leon_in_a_round_with_cooldown():
    g = FakeRE4(1200)
    assert RM.maintain_first_aid(g, snap(1200), now=0)["auto_first_aid"] is False        # off: nothing happens
    RM.auto_first_aid(g, True)
    assert RM.maintain_first_aid(g, snap(1200), round_id=1, now=0)["healed"] is False      # full health
    g.put(g.PG + g.V.G_HP, struct.pack(">h", 300))
    s = snap(300)
    r = RM.maintain_first_aid(g, s, round_id=1, now=1)
    assert r["healed"] and g.hp() == 1200 and s["hp"] == 1200 and r["sprays_used"] == 1
    g.put(g.PG + g.V.G_HP, struct.pack(">h", 200))
    assert RM.maintain_first_aid(g, snap(200), round_id=1, now=2)["healed"] is False        # cooldown 2.5 s
    assert RM.maintain_first_aid(g, snap(200), round_id=1, now=4)["healed"] is True
    g.put(g.PG + g.V.G_HP, struct.pack(">h", 0))
    assert RM.maintain_first_aid(g, snap(0), round_id=1, now=9)["healed"] is False          # dead: Continue is the bot's
    assert g.hp() == 0
    g.put(g.PG + g.V.G_HP, struct.pack(">h", 100))
    assert RM.maintain_first_aid(g, snap(100, room=0x120), round_id=1, now=20)["healed"] is False   # not Mercenaries
    assert RM.maintain_first_aid(g, snap(100, timer=0), round_id=1, now=21)["healed"] is False      # results
    RM.auto_first_aid(g, False)
    assert RM.maintain_first_aid(g, snap(100), round_id=1, now=30)["auto_first_aid"] is False


def test_re4_first_aid_rereads_before_writing_and_validates_settings():
    g = FakeRE4(1200)
    RM.auto_first_aid(g, True, threshold=0.5)
    g.put(g.PG + g.V.G_HP, struct.pack(">h", 1000))                 # recovered between snapshot and write
    assert RM.maintain_first_aid(g, snap(400), round_id=2, now=0)["healed"] is False and g.hp() == 1000
    with pytest.raises(ValueError):
        RM.auto_first_aid(g, True, threshold=1.5)
    with pytest.raises(ValueError):
        RM.auto_first_aid(g, True, cooldown_s=0.1)


def record(idw, count=0, grid=0, hand=0, levels=0):
    return struct.pack(">11I", idw, count, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, grid, hand, levels, 0, 0, 0)


def template(blocks):
    t = bytearray(R5.TEMPLATE_BLOCKS * R5.TEMPLATE_BLOCK)
    for b, recs in blocks.items():
        for r, rec in enumerate(recs):
            t[b * R5.TEMPLATE_BLOCK + r * R5.TEMPLATE_REC:][:R5.TEMPLATE_REC] = rec
            off = b * R5.TEMPLATE_BLOCK + r * R5.TEMPLATE_REC
            t[off:off + R5.TEMPLATE_REC] = rec
    return bytes(t)


def test_re5_template_gains_one_spray_per_block_from_ammo_then_herb_and_keeps_existing_sprays():
    gun, ammo, herb = record(0x102, 15, 0, 1), record(0x202, 60, 1), record(0x305, 1, 3)
    t = template({0: [gun, ammo, herb], 1: [gun, herb], 2: [gun, record(0x304, 1, 5)]})
    out, converted, skipped = R5.spray_overlay(t, None)
    sprays = {off // R5.TEMPLATE_BLOCK for off, idw, *_ in R5.template_records(bytes(out)) if idw == R5.SPRAY_ID}
    assert {0, 1, 2} <= sprays
    by_block = {c["block"]: c for c in converted}
    assert by_block[0]["source"] == "ammo" and by_block[0]["grid"] == 1
    assert by_block[1]["source"] == "herb" and 2 not in by_block            # block 2 already carries one
    assert any(idw == 0x102 for off, idw, *_ in R5.template_records(bytes(out)) if off // R5.TEMPLATE_BLOCK == 0)


class FakeInv:
    """RE5's player inventory region for _maintain_spray."""
    PL = 0x31000000

    def __init__(self):
        self.ram = bytearray(R5.INV_SLOTS * R5.SLOT)
        self.hp = (500, 1000)

    def slot(self, k, idw, count=1, grid=2, hand=0):
        s = bytearray(R5.SLOT)
        struct.pack_into(">I", s, R5.SLOT_ID, idw)
        struct.pack_into(">I", s, R5.SLOT_COUNT, count)
        struct.pack_into(">I", s, R5.SLOT_GRID, grid)
        struct.pack_into(">I", s, R5.SLOT_HAND, hand)
        s[R5.SLOT_USED] = 1
        self.ram[k * R5.SLOT:(k + 1) * R5.SLOT] = s

    def free(self, k):
        self.ram[k * R5.SLOT:(k + 1) * R5.SLOT] = bytes(R5.SLOT)

    def rd(self, a, n):
        if a == self.PL + R5.P_HP:
            return struct.pack(">hh", *self.hp)
        o = a - (self.PL + R5.INV_OFS)
        return bytes(self.ram[o:o + n])

    def wr(self, a, data):
        o = a - (self.PL + R5.INV_OFS)
        self.ram[o:o + len(data)] = data
        return True


def test_re5_spray_record_is_replayed_byte_for_byte_only_into_its_free_slot(monkeypatch):
    g = FakeInv()
    monkeypatch.setattr(R5, "_health_player", lambda _g: g.PL)
    state = {"on": True}
    g.slot(4, R5.SPRAY_ID, grid=5)
    original = bytes(g.ram[4 * R5.SLOT:5 * R5.SLOT])
    r = R5._maintain_spray(g, state, None, now=0)
    assert r["carried"] == 1 and state["spray_record"]["slot"] == 4          # remembered while carried
    g.free(4)                                                                  # the bot used it
    r = R5._maintain_spray(g, state, None, now=1)
    assert r["restored"] and bytes(g.ram[4 * R5.SLOT:5 * R5.SLOT]) == original and state["restored"] == 1
    g.free(4)
    assert R5._maintain_spray(g, state, None, now=2)["restored"] is False      # replayed: wait for the game to hold it
    R5._maintain_spray(g, state, None, now=2.1)
    g.slot(4, R5.SPRAY_ID, grid=5)
    R5._maintain_spray(g, state, None, now=3)                                  # re-armed by the game-held record
    g.free(4)
    g.slot(4, 0x202, count=30, grid=1)                                         # the slot now holds ammo
    r = R5._maintain_spray(g, state, None, now=10)
    assert r["restored"] is False and "in use" in r["reason"]
    g.free(4)
    g.slot(6, 0x305, grid=7)                                                   # carrying a herb: no replay needed
    assert R5._maintain_spray(g, state, None, now=20)["restored"] is False
    g.free(6)
    g.hp = (0, 1000)                                                           # dead
    assert R5._maintain_spray(g, state, None, now=30)["restored"] is False


def test_re5_spray_is_never_created_without_a_game_made_record(monkeypatch):
    g = FakeInv()
    monkeypatch.setattr(R5, "_health_player", lambda _g: g.PL)
    r = R5._maintain_spray(g, {"on": True}, None, now=0)
    assert r["restored"] is False and "no game-created" in r["reason"] and not any(g.ram)
