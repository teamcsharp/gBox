"""Tests for gbox.konami88_inventory ('88 Games, MAME set 88games)."""

import hashlib
import zipfile
import zlib

import pytest

from gbox import konami88_inventory as k88


def test_known_table_consistency():
    assert len(k88.KNOWN) == 36
    for name, e in k88.KNOWN.items():
        assert e["region"] in k88.REGION_SIZES
        assert e["size"] <= 0x10000
        if e["interleave"]:
            # interleaved members live in 4-byte lanes of a 64KB bank
            assert (e["offset"] & 0xFFFF) < 4
        else:
            assert e["offset"] % e["size"] == 0
        assert len(e["crc32"]) == 8 and len(e["sha1"]) == 40


def test_region_bytes_linear(tmp_path):
    rom_dir = tmp_path / "roms"
    rom_dir.mkdir()
    (rom_dir / "861.g3").write_bytes(bytes(range(256)))
    got = k88.region_bytes(rom_dir, "proms")
    assert got == bytes(range(256))
    assert len(got) == 0x100


def test_region_bytes_interleave_four_lanes(tmp_path):
    rom_dir = tmp_path / "roms"
    rom_dir.mkdir()
    # k051960: 16 members, 4 banks of 4 lanes (lane = offset & 3 in bank)
    lanes = [0xAA, 0x55, 0xCC, 0x33]
    for name, e in k88.KNOWN.items():
        if e["region"] != "k051960":
            continue
        (rom_dir / name).write_bytes(bytes([lanes[e["offset"] & 3]]) * e["size"])
    got = k88.region_bytes(rom_dir, "k051960")
    assert len(got) == 0x100000
    assert got[:8] == bytes(lanes) * 2
    assert got[0x40000:0x40008] == bytes(lanes) * 2  # second bank


def test_sprite_px_layout():
    # one 128-byte code: word y holds left 8 px (planes 0..3 = bytes 0..3),
    # word y+8 holds right 8 px. Build plane 0 pattern so pixel (x, 0)
    # equals x for x<8 and x for x>=8 via word 8.
    code = bytearray(128)
    for x in range(8):
        code[0] |= 1 << x          # plane 0, row 0, left half
    code[3] |= 0b11110000          # plane 3 bits 4..7 of left half
    code[32] |= 0b10101010         # plane 0, row 0, right half (word 8): odd x set
    for x in range(8):
        assert k88.sprite_px(code, 0, x, 0) & 1 == 1          # plane 0 all ones
        assert (k88.sprite_px(code, 0, x, 0) >> 3) & 1 == ((x >> 2) & 1)
    for x in range(8, 16):
        assert k88.sprite_px(code, 0, x, 0) & 1 == (x & 1)    # bits 1,3,5,7 set
        assert k88.sprite_px(code, 0, x, 0) >> 3 == 0
    # row 1 lives at bytes 4..7
    assert k88.sprite_px(code, 0, 0, 1) == 0


def test_sprite_px_row_geometry():
    # pixel (0,1) is bit 0 of byte 4 (word 1 = row 1 left half)
    code = bytearray(128)
    code[4] = 1
    assert k88.sprite_px(code, 0, 0, 1) == 1
    # pixel (15, 8) is bit 7 of byte 64+3 (word 24 = row 8 right half)
    code[64 + 3] = 0x80
    assert k88.sprite_px(code, 0, 15, 8) == 8


def test_tile_px_layout():
    # plane b is byte 3-b of each 4-byte row
    tile = bytearray(32)
    tile[3] = 0x01  # plane 0, pixel x=0 of row 0
    tile[7] = 0x80  # plane 0, pixel x=7 of row 1
    tile[2] = 0x01  # plane 1
    assert k88.tile_px(tile, 0, 0, 0) == 1 + 2
    assert k88.tile_px(tile, 0, 7, 1) == 1


def test_zoom_px_layout():
    code = bytearray(128)
    code[0] = 0xF0  # row 0: x=0 -> low nibble 0x0, x=1 -> high nibble 0xF
    code[8] = 0x0F  # row 1: x=0 -> low nibble 0xF, x=1 -> high nibble 0x0
    assert k88.zoom_px(code, 0, 0, 0) == 0x0
    assert k88.zoom_px(code, 0, 1, 0) == 0xF
    assert k88.zoom_px(code, 0, 0, 1) == 0xF
    assert k88.zoom_px(code, 0, 1, 1) == 0x0
    assert k88.zoom_px(code, 0, 15, 15) == 0


def test_decode_code_sizes():
    sprite = bytearray(128 * 4)
    assert len(k88.decode_code(bytes(sprite), "sprite", 1)) == 16
    tiles = bytearray(32 * 4)
    assert len(k88.decode_code(bytes(tiles), "tile", 1)[0]) == 8
    zm = bytearray(128 * 4)
    assert len(k88.decode_code(bytes(zm), "zoom", 1)) == 16


def test_verify_zip_mismatch(tmp_path):
    z = tmp_path / "owned.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("861.g3", b"\x00" * 0x100)  # wrong content
    res = k88.verify_zip(z)
    assert res["summary"]["complete"] is False
    assert "861.g3" in res["summary"]["mismatched"]
    assert len(res["summary"]["extra_members"]) == 0
    # every other member is missing
    assert len(res) == 37  # 36 roms + summary


def test_verify_zip_complete(tmp_path):
    z = tmp_path / "owned.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for name, e in k88.KNOWN.items():
            zf.writestr(name, bytes(e["size"]))
    res = k88.verify_zip(z)
    assert res["summary"]["complete"] is False  # content is fake, sizes only


def test_verify_zip_extra_member(tmp_path):
    z = tmp_path / "owned.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("note.txt", b"hi")
    res = k88.verify_zip(z)
    assert res["summary"]["extra_members"] == ["note.txt"]
    assert len(res["summary"]["mismatched"]) == 36


def test_inventory_rejects_incomplete_zip(tmp_path):
    z = tmp_path / "owned.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("861.g3", b"\x00" * 0x100)
    with pytest.raises(ValueError):
        k88.inventory(z, tmp_path / "out")
