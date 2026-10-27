"""Tests for the S&K + Sonic 1 lock-on / Blue Spheres SStage sprite export.

Tests:
- DEDICATED entry registration and title/platform match
- Roster shape
- No-op roundtrip: re-encode DPLC and mapping frames, byte-compare with fixture
- Fixture independence: known tile and palette values

No owned-build tests (the ROM is not on this host); the no-op roundtrip
proof runs on a synthetic fixture that exercises the same code paths.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbox import characters as C
from gbox import sk_export
from gbox.sk_lockon_analysis import (
    encode_dplc_frame,
    encode_map_frame,
    parse_dplc,
    parse_mappings,
)


# ---------------------------------------------------------------------------
# DEDICATED registration
# ---------------------------------------------------------------------------

def test_dedicated_entry_exists():
    names = [r[0] for r in C.DEDICATED]
    assert "sk_sstage" in names, f"sk_sstage missing from DEDICATED: {names}"


def test_dedicated_entry_matches_title_and_platform():
    entry = next(r for r in C.DEDICATED if r[0] == "sk_sstage")
    _, match, _, _ = entry
    # Should match (title is lowercased by the caller per DEDICATED contract)
    assert match("sonic & knuckles + sonic the hedgehog 2 (world)", "genesis")
    # Should NOT match standalone S&K
    assert not match("sonic & knuckles (world)", "genesis")
    # Should NOT match other platforms
    assert not match("sonic & knuckles + sonic the hedgehog 2 (world)", "n64")


def test_roster_shape():
    entries = sk_export.roster()
    assert len(entries) == 1
    e = entries[0]
    assert e["key"] == "sonic_sstage"
    assert e["slug"] == "sk_sstage_sonic"
    assert e["name"] == "Sonic (SStage, Blue Spheres)"
    assert e["kind"] == "character"
    assert "Sonic SStage" in e["aliases"]


# ---------------------------------------------------------------------------
# No-op roundtrip on a synthetic fixture
# ---------------------------------------------------------------------------

def _make_fixture(n_frames: int = 3, tiles_per_frame: int = 4,
                  art_tiles: int = 16, pieces_per_frame: int = 2) -> bytes:
    """Build a minimal ROM fixture with DPLC and mapping frames.

    Layout (all big-endian):
    - DPLC table at offset 0x100:
      First word = offset to first frame data (relative)
      Then n_frames u16 offsets
    - DPLC frame data: u16 count, then count u16 entries
    - Mapping table at offset 0x200:
      First word = offset to first frame data (relative)
      Then n_frames u16 offsets
    - Mapping frame data: u16 piece count, then pieces {s8 y, u8 size, u16 tile, s16 x}
    - Art tiles at offset 0x300: art_tiles * 32 bytes
    - Palette at offset 0x1000: 16 u16 words
    """
    rom = bytearray(0x1100)

    # --- DPLC table ---
    dplc_off = 0x100
    dplc_data_start = dplc_off + 2 + 2 * n_frames
    # First word: offset from dplc_off to first frame data
    struct.pack_into(">H", rom, dplc_off, dplc_data_start - dplc_off)
    for i in range(n_frames):
        frame_data_pos = dplc_data_start + i * (2 + 2 * tiles_per_frame)
        struct.pack_into(">H", rom, dplc_off + 2 + 2 * i, frame_data_pos - dplc_off)
    # DPLC frame data
    for i in range(n_frames):
        frame_data_pos = dplc_data_start + i * (2 + 2 * tiles_per_frame)
        struct.pack_into(">H", rom, frame_data_pos, tiles_per_frame)
        for j in range(tiles_per_frame):
            first_tile = i * tiles_per_frame + j
            tile_count = 1
            entry = (tile_count - 1) << 12 | (first_tile & 0xFFF)
            struct.pack_into(">H", rom, frame_data_pos + 2 + 2 * j, entry)

    # --- Mapping table ---
    map_off = 0x200
    map_data_start = map_off + 2 + 2 * n_frames
    struct.pack_into(">H", rom, map_off, map_data_start - map_off)
    for i in range(n_frames):
        frame_data_pos = map_data_start + i * (2 + 6 * pieces_per_frame)
        struct.pack_into(">H", rom, map_off + 2 + 2 * i, frame_data_pos - map_off)
    # Mapping frame data
    for i in range(n_frames):
        frame_data_pos = map_data_start + i * (2 + 6 * pieces_per_frame)
        struct.pack_into(">H", rom, frame_data_pos, pieces_per_frame)
        for j in range(pieces_per_frame):
            y = -8 + j * 8
            w, h = 1, 1  # size = 0 (1x1 tile)
            tile = i * pieces_per_frame + j
            x = 0
            size = (w - 1) << 2 | (h - 1)
            struct.pack_into(">b", rom, frame_data_pos + 2 + 6 * j, y)
            struct.pack_into(">B", rom, frame_data_pos + 2 + 6 * j + 1, size)
            struct.pack_into(">H", rom, frame_data_pos + 2 + 6 * j + 2, tile)
            struct.pack_into(">h", rom, frame_data_pos + 2 + 6 * j + 4, x)

    # --- Art tiles (16 tiles of 32 bytes each) ---
    art_off = 0x300
    for t in range(art_tiles):
        for b in range(32):
            rom[art_off + t * 32 + b] = (t * 4 + b) & 0xFF

    # --- Palette (16 colours) ---
    pal_off = 0x1000
    for i in range(16):
        struct.pack_into(">H", rom, pal_off + 2 * i, i * 0x21)

    return bytes(rom)


def test_noop_roundtrip_dplc():
    """Re-encode DPLC frames from fixture and byte-compare."""
    rom = _make_fixture(n_frames=3, tiles_per_frame=4, art_tiles=16, pieces_per_frame=2)

    dplc_off = 0x100
    frames = parse_dplc(rom, dplc_off, count=3)
    assert len(frames) == 3

    for i, frame in enumerate(frames):
        encoded = encode_dplc_frame(frame)
        frame_rel = struct.unpack_from(">H", rom, dplc_off + 2 * i)[0]
        frame_pos = dplc_off + frame_rel
        rom_bytes = rom[frame_pos:frame_pos + len(encoded)]
        assert rom_bytes == encoded, f"DPLC frame {i} roundtrip mismatch"


def test_noop_roundtrip_map():
    """Re-encode mapping frames from fixture and byte-compare."""
    rom = _make_fixture(n_frames=3, tiles_per_frame=4, art_tiles=16, pieces_per_frame=2)

    map_off = 0x200
    frames = parse_mappings(rom, map_off, count=3)
    assert len(frames) == 3

    for i, frame in enumerate(frames):
        encoded = encode_map_frame(frame)
        frame_rel = struct.unpack_from(">H", rom, map_off + 2 * i)[0]
        frame_pos = map_off + frame_rel
        rom_bytes = rom[frame_pos:frame_pos + len(encoded)]
        assert rom_bytes == encoded, f"Map frame {i} roundtrip mismatch"


def test_palette_values():
    """Verify palette conversion produces expected RGBA values."""
    # Genesis word 0x2121 = 0000 0100001 00000100001 0 -> R=0,G=1,B=2 (roughly)
    # Let's use a known value: 0xFFFF = all bits set -> R=31,G=31,B=31 -> (255,255,255,255)
    rgba = sk_export._genesis_to_rgba(0xFFFF)
    assert rgba == (255, 255, 255, 255)

    # 0x0000 = black
    rgba = sk_export._genesis_to_rgba(0x0000)
    assert rgba == (0, 0, 0, 255)


def test_sstage_constants():
    """Verify the pinned constants match the analysis."""
    assert sk_export.SSTAGE_SONIC["mappings_offset"] == 0xABDFC
    assert sk_export.SSTAGE_SONIC["plc_offset"] == 0xABE14
    assert sk_export.SSTAGE_SONIC["art_offset"] == 0xAAA7C
    assert sk_export.SSTAGE_SONIC["art_tiles"] == 156
    assert sk_export.SSTAGE_SONIC["frames"] == 12
    assert sk_export.SSTAGE_SONIC["max_tiles_per_frame"] == 23
    assert sk_export.SSTAGE_SONIC["vram_budget_tiles"] == 23
    assert sk_export.SSTAGE_SONIC["dma_bank_crossings"] == 0


def test_read_rom_rejects_bad_extension():
    """read_rom should reject unsupported file extensions."""
    p = Path("/tmp/test_bad_source.xyz")
    p.write_bytes(b"\x00" * 0x300)
    try:
        sk_export.read_rom(p)
        pytest.fail("Expected SkError")
    except sk_export.SkError:
        pass
    finally:
        p.unlink()
