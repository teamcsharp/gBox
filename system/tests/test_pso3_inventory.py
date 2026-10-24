"""Tests for gbox.pso3_inventory (PSO Episode III, GPSE8P)."""
import struct
from pathlib import Path

import pytest

from gbox import pso3_inventory as inv

GCZ = Path("/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/Phantasy Star Online Episode III - C.A.R.D. Revolution (USA).gcz")


def test_njcm_header():
    assert inv.parse_njcm_header(b"NJCM" + struct.pack("<I", 0x52B0)) == {"tag": "NJCM", "body_size": 0x52B0, "end": 0x52B8}
    with pytest.raises(ValueError):
        inv.parse_njcm_header(b"NJTL\0\0\0\0")


def test_afs_toc():
    blob = b"AFS\0" + struct.pack("<I", 2) + struct.pack("<IIII", 0x800, 10, 0x1000, 20)
    assert inv.parse_afs_toc(blob) == [(0x800, 10), (0x1000, 20)]
    with pytest.raises(ValueError):
        inv.parse_afs_toc(b"XXXX")


def test_player_names():
    assert inv.player_name_parts("plAbdy00.nj") == ("A", "bdy", "00")
    assert inv.player_name_parts("plAtex.afs") is None


def test_owned_disc():
    if not GCZ.is_file():
        pytest.skip("owned source not reachable")
    r = inv.inventory(str(GCZ), source_sha256="0" * 64, image_sha256=False)
    assert r["build"] == "GPSE8P" and r["image_size"] == 1459978240
    assert len(r["player_models"]) == 198
    assert all(p["njcm"] and p["njcm"]["body_size"] + 8 <= p["size"] for p in r["player_models"])
    assert r["plAtex_afs"]["entries"] == 137 and r["plAtex_afs"]["in_range"]
    assert r["gvm_count"] == 440
