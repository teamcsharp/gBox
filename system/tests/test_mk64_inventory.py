"""gbox.mk64_inventory on a synthetic cart (no game needed); the owned-ROM check skips when absent."""
import os
import struct
import zipfile
from pathlib import Path

import pytest

from gbox import mk64_inventory as inv
from gbox.sm64_writer import crc6102

OWNED = Path(os.environ.get("GBOX_MK64_SOURCE", Path.home() / "gBox_alt/gbox-cache" / "7f5c674909d63b5f" / "source.zip"))


def _rom() -> bytes:
    rom = bytearray(0x101000 + 0x1000)
    rom[0:4] = b"\x80\x37\x12\x40"
    struct.pack_into(">I", rom, 0x08, 0x80000400)
    struct.pack_into(">I", rom, 0x0C, 0x1446)
    rom[0x20:0x34] = b"MARIOKART64".ljust(20)
    rom[0x3B:0x40] = b"NKTE\x00"
    for i in range(0x1000, 0x101000, 4):
        struct.pack_into(">I", rom, i, (i * 2654435761) & 0xFFFFFFFF)
    rom[0x2000:0x2010] = b"MIO0" + struct.pack(">III", 0x100, 0x10, 0x20)
    rom[0x3001:0x3005] = b"MIO0"                           # unaligned: ignored
    struct.pack_into(">II", rom, 0x10, *crc6102(rom))
    return bytes(rom)


def test_identify_reads_crc_at_0x10_and_release_at_0x0c():
    rom = _rom()
    ident = inv.identify(rom)
    c1, c2 = crc6102(rom)
    assert ident["header_crc"] == [hex(c1), hex(c2)]
    assert ident["libultra_release"] == "0x1446"
    assert ident["cic"] == "6102"
    assert ident["title"] == "MARIOKART64" and ident["cart_id"] == "KT" and ident["country"] == "US"
    bad = bytearray(rom)
    bad[0x14] ^= 1
    assert inv.identify(bytes(bad))["cic"] == "unknown"


def test_identify_rejects_short_data():
    with pytest.raises(ValueError):
        inv.identify(b"\x80\x37\x12\x40")


def test_mio0_scan_counts_aligned_valid_headers():
    m = inv.mio0_streams(_rom())
    assert m["count"] == 1 and m["valid"] == 1 and m["max_uncompressed"] == 0x100


def test_inventory_from_v64_zip(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOX_N64_ROM_CACHE", "")
    rom = _rom()
    v64 = bytearray(len(rom))
    v64[0::2], v64[1::2] = rom[1::2], rom[0::2]
    src = tmp_path / "mk64.zip"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("Mario Kart 64 (USA).n64", bytes(v64))
    m = inv.inventory(src)
    assert m["rom"]["sha1"] == __import__("hashlib").sha1(rom).hexdigest()
    assert m["rom"]["known"] is None and m["characters"]["roster"] == inv.DRIVERS


@pytest.mark.skipif(not OWNED.exists(), reason="owned Mario Kart 64 (USA) zip not cached")
def test_owned_build():
    m = inv.inventory(OWNED)
    assert m["rom"]["known"]["name"] == "Mario Kart 64 (USA)"
    assert m["rom"]["cic"] == "6102" and m["rom"]["libultra_release"] == "0x1446"
