"""gbox.pso_ram.stage_flags: the native per-floor stage-flag group, decoded read-only.

Exercises ``stage_flag_locus``, ``decode_stage_flags`` and ``stage_flags`` on a synthetic 24 MiB
RAM image (no emulator), in the same style as ``test_pso_ram.py``. The flag array is the one
reverse-engineered 2026-11-02: 18 groups (one per floor 0..17) x 32 bytes, MSB-first, at
``STAGE_FLAG_BASE + floor*32``; the group index equals the current floor.
"""
import struct

import pytest

from gbox import pso_ram as R


class Mem:
    """A sparse 24 MiB RAM image exposing read_memory, like the Dolphin adapter's primitive."""

    def __init__(self):
        self.data = bytearray(R.RAM_END - R.RAM_START)

    def poke(self, address, blob):
        self.data[address - R.RAM_START:address - R.RAM_START + len(blob)] = blob

    def u32(self, address, value):
        self.poke(address, struct.pack(">I", value))

    def read_memory(self, address, length):
        off = address - R.RAM_START
        if off < 0 or off + length > len(self.data):
            return None
        return bytes(self.data[off:off + length])


def group_addr(floor):
    return R.STAGE_FLAG_BASE + floor * R.STAGE_GROUP_SIZE


def live(floor=1):
    m = Mem()
    m.u32(R.FLOOR, floor)
    return m


def test_constants_are_in_ram_and_group_size_is_the_proven_32_bytes():
    assert R.STAGE_FLAG_BASE + (R.STAGE_FLAG_GROUPS - 1) * R.STAGE_GROUP_SIZE + R.STAGE_GROUP_SIZE <= R.RAM_END
    assert R.RAM_START <= R.STAGE_FLAG_BASE < R.RAM_END
    assert R.STAGE_GROUP_SIZE == 32 and R.STAGE_FLAG_GROUPS == 18


def test_stage_flag_locus_matches_bit_and_byte_split():
    # index 0 is the high bit of the first byte; index 7 the low bit; index 8 the high bit of byte 1.
    assert R.stage_flag_locus(0, 0) == (R.STAGE_FLAG_BASE, 0x80)
    assert R.stage_flag_locus(0, 7) == (R.STAGE_FLAG_BASE, 0x01)
    assert R.stage_flag_locus(0, 8) == (R.STAGE_FLAG_BASE + 1, 0x80)
    # group stride is 32 bytes (floor 3 -> base + 96).
    assert R.stage_flag_locus(3, 0) == (R.STAGE_FLAG_BASE + 96, 0x80)


@pytest.mark.parametrize("group,index", [(-1, 0), (18, 0), (0, -1), (0, 256), (0.0, 0), (0, "0")])
def test_stage_flag_locus_rejects_out_of_range_and_untyped(group, index):
    assert R.stage_flag_locus(group, index) is None


def test_decode_stage_flags_reports_msb_first_indices_ascending():
    g = bytearray(32)
    g[0] = 0x80          # flag 0
    g[0] |= 0x01         # flag 7
    g[1] = 0x40          # flag 9  (byte 1, 0x40 -> bit 1 of byte 1 -> index 9)
    g[31] = 0x01         # flag 255
    assert R.decode_stage_flags(bytes(g)) == [0, 7, 9, 255]
    assert R.decode_stage_flags(bytes(32)) == []


def test_decode_stage_flags_rejects_wrong_length():
    with pytest.raises(R.RamError):
        R.decode_stage_flags(b"\x00" * 31)


def test_stage_flags_reads_the_current_floors_group():
    m = live(floor=2)
    addr = group_addr(2)
    m.poke(addr, b"\xff\x00" + b"\x00" * 30)   # floor 2: flags 0..7 set
    r = R.Reader(m)
    out = R.stage_flags(r)
    assert out["floor"] == 2
    assert out["set_indices"] == [0, 1, 2, 3, 4, 5, 6, 7]
    assert out["group_hex"].startswith("ff00")
    # a different floor does not leak into this read: the group is addressed by floor, not by base.
    m.u32(R.FLOOR, 3)
    assert R.stage_flags(R.Reader(m))["set_indices"] == []


def test_stage_flags_rejects_an_off_table_floor():
    m = live(floor=18)          # 18 is one past the last group (0..17)
    r = R.Reader(m)
    with pytest.raises(R.RamError):
        R.stage_flags(r)


def test_stage_flags_reports_but_never_authors():
    m = live(floor=0)
    m.poke(group_addr(0), bytes.fromhex("8000") + b"\x00" * 30)  # only flag 0 set
    r = R.Reader(m)
    out = R.stage_flags(r)
    assert out["set_indices"] == [0]
    # the reader API is read-only: no write_memory path is exposed or used.
    assert not hasattr(r, "write_memory")
