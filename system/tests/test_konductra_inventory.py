"""Focused tests for the Konductra (USA) NDS inventory reader (stage 1: inventory).

The synthetic fixture is hand-built (offsets, ids, sizes and payloads are
literals written down in the test), so the assertions are NOT produced by the
parser under test.  The owned-build tests then validate the same code against
the real owned cartridge and cross-check it with the independent
gbox.tetris_ds.NDSRom reader.
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbox.konductra import (  # noqa: E402
    ASSET_EXTS, KONDUKTRA_ROM_SHA256, KonductraNDS, find_rom, inventory, sha256_file,
)


def _synthetic_nds() -> bytes:
    """Hand-built NDS image: 0x200 header + FNT + FAT + body, flat FNT."""
    fnt = bytearray()
    fnt += struct.pack("<IHH", 8, 0, 0)        # root subtable at 8, first file id 0
    fnt += bytes([5]) + b"a.bin"               # file id 0
    fnt += bytes([5]) + b"b.bin"               # file id 1
    fnt += bytes([0])                          # end of root table
    fat = struct.pack("<II", 0x200 + len(fnt) + 16, 0x200 + len(fnt) + 21) \
         + struct.pack("<II", 0x200 + len(fnt) + 21, 0x200 + len(fnt) + 26)
    header = bytearray(0x200)
    header[0x00:0x0C] = b"KONDUCTRA" + b"\x00" * 4
    header[0x0C:0x10] = b"KDCT"
    header[0x12] = 0
    struct.pack_into("<II", header, 0x40, 0x200, len(fnt))
    struct.pack_into("<II", header, 0x48, 0x200 + len(fnt), len(fat))
    return bytes(header) + bytes(fnt) + fat + b"HELLO" + b"WORLD"


def test_synthetic_fnt_fat_walk():
    rom = KonductraNDS(_synthetic_nds())
    assert rom.gamecode == "KDCT"
    assert rom.title == "KONDUCTRA"
    assert rom.unitcode == 0
    assert rom.paths() == ["a.bin", "b.bin"]
    sizes = {f["path"]: f["size"] for f in rom.files()}
    assert sizes == {"a.bin": 5, "b.bin": 5}
    assert rom.raw("a.bin") == b"HELLO"
    assert rom.raw("b.bin") == b"WORLD"


def test_census_counts_assets_and_separates_name_guesses():
    rom = KonductraNDS(_synthetic_nds())
    census = rom.census()
    assert census["counted_total"] == 2
    assert {"ext": ".bin", "count": 2} in census["counted_by_ext"]
    assert census["name_guesses"] == []
    assert [c["path"] for c in census["target_candidates"]] == ["a.bin", "b.bin"]
    assert census["counted_bytes"] == 10


def test_fat_range_is_validated():
    data = bytearray(_synthetic_nds())
    rom = KonductraNDS(bytes(data))
    fat = bytearray(data[rom.fat_off:rom.fat_off + rom.fat_size])
    fat[4:8] = struct.pack("<I", 0xFFFFFF)
    data[rom.fat_off:rom.fat_off + rom.fat_size] = fat
    with pytest.raises(ValueError):
        KonductraNDS(bytes(data))


def _owned_rom():
    rom = find_rom()
    if rom is None:
        pytest.skip("owned Konductra (USA) ROM not reachable from this node")
    return rom


def test_owned_rom_identity_is_streamed_sha256():
    assert sha256_file(_owned_rom()) == KONDUKTRA_ROM_SHA256


def test_owned_rom_inventory_layout():
    data = _owned_rom().read_bytes()
    nds = KonductraNDS(data)
    assert nds.gamecode.strip() and len(nds.gamecode) == 4
    assert nds.fat_size % 8 == 0 and nds.fnt_size >= 8
    files = nds.files()
    assert files, "cartridge filesystem must not be empty"
    for f in files:
        assert 0 <= f["start"] <= f["end"] <= len(data)
    census = nds.census()
    assert census["counted_total"] == len(files)
    assert census["counted_bytes"] == sum(f["size"] for f in files)
    assert census["counted_by_ext"]


def test_inventory_reports_identity_and_target_candidates():
    inv = inventory()
    assert inv["source"]["identity_ok"] is True
    assert inv["source"]["sha256"] == KONDUKTRA_ROM_SHA256
    assert inv["files"]["count"] == len(inv["files"]["list"])
    assert inv["census"]["counted_total"] == inv["files"]["count"]
    assert inv["cross_check"]["agrees"] is True
    for cand in inv["census"]["target_candidates"]:
        assert cand["size"] > 0
        assert os.path.splitext(cand["path"])[1].lower() in ASSET_EXTS
