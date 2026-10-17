"""Capcom vs. SNK 2 EO (GC, GEOE08) inventory: little-endian CRI AFS, name-dir slots, asset categorisation."""
import os
import struct
from pathlib import Path

import pytest

from gbox import cvs2eo_inventory as ci

GCZ = Path(os.environ.get("GBOX_CVS2EO_GCZ", Path(
    "/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/"
    "Capcom vs. SNK 2 EO - Millionaire Fighting 2001 (USA).gcz")))


def _afs(names_sizes, slot):
    """Build a minimal little-endian CRI AFS.  slot selects where the (offset,size)
    pointer to the filename directory is written: 'first-8', 'table_end' or 'end'."""
    names = [n for n, _ in names_sizes]
    sizes = [s for _, s in names_sizes]
    count = len(names)
    table_end = 8 + 8 * count
    data_start = 0x800  # keep data well clear of the table
    offsets, pos = [], data_start
    for s in sizes:
        offsets.append(pos)
        pos += s
    dir_off = pos
    dir_size = 48 * count
    records = bytearray()
    for nm, sz in names_sizes:
        records += nm.encode("latin-1").ljust(32, b"\0") + struct.pack("<12xI", sz)
    data = b"X" * sum(sizes)
    header = b"AFS\x00" + struct.pack("<I", count)
    for o, s in zip(offsets, sizes):
        header += struct.pack("<II", o, s)
    ptr = struct.pack("<II", dir_off, dir_size)
    if slot == "table_end":
        blob = header + ptr
        blob = blob.ljust(data_start, b"\0") + data + bytes(records)
    elif slot == "first-8":
        blob = header.ljust(data_start - 8, b"\0") + ptr + data + bytes(records)
    elif slot == "end":
        blob = header.ljust(data_start, b"\0") + data + bytes(records) + ptr
    else:
        raise ValueError(slot)
    return blob


def test_afs_entries_little_endian():
    blob = _afs([("font.tm2", 66816), ("ask.bin", 604160)], slot="end")
    count, offsets, sizes, table_end = ci.afs_entries(blob)
    assert count == 2 and table_end == 8 + 8 * 2
    assert offsets == [0x800, 0x800 + 66816] and sizes == [66816, 604160]
    with pytest.raises(ValueError):
        ci.afs_entries(b"NOPE\x00" + blob[4:])
    with pytest.raises(ValueError):
        ci.afs_entries(blob[:10])  # truncated table


@pytest.mark.parametrize("slot", ["first-8", "table_end", "end"])
def test_find_name_dir_probes_three_slots(slot):
    names_sizes = [("pl00pak.bin", 100), ("pl00_hit.bin", 50), ("pl01pak.bin", 120)]
    blob = _afs(names_sizes, slot=slot)
    count, offsets, sizes, table_end = ci.afs_entries(blob)

    def rd(at, n):
        return blob[at:at + n]

    names, d_off, d_size = ci.find_name_dir(rd, len(blob), count, offsets, sizes, table_end)
    assert names == [n for n, _ in names_sizes]
    assert d_size == 48 * count


def test_find_name_dir_rejects_mismatched_sizes():
    names_sizes = [("pl00pak.bin", 100), ("pl00_hit.bin", 50)]
    blob = _afs(names_sizes, slot="end")
    # corrupt the recorded size of entry 0 in the name dir (last 4 bytes of its record)
    dir_off, dir_size = len(blob) - 8 - 48 * 2, 48 * 2
    rec = bytearray(blob[dir_off:dir_off + dir_size])
    struct.pack_into("<I", rec, 44, 999)
    blob = blob[:dir_off] + bytes(rec) + blob[dir_off + dir_size:]
    count, offsets, sizes, table_end = ci.afs_entries(blob)

    def rd(at, n):
        return blob[at:at + n]

    assert ci.find_name_dir(rd, len(blob), count, offsets, sizes, table_end) is None


def test_categorize_assets():
    names = ["font.tm2", "font_e.tm2", "pl00_fac.bin", "pl2f_fac.bin", "pl00pak.bin",
             "pl00_hit.bin", "pl00_tbl.bin", "edit_p00.bin", "dc00pol.bin", "dc00tex.bin",
             "dm00pol.bin", "dm00tex.bin", "dm00fac.bin", "efctpol.bin", "em00_dat.bin",
             "stg00pol.bin", "stg00tex.bin", "spr_ttl.bin", "ask.bin", "sce22ft.bin"]
    c = ci._categorize_assets(names)
    assert c["fonts_tm2"] == ["font.tm2", "font_e.tm2"]
    assert c["portraits_plNN_fac"] == ["pl00_fac.bin", "pl2f_fac.bin"]
    assert c["model_packs_plNNpak"] == ["pl00pak.bin"]
    assert c["hitboxes_plNN_hit"] == ["pl00_hit.bin"] and c["tables_plNN_tbl"] == ["pl00_tbl.bin"]
    assert c["edit_palettes"] == ["edit_p00.bin"]
    assert c["shared_models_dc"] == ["dc00pol.bin", "dc00tex.bin"]
    assert c["shared_models_dm"] == ["dm00fac.bin", "dm00pol.bin", "dm00tex.bin"]
    assert c["effects_efct"] == ["efctpol.bin"] and c["effects_em"] == ["em00_dat.bin"]
    assert c["stages"] == ["stg00pol.bin", "stg00tex.bin"]
    assert c["sprites"] == ["spr_ttl.bin"] and c["messages"] == ["ask.bin"]
    assert c["other"] == ["sce22ft.bin"]


@pytest.mark.skipif(not GCZ.exists(), reason="owned CvS2 EO GCZ not mounted (GBOX_CVS2EO_GCZ)")
def test_owned_disc_inventory():
    m = ci.manifest(str(GCZ), ci.SOURCE_SHA256)
    assert m["disc"]["game_code"] == "GEOE08"
    assert m["disc"]["title"] == "CAPCOM VS. SNK 2  EO"
    assert m["source"]["sha256"] == ci.SOURCE_SHA256
    assert m["executables"]["default_dol_fst"]["sha256"] == \
        "455591ea31c5904da3546bd2e713097740846b89db0cb167240187741b5c1435"
    assert m["executables"]["boot_dol_0x420"]["sha256"] == \
        "287c7bc5577138a15eefb8dc26633c80b58713bbab034e4b9a0dbd83aa76d69e"
    assert m["disc"]["file_count"] == 65
    assert m["character_roster"]["count"] == 48
    assert len(m["afs_archives"]) == 3
    assert all(s["out_of_range_entries"] == 0 and s["endianness"] == "little"
               for s in m["afs_archives"])
    ca = m["character_assets"]
    assert len(ca["model_packs_plNNpak"]) == 48
    assert len(ca["portraits_plNN_fac"]) == 108
    assert ca["fonts_tm2"] == ["font.tm2", "font_e.tm2"]
    # afs00.afs is ADX audio, not models (fingerprint correction)
    afs00 = next(s for s in m["afs_archives"] if s["path"].endswith("afs00.afs"))
    assert afs00["name_directory"]["names"][0].endswith(".adx")
