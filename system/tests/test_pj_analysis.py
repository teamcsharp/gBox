"""Focused tests for gbox.pj_analysis (Project Justice USA Dreamcast analysis).

Real-disc tests are gated on the staged cache at
~/gbox-cache/dc/6334be1925fbe016 and skip otherwise.
"""

import struct
from pathlib import Path

import pytest

from gbox.pj_analysis import (
    ALT_FORMS,
    CHARACTER_TABLE_FILE_OFF,
    CHARACTER_RECORD_SIZE,
    NPC_NAMES,
    PLAYABLE_ROSTER,
    character_table,
    classify_entry,
    playable_roster,
    uplmdl_pointers,
    wplmot_offsets,
)
from gbox.pj_inventory import FIRST_READ_SHA256, read_disc_file
from gbox.jgr import afs_entries

CACHE = Path.home() / "gbox-cache/dc/6334be1925fbe016"


def _build_exe(records):
    """Synthetic 1ST_READ.BIN image with a character table at the pinned offset."""
    n = len(records)
    blob = bytearray(CHARACTER_TABLE_FILE_OFF + n * CHARACTER_RECORD_SIZE)
    for i, (idx, group, name) in enumerate(records):
        off = CHARACTER_TABLE_FILE_OFF + i * CHARACTER_RECORD_SIZE
        blob[off] = blob[off + 1] = blob[off + 2] = idx
        blob[off + 3] = group
        blob[off + 4:off + 4 + len(name)] = name.encode("latin-1")
    return bytes(blob)


def test_character_table_parses_records():
    recs = [(1, 1, "BATSU"), (2, 1, "HINATA"), (3, 1, "KYOSUKE")]
    exe = _build_exe(recs)
    got = character_table(exe)
    assert [r["name"] for r in got] == ["BATSU", "HINATA", "KYOSUKE"]
    assert [r["idx"] for r in got] == [1, 2, 3]
    assert [r["group"] for r in got] == [1, 1, 1]


def test_character_table_stops_at_bad_index():
    recs = [(1, 1, "BATSU"), (2, 1, "HINATA"), (0x30, 1, "BREAK")]
    exe = _build_exe(recs)
    got = character_table(exe)
    assert [r["name"] for r in got] == ["BATSU", "HINATA"]


def test_playable_roster_filters_alts_and_npcs():
    recs = [
        (1, 1, "BATSU"), (2, 1, "HYO"), (3, 1, "POWERED AKIRA"),
        (4, 1, "HIDEO"), (5, 1, "IINCYO"), (6, 1, "KYOKO"),
    ]
    exe = _build_exe(recs)
    assert playable_roster(exe) == ["BATSU", "HYO", "IINCYO"]


def test_roster_constants_partition_28_records():
    # 22 playable + 4 alt forms + 2 NPCs = 28 records (idx 0x01..0x1c)
    assert len(PLAYABLE_ROSTER) == 22
    assert len(ALT_FORMS) == 4
    assert len(NPC_NAMES) == 2
    assert len(PLAYABLE_ROSTER) + len(ALT_FORMS) + len(NPC_NAMES) == 28
    assert "RAIZO" not in PLAYABLE_ROSTER
    assert "HYO" in PLAYABLE_ROSTER
    assert "IINCYO" in PLAYABLE_ROSTER


def test_wplmot_offsets_parses_count_and_offsets():
    offsets = [0x130, 0x1D0, 0x2A8]
    blob = struct.pack("<I", len(offsets)) + b"".join(struct.pack("<I", o) for o in offsets) + b"\x00" * 0x400
    assert wplmot_offsets(blob) == offsets


def test_wplmot_offsets_rejects_nonmonotonic():
    blob = struct.pack("<I", 2) + struct.pack("<II", 0x300, 0x100) + b"\x00" * 0x400
    with pytest.raises(ValueError):
        wplmot_offsets(blob)


def test_wplmot_offsets_rejects_out_of_range():
    blob = struct.pack("<I", 1) + struct.pack("<I", 0xFFFFF)
    with pytest.raises(ValueError):
        wplmot_offsets(blob)


def test_uplmdl_pointers_stops_at_grammar_break():
    # flags 0/1 alternate with offsets; a bad flag (0xd460) ends the table
    blob = b"".join(struct.pack("<HH", fl, off) for fl, off in [
        (0, 0xED20), (1, 0xB960), (1, 0xB4E0), (1, 0x0000),
    ]) + struct.pack("<HH", 0xD460, 1)
    flags, offsets = uplmdl_pointers(blob)
    assert flags == [0, 1, 1, 1]
    assert offsets == [0xED20, 0xB960, 0xB4E0, 0x0000]


def test_classify_entry():
    assert classify_entry(b"AFS\x00\x00\x00\x00\x00") == "afs"
    assert classify_entry(b"DTPK\x11\x00\x00\x00") == "dtpk"
    assert classify_entry(b"NJCMxxxx") == "ninja-chunk"
    assert classify_entry(b"GBIXxxxx") == "pvr-texture"
    assert classify_entry(struct.pack("<I", 16) + b"\x00" * 64) == "count-table"
    assert classify_entry(b"\x00\x00\x20\xed\x01\x00") == "headerless"


@pytest.mark.skipif(not (CACHE / "disc.gdi").exists(),
                    reason="staged Project Justice GDI not present")
def test_real_character_table_roster():
    from gbox.gdrom import GDRom
    g = GDRom(CACHE / "disc.gdi")
    try:
        exe = g.read("1ST_READ.BIN")
    finally:
        for f in g._fh.values():
            f.close()
    assert len(exe) == 3011944
    import hashlib
    assert hashlib.sha256(exe).hexdigest() == FIRST_READ_SHA256

    recs = character_table(exe)
    assert len(recs) == 28
    names = [r["name"] for r in recs]
    # the boss and the 22nd playable resolve the "RAIZO" question
    assert "HYO" in names
    assert "IINCYO" in names
    assert "DEMON HYO" in names
    assert "RAIZO" not in names
    assert playable_roster(exe) == PLAYABLE_ROSTER


@pytest.mark.skipif(not (CACHE / "disc.gdi").exists(),
                    reason="staged Project Justice GDI not present")
def test_real_uplmdl_and_wplmot_tables():
    from gbox.gdrom import GDRom
    g = GDRom(CACHE / "disc.gdi")
    try:
        upl = g.read("UPLMDL.AFS")
        mot = g.read("WPLMOT.AFS")
    finally:
        for f in g._fh.values():
            f.close()

    _, uoff, usize = afs_entries(upl)
    _, moff, msize = afs_entries(mot)

    # UPLMDL entry 0: headerless (no NJCM magic), (flag,offset) table in-bounds
    e0 = upl[uoff[0]:uoff[0] + usize[0]]
    assert e0[:4] not in (b"NJCM", b"NJTL", b"NJMD")
    flags, offsets = uplmdl_pointers(e0)
    assert flags and flags[0] == 0
    assert all(0 <= o < len(e0) for o in offsets)

    # WPLMOT entry 0: count-prefixed monotonic offset table
    m0 = mot[moff[0]:moff[0] + msize[0]]
    offs = wplmot_offsets(m0)
    assert len(offs) == 16  # entry 0 has 16 motion clips on this build
    assert offs == sorted(offs)
