"""Pinned extraction tests for Clay Fighter: Sculptor's Cut (USA, N64).

Requires the cached normalized ROM (~/gBox_alt/gbox-cache/f87ec3e2f6b266a1/rom.z64);
set GBOX_CLAYFIGHTER_ROM to override. Skipped when the cache is absent.
"""
import os
from pathlib import Path

import pytest

from gbox.clay_fighter import (
    CHAR_NAMES,
    PIPELINE_STRINGS,
    STAGE_NAMES,
    characters,
    manifest,
    palette_clusters,
    pipeline_strings,
    read_rom,
    reserialize,
    stage_names,
    verify_build,
)


def _rom_path() -> Path:
    override = os.environ.get("GBOX_CLAYFIGHTER_ROM")
    if override:
        return Path(override)
    return Path.home() / "gBox_alt/gbox-cache/f87ec3e2f6b266a1/rom.z64"


@pytest.fixture(scope="module")
def rom() -> bytes:
    path = _rom_path()
    if not path.exists():
        pytest.skip("clay fighter ROM cache not present")
    return read_rom(path)


def test_build_identity(rom):
    b = verify_build(rom)
    assert b["sha1"] == "28697FBA130DED056BF7C497DEAA3E154CCE8022"
    assert b["md5"] == "30E7E083B978408D5B7760D0CE4DC61D"
    assert b["game_code"] == "NC2E"
    assert b["entry"] == 0x80000400
    assert b["title"] == "Clayfighter SC"
    # Stored header CRCs are pinned as provenance, not as a checksum check:
    # they do not reproduce with the standard uCON64 N64 CRC algorithm.
    assert b["stored_crc1"] == "FA5A3DFF"
    assert b["stored_crc2"] == "B4C9CDB9"


def test_build_rejects_foreign_rom(rom):
    tampered = bytearray(rom)
    tampered[0x40] ^= 0xFF
    with pytest.raises(ValueError):
        verify_build(bytes(tampered))


def test_character_table(rom):
    chars = characters(rom)
    assert [c.name for c in chars] == CHAR_NAMES
    assert len(chars) == 17
    assert chars[0].rom_offset == 0xC5ED0
    assert chars[-1].name == "CHAR_BMF" and chars[-1].rom_offset == 0xC5FA4
    by_name = {c.name: c for c in chars}
    assert by_name["CHAR_ZAPPA"].display_name == "Zappa Boys"
    assert by_name["CHAR_EWJ"].display_name == "E. W. Jim"
    assert by_name["CHAR_BMF"].display_name == "Frosty"


def test_pipeline_strings(rom):
    p = pipeline_strings(rom)
    assert p["charbio"]["rom_offset"] == 0xC512C
    assert p["charbio"]["text"].startswith("CHARBIO.C leaked")
    assert p["charfram"]["rom_offset"] == 0xC6400
    assert "Out of frame slots" in p["charfram"]["text"]
    assert p["bkgbank"]["rom_offset"] == 0xC6500
    assert "Unrecognized texture type" in p["bkgbank"]["text"]
    assert p["combat"]["rom_offset"] == 0xC7F50
    assert p["combat"]["text"].startswith("COMBAT.C")


def test_stage_names(rom):
    stages = stage_names(rom)
    texts = {s["text"].lstrip("\\/") for s in stages}
    for name in STAGE_NAMES:
        assert name in texts, f"stage {name!r} missing"
    # spot-check a few absolute offsets recorded during discovery
    offs = {s["text"]: s["rom_offset"] for s in stages}
    assert offs.get("hanger") == 0xC67C0
    assert offs.get("dungeon1") == 0xC69F8


def test_palette_clusters(rom):
    clusters = palette_clusters(rom)
    assert len(clusters) == 36
    spans = sorted(clusters, key=lambda c: -(c.end - c.start))
    assert spans[0].start == 0xFBB1D0  # largest candidate bank
    starts = {c.start for c in clusters}
    for expected in (0xB50780, 0xB79790, 0xCAC0C0, 0xFF9980):
        assert expected in starts, f"cluster 0x{expected:X} missing"
    # determinism
    assert palette_clusters(rom) == clusters


def test_round_trip_is_exact(rom):
    m = manifest(rom)
    assert m["game_id"] == "f87ec3e2f6b266a1"
    assert len(m["characters"]) == 17
    for label, region in m["regions"].items():
        assert 0 <= region["start"] < region["end"] <= len(rom)
    assert reserialize(rom, m) == rom
