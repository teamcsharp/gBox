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


def _sfc_bytes() -> bytes:
    if OWNED.exists():
        return (OWNED.parent / "Killer Instinct (USA) (Rev 1).sfc").read_bytes()
    raise FileNotFoundError("owned KI SNES zip not present")


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


def test_identity_matches_no_intro():
    rom = _sfc_bytes()
    ident = I.identity(rom)
    assert ident["size"] == 4 * 1024 * 1024
    assert ident["sha1"] == I.KNOWN["sha1"]
    assert ident["md5"] == I.KNOWN["md5"]
    assert ident["crc32"] == I.KNOWN["crc32"]
    assert ident["known"]


@pytest.mark.skipif(not OWNED.exists(), reason="owned KI SNES source not cached")
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
