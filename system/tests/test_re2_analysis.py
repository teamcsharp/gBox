"""Focused tests for gbox.re2_analysis on the owned Resident Evil 2 N64 ROM.

Tests use the real verified ROM in ~/gbox-cache/46eec2fc627c8f58/rom.z64.
They exercise the overlay xref scanner and the 0x01410000 mesh probe.
"""

from pathlib import Path

import pytest

from gbox import re2_analysis as ra
from gbox import re2_inventory as ri

ROM_PATH = Path.home() / "gbox-cache" / "46eec2fc627c8f58" / "rom.z64"


@pytest.fixture(scope="module")
def loaded_overlay1():
    rom, _, _ = ri.load_rom(ROM_PATH)
    overlays = ri.read_overlays(rom)
    main = next(e for e in overlays if e.index == 1)
    overlay1 = main.decompress(rom)
    assert overlay1 is not None
    return overlay1, main.load_addr


@pytest.fixture(scope="module")
def asset_directory():
    rom, _, _ = ri.load_rom(ROM_PATH)
    overlays = ri.read_overlays(rom)
    directory = ri.read_asset_directory(rom, overlays)
    by_index = {e.index: e for e in directory.entries}
    return rom, directory, by_index


def test_overlay_xrefs_find_character_tables(loaded_overlay1):
    overlay1, load_base = loaded_overlay1
    xrefs = ra.find_table_xrefs(overlay1, load_base)
    tables = {x.table_name for x in xrefs}
    assert "char_asset_table" in tables
    assert "pair_table" in tables


def test_overlay_xrefs_addresses_reproducible(loaded_overlay1):
    overlay1, load_base = loaded_overlay1
    xrefs = ra.find_table_xrefs(overlay1, load_base)
    char_xrefs = [x for x in xrefs if x.table_name == "char_asset_table"]
    pair_xrefs = [x for x in xrefs if x.table_name == "pair_table"]

    # These addresses are stable for the USA Rev 1 build.
    assert any(x.lui_address == 0x80031D34 for x in char_xrefs)
    assert any(x.lui_address == 0x80031E40 for x in char_xrefs)
    assert any(x.lui_address == 0x80087518 for x in pair_xrefs)
    assert any(x.lui_address == 0x800876E0 for x in pair_xrefs)
    assert any(x.lui_address == 0x8008788C for x in pair_xrefs)


def test_mesh_probe_header(asset_directory):
    rom, directory, by_index = asset_directory
    data = by_index[5599].decode(rom, directory.base)
    mesh = ra.parse_mesh_asset(5599, data)
    assert mesh.magic == 0x01410000
    assert mesh.version == 0x11
    assert mesh.body_size == len(data) - ra.MESH_HEADER_SIZE
    assert mesh.chunk_count == 13
    assert mesh.valid


def test_mesh_probe_tail_records(asset_directory):
    rom, directory, by_index = asset_directory
    data = by_index[5599].decode(rom, directory.base)
    mesh = ra.parse_mesh_asset(5599, data)
    assert len(mesh.tail_records) == 4
    assert mesh.tail_records[-1].record_type in (2, 3)
    assert mesh.index_table_offset is not None
    assert len(mesh.index_entries) == mesh.chunk_count


def test_analyze_integration():
    report = ra.analyze(ROM_PATH, mesh_assets=[5599, 5600])
    assert report["source"]["overlay_1_size"] == 1172240
    assert any(x["table"] == "char_asset_table" for x in report["overlay_xrefs"])
    assert any(x["table"] == "pair_table" for x in report["overlay_xrefs"])
    assert len(report["mesh_probe"]) == 2
    assert all(p["valid"] for p in report["mesh_probe"])
