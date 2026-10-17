"""Focused tests for the pso_mods dupe op: item-record extraction, exact clone via give_records, ids, equip.

A FakeMem models the parts of PSO DC v2 RAM the tool touches and simulates the game thread running a queued
call batch (like TObjPlayer::update does), so give/dupe execute end-to-end without an emulator.
"""
import struct

import pytest

from gbox.pso_mods_tool import (BUF, CAVE, CAVE2, F_EQUIP, ID_BASE, ITEM_FLAGS, ITEM_RECORD, NEXT_ID, ORIG_UPDATE,
                                PLAYER_TBL, PLY_ITEM, PSO, QUEUE, SIGNATURE, VT_UPDATE, give_addr, speed_code,
                                stub_code)

PLAYER = 0x8C100000
TPLYITEM = 0x8C110000
ROOT = 0x8C110100
NODE = 0x8C110200
OBJ = 0x8C120000
VT = 0x8C130000
SRC_ID = 0xA0000001

# 20-byte item record: DB's Saber (000105), some %-stats, grind 0x5A, stack 1, id 0xA0000001 (little-endian, as
# item_data packs it), trailing bytes 0xDEADBEEF
REC = bytes([0x00, 0x01, 0x05, 0x19, 0x5A, 1, 0x5A, 0x33, 0x00, 0x00, 0x00, 0x00,
             0x01, 0x00, 0x00, 0xA0, 0xDE, 0xAD, 0xBE, 0xEF])


class FakeMem:
    """Dict-addressed RAM; when the QUEUE count is written, 'the game' runs the batch like the dispatcher does."""

    def __init__(self):
        self.mem = {}
        self.seq = 0
        self.put(SIGNATURE[0], SIGNATURE[1])
        self.put(CAVE, stub_code())
        self.put(CAVE2, speed_code())
        self.put(VT_UPDATE, struct.pack("<I", ORIG_UPDATE))
        self.put(PLAYER_TBL, struct.pack("<I", PLAYER))
        self.put(NEXT_ID, struct.pack("<I", ID_BASE))
        self.put(PLAYER + PLY_ITEM, struct.pack("<I", TPLYITEM))
        self.put(TPLYITEM + 0x14, struct.pack("<I", ROOT))
        self.put(ROOT + 0x14, struct.pack("<I", NODE))
        self.put(NODE + 0x8, b"\0" * 4)
        self.put(NODE + 0xC, b"\0" * 4)
        self.put(NODE + 0x20, struct.pack("<I", OBJ))
        self.put(OBJ, struct.pack("<I", VT))
        self.put(VT, b"TWeaponItem\0" + b"\0" * 21)          # 32-byte class name

    def put(self, a, data):
        for i, b in enumerate(data):
            self.mem[a + i] = b

    def read(self, a, n):
        return bytes(self.mem.get(a + i, 0) for i in range(n))

    def write(self, a, data):
        self.put(a, data)
        if a == QUEUE:                                        # the game thread runs the batch immediately
            self.seq += 1
            self.put(QUEUE + 4, struct.pack("<I", self.seq))
            self.put(QUEUE, b"\0" * 4)
            for i in range(data[0] if data else 0):
                e = QUEUE + 8 + 24 * i
                fn = struct.unpack("<I", self.read(e, 4))[0]
                if fn == F_EQUIP:                             # the 6x25 path: equip slot pointer = item object
                    p, obj, slot = struct.unpack("<3I", self.read(e + 4, 12))
                    self.put(p + [0xBD0, 0xBD4, 0xBE4][slot], struct.pack("<I", obj))
                self.put(e + 20, struct.pack("<I", fn))       # result: the called function's address


def set_item(fake, record: bytes, id_: int, flags: int = 1):
    for i, b in enumerate(record):
        fake.mem[OBJ + ITEM_RECORD + 2 * i] = b               # data bytes spaced 2 apart, like a real TItem
    fake.put(OBJ + 0xE8, struct.pack("<I", id_))
    fake.put(OBJ + ITEM_FLAGS, struct.pack("<I", flags))


def test_item_record_interleave():
    fake = FakeMem()
    set_item(fake, REC, SRC_ID)
    m = PSO(fake.read, fake.write)
    assert m.item_record(OBJ) == REC


def test_dupe_exact_clone_unique_ids():
    fake = FakeMem()
    set_item(fake, REC, SRC_ID)
    m = PSO(fake.read, fake.write)
    res = m.dupe("000105", count=2)
    assert res["verified"] and res["created"] == 2 and res["requested"] == 2
    assert res["record"] == REC.hex() and res["source"]["id"] == hex(SRC_ID)
    want0 = bytearray(REC)
    struct.pack_into("<I", want0, 12, ID_BASE)                # copies keep every byte but get fresh unique ids
    want1 = bytearray(REC)
    struct.pack_into("<I", want1, 12, ID_BASE + 1)
    assert bytes(fake.read(BUF, 20)) == bytes(want0)          # the 6x2B path received the clone records
    assert bytes(fake.read(BUF + 24, 20)) == bytes(want1)


def test_dupe_by_slot_with_equip():
    fake = FakeMem()
    set_item(fake, REC, SRC_ID)
    m = PSO(fake.read, fake.write)
    res = m.dupe("0", count=1, equip=True)
    assert res["created"] == 1 and res["equipped_first"]
    assert struct.unpack("<I", fake.read(PLAYER + 0xBD0, 4))[0] == give_addr()   # equipped slot points at the clone


def test_dupe_equipped_weapon_target():
    fake = FakeMem()
    set_item(fake, REC, SRC_ID, flags=3)                      # in inventory + equipped
    fake.put(PLAYER + 0xBE4, struct.pack("<I", OBJ))
    m = PSO(fake.read, fake.write)
    res = m.dupe("weapon", count=3)
    assert res["verified"] and res["created"] == 3
    assert res["source"]["equipped"] == "weapon"
    # three distinct records at BUF, all sharing the source bytes except the id
    recs = [bytes(fake.read(BUF + 24 * i, 20)) for i in range(3)]
    ids = [struct.unpack("<I", r[12:16])[0] for r in recs]
    assert len(set(ids)) == 3 and all(r[:12] + r[16:] == REC[:12] + REC[16:] for r in recs)


def test_dupe_missing_target_raises():
    fake = FakeMem()
    m = PSO(fake.read, fake.write)
    with pytest.raises(ValueError):
        m.dupe("000999", count=1)


def test_give_still_creates_default_records():
    fake = FakeMem()
    m = PSO(fake.read, fake.write)
    made = m.give("000105", count=2)
    assert sum(1 for o in made if o) == 2
    r = bytes(fake.read(BUF, 20))
    assert r[:3] == b"\x00\x01\x05"
    assert struct.unpack("<I", r[12:16])[0] == ID_BASE
