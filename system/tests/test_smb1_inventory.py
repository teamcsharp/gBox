"""Tests for `gbox.smb1_inventory`.

These tests verify the owned Super Mario Bros. (World) NES build and its
character/sprite inventory against the cached ROM.
"""
from __future__ import annotations

import pathlib

import pytest

from gbox import smb1_inventory

ROM_PATH = pathlib.Path.home() / "gbox-cache" / "49b6a2f65aca26a2" / "rom" / "Super Mario Bros. (World).nes"
SOURCE_SHA256 = "fb16c56ad6e0f2db925b09468f477de911ac8c52db0ea62a8553a72df2851883"


@pytest.fixture(scope="module")
def rom_data() -> bytes:
    if not ROM_PATH.exists():
        pytest.skip(f"owned ROM not found at {ROM_PATH}")
    return ROM_PATH.read_bytes()


def test_header_is_ines(rom_data: bytes):
    h = smb1_inventory.parse_header(rom_data)
    assert h["format"] == "iNES 1.0"


def test_mapper_and_layout(rom_data: bytes):
    h = smb1_inventory.parse_header(rom_data)
    assert h["mapper"] == 0
    assert h["prg_rom_16kb_banks"] == 2
    assert h["chr_rom_8kb_banks"] == 1
    assert h["mirroring"] == "vertical"
    assert not h["battery"]
    assert not h["trainer"]


def test_build_is_known(rom_data: bytes):
    assert smb1_inventory.identify(rom_data) is not None


def test_prg_crc32_matches_no_intro(rom_data: bytes):
    h = smb1_inventory.parse_header(rom_data)
    prg = rom_data[h["prg_offset"]: h["prg_offset"] + h["prg_bytes"]]
    assert smb1_inventory._crc32(prg) == 0x5CF548D3


def test_source_sha256_matches(rom_data: bytes):
    h = smb1_inventory.parse_header(rom_data)
    assert h["prg_bytes"] == 32768
    assert h["chr_bytes"] == 8192
    inv = smb1_inventory.build_inventory(str(ROM_PATH), SOURCE_SHA256)
    assert inv["source"]["zip_sha256"] == SOURCE_SHA256


def test_player_frames_count(rom_data: bytes):
    inv = smb1_inventory.build_inventory(str(ROM_PATH), SOURCE_SHA256)
    assert len(inv["characters"]["player"]["frames"]) == 26
    assert len(inv["characters"]["player"]["state_rows"]) == 16


def test_enemy_rows_count(rom_data: bytes):
    inv = smb1_inventory.build_inventory(str(ROM_PATH), SOURCE_SHA256)
    assert len(inv["characters"]["enemies"]["rows"]) == 43
    assert len(inv["characters"]["enemies"]["slots"]) == 27


def test_palettes_have_four_colors(rom_data: bytes):
    inv = smb1_inventory.build_inventory(str(ROM_PATH), SOURCE_SHA256)
    ground = inv["characters"]["palettes"]["GroundPaletteData"]
    assert ground["ppu_addr"] == 0x3F00
    assert len(ground["palettes"]) == 8
    assert all(len(p) == 4 for p in ground["palettes"])


def test_tile_decoder_output(rom_data: bytes):
    h = smb1_inventory.parse_header(rom_data)
    chr_ = rom_data[h["chr_offset"]: h["chr_offset"] + h["chr_bytes"]]
    pixels = smb1_inventory.tile_pixels(chr_, 0)
    assert len(pixels) == 64
    assert all(0 <= p <= 3 for p in pixels)
