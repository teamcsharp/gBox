"""Focused tests for gbox.ki2_boot (Killer Instinct 2 boot-ROM program unpacker)."""
from __future__ import annotations

import hashlib
import os
import struct
from pathlib import Path

import pytest

from gbox import ki2_boot as kb

OWNED_ZIP = Path(os.environ.get(
    "GBOX_KI2_ZIP", str(Path.home() / "gbox-cache/2e9b5e24e3b5d0bc/kinst2.zip")))
OWNED_RAW = Path(os.environ.get(
    "GBOX_KI2_RAW", str(Path.home() / "gbox-cache/2e9b5e24e3b5d0bc/kinst2.raw")))


def test_bitreader_is_lsb_first_and_aligns():
    br = kb.BitReader(bytes([0b10110010, 0xFF, 0x34, 0x12]), 0)
    assert br.get(1) == 0
    assert br.get(3) == 0b001
    assert br.get(4) == 0b1011
    br.align()
    assert br.byte_pos == 1
    br.seat(2)
    assert br.get(16) == 0x1234


def test_symbol_walk_bit1_falls_through_bit0_skips():
    # node(skip=2) -> [leaf 'A'] , [node(skip=2) -> leaf 'B', leaf 'C']
    tree = bytes([2, 0, 0x41, 2, 0, 0x42, 0, 0x43])
    bits = bytes([0b0000_0101])  # 1 -> A ; 0,1 -> B ; 0,0 -> C
    br = kb.BitReader(tree + bits, len(tree))
    assert br.symbol(0) == 0x41
    assert br.symbol(0) == 0x42
    br2 = kb.BitReader(tree + bytes([0]), len(tree))
    assert br2.symbol(0) == 0x43


def test_symbol_walk_long_skip_node():
    left = bytes([0, 0x11]) + bytes(298)  # padded subtree reached via bit 1
    skip = len(left)
    tree = bytes([0x80 | (skip >> 8), skip & 0xFF]) + left + bytes([0, 0x22])
    br = kb.BitReader(tree + bytes([0]), len(tree))
    assert br.symbol(0) == 0x22


def test_register_cache_moves_hit_to_back():
    c = kb._RegCache()
    assert c.t[0] == 31 and c.t[31] == 0
    assert c.take(0) == 31
    assert c.t[31] == 31 and c.t[0] == 30
    assert c.take(31) == 31 and len(c.t) == 32


def test_find_layout_from_loader_signatures():
    words = [0] * 0x400
    words[0x10] = 0x3C05BFC0
    words[0x11] = 0x24A51034
    for i, imm in zip((0x40, 0x50, 0x60, 0x70), (0x0FB0, 0x0EB0, 0x0F30, 0x0F70)):
        words[i] = 0x3C14BFC0
        words[i + 1] = 0x3C01DFFF
        words[i + 2] = 0x26940000 | imm
    lay = kb.find_layout(struct.pack("<%dI" % len(words), *words))
    assert lay.src == 0xBFC01040
    assert (lay.opcode_table, lay.special_table, lay.regimm_table, lay.cop_table) == (
        0xBFC00FB0, 0xBFC00EB0, 0xBFC00F30, 0xBFC00F70)


def test_game_chs_translation_roundtrip():
    regs = kb.chs_registers(0x190)
    assert regs == {"sector": 1, "head": 10, "cyl_lo": 0, "cyl_hi": 0}
    for lba in (0, 39, 40, 559, 560, 0x1504, 893892):
        r = kb.chs_registers(lba)
        cyl = r["cyl_lo"] | (r["cyl_hi"] << 8)
        assert kb.chs_to_lba(cyl, r["head"], r["sector"]) == lba


@pytest.mark.skipif(not OWNED_ZIP.exists(), reason="owned kinst2.zip not present")
@pytest.mark.parametrize("member", sorted(kb.REVISION_IMAGES))
def test_owned_revisions_unpack_to_recorded_images(member):
    rom = kb.load_u98(OWNED_ZIP, member)
    prog = kb.decompress(rom)
    assert prog.entry == 0x88000000
    assert len(prog.segments) == 3
    lo, img = prog.image()
    assert lo == 0x88000000
    assert hashlib.sha256(img).hexdigest() == kb.REVISION_IMAGES[member]
    code = kb.code_stats(prog.segments[0].data)
    assert code["jr_ra"] > 500 and code["addiu_sp_neg"] > 300


@pytest.mark.skipif(not OWNED_ZIP.exists(), reason="owned kinst2.zip not present")
def test_owned_l14_program_has_disk_driver_and_roster():
    prog = kb.decompress(kb.load_u98(OWNED_ZIP))
    lo, img = prog.image()

    def word(addr):
        return struct.unpack_from("<I", img, addr - lo)[0]

    # ide_init issues INITIALIZE DEVICE PARAMETERS with 40 sectors / head reg 13
    assert word(0x8801BA74) == 0x24020028 and word(0x8801BA7C) == 0x2402000D
    assert word(0x8801BA84) == 0x24020091
    # disk_read issues READ SECTORS (0x20) to the command register 0xb0000138
    assert word(0x8801BAEC) == 0x24020020 and word(0x8801BAF0) == 0xAC620138
    # set_chs divides by 40 sectors and 14 heads
    assert word(0x8801BD30) == 0x24010028 and word(0x8801BD54) == 0x2401000E
    names = [n for _a, n in kb.roster_strings(img)]
    # audit-page order of all 11 fighters ('KIM' = Kim Wu)
    assert names == ["JAGO", "COMBO", "FULGORE", "ORCHID", "GLACIUS", "SPINAL",
                     "SABREWULF", "TUSK", "KIM", "MAYA", "GARGOS"]


@pytest.mark.skipif(not OWNED_RAW.exists(), reason="extracted kinst2.raw not present")
def test_owned_boot_overlay_read_is_pointer_table():
    b = kb.BOOT_DISK_READ
    data = kb.read_sectors(OWNED_RAW, b["lba"], b["count"])
    assert len(data) == b["count"] * kb.SECTOR
    first = struct.unpack_from("<8I", data)
    # self-relative 256-byte record table located at the RAM destination
    assert first[0] == b["dest"] + 0x100
    assert all(first[i + 1] - first[i] == 0x100 for i in range(7))
