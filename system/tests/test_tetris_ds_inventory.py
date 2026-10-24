"""Tests for Tetris DS (USA) inventory module.

These tests verify:
  - ROM verification against the known SHA256
  - Inventory manifest structure and consistency
  - Roster generation covers all sprite sets
  - Integration with the native reader
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest

from gbox.tetris_ds_inventory import (
    TETRIS_DS_SETS,
    TETRIS_DS_ROM_SHA256,
    build_inventory,
    ensure_inventory,
    roster,
    sha256_bytes,
    verify_rom,
)


# Build a minimal valid NDS header for testing (only for verify_rom, not build_inventory)
def make_nds_header(
    title: str = "TETRIS DS",
    gamecode: str = "ATRE",
    unitcode: int = 0x00,
) -> bytes:
    """Build a minimal NDS ROM header for testing (only header, no filesystem)."""
    header = bytearray(0x200)
    # Title (12 bytes)
    header[0x00:0x0C] = title.encode("ascii").ljust(12, b"\x00")
    # Game code (4 bytes)
    header[0x0C:0x10] = gamecode.encode("ascii")
    # Unit code (1 byte)
    header[0x12] = unitcode
    # ARM9 info
    struct.pack_into("<IIII", header, 0x20, 0x00010000, 0x00010000, 0x02000000, 0x4000)
    struct.pack_into("<IIII", header, 0x30, 0x00014000, 0x00014000, 0x02000000, 0x1000)
    # FNT/FAT offsets and sizes - minimal valid values for header-only tests
    struct.pack_into("<II", header, 0x40, 0x200, 0x20)  # fnt_off=0x200, fnt_size=0x20
    struct.pack_into("<II", header, 0x48, 0x220, 0x10)  # fat_off=0x220, fat_size=0x10
    return bytes(header)


def test_sha256_bytes():
    """sha256_bytes produces correct hex digest."""
    data = b"test data"
    expected = hashlib.sha256(data).hexdigest()
    assert sha256_bytes(data) == expected


def test_verify_rom_header_fields():
    """verify_rom extracts correct header fields."""
    header = make_nds_header()
    rom_data = header + b"\x00" * (16 * 1024 * 1024 - 0x200)

    result = verify_rom(rom_data)
    # Header fields should be extracted correctly
    assert result["gamecode"] == "ATRE"
    assert result["title"] == "TETRIS DS"
    assert result["unitcode"] == 0x00
    assert result["verified"] is False  # SHA256 will differ for header-only
    # Verify that SHA256 mismatch is the reason
    assert "reason" in result
    assert "SHA256" in result["reason"]


def test_verify_rom_negative_wrong_gamecode():
    """verify_rom rejects wrong gamecode."""
    header = make_nds_header(gamecode="XXXX")
    rom_data = header + b"\x00" * (16 * 1024 * 1024 - 0x200)

    result = verify_rom(rom_data)
    assert result["verified"] is False
    assert "Gamecode mismatch" in result.get("reason", "")


def test_verify_rom_negative_wrong_title():
    """verify_rom rejects wrong title."""
    header = make_nds_header(title="WRONG")
    rom_data = header + b"\x00" * (16 * 1024 * 1024 - 0x200)

    result = verify_rom(rom_data)
    assert result["verified"] is False
    assert "Title mismatch" in result.get("reason", "")


def test_verify_rom_negative_wrong_unitcode():
    """verify_rom rejects wrong unitcode."""
    header = make_nds_header(unitcode=0x01)
    rom_data = header + b"\x00" * (16 * 1024 * 1024 - 0x200)

    result = verify_rom(rom_data)
    assert result["verified"] is False
    assert "Unitcode mismatch" in result.get("reason", "")


def test_verify_rom_too_small():
    """verify_rom rejects ROMs smaller than 512 bytes."""
    result = verify_rom(b"\x00" * 256)
    assert result["verified"] is False
    assert "too small" in result.get("reason", "")


def test_roster_returns_all_sets():
    """roster() covers all sprite sets from TETRIS_DS_SETS."""
    sets = set(s["key"] for s in roster())
    assert sets == set(TETRIS_DS_SETS)

    # Check structure of each entry
    for entry in roster():
        assert "key" in entry
        assert "slug" in entry
        assert "name" in entry
        assert "aliases" in entry
        assert "kind" in entry
        assert entry["kind"] == "character"


def test_roster_consistent_with_reader():
    """roster() matches TetrisDSReader.sprite_sets()."""
    # This test requires an actual ROM file - if one exists in TETRIS_DS_ROM
    # env var, run the test; otherwise skip
    import os

    rom_path = os.environ.get("TETRIS_DS_ROM")
    if not rom_path or not Path(rom_path).exists():
        pytest.skip("TETRIS_DS_ROM not set or file not found")

    from gbox.tetris_ds import TetrisDSReader, NDSRom

    rom_data = Path(rom_path).read_bytes()
    reader = TetrisDSReader(rom_data)

    roster_keys = {e["key"] for e in roster()}
    reader_sets = set(reader.sprite_sets())

    # All roster entries should be found in reader sets
    assert roster_keys.issubset(reader_sets)


def test_build_inventory_structure():
    """build_inventory produces all required fields (using actual ROM if available)."""
    import os

    rom_path = os.environ.get("TETRIS_DS_ROM")
    if not rom_path or not Path(rom_path).exists():
        pytest.skip("TETRIS_DS_ROM not set or file not found")

    rom_data = Path(rom_path).read_bytes()
    manifest = build_inventory(rom_data)

    # Check required fields
    assert manifest["game_id"] == "25da54968d78f816"
    assert manifest["title"] == "Tetris DS (USA)"
    assert manifest["platform"] == "nds"
    assert manifest["rom_sha256"] == TETRIS_DS_ROM_SHA256
    assert manifest["verified"] is True
    assert "asset_counts" in manifest
    assert "sprite_sets" in manifest
    assert "sprite_set_count" in manifest
    assert "file_count" in manifest
    assert "manifest_sha256" in manifest

    # Verify manifest integrity
    manifest_copy = manifest.copy()
    computed_hash = manifest_copy.pop("manifest_sha256")
    recomputed = hashlib.sha256(
        json.dumps(manifest_copy, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert recomputed == computed_hash


def test_build_inventory_verify_false_for_corrupt():
    """build_inventory sets verified=False for non-matching ROM."""
    import os

    rom_path = os.environ.get("TETRIS_DS_ROM")
    if not rom_path or not Path(rom_path).exists():
        pytest.skip("TETRIS_DS_ROM not set or file not found")

    rom_data = Path(rom_path).read_bytes()
    # Corrupt the header
    rom_data = rom_data[:0x0C] + b"XXXX" + rom_data[0x10:]

    manifest = build_inventory(rom_data)
    assert manifest["verified"] is False


def test_ensure_inventory_writes_manifest(tmp_path):
    """ensure_inventory writes manifest.json when cache_dir provided."""
    import os

    rom_path = os.environ.get("TETRIS_DS_ROM")
    if not rom_path or not Path(rom_path).exists():
        pytest.skip("TETRIS_DS_ROM not set or file not found")

    src_rom = Path(rom_path)
    test_rom = tmp_path / "test.nds"
    test_rom.write_bytes(src_rom.read_bytes())

    result = ensure_inventory(test_rom, tmp_path)

    assert "manifest_path" in result
    assert Path(result["manifest_path"]).exists()

    # Verify written content
    with open(result["manifest_path"]) as f:
        loaded = json.load(f)
    assert loaded["verified"] is True
    assert loaded["rom_sha256"] == TETRIS_DS_ROM_SHA256


def test_roster_has_expected_sprite_sets():
    """roster() includes all known sprite sets."""
    keys = [e["key"] for e in roster()]

    # Verify some key sprite sets are present
    expected = {"ct_", "donkey", "super_mario", "zelda", "ctanime_zelda"}
    assert expected.issubset(set(keys))

    # Verify the count matches TETRIS_DS_SETS
    assert len(keys) == len(TETRIS_DS_SETS)


def test_roster_slugs_are_unique():
    """roster() entries have unique slugs."""
    slugs = [e["slug"] for e in roster()]
    assert len(slugs) == len(set(slugs))


def test_verify_rom_provides_detailed_reasons():
    """verify_rom provides specific reasons for rejection."""
    # Test each mismatch type
    for gamecode in ["XXXX"]:
        header = make_nds_header(gamecode=gamecode)
        rom_data = header + b"\x00" * (16 * 1024 * 1024 - 0x200)
        result = verify_rom(rom_data)
        assert "reason" in result
        assert "Gamecode" in result["reason"]

    for title in ["WRONG"]:
        header = make_nds_header(title=title)
        rom_data = header + b"\x00" * (16 * 1024 * 1024 - 0x200)
        result = verify_rom(rom_data)
        assert "reason" in result
        assert "Title" in result["reason"]


def test_manifest_sha256_changes_on_modification():
    """manifest_sha256 changes when content changes."""
    import os

    rom_path = os.environ.get("TETRIS_DS_ROM")
    if not rom_path or not Path(rom_path).exists():
        pytest.skip("TETRIS_DS_ROM not set or file not found")

    rom_data = Path(rom_path).read_bytes()
    manifest1 = build_inventory(rom_data)
    hash1 = manifest1["manifest_sha256"]

    # Modify a non-hash field
    manifest1["test_field"] = "modified"
    hash2 = hashlib.sha256(json.dumps(manifest1, sort_keys=True).encode("utf-8")).hexdigest()

    assert hash1 != hash2
