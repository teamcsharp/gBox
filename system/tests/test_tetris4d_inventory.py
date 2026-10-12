import os
from pathlib import Path

import pytest

from gbox.tetris4d_inventory import ensure_inventory, inventory, sha256_file, split_cue_bin_to_gdi, SECTOR_SIZE

CHD = Path("/mnt/gbox/hyperspin/Arcade/collections/Sega Dreamcast/roms/Tetris 4D (Japan).chd")
CACHE = Path.home() / "gbox-cache" / "dc" / "864538c6473a986e"


@pytest.mark.skipif(not CHD.exists(), reason="owned CHD not mounted")
def test_chd_sha256_matches_known():
    assert sha256_file(CHD) == "531a6ce7fb56c8bdb367d9c98eb724b13404d548f0e817e9958a6f55fb456058"


@pytest.mark.skipif(not (CACHE / "disc.gdi").exists(), reason="cached split GDI not present")
def test_inventory_matches_known_build():
    manifest = inventory(CACHE / "disc.gdi", sha256_file(CHD) if CHD.exists() else "unknown")
    assert manifest["1ST_READ.BIN"]["size"] == 1045056
    assert manifest["1ST_READ.BIN"]["sha256"] == "5579d8c6f9e21e570eecb880d4ac52d688c3ba17428ce2cd7be81c9b66a86055"
    assert len(manifest["files"]) == 419
    assert manifest["asset_counts"].get("PVR", 0) == 369
    assert manifest["asset_counts"].get("NJ", 0) == 24
    assert manifest["asset_counts"].get("NJM", 0) == 18


@pytest.mark.skipif(not CHD.exists() or not (CACHE / "disc.gdi").exists(), reason="needs cached CHD/GDI")
def test_ensure_inventory_idempotent():
    out = CACHE / "tetris4d_test_manifest.json"
    m1 = ensure_inventory(CHD, CACHE, out)
    m2 = ensure_inventory(CHD, CACHE, out)
    assert m1["chd_sha256"] == m2["chd_sha256"]
    assert m1["1ST_READ.BIN"]["sha256"] == m2["1ST_READ.BIN"]["sha256"]


@pytest.mark.skipif(not (CACHE / "disc.cue").exists() or not (CACHE / "disc.bin").exists(),
                    reason="needs extracted cue/bin")
def test_split_cue_bin_creates_gdi(tmp_path):
    gdi = split_cue_bin_to_gdi(CACHE / "disc.bin", CACHE / "disc.cue", tmp_path, name="split")
    assert gdi.exists()
    # Track 1 + 3 + 6 are present as data tracks and point back into the split bin files
    lines = gdi.read_text().splitlines()
    assert lines[0].strip() == "3"
    assert len([ln for ln in lines[1:] if " 4 " in ln]) == 3


def test_split_cue_bin_synthetic(tmp_path):
    """A lightweight correctness check on a tiny fake cue/bin."""
    from gbox.tetris4d_inventory import _msf_to_lba, _cue_track_boundaries, split_cue_bin_to_gdi
    sector = bytes(SECTOR_SIZE)
    # Two tracks: track1 data 2 sectors, track2 audio 3 sectors
    bin_path = tmp_path / "tiny.bin"
    bin_path.write_bytes(sector * 5)
    cue_path = tmp_path / "tiny.cue"
    cue_path.write_text(
        'FILE "tiny.bin" BINARY\n'
        "  TRACK 01 MODE1/2352\n"
        "    INDEX 01 00:00:00\n"
        "  TRACK 02 AUDIO\n"
        "    INDEX 01 00:00:02\n"
    )
    gdi = split_cue_bin_to_gdi(bin_path, cue_path, tmp_path / "out", name="tiny")
    assert gdi.exists()
    boundaries = _cue_track_boundaries(cue_path.read_text(), 5 * SECTOR_SIZE)
    assert boundaries == [(0, 2), (2, 5)]
    track1 = tmp_path / "out" / "tiny.track01.bin"
    assert track1.exists() and track1.stat().st_size == 2 * SECTOR_SIZE
