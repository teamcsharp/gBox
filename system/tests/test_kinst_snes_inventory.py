"""gbox.kinst_snes_inventory: header parsing and owned-build verification.

The owned build ships as a bare headerless .sfc inside the task workspace (a
.zip is also accepted).  Resolve whichever exists so the suite runs against the
real owned bytes instead of skipping.
"""
import os
from pathlib import Path

import pytest

from gbox import kinst_snes_inventory as I

TASK_ID = "9ff3cb2c31d64dff"
REPO = Path(__file__).resolve().parent.parent
_ROM_STEM = "Killer Instinct (USA) (Rev 1)"

_CANDIDATES = [
    os.environ.get("GBOX_KINST_SNES_ZIP"),
    os.environ.get("GBOX_KINST_SNES_SFC"),
    str(REPO.parent / "rom" / f"{_ROM_STEM}.sfc"),
    str(REPO.parent / "rom" / f"{_ROM_STEM}.zip"),
    str(Path.home() / "gbox-hermes-tasks" / TASK_ID / "rom" / f"{_ROM_STEM}.sfc"),
    str(Path.home() / "gbox-hermes-tasks" / TASK_ID / "rom" / f"{_ROM_STEM}.zip"),
]


def _find_owned():
    for cand in _CANDIDATES:
        if not cand:
            continue
        p = Path(cand)
        if p.exists():
            return p
    return None


OWNED = _find_owned()


def _sfc_bytes() -> bytes:
    if OWNED is None:
        raise FileNotFoundError("owned KI SNES source not present")
    return I._read_sfc(OWNED)[0]


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
    # sha256 of the actual owned bytes, streamed from the real file.
    assert ident["sha256"] == "7a5261f1a5e84b67483c79fb002ce1539f2360f88333bda60f12e617d86e0def"


@pytest.mark.skipif(OWNED is None, reason="owned KI SNES source not cached")
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
