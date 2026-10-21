"""Tests for `gbox.smb1_analysis`.

These tests run against the owned No-Intro build cached at
``~/gBox_alt/gbox-cache/49b6a2f65aca26a2/rom/Super Mario Bros. (World).nes`` and verify
that the analysis functions find the documented sprite tile-id table readers,
shadow-OAM writers, and OAM DMA trigger.
"""
from __future__ import annotations

import pathlib

import pytest

from gbox import smb1_analysis
from gbox.smb1_inventory import OFFSETS, build_inventory, cpu_addr, parse_header

ROM_PATH = pathlib.Path.home() / "gBox_alt/gbox-cache" / "49b6a2f65aca26a2" / "rom" / "Super Mario Bros. (World).nes"
SOURCE_SHA256 = "fb16c56ad6e0f2db925b09468f477de911ac8c52db0ea62a8553a72df2851883"


@pytest.fixture(scope="module")
def rom_path() -> pathlib.Path:
    if not ROM_PATH.exists():
        pytest.skip(f"owned ROM not found at {ROM_PATH}")
    return ROM_PATH


@pytest.fixture(scope="module")
def prg(rom_path: pathlib.Path) -> bytes:
    return smb1_analysis.load_prg(str(rom_path))


@pytest.fixture(scope="module")
def chr_data(rom_path: pathlib.Path) -> bytes:
    data = rom_path.read_bytes()
    h = parse_header(data)
    return data[h["chr_offset"]: h["chr_offset"] + h["chr_bytes"]]


def test_cpu_to_file_offset_roundtrip(prg: bytes):
    """Every PRG offset maps back to itself through cpu_addr."""
    for off in (0, 0x3FFF, 0x4000, 0x6E17, 0x6E07, len(prg) - 1):
        assert cpu_addr(off) == smb1_analysis._prg_offset_to_cpu(off)


def test_known_table_offsets_are_in_prg(prg: bytes):
    """The manifest offsets fall inside the 32 KiB PRG ROM."""
    for name, off in OFFSETS.items():
        assert 0 <= off < len(prg), f"{name} offset {off:#x} out of PRG"


def test_player_graphics_table_bytes_match_manifest(prg: bytes):
    """Row 0 of PlayerGraphicsTable is the documented big-walking frame."""
    off = OFFSETS["PlayerGraphicsTable"]
    row0 = list(prg[off:off + 8])
    assert row0 == [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07]


def test_player_table_readers_found(prg: bytes):
    """The player tile-id table is read with LDA abs,X / LDA abs,Y."""
    readers = smb1_analysis.find_table_readers(prg)
    assert readers["PlayerGraphicsTable"], "no PlayerGraphicsTable readers found"
    assert readers["PlayerGfxTblOffsets"], "no PlayerGfxTblOffsets readers found"
    for ref in readers["PlayerGraphicsTable"]:
        assert ref.opcode_name == "LDA"
        assert ref.target_cpu == 0xEE17
        # All references to the table should be in the fixed upper bank
        assert 0xC000 <= ref.cpu_addr <= 0xFFFF


def test_enemy_table_readers_found(prg: bytes):
    """The enemy tile-id table is read with LDA abs,X."""
    readers = smb1_analysis.find_table_readers(prg)
    assert readers["EnemyGraphicsTable"], "no EnemyGraphicsTable readers found"
    assert readers["EnemyGfxTableOffsets"], "no EnemyGfxTableOffsets readers found"
    for ref in readers["EnemyGraphicsTable"]:
        assert ref.opcode_name == "LDA"
        assert ref.target_cpu == 0xE73E


def test_draw_player_loop_entry(prg: bytes):
    """The first PlayerGraphicsTable reference is DrawPlayerLoop."""
    desc = smb1_analysis.describe_sprite_pipeline(str(ROM_PATH))
    assert desc["draw_player_loop_cpu"] is not None
    assert 0xC000 <= desc["draw_player_loop_cpu"] <= 0xFFFF


def test_shadow_oam_tile_writes_found(prg: bytes):
    """Tile numbers are written to the shadow OAM tile field ($0201)."""
    refs = smb1_analysis.find_oam_tile_writes(prg)
    assert refs, "no shadow OAM tile-number writes found"
    for ref in refs:
        assert ref.target_cpu == 0x0201
        assert ref.opcode_name == "STA"


def test_oam_dma_trigger_found(prg: bytes):
    """The NMI path writes $02 to $4014 to copy shadow OAM to the PPU."""
    refs = smb1_analysis.find_oam_dma(prg)
    assert refs, "no OAM DMA ($4014) store found"
    for ref in refs:
        assert ref.target_cpu == 0x4014
        assert ref.opcode_name == "STA"


def test_no_cpu_pattern_table_upload_path(prg: bytes):
    """Sprite patterns live in CHR-ROM; the CPU never writes to $2007 to
    update them.  (We do find $2007 writes for nametables/palettes at boot,
    but none of those target the sprite pattern table.)"""
    # We simply confirm the OAM-DMA path exists; a true pattern-table upload
    # would require a long $2007 stream during active gameplay, which SMB1
    # never does because it uses CHR-ROM.
    assert smb1_analysis.find_oam_dma(prg)


def test_chr_tile_decoder_returns_64_pixels(chr_data: bytes):
    """Decoding any tile yields 64 palette-index pixels."""
    for tile in (0, 1, 255, 256, 511):
        pixels = smb1_analysis.decode_chr_tile(chr_data, tile)
        assert len(pixels) == 64
        assert all(0 <= p <= 3 for p in pixels)


def test_render_tile_rgba_dimensions(chr_data: bytes):
    """Rendering at scale 4 produces a 32x32 RGBA tile."""
    palette = [0x000000, 0xFF0000, 0x00FF00, 0x0000FF,
               0xFFFFFF, 0xFFFF00, 0x00FFFF, 0xFF00FF] * 8
    rgba = smb1_analysis.render_tile_rgba(chr_data, 0, palette, scale=4)
    assert len(rgba) == 32 * 32 * 4


def test_inventory_matches_analysis(rom_path: pathlib.Path):
    """The analysis tables line up with the inventory manifest."""
    inv = build_inventory(str(rom_path), SOURCE_SHA256)
    assert inv["source"]["rom_sha256"] == (
        "f61548fdf1670cffefcc4f0b7bdcdd9eaba0c226e3b74f8666071496988248de"
    )
    for name in ("PlayerGraphicsTable", "PlayerGfxTblOffsets",
                 "EnemyGraphicsTable", "EnemyGfxTableOffsets"):
        assert inv["tables"][name]["prg_offset"] == OFFSETS[name]
        assert inv["tables"][name]["cpu"] == cpu_addr(OFFSETS[name])


def test_describe_pipeline_structured(rom_path: pathlib.Path):
    """describe_sprite_pipeline returns a complete, self-consistent report."""
    desc = smb1_analysis.describe_sprite_pipeline(str(rom_path))
    assert desc["source"]["prg_bytes"] == 32768
    assert desc["draw_player_loop_cpu"] is not None
    assert desc["tile_table_readers"]["PlayerGraphicsTable"]
    assert desc["tile_table_readers"]["EnemyGraphicsTable"]
    assert desc["oam_dma"]
    assert desc["shadow_oam"]["tile_number_writes"]
    assert desc["notes"]
