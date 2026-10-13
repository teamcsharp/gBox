"""gbox.kinst_snes_inventory: header parsing and owned-build verification."""
import os
from pathlib import Path

import pytest

from gbox import kinst_snes_inventory as I

OWNED = Path(
    os.environ.get(
        "GBOX_KINST_SNES_ZIP",
        Path.home()
        / "gbox-hermes-tasks/9ff3cb2c31d64dff/rom/Killer Instinct (USA) (Rev 1).zip",
    )
)


owned = pytest.mark.skipif(not OWNED.exists(), reason="owned KI SNES source not cached")


def _sfc_bytes() -> bytes:
    # the .sfc inside the owned zip (the same read inventory() does); no extracted copy needed
    return I._read_sfc(OWNED)[0]


def test_parse_header_on_synthetic_hirom():
    """Header offsets checked on any machine: a blank 64 KiB bank with a HiROM header at 0xFFB0."""
    import struct

    rom = bytearray(0x10000)
    base = 0xFFB0
    rom[base + 0x10 : base + 0x25] = b"KILLER INSTINCT".ljust(21, b" ")
    rom[base + 0x25 : base + 0x29] = bytes([0x31, 0x00, 0x0C, 0x00])
    struct.pack_into(">HH", rom, base + 0x2C, 0x1234 ^ 0xFFFF, 0x1234)
    struct.pack_into("<H", rom, base + 0x3C, 0x5551)
    h = I.parse_header(bytes(rom))
    assert h["title"] == "KILLER INSTINCT"
    assert (h["map_mode"], h["cartridge_type"], h["rom_size_code"], h["ram_size_code"]) == ("0x31", "0x00", "0x0c", "0x00")
    assert h["checksum_ok"] and h["checksum"] == "0x1234"
    assert h["native_reset_vector"] == "0x5551"
    rom[base + 0x2C] ^= 1
    assert not I.parse_header(bytes(rom))["checksum_ok"]
    with pytest.raises(I.RomError):
        I.parse_header(b"\x00" * 0x100)


@owned
def test_parse_header_on_known_rom():
    rom = _sfc_bytes()
    h = I.parse_header(rom)
    assert h["title"] == "KILLER INSTINCT"
    assert h["map_mode"] == "0x31"
    assert h["cartridge_type"] == "0x00"
    assert h["rom_size_code"] == "0x0c"  # 2^12 = 4096 KiB
    assert h["ram_size_code"] == "0x00"
    assert h["checksum_ok"]
    assert h["native_reset_vector"] == "0x5551"


@owned
def test_identity_matches_no_intro():
    rom = _sfc_bytes()
    ident = I.identity(rom)
    assert ident["size"] == 4 * 1024 * 1024
    assert ident["sha1"] == I.KNOWN["sha1"]
    assert ident["md5"] == I.KNOWN["md5"]
    assert ident["crc32"] == I.KNOWN["crc32"]
    assert ident["known"]


@owned
def test_inventory_from_owned_zip():
    m = I.inventory(OWNED)
    assert m["game_id"] == I.GAME_ID
    assert m["rom"]["known"]
    assert m["header"]["map_mode"] == "0x31"
    assert m["characters"]["playable"] == I.ROSTER[:10]
    assert m["characters"]["boss"] == "Eyedol"
    regions = m["artwork"]["candidate_regions"]
    kinds = {r["kind"] for r in regions}
    assert "high_entropy" in kinds
    summary = m["artwork"]["region_summary"]
    assert summary["by_kind"]["high_entropy"] >= 1


def test_identity_rejects_blank_rom():
    bad = b"\x00" * (4 * 1024 * 1024)
    assert not I.identity(bad)["known"]
