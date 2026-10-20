"""Focused tests for gbox.mm64_inventory (Mega Man 64 USA, N64 NM6E rev 0)."""
from __future__ import annotations

import os
from pathlib import Path
import struct

import pytest

from gbox import mm64_inventory as mm

SOURCE = Path(os.environ.get(
    "GBOX_MM64_SOURCE",
    Path.home() / "gBox_alt/gbox-cache" / "7815f5fed884d651" / "source.zip"))


def test_lzss_zero_ring_backrefs_rebuild_u32_table():
    # First bytes of archive 0x2CAC60 entry 0: flags 0xAA = ref, lit, ref, lit ...
    stream = bytes.fromhex("aaedf005edf030edf0c0edf0f0")
    data, used = mm.lzss_decompress(stream, 0, 16)
    assert data == bytes.fromhex("00000005" "00000030" "000000c0" "000000f0")
    assert used == len(stream)


def test_lzss_overlapping_copy_and_bounds():
    # literal 'A' at ring 0xFEE, then a 5-byte copy from 0xFEE (overlapping run)
    stream = bytes([0x01, 0x41, 0xEE, 0xF2])
    assert mm.lzss_decompress(stream) == (b"AAAAAA", 4)
    assert mm.lzss_decompress(stream, 0, 3)[0] == b"AAA"
    assert mm.lzss_decompress(stream, 0, None, 2) == (b"A", 2)


def test_unpack_entry_lzss_and_raw():
    stream = bytes.fromhex("aaedf005edf030edf0c0edf0f0")
    rom = bytes(0x10) + struct.pack(">I", 16) + stream + bytes(3)
    data, facts = mm.unpack_entry(rom, 0x10, 0, 4 + len(stream))
    assert data[:4] == b"\0\0\0\x05" and facts == {"codec": "lzss", "unpacked": 16, "slack": 0}
    raw = bytes(0x10) + struct.pack(">I", 0x7FFFFFFF) + bytes(12)
    assert mm.unpack_entry(raw, 0x10, 0, 16) == (None, {"codec": "raw"})


def test_scan_directories_chain_and_candidate_bases():
    rom = bytearray(0x200)
    struct.pack_into(">6I", rom, 0x100,
                     0x00, 0x80000010,      # off 0, lzss, 0x10 bytes
                     0x10, 0x00000006,      # off 0x10, raw, 6 bytes
                     0x18, 0x80000008)      # align4(0x16) = 0x18
    struct.pack_into(">2I", rom, 0x118, 0x1234, 0x7F000001)   # breaks the chain
    dirs = mm.scan_directories(bytes(rom), 0, 0x200, min_len=3)
    assert [d["rom"] for d in dirs] == [0x100]
    assert dirs[0]["entries"] == [(0, 0x10, 0x80), (0x10, 6, 0), (0x18, 8, 0x80)]
    assert mm.directory_span(dirs[0]["entries"]) == 0x20
    assert mm.candidate_bases(dirs, [0x1000, 0x1020]) == {}   # span < 0x800 is ignored
    big = [{"rom": 0x100, "entries": [(0, 0x1000, 0x80), (0x1000, 0x7F5, 0x80)]}]
    assert mm.candidate_bases(big, [0x5000, 0x6800, 0x8000]) == {0x100: [0x5000, 0x6800]}


def test_rom_constants_lui_addiu_sign_extends():
    lui = (0x0F << 26) | (4 << 16) | 0x002D            # lui a0, 0x002d
    addiu = (0x09 << 26) | (4 << 21) | (4 << 16) | 0xAC60   # addiu a0, a0, -0x53a0
    rom = bytes(0x10) + struct.pack(">2I", lui, addiu)
    assert mm.rom_constants(rom, 0x10, 0x18, high=0x2000000) == {0x2CAC60: [0x14]}


def test_classify_payload():
    assert mm.classify_payload(b"") == "empty"
    assert mm.classify_payload(struct.pack(">3I", 2, 0x0C, 0x10) + bytes(8)) == "container:2"
    assert mm.classify_payload(struct.pack(">3I", 2, 0x10, 0x0C) + bytes(8)) == "blob"


def test_check_build_refuses_other_roms():
    good = {k: mm.KNOWN[k] for k in ("z64_sha1", "z64_md5", "z64_size")}
    with pytest.raises(mm.WrongBuild):
        mm.check_build(dict(good, z64_sha1="0" * 40), {"game_code": "NM6E", "version": 0})
    with pytest.raises(mm.WrongBuild):
        mm.check_build(good, {"game_code": "NM6J", "version": 0})
    mm.check_build(good, {"game_code": "NM6E", "version": 0})


@pytest.mark.skipif(not SOURCE.is_file(), reason="owned Mega Man 64 USA zip not cached")
def test_owned_build_inventory(monkeypatch, tmp_path):
    monkeypatch.setenv("GBOX_N64_ROM_CACHE", str(tmp_path))
    m = mm.inventory(SOURCE, detail=False)
    s = m["source"]
    assert s["sha256"] == "65b94d0bff869aa93b0a16e7d2dcdcc85724fb3df7ea7c394c88fc317ea03d3c"
    assert s["byte_order"] == "v64" and s["member_size"] == 0x2000000
    assert s["z64_sha256"] == "618d49bf62913b376e4858f1422a51a4352792b070fe6305860dd43e28353999"
    assert m["no_intro_match"] is True
    h = m["header"]
    assert (h["game_code"], h["version"], h["internal_name"]) == ("NM6E", 0, "Mega Man 64")
    assert h["entry_point"] == mm.ENTRY_POINT
    assert m["boot"] == {"cic": "6102", "ipl3_crc32": "90bb6cb5", "header_crc_matches": True}
    res = m["layout"]["resident"]
    assert (res["rom_end"], res["bss_size"], res["main"]) == (0xAE8D0, 0x14A500, 0x80089FD0)
    assert m["launch"]["expansion_pak_required"] is False
    arcs = {a["base"]: a for a in m["archives_detail"]}
    assert len(arcs) == m["layout"]["archives"] == 62
    a = arcs[0x2CAC60]
    assert (a["directory_rom"], a["directory_ram"], a["entries"]) == (0x99370, 0x800BDF70, 445)
    assert a["codecs"] == {"lzss": 445} and a["unpacked_bytes"] == 0x60F848
    assert a["kinds"]["container:5"] == 367
    assert arcs[0x59DF00]["entries"] == 1508 and arcs[0x59DF00]["directory_in"] == "overlay"
    assert all(x["verified"] for x in arcs.values())
    assert m["assets"]["entries"] == 5672 and m["codec"]["verified_entries"] == 4021
    gaps = {g["start"]: g for g in m["layout"]["gaps"]}
    assert gaps[0x879480]["lzss_head"]["magic"].startswith("N64 PtrTablesV2")
