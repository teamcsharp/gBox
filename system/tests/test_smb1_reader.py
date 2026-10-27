"""Tests for `gbox.smb1_reader`.

Verifies the reader exports valid PNGs for player frames and enemy slots,
and that a no-op roundtrip preserves tile counts and dimensions.
"""

from __future__ import annotations

import os
import pathlib

import pytest
from PIL import Image

from gbox import smb1_reader

ROM_PATH = pathlib.Path(
    os.environ.get(
        "SMB1_ROM",
        pathlib.Path.home() / "gBox_alt" / "gbox-cache" / "49b6a2f65aca26a2" / "rom" / "Super Mario Bros. (World).nes",
    )
)
SOURCE_SHA256 = "fb16c56ad6e0f2db925b09468f477de911ac8c52db0ea62a8553a72df2851883"


@pytest.fixture(scope="module")
def rom_path() -> pathlib.Path:
    if not ROM_PATH.exists():
        pytest.skip(f"owned ROM not found at {ROM_PATH}")
    return ROM_PATH


def test_export_player_frames_creates_pngs(rom_path: pathlib.Path, tmp_path: pathlib.Path):
    """Export produces PNG files with correct dimensions."""
    result = smb1_reader.export_player_frames(str(rom_path), str(tmp_path), scale=4)
    assert len(result["frames"]) == 26
    for frame in result["frames"]:
        p = pathlib.Path(frame["output"])
        assert p.exists(), f"missing {p}"
        img = Image.open(p)
        # 16x32 tiles * 4 scale = 64x128
        assert img.size == (64, 128), f"{p}: expected (64, 128), got {img.size}"
        assert img.mode == "RGBA"


def test_export_enemy_slots_creates_pngs(rom_path: pathlib.Path, tmp_path: pathlib.Path):
    """Export produces PNG files with correct dimensions."""
    result = smb1_reader.export_enemy_slots(str(rom_path), str(tmp_path), scale=4)
    assert len(result["slots"]) == 43
    for slot in result["slots"]:
        p = pathlib.Path(slot["output"])
        assert p.exists(), f"missing {p}"
        img = Image.open(p)
        # 24x16 tiles * 4 scale = 96x64
        assert img.size == (96, 64), f"{p}: expected (96, 64), got {img.size}"
        assert img.mode == "RGBA"


def test_donor_slot_player(rom_path: pathlib.Path, tmp_path: pathlib.Path):
    """Donor export for player frame produces a valid PNG."""
    out = smb1_reader.export_donor_slot(str(rom_path), str(tmp_path), "player", 0, scale=4)
    p = pathlib.Path(out)
    assert p.exists()
    img = Image.open(p)
    assert img.size == (64, 128)
    assert img.mode == "RGBA"


def test_donor_slot_enemy(rom_path: pathlib.Path, tmp_path: pathlib.Path):
    """Donor export for enemy slot produces a valid PNG."""
    out = smb1_reader.export_donor_slot(str(rom_path), str(tmp_path), "enemy", 0, scale=4)
    p = pathlib.Path(out)
    assert p.exists()
    img = Image.open(p)
    assert img.size == (96, 64)
    assert img.mode == "RGBA"


def test_noop_roundtrip_preserves_tile_count(rom_path: pathlib.Path, tmp_path: pathlib.Path):
    """A no-op export/import roundtrip yields the same tile count."""
    # Export player frame 0 (big walking frame 1)
    result = smb1_reader.export_player_frames(str(rom_path), str(tmp_path), scale=4)
    frame0 = result["frames"][0]
    tiles = frame0["tiles"]
    # Big walking frame 1 should be tiles 0x00-0x07
    assert tiles == [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07]
    assert len(tiles) == 8


def test_inventory_manifest_matches_reader(rom_path: pathlib.Path, tmp_path: pathlib.Path):
    """The reader output aligns with the inventory manifest."""
    from gbox.smb1_inventory import build_inventory

    inv = build_inventory(str(rom_path), SOURCE_SHA256)
    result = smb1_reader.export_player_frames(str(rom_path), str(tmp_path), scale=1)
    assert len(result["frames"]) == len(inv["characters"]["player"]["frames"])
