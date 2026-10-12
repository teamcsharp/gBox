import hashlib
import struct
import zipfile
from pathlib import Path

import pytest

from gbox import sk_inventory as sk

REAL = Path.home() / "gbox-cache/286b3fae79e33f17/source.zip"
REAL_ROM_SHA256 = "840acb121e10f12bf12a4e09780d004f00dc354c98f7cadd90fcbb5c29ee560a"
REAL_ZIP_SHA256 = "4526806489260bb6dbc5d2342d85bfdf6a476034e58d7ac3f39988d37b46ffe1"


def _synthetic() -> bytes:
    d = bytearray(0x280000)
    for base, serial, dom in ((0x0, b"GM MK-1563 -00", b"SONIC & KNUCKLES"), (0x200000, b"GM 00001009-00", b"SONIC THE HEDGEHOG 1")):
        h = d[base + 0x100 : base + 0x200]
        h[0:16] = b"SEGA GENESIS    "
        h[32 : 32 + len(dom)] = dom
        h[128 : 128 + len(serial)] = serial
        h[164:168] = struct.pack(">I", 0x27FFFF)
        d[base + 0x100 : base + 0x200] = h
    # one fake S3K-style DPLC loader: art table at 0x5000
    d[0x1000 : 0x1000 + 28] = (
        b"\x45\xf9" + struct.pack(">I", 0x5000) + b"\xd0\x40\xd4\xf2\x00\x00\x7a\x00\x1a\x1a"
        b"\x53\x45\x6b\x36\x38\x3c"
        + struct.pack(">H", 0xFB00)
        + b"\x33\x7c"
        + struct.pack(">H", 0x00C0)
    )
    return bytes(d)


def test_synthetic_zip_inventory(tmp_path):
    z = tmp_path / "s.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("combo.md", _synthetic())
    m = sk.inventory(z, source_sha256="abc")
    assert m["rom_size"] == 0x280000
    assert m["lock_on"]["attached"] == "sonic1"
    assert m["lock_on"]["serial"] == "GM 00001009-00"
    assert [s["name"] for s in m["segments"]] == ["sonic_and_knuckles", "sonic1"]
    assert m["segments"][0]["header"]["serial"] == "GM MK-1563 -00"
    assert m["playable"]["mode"] == "blue_sphere"
    probe = m["dplc_loader_probe"]
    assert probe and probe[0]["art_table"] == 0x5000
    assert probe[0]["vram_dest"] == 0xFB00


def test_lock_on_none_for_standalone():
    d = bytearray(0x200000)
    h = d[0x100:0x200]
    h[0:16] = b"SEGA GENESIS    "
    d[0x200180:0x20018E] = b"GM 00001009-00"  # beyond end of standalone dump
    d = bytes(d[:0x200000])
    assert sk.lock_on(d)["attached"] is None


def test_genesis_checksum():
    d = bytearray(0x400)
    d[0x200:0x204] = b"\x00\x01\x00\x02"
    assert sk.genesis_checksum(bytes(d), 0x200, 0x400) == 0x0003


@pytest.mark.skipif(not REAL.exists(), reason="owned build cache missing")
def test_real_build():
    m = sk.inventory(REAL, source_sha256=REAL_ZIP_SHA256)
    assert m["source_sha256"] == REAL_ZIP_SHA256
    assert m["rom_sha256"] == REAL_ROM_SHA256
    assert m["lock_on"]["attached"] == "sonic1", m["lock_on"]
    assert m["segments"][1]["header"]["serial"] == "GM 00001009-00"
    # segment hashes are stable identifiers reused across stages
    rom, _ = sk.read_rom(REAL)
    assert m["segments"][0]["sha256"] == hashlib.sha256(rom[:0x200000]).hexdigest()
    assert m["segments"][1]["sha256"] == hashlib.sha256(rom[0x200000:]).hexdigest()
