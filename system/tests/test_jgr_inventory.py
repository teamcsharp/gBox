"""Tests for gbox.jgr_inventory. Synthetic and real-disc checks."""
from __future__ import annotations

import json
import os
import struct
from pathlib import Path

import pytest

import collections

from gbox import jgr, jgr_inventory
from gbox.gdrom import GDRom

JGR_GDI = Path(os.environ.get("JGR_GDI", "/home/ehm_eckx/gbox-cache/dc/4187aeab4d67638c/disc.gdi"))


def make_exe_with_debug_names(names: list[str]) -> bytearray:
    base = jgr_inventory.FIRST_READ_BASE
    va = jgr_inventory.DEBUG_NAME_TABLE
    exe = bytearray(va - base + 256)
    strings: list[int] = []
    for s in names:
        off = len(exe)
        exe.extend(s.encode("ascii") + b"\0")
        strings.append(base + off)
    exe[va - base:va - base + 4 * len(strings)] = struct.pack(f"<{len(strings)}I", *strings)
    return exe


def test_debug_names_resolve():
    exe = bytes(make_exe_with_debug_names(["BEAT(EREKI)", "GUM", "CORN", "COMBO"]))
    assert jgr_inventory.debug_names(exe, n=4) == ["BEAT(EREKI)", "GUM", "CORN", "COMBO"]


def test_debug_names_out_of_range_is_none():
    base = jgr_inventory.FIRST_READ_BASE
    va = jgr_inventory.DEBUG_NAME_TABLE
    exe = bytearray(va - base + 128)
    # place four targets at the end, well separated; index1 out-of-range, index3 non-ascii
    targets = [
        (b"BEAT(EREKI)\0", -80),
        (b"ignored\0", 0xF0000),  # pointer only, not written
        (b"CORN\0", -55),
        (b"A\x80\x80\x80\x80\0", -40),
    ]
    strings = []
    for s, off in targets:
        if isinstance(off, int) and off < 0:
            o = len(exe) + off
            exe[o:o + len(s)] = s
            strings.append(base + o)
        else:
            strings.append(base + off)
    exe[va - base:va - base + 16] = struct.pack("<4I", *strings)
    names = jgr_inventory.debug_names(bytes(exe), n=4)
    assert names[0] == "BEAT(EREKI)"
    assert names[1] is None
    assert names[2] == "CORN"
    assert names[3] is None


def test_entry_kind_classification():
    assert jgr_inventory.entry_kind(b"PLAY") == "play"
    assert jgr_inventory.entry_kind(b"PTEX") == "ptex"
    assert jgr_inventory.entry_kind(b"EFTX") == "eftx"
    assert jgr_inventory.entry_kind(b"GBIX") == "pvr"
    assert jgr_inventory.entry_kind(b"\x80\x00\x00\x00") == "adx"
    assert jgr_inventory.entry_kind(b"\x00\x00\x90\x8c") == "ram_linked"
    assert jgr_inventory.entry_kind(b"\x11\x25\x02\x00") == "ninja_chunk"
    assert jgr_inventory.entry_kind(b"MISC") == "other"
    assert jgr_inventory.entry_kind(b"") == "empty"


def test_afs_layout_room_uses_directory_boundary():
    # AFS: count=3, entries at 0x100, 0x400, 0x700, sizes 0x300, 0x300, 0x200;
    # filename-directory records after the entries at 0x900, descriptor 8 bytes before entry 0.
    count = 3
    dsize = 48 * count
    data = bytearray(b"AFS\x00" + struct.pack("<I", count))
    data += struct.pack("<6I", 0x100, 0x300, 0x400, 0x300, 0x700, 0x200)
    data += b"\0" * (0x100 - len(data))
    data += b"\xAA" * 0x300 + b"\xBB" * 0x300 + b"\xCC" * 0x200
    o = 0x900
    data.extend(b"\0" * (o - len(data)))
    data.extend(b"C" * 32 + b"\0" * 12 + struct.pack("<I", 0x300))  # entry 0
    data.extend(b"B" * 32 + b"\0" * 12 + struct.pack("<I", 0x300))  # entry 1
    data.extend(b"A" * 32 + b"\0" * 12 + struct.pack("<I", 0x200))  # entry 2
    # directory descriptor at min(offsets) - 8
    desc = 0x100 - 8
    data[desc:desc + 8] = struct.pack("<II", o, dsize)
    layout = jgr_inventory.afs_layout(bytes(data))
    assert [e["room"] for e in layout] == [0x300, 0x300, 0x200]
    assert jgr_inventory.afs_directory(bytes(data)) == (o, dsize)


