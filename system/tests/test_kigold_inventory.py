"""Tests for gbox.kigold_inventory — the Killer Instinct Gold (USA) N64 inventory."""

import hashlib
import json
import os
import struct
import zipfile
from pathlib import Path

import pytest

from gbox import kigold_inventory as ki
from gbox import n64_rom

REAL_ROM = Path.home() / "gBox_alt/gbox-cache" / "407771fca8e3cd17" / "rom.z64"


def _make_z64(size: int = 12 * 1024 * 1024) -> bytes:
    """Build a synthetic z64 ROM with a plausible header and 0xFF tail."""
    rom = bytearray(b"\x00" * size)
    rom[0:4] = b"\x80\x37\x12\x40"
    struct.pack_into(">I", rom, 8, 0x80000400)
    struct.pack_into(">I", rom, 0x10, 0xF908CA4C)  # crc1
    struct.pack_into(">I", rom, 0x14, 0x36464327)  # crc2
    rom[0x20:0x34] = b"KILLER INSTINCT GOLD"  # exactly 20 bytes
    rom[0x3C:0x40] = b"KI" + b"\x45" + b"\x02"
    struct.pack_into(">I", rom, 0x4C, 0x3C08A470)
    # 0xA0..0xFF cycle: deterministic, high-entropy enough, and it can never
    # contain the "1172" or 1F 8B gzip-marker bytes.
    rom[0x1000:0x49000] = bytes(0xA0 + (i % 96) for i in range(0x49000 - 0x1000))
    rom[0xBFB000:size] = b"\xFF" * (size - 0xBFB000)
    return bytes(rom)


def _to_v64(z64: bytes) -> bytes:
    out = bytearray(len(z64))
    out[0::2], out[1::2] = z64[1::2], z64[0::2]
    return bytes(out)


def _write_zip(tmp_path: Path, data: bytes, member: str = "Killer Instinct Gold (USA) (Rev B).n64") -> Path:
    path = tmp_path / "ki_gold.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, data)
    return path


def test_read_zip_v64_member_normalizes(tmp_path):
    z64 = _make_z64()
    src = _write_zip(tmp_path, _to_v64(z64))
    assert n64_rom.read(src) == z64


def test_parse_header_and_cic_on_synthetic():
    rom = _make_z64()
    header = ki.parse_header(rom)
    assert header["entry"] == "0x80000400"
    assert header["crc1"] == "0xf908ca4c"
    assert header["crc2"] == "0x36464327"
    assert header["cart_id"] == "KI"
    assert header["country"] == "E"
    assert header["revision"] == 2
    assert header["cic"] == "unknown"  # synthetic boot block matches no known CIC


def test_layout_map_synthetic():
    layout = ki.layout_map(_make_z64())
    assert layout["ff_tail"]["pure_ff"] is True
    assert layout["ff_tail"]["offset"] == "0xbfb000"
    assert layout["no_rare_gzip_markers"] is True
    assert any(p["offset"] == 0xBFB000 and p["byte"] == 0xFF for p in layout["padding_blocks"])


def test_inventory_manifest_on_zip(tmp_path):
    src = _write_zip(tmp_path, _to_v64(_make_z64()))
    manifest = ki.inventory(src)
    assert manifest["game_id"] == ki.GAME_ID
    assert manifest["rom"]["header"]["cart_id"] == "KI"
    assert manifest["rom"]["matches_no_intro"] is False  # synthetic body
    assert manifest["rom"]["sha256"] == hashlib.sha256(_make_z64()).hexdigest()
    assert manifest["layout"]["ff_tail"]["pure_ff"] is True
    json.dumps(manifest)  # serializable


@pytest.mark.skipif(not REAL_ROM.exists(), reason="owned ROM not staged in ~/gBox_alt/gbox-cache")
def test_owned_build_identity():
    rom = REAL_ROM.read_bytes()
    ident = ki.identity(rom)
    assert ident["matches_no_intro"] is True
    assert ident["sha1"] == ki.KNOWN["sha1"]
    assert ident["crc32"] == ki.KNOWN["crc32"]
    assert ident["md5"] == ki.KNOWN["md5"]


@pytest.mark.skipif(not REAL_ROM.exists(), reason="owned ROM not staged in ~/gBox_alt/gbox-cache")
def test_owned_build_header_and_layout():
    rom = REAL_ROM.read_bytes()
    header = ki.parse_header(rom)
    assert header["cic"] == "CIC-NUS-6102/7102"
    assert header["cart_id"] == "KI" and header["country"] == "E" and header["revision"] == 2
    assert header["crc1"] == "0xf908ca4c" and header["crc2"] == "0x36464327"
    layout = ki.layout_map(rom)
    assert layout["ff_tail"]["pure_ff"] is True
    assert layout["no_rare_gzip_markers"] is True
    assert layout["rdp_op_constant_counts_in_code"]["G_LOADTLUT"] > 100
    assert os.path.getsize(REAL_ROM) == ki.KNOWN["size"]
