"""Reader-stage tests for gbox.pm_sprite_export: PNG codec round-trip + Mario1 export (#1673)."""
from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from gbox import pm_sprite_export as pe
from gbox import pm_sprite_probe as pr

ROM = Path(__import__("os").environ.get(
    "PM_ROM", Path.home() / "gbox-cache/b74d223b195befba/rom.z64"))
pytestmark = pytest.mark.skipif(not ROM.exists(), reason="owned Paper Mario (USA) ROM not cached")


def test_synthetic_roundtrip():
    pal = struct.pack(">16H", 0, *[0x8001 | (i * 3674) for i in range(1, 16)])
    pix = bytes(((i * 7) & 0xF0) | ((i * 13) & 0xF) for i in range(128))
    png = pr.ci4_to_png(pix, 16, 16, pal)
    assert pe.png_to_ci4(png, pal) == pix
    w, h, rgba = pe.decode_png_rgba(png)
    assert (w, h, len(rgba)) == (16, 16, 16 * 16 * 4)


def test_mario1_export_and_roundtrip(tmp_path):
    rom = ROM.read_bytes()
    idx = pe.export_sprite(rom, 0, tmp_path / "Mario1", name="Mario1")
    files = sorted(p.name for p in (tmp_path / "Mario1").iterdir())
    assert "index.json" in files
    assert idx["raster_count"] == len(idx["rasters"]) > 0
    assert idx["roundtrip_verified"] is True
    # every PNG listed exists and re-encodes byte-identical to ROM pixels
    spr = pr.player_sprite(rom, 0)
    for rec in idx["rasters"]:
        p = tmp_path / "Mario1" / rec["file"]
        assert p.exists() and p.stat().st_size > 100
        r = spr["rasters"][rec["index"]]
        enc = pe.png_to_ci4(p.read_bytes(), spr["palettes"][r["palette"]])
        # byte-identical, or canonicalized duplicate-palette indices that decode to the same image
        assert enc == r["pixels"] or pr.ci4_to_png(enc, r["w"], r["h"], spr["palettes"][r["palette"]]) == p.read_bytes()
    assert idx["animation_component_counts"], "Mario1 should expose animation components"
    meta = json.loads((tmp_path / "Mario1" / "index.json").read_text())
    assert meta["sprite"] == "Mario1" and meta["npc"] is False
    # palette swatches written for every palette
    assert len([f for f in files if f.startswith("palette_")]) == len(spr["palettes"])


def test_npc_export_worldgoombario(tmp_path):
    rom = ROM.read_bytes()
    idx = pe.export_sprite(rom, 0, tmp_path / "Goombario", npc=True, name="WorldGoombario")
    assert idx["npc"] is True and idx["raster_count"] > 0
    assert idx["roundtrip_verified"] is True
