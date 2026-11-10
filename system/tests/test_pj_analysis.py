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
    afs_descriptors,
    character_pointer_table,
    character_table,
    costume_block_header,
    costume_block_table,
    CHAR_SLOT_COUNT,
    character_slots,
    character_stat_records,
    classify_entry,
    p0_to_va,
    stream_table,
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


def test_afs_descriptors_synthetic():
    from gbox.pj_analysis import AFS_DESC_VA, AFS_DESC_COUNT, _va_to_off
    blob = bytearray(_va_to_off(AFS_DESC_VA) + AFS_DESC_COUNT * 12 + 0x1000)
    name_off = _va_to_off(AFS_DESC_VA) + AFS_DESC_COUNT * 12
    blob[name_off:name_off + 10] = b"uplmdl.afs"
    for i in range(AFS_DESC_COUNT):
        struct.pack_into("<III", blob, _va_to_off(AFS_DESC_VA) + i * 12,
                         0x0C000000 + 0x10000 + name_off, 0x0C300000 + i, 42 + i)
    d = afs_descriptors(bytes(blob))
    assert len(d) == AFS_DESC_COUNT
    assert d[0]["name"] == "uplmdl.afs" and d[0]["count"] == 42
    assert d[3]["toc_va"] == 0x8C300003


@pytest.mark.skipif(not (CACHE / "disc.gdi").exists(),
                    reason="staged Project Justice GDI not present")
def test_real_afs_descriptors_match_disc_and_char_ptrs():
    from gbox.gdrom import GDRom
    g = GDRom(CACHE / "disc.gdi")
    try:
        exe = g.read("1ST_READ.BIN")
        counts = {}
        for nm in ("UPLMDL", "XPLTEX", "WPLMOT", "YPLPACK", "UGMEDMDL"):
            counts[nm.lower() + ".afs"] = len(afs_entries(g.read(nm + ".AFS"))[1])
    finally:
        for f in g._fh.values():
            f.close()
    desc = {d["name"]: d for d in afs_descriptors(exe)}
    assert len(desc) == 14
    for name, n in counts.items():
        assert desc[name]["count"] == n, name
    assert [desc[k]["slot"] for k in ("yplpack.afs", "xpltex.afs", "uplmdl.afs",
                                      "wplmot.afs", "ugmedmdl.afs")] == [5, 6, 7, 8, 13]
    ptrs = character_pointer_table(exe)
    recs = character_table(exe)
    assert ptrs[0] == ptrs[1] == recs[0]["va"]
    assert ptrs[1:] == [r["va"] for r in recs]


def test_p0_to_va():
    assert p0_to_va(0x0C19D340) == 0x8C19D340
    assert p0_to_va(0xAC19D340) == 0x8C19D340


@pytest.mark.skipif(not (CACHE / "1ST_READ.BIN").exists(),
                    reason="staged 1ST_READ.BIN not present")
def test_real_loader_tables_40_slots_stats_and_stream_table():
    import hashlib
    exe = (CACHE / "1ST_READ.BIN").read_bytes()
    assert hashlib.sha256(exe).hexdigest() == FIRST_READ_SHA256
    slots = character_slots(exe)
    assert len(slots) == CHAR_SLOT_COUNT == 40
    assert [s["name"] for s in slots[:3]] == ["BATSU", "BATSU", "HINATA"]
    assert [s["name"] for s in slots[29:]][0] == "VATSU"
    assert slots[32]["name"] == "GORIN-M" and slots[39]["name"] == "JUS-F"
    for s in slots[:29]:
        assert s["ids"][0] == s["slot"] or s["slot"] == 0
    stats = character_stat_records(exe)
    assert all(0x8C010000 <= r["stat_va"] < 0x8C300000 for r in stats)
    assert all(0.5 < r["scale_a"] < 1.5 for r in stats[:29])
    st = stream_table(exe)
    assert st[0]["group"] == 0xFFFF
    assert [r["entry"] for r in st[1:52]] == list(range(51))
    assert {r["group"] for r in st[1:52]} == {0}


@pytest.mark.skipif(not (CACHE / "1ST_READ.BIN").exists(),
                    reason="staged 1ST_READ.BIN not present")
def test_real_costume_block_table_and_header():
    exe = (CACHE / "1ST_READ.BIN").read_bytes()
    tbl = costume_block_table(exe)
    assert len(tbl) >= 45
    assert all(0x8C010000 <= v < 0x8C010000 + len(exe) for v in tbl)
    hdr = costume_block_header(exe, tbl[0])
    assert len(hdr) == 13
    assert hdr[0] == 0x8C0E4AF8  # shared rts stub
    # stat-record ptr_0x18 targets are code-pointer tables, not model indices
