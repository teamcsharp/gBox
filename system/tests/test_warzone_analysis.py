"""Focused tests for gbox.warzone_analysis (WWF War Zone USA N64).

Parser-level tests run on synthetic bytes; the integration test runs against
the owned build when a local copy exists (skipped otherwise).
"""
from __future__ import annotations

import struct

import pytest

from gbox import warzone_analysis as wz


def make_rom(**kw) -> bytes:
    rom = bytearray(0xC00000)
    rom[:4] = b"\x80\x37\x12\x40"
    for k, v in kw.items():
        if isinstance(k, str) and k.startswith("@"):
            off = int(k[1:], 16)
            rom[off:off + len(v)] = v
    return bytes(rom)


def _put_u32(rom: bytearray, off: int, value: int) -> None:
    rom[off:off + 4] = struct.pack(">I", value)


def test_virtual_mapping_roundtrips():
    assert wz.virtual(0xBE7900) == 0x80BE7900
    assert wz.rom_offset(0x80BF2E00) == 0xBF2E00
    assert wz.rom_offset(wz.virtual(0x521000)) == 0x521000


def test_find_pointers_into_isolates_range():
    rom = bytearray(0x2000)
    _put_u32(rom, 0x1000, 0x80BE7936)   # inside name bank
    _put_u32(rom, 0x1004, 0x80BE8E51)   # inside name bank
    _put_u32(rom, 0x1008, 0x80B81C50)   # inside move table, not name bank
    _put_u32(rom, 0x100C, 0x00000000)
    lo = wz.virtual(wz.NAME_BANK[0])
    hi = wz.virtual(wz.NAME_BANK[1])
    hits = wz.find_pointers_into(bytes(rom), lo, hi)
    assert hits == [(0x1000, 0x80BE7936), (0x1004, 0x80BE8E51)]


def test_venue_pointer_matches_mapping():
    rom = bytearray(0xE3000)
    _put_u32(rom, wz.VENUE_REF, 0x80BF2E00)
    assert wz.venue_pointer(bytes(rom))["matches_virtual_mapping"] is True


def test_roster_locations_finds_clean_fragments():
    rom = bytearray(0xC00000)
    bank = wz.NAME_BANK[0]
    rom[bank:bank + 4] = b"KANE"
    rom[bank + 0x40:bank + 0x47] = b"FAAROOQ"
    locs = wz.roster_locations(bytes(rom))
    assert 0xBE7900 in locs["KANE"]
    assert 0xBE7940 in locs["FAAROOQ"]


def test_debug_string_table_parses_z_records():
    rom = bytearray(0x530000)
    base = wz.DEBUG_STRINGS
    rom[base:base + 0x20] = b"z202\r\n" + b"\x00" * 0x1B
    rom[base + 0x20:base + 0x40] = b"z203\r\n" + b"\x00" * 0x1B
    tbl = wz.debug_string_table(bytes(rom))
    assert tbl["count"] == 2
    assert tbl["ids"][0]["id"] == "z202"
    assert tbl["ids"][1]["offset"] == base + 0x20


def test_analysis_against_owned_build():
    """The owned build must reproduce the exact reference counts discovered in
    this run (8 name-bank refs, 4 move-table refs, roster fragments present)."""
    from pathlib import Path
    rom_path = Path.home() / "gbox-cache" / "warzone" / "rom.z64"
    if not rom_path.is_file():
        pytest.skip("owned build not staged")
    rep = wz.analysis(rom_path)
    assert rep["mapping"]["venue_pointer"]["matches_virtual_mapping"] is True
    assert len(rep["name_bank"]["refs"]) == 8
    assert len(rep["move_table"]["refs"]) == 4
    roster = rep["name_bank"]["roster"]
    assert roster["BRITISH BULLDOG"]          # both fragments present
    assert len(roster["SHAWN MICHAELS"]) >= 2
    assert roster["KANE"] and roster["FAAROOQ"]
