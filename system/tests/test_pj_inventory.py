"""Focused tests for gbox.pj_inventory (Project Justice USA Dreamcast inventory).

The real-disc test is gated on the staged cache at
~/gBox_alt/gbox-cache/dc/6334be1925fbe016/disc.gdi and skips otherwise.
"""

import struct
from pathlib import Path

import pytest

from gbox.pj_inventory import (
    CHAR_ARCHIVES,
    FIRST_READ_SHA256,
    SOURCE_CHD_SHA256,
    ROSTER_NAMES,
    inventory,
    ip_fields,
    sniff_afs,
)

CACHE = Path.home() / "gBox_alt/gbox-cache/dc/6334be1925fbe016"


def build_afs(entries: list[bytes]) -> bytes:
    """Minimal CRI AFS: magic, count, (offset,size) pairs, then payloads."""
    n = len(entries)
    table_size = 8 + 8 * n
    data_start = table_size
    offs = []
    payloads = b""
    cur = data_start
    for e in entries:
        offs.append((cur, len(e)))
        payloads += e
        cur += len(e)
    head = b"AFS\x00" + struct.pack("<I", n)
    for off, size in offs:
        head += struct.pack("<II", off, size)
    return head + payloads


def test_sniff_afs_parses_entry_table():
    data = build_afs([b"AAAA", b"BB", b"CCCCCC"])
    info = sniff_afs(data)
    assert info["count"] == 3
    assert info["first_data_offset"] == 8 + 3 * 8
    assert [e["size"] for e in info["entries"]] == [4, 2, 6]
    assert info["entries"][0]["magic16"].startswith(b"AAAA".hex())


def test_sniff_afs_rejects_bad_magic():
    with pytest.raises(ValueError):
        sniff_afs(b"NOPE\x00\x00\x00\x00\x00")


def test_ip_fields_offsets():
    ip = bytearray(0x100)
    ip[0x00:0x20] = b"SEGA SEGAKATANA SEGA ENTERPRISES"
    ip[0x20:0x30] = b"1EAC GD-ROM1/1  "
    ip[0x30:0x40] = b" U      07BBA10 "
    ip[0x40:0x50] = b"T1219N    V1.001"
    ip[0x50:0x60] = b"20010126        "
    ip[0x60:0x70] = b"1ST_READ.BIN    "
    ip[0x70:0x80] = b"SEGA LC-T-12    "
    ip[0x80:0x90] = b"PROJECT JUSTICE "
    f = ip_fields(bytes(ip))
    assert f["product_version"].startswith("T1219N")
    assert f["date"] == "20010126"
    assert f["boot_file"] == "1ST_READ.BIN"
    assert f["title"] == "PROJECT JUSTICE"


@pytest.mark.skipif(not (CACHE / "disc.gdi").exists(),
                    reason="staged Project Justice GDI not present")
def test_real_disc_inventory_matches_build():
    man = inventory(CACHE / "disc.gdi", chd=CACHE / "source.chd")
    # owned-source identity must stay constant across stages
    assert man["source"]["sha256"] == SOURCE_CHD_SHA256
    # executable pin
    assert man["executable"]["sha256"] == FIRST_READ_SHA256
    assert man["executable"]["size"] == 3011944
    assert man["executable"]["load_base"] == 0x8C010000
    # IP.BIN facts
    assert man["disc"]["ip"]["product_version"].startswith("T1219N")
    assert man["disc"]["ip"]["date"] == "20010126"
    assert man["disc"]["ip"]["boot_file"] == "1ST_READ.BIN"
    # container layout: 20 root files, 15 CRI AFS + UDCSDM not an AFS
    assert len(man["files"]) == 20
    assert man["udcsdm"]["is_afs"] is False
    assert man["udcsdm"]["size"] == 471859200
    # character chain sizes on this exact build
    for name, want in CHAR_ARCHIVES.items():
        info = man["archives"][name]
        assert info["count"] == want, name
        assert info["first_data_offset"] == 0x80000, name
    assert man["characters"]["textures_per_model"] == 8
    # every roster name appears in the executable, except RAIZO (no ASCII
    # spelling in 1ST_READ on this build - name table TBD in analysis)
    missing = [n for n in ROSTER_NAMES if man["characters"]["roster_names_in_exe"][n] == 0]
    assert missing == ["RAIZO"]
