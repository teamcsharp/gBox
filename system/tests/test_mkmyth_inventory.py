"""Focused tests for gbox.mkmyth_inventory (MK Mythologies USA, N64 NMYE rev 0)."""
from __future__ import annotations

import os
from pathlib import Path
import struct

import pytest

from gbox import mkmyth_inventory as mk

SOURCE = Path(os.environ.get(
    "GBOX_MKMYTH_SOURCE",
    Path.home() / "gbox-cache" / "6d46221997228c6a" / "source.zip"))


def _lui(rt: int, imm: int) -> int:
    return (0x0F << 26) | (rt << 16) | (imm & 0xFFFF)


def _addiu(rt: int, rs: int, imm: int) -> int:
    return (0x09 << 26) | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


def test_decode_entry_stub_sign_extends_addiu():
    words = [_lui(8, 0x800B), _addiu(8, 8, 0x43C0),
             _lui(9, 0x0024), _addiu(9, 9, -0x7590),
             0, 0, 0, 0, 0, 0,
             _lui(10, 0x8000), _addiu(10, 10, 0x0450),
             _lui(29, 0x802F), 0x01400008, _addiu(29, 29, -0x7C40), 0]
    rom = bytes(0x1000) + struct.pack(">16I", *words)
    e = mk.decode_entry(rom)
    assert e["bss_start"] == 0x800B43C0
    assert e["bss_size"] == 0x238A70
    assert e["main"] == 0x80000450
    assert e["stack_top"] == 0x802E83C0
    assert e["resident_rom_end"] == 0xB4FC0


def test_segment_table_null_record_classes_and_gap():
    rom = bytearray(0x3000)
    struct.pack_into(">2I", rom, 0x1000, 8, 0x10)            # offset table, 2 entries
    struct.pack_into(">2I", rom, 0x1040, 0x1234, 0x80002047)  # packed blob
    tab = 0x2000
    struct.pack_into(">9I", rom, tab, 0x1000, 0x1020, 0, 0, 0, 0, 0x1040, 0x1080, 1)
    struct.pack_into(">3I", rom, tab + 36, 0x1020, 0x1040, 7)  # bad flag ends table
    recs = mk.segment_table(bytes(rom), off=tab, lo=0x1000)
    assert [r["null"] for r in recs] == [False, True, False]
    assert recs[0]["kind"] == "offset_table" and recs[0]["entries"] == 2
    assert recs[2]["kind"] == "packed" and recs[2]["signature"] == "80002000"
    assert recs[2]["flag"] == 1 and recs[2]["word0"] == 0x1234
    cov = mk.coverage(recs, 0x1000, 0x1080)
    assert cov["gaps"] == [(0x1020, 0x1040)] and cov["overlaps"] == []


def test_pointer_strings_stop_at_empty_string():
    rom = bytearray(0x2000)
    rom[0x1800:0x1806] = b"MONK1\0"
    rom[0x1808:0x1810] = b"SHINNOK\0"
    struct.pack_into(">3I", rom, 0x1000, mk.rom_to_ram(0x1800),
                     mk.rom_to_ram(0x1808), mk.rom_to_ram(0x1810))
    assert mk.pointer_strings(bytes(rom), 0x1000, resident_end=0x2000) == ["MONK1", "SHINNOK"]


def test_check_build_refuses_other_roms():
    src = {"z64_sha1": "0" * 40, "z64_md5": mk.KNOWN["z64_md5"],
           "z64_size": mk.KNOWN["z64_size"]}
    with pytest.raises(mk.WrongBuild):
        mk.check_build(src, {"game_code": "NMYE", "version": 0})
    good = {k: mk.KNOWN[k] for k in ("z64_sha1", "z64_md5", "z64_size")}
    with pytest.raises(mk.WrongBuild):
        mk.check_build(good, {"game_code": "NMYP", "version": 0})
    mk.check_build(good, {"game_code": "NMYE", "version": 0})


@pytest.mark.skipif(not SOURCE.is_file(), reason="owned MK Mythologies USA zip not cached")
def test_owned_build_inventory(monkeypatch, tmp_path):
    monkeypatch.setenv("GBOX_N64_ROM_CACHE", str(tmp_path))
    m = mk.inventory(SOURCE)
    s = m["source"]
    assert s["sha256"] == "92bf2f4584c19490297bb902533fe57f8519663128845da654ecece9f8958b9a"
    assert s["byte_order"] == "v64" and s["member_size"] == 0x1000000
    assert s["z64_sha256"] == "9c18254abf6722b95aa782fcd310bd95f6bcf147da66beb77ce32ca90673ffc6"
    h = m["header"]
    assert (h["game_code"], h["version"], h["internal_name"]) == ("NMYE", 0, "MK_MYTHOLOGIES")
    assert h["entry_point"] == 0x80000400
    assert m["boot"] == {"cic": "6102", "ipl3_crc32": "90bb6cb5", "header_crc_matches": True}
    lay = m["layout"]
    assert lay["resident"]["rom_end"] == 0xB4FC0
    assert lay["resident"]["bss_size"] == 0x238A70
    st = lay["segment_table"]
    assert (st["records"], st["real"], st["null_indices"], st["flagged"]) == (144, 143, [118], 58)
    assert st["ram"] == 0x800A4560 and st["kinds"]["offset_table"] == 42
    cov = lay["coverage"]
    assert cov["overlaps"] == [] and cov["high"] == 0xEF6B60
    assert [(g["start"], g["end"], g["kind"]) for g in cov["gaps"]] == [
        (0x947C80, 0xD2DA50, "sn64_sound_bank")]
    assert lay["padding"] == [0xEF6B57, 0x1000000]
    names = [c["name"] for c in m["characters"]["debug_select"]]
    assert len(names) == 25
    assert (names[0], names[13], names[14], names[23], names[24]) == (
        "MONK1", "SCORPION", "UNDEAD SCORP", "QUANCHI", "SHINNOK")
    levels = [x["name"] for x in m["levels"]["debug_select"]]
    assert len(levels) == 11 and levels[0] == "TEMPLE" and levels[-1] == "TEST CHARACTERS"
    assert m["string_hints"]["No more palettes!"] == 0xADE28