def test_record_spans():
    recs = [(0x6C, 1), (0x100, 4), (0x200, 5), (0x300, 6), (0x400, 7), (0x500, 0)]
    spans = jgr_inventory.record_spans(recs, 0x600)
    assert {s["kind"]: s["span"] for s in spans} == {0: 0x100, 4: 0x100, 5: 0x100, 6: 0x100, 7: 0x100}


def test_parse_chd_info():
    text = "File Version: 5\nLogical size: 818566504\nSHA1: abc123\nCompression: lzma"
    assert jgr_inventory.parse_chd_info(text) == {"version": "5", "logical_size": "818566504",
                                                    "sha1": "abc123", "compression": "lzma"}


def test_compare_tracks():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "disc03.bin").write_bytes(b"track3")
        tracks = [{"file": "disc03.bin", "sha256": "c8a4d6b0e0c6d3f9c2e9f2a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c"},
                  {"file": "disc01.bin", "sha256": "d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2"}]
        Path(tmp, "disc01.bin").write_bytes(b"track1")
        assert jgr_inventory.compare_tracks(tracks, tmp) == {"disc03.bin": False, "disc01.bin": False}


@pytest.mark.skipif(not JGR_GDI.is_file(), reason="JGR disc not present")
def test_real_inventory_consistency():
    man = jgr_inventory.inventory(JGR_GDI, hash_tracks=False)
    assert man["game_id"] == jgr_inventory.GAME_ID
    assert man["ip"]["product"] == "MK-51058"
    assert man["ip"]["version"] == jgr_inventory.VERSION
    assert man["first_read"]["sha256"] == jgr_inventory.FIRST_READ_SHA256
    # Debug-name table resolves the first 10 expected names; any out-of-range entries stay None
    assert man["checks"]["debug_names_match_reader"]
    assert man["checks"]["roster_matches_reader"]
    assert man["checks"]["player_afs_entries"]
    assert man["checks"]["body_groups_20_nodes"]
    # every native ID is a unique value 0-15
    ids = [c["native_id"] for c in man["characters"]]
    assert sorted(ids) == list(range(16))
    # every body group (0) has non-zero triangle count
    assert all(c["draw_groups"][0]["triangles"] > 0 for c in man["characters"])
    # atlas_texture points inside the PTEX texture list
    assert all(0 <= c["atlas_texture"] < len(c["textures"]) for c in man["characters"])
    # PLAYER.AFS has exactly 16 PLAY, 16 PTEX, main, EFTX
    kinds = collections.Counter(e["kind"] for e in man["player_afs"]["entries"])
    assert kinds == {"play": 16, "ptex": 16, "main": 1, "eftx": 1}
    # ENEMY.AFS has 54 entries and 27 dat/txr model/texture pairs
    assert man["enemy_afs"]["count"] == 54
    dat = {e["name"] for e in man["enemy_afs"]["entries"] if (e["name"] or "").endswith("dat.bin")}
    txr = {e["name"] for e in man["enemy_afs"]["entries"] if (e["name"] or "").endswith("txr.bin")}
    assert len(dat) == len(txr) == 27


@pytest.mark.skipif(not JGR_GDI.is_file(), reason="JGR disc not present")
def test_player_afs_writer_room_sanity():
    man = jgr_inventory.inventory(JGR_GDI, hash_tracks=False)
    player = man["player_afs"]["entries"]
    # last entry cannot grow past the file-name directory in a real writer, even if entry_room ignores it
    last = max(player, key=lambda e: e["offset"])
    assert last["room"] <= last["jgr_entry_room"]
