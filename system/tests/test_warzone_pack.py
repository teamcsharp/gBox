"""Focused tests for gbox.warzone_pack (WWF War Zone USA N64 pack directory + RNC1)."""
from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest

from gbox import warzone_pack as wp

ROM_CANDIDATES = [os.environ.get("WARZONE_ROM", ""),
                  str(Path.home() / "gBox_alt/gbox-cache/warzone/rom.z64"),
                  str(Path.home() / "gbox-cache/warzone/rom.z64")]


def test_crc16_check_value():
    assert wp.crc16(b"123456789") == 0xBB3D


def test_parse_pack_table_synthetic():
    img = bytearray(0x1000)
    base = wp.PACK_TABLE_VADDR - wp.IMAGE_BASE
    img = bytearray(base + 64)
    struct.pack_into(">4I", img, base, 0x100, 0x40, 0x20, 0x40000)
    e = wp.parse_pack_table(bytes(img), 1)[0]
    assert e["rom"] == 0xDDE0 + 0x100 and e["unpacked"] == 0x40 and e["flags"] == 0x40000


def test_rnc1_rejects_bad_magic():
    with pytest.raises(ValueError):
        wp.rnc1_unpack(b"XXXX" + bytes(20))


def _rom():
    for p in ROM_CANDIDATES:
        if p and Path(p).is_file():
            return Path(p).read_bytes()
    pytest.skip("owned War Zone ROM not available")


def test_owned_build_rnc_entries_pass_header_crc():
    pytest.importorskip("unicorn")
    from gbox import warzone_boot as wb
    rom = _rom()
    img, _ = wb.decompress_main(rom)
    table = wp.parse_pack_table(img, 400)
    ok = 0
    for e in table[:12]:
        blob = wp.entry_bytes(rom, e)
        if blob[:4] != b"RNC\x01" or e["index"] in (9,):
            continue
        out = wp.rnc1_unpack(blob)
        assert len(out) == e["unpacked"]
        assert wp.crc16(out) == struct.unpack(">H", blob[12:14])[0]
        ok += 1
    assert ok >= 8
