"""Focused tests for the Nemesis format probe."""
from pathlib import Path

import pytest

import nemesis_probe

ROM = Path(__file__).resolve().parent.parent / "work" / "rom" / "Sonic 1 and 2.bin"


def test_rom_exists():
    assert ROM.exists(), f"ROM not found at {ROM}"
    data = ROM.read_bytes()
    assert len(data) == 2 * 1024 * 1024
    assert data[0x100:0x110] == b"SEGA GENESIS    "


def test_decode_stream_at_d49a(tmp_path):
    rom = ROM.read_bytes()
    chunk = rom[0xD49A : 0xD49A + 0x2000]
    tiles = nemesis_probe.decode_with_clownnemesis(chunk)
    # Header word at 0xd49a is 0x8040: XOR mode, 64 tiles.
    assert len(tiles) == 64 * 32


def test_scan_finds_d49a():
    rom = ROM.read_bytes()
    results = nemesis_probe.scan_nemesis_streams(rom, max_results=10)
    offsets = {off for off, _size, _xor, _tiles in results}
    assert 0xD49A in offsets


def test_png_dump(tmp_path):
    rom = ROM.read_bytes()
    chunk = rom[0xD49A : 0xD49A + 0x2000]
    tiles = nemesis_probe.decode_with_clownnemesis(chunk)
    out_png = tmp_path / "d49a.png"
    img = nemesis_probe.tiles_to_image(tiles, cols=8)
    img.save(out_png)
    assert out_png.exists()
    assert out_png.stat().st_size > 0
