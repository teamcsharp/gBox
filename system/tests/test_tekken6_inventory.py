"""Focused tests for Tekken 6 (Xbox 360) disc inventory.

These read only headers and directory sectors from the owned ISO (a few MB of
seeks, not the full 7 GB). Skip cleanly when the disc is absent, so the suite
runs anywhere. The ISO is never modified.
"""
import os
import struct
from pathlib import Path

import pytest

from gbox import tekken6_inventory as t6

ISO = Path(os.environ.get("GBOX_TEKKEN6_ISO", t6.DEFAULT_ISO))

owned_disc = pytest.mark.skipif(not ISO.exists(), reason="Tekken 6 ISO not present")


def test_classify_magics():
    assert t6.classify(b"XEX2" + b"\x00" * 12) == "xex"
    assert t6.classify(t6.PACK_MAGIC_BYTES + b"\x00" * 12) == "pack"
    assert t6.classify(b"PAC\x01" + b"\x00" * 12) == "pac"
    assert t6.classify(t6.ASF_GUID + b"\x00" * 12) == "asf"
    assert t6.classify(b"DINF" + b"\x00" * 12) == "dinf"
    assert t6.classify(b"\x00" * 16) == "unknown"


@owned_disc
def test_inventory_layout():
    inv = t6.inventory(ISO)

    assert inv["engine"] == "Namco (Tekken 6 / TTT2 family)"
    assert inv["pack_magic"] == "0x0FF512ED"
    assert inv["file_count"] == 43

    # Boot executable is a real XEX2
    boot = inv["boot"]
    assert boot["path"].casefold() == "default.xex"
    assert boot["format"] == "xex2"
    assert len(boot["sha256"]) == 64

    # DINF master directory declares the data-file count and build date
    dinf = inv["dinf"]
    assert dinf["count"] == 20
    assert any("x360" in r for r in dinf["build_roots"])
    assert dinf["build_dates"], "expected a build date stamp (e.g. 20090916)"

    by_path = {c["path"].upper(): c for c in inv["containers"]}
    assert by_path["DATA301.BIN"]["kind"] == "pack"
    assert by_path["DATA301.BIN"]["magic"] == "0ff512ed"
    assert by_path["DATA314.BIN"]["kind"] == "pac"
    for name in ("DATA315.BIN", "DATA320.BIN"):
        assert by_path[name]["kind"] == "asf", f"{name} should be an ASF/WMA stream"

    # every .BIN has a paired .IDX with 8-byte records
    bins = {c["path"].upper() for c in inv["containers"]}
    idx = {i["path"].upper(): i for i in inv["indexes"]}
    for b in bins:
        i = b[:-4] + ".IDX"
        assert i in idx, f"missing index for {b}"
        assert idx[i]["records"] > 0, f"{i} has no records"


@owned_disc
def test_idx_records_are_big_endian_pairs():
    inv = t6.inventory(ISO)
    idx = {i["path"].upper(): i for i in inv["indexes"]}
    # DATA308.IDX maps ids 0,1,2,... to a uniform 0x30 size - a clean sanity case.
    records = t6.idx_records(ISO, idx["DATA308.IDX"]["sector"], idx["DATA308.IDX"]["size"])
    assert records[0] == (0, 0x30)
    assert records[1] == (1, 0x30)
    # records are (key, value) u32 pairs; first field of the first record is the key
    assert all(isinstance(k, int) and isinstance(v, int) for k, v in records)


@pytest.mark.parametrize("base", [0, 0x2080000])
def test_partition_offsets_survive_file_listing(tmp_path, base):
    iso = tmp_path / "small.iso"
    name = b"Default.xex"
    entry = struct.pack("<HHIIBB", 0, 0, 34, 16, 0, len(name)) + name
    with iso.open("wb") as stream:
        stream.seek(base + 32 * t6.SECTOR)
        stream.write(t6.XDVDFS_MAGIC + struct.pack("<II", 33, len(entry)))
        stream.seek(base + 33 * t6.SECTOR)
        stream.write(entry)
        stream.seek(base + 34 * t6.SECTOR)
        stream.write(b"XEX2" + bytes(12))
    assert t6.xdvdfs_files(iso)["Default.xex"] == (base // t6.SECTOR + 34, 16)
    assert t6.inventory(iso)["boot"]["format"] == "xex2"
