"""Tests for gbox.goldeneye_inventory.

These tests run against the owned 007 - GoldenEye (Europe) zip from the
HyperSpin library.  They verify that the inventory module can identify the
build, validate the CIC checksum, and produce a manifest without touching
the original archive.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from gbox import goldeneye_inventory, n64_rom

# Owned source from the HyperSpin catalog (rel_path, library=hyperspin).
SRC_ZIP = Path("/mnt/gbox/hyperspin/Arcade/collections/Nintendo 64/roms/Europe/007 - GoldenEye (Europe).zip")


def _skip_if_no_source():
    if not SRC_ZIP.is_file():
        pytest.skip(f"owned source not reachable: {SRC_ZIP}")


@pytest.fixture(scope="module")
def rom():
    _skip_if_no_source()
    return n64_rom.read(SRC_ZIP)


def test_source_zip_unchanged():
    _skip_if_no_source()
    stat = SRC_ZIP.stat()
    assert stat.st_size == 10_794_599, "unexpected zip size"
    assert stat.st_mtime_ns > 0


def test_rom_normalised_to_z64(rom):
    assert rom[:4] == b"\x80\x37\x12\x40"
    assert len(rom) == 12 * 1024 * 1024


def test_header_is_goldeneye_europe(rom):
    title = rom[0x20:0x34].split(b"\x00")[0].decode("ascii").strip()
    assert title == "GOLDENEYE"
    assert rom[0x3C:0x3E] == b"GE"
    assert rom[0x3E] == 0x50  # P = Europe


def test_cic6102_checksum_validates(rom):
    c1, c2 = goldeneye_inventory.crc6102(rom)
    import struct
    s1, s2 = struct.unpack_from(">II", rom, 0x10)
    assert c1 == s1
    assert c2 == s2


def test_inventory_runs_and_is_verified(rom):
    data = goldeneye_inventory.inventory(rom)
    assert data["header"]["region"] == "Europe"
    assert data["header"]["cart_id"] == "GE"
    assert data["header"]["boot_checksum_ok"] is True
    assert data["rom_size"] == 12 * 1024 * 1024
    assert data["container_layout"]["kind"] == "flat_n64_rom"
    assert data["character_inventory"]["verified"] is False
    # SHA-256 must be the canonical big-endian ROM.
    import hashlib
    assert data["rom_sha256"] == hashlib.sha256(rom).hexdigest()


def test_inventory_outputs_json(tmp_path, rom):
    out = tmp_path / "manifest.json"
    data = goldeneye_inventory.inventory(rom)
    out.write_text(json.dumps(data, indent=2))
    loaded = json.loads(out.read_text())
    assert loaded["game"] == "007 - GoldenEye"
    assert loaded["header"]["region"] == "Europe"


def test_region_map_covers_whole_rom(rom):
    regions = goldeneye_inventory.region_map(rom)
    assert regions[0].start == 0
    assert regions[-1].end >= len(rom)
    # Header and boot_code labels should appear.
    labels = {r.label for r in regions}
    assert "header" in labels
    assert "boot_code" in labels
