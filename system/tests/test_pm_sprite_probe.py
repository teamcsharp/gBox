import os
import struct
import zlib
from pathlib import Path

import pytest

from gbox import pm_sprite_probe as pr

ROM = Path(os.environ.get("PM_ROM", Path.home() / "gBox_alt/gbox-cache/b74d223b195befba/rom.z64"))


def _decode(png: bytes):
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    p, idat, ihdr = 8, b"", None
    while p < len(png):
        n, t = struct.unpack_from(">I4s", png, p)
        d = png[p + 8:p + 8 + n]
        assert struct.unpack_from(">I", png, p + 8 + n)[0] == zlib.crc32(t + d)
        if t == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", d)
        if t == b"IDAT":
            idat += d
        p += 12 + n
    return ihdr, zlib.decompress(idat)


def test_ci4_png_synthetic():
    pal = struct.pack(">16H", *([0] * 1 + [0xF801] + [0x07C1] * 14))
    (w, h, *_), raw = _decode(pr.ci4_to_png(bytes([0x01, 0x20]), 4, 1, pal))
    assert (w, h) == (4, 1)
    px = raw[1:]
    assert px[0:4] == b"\0\0\0\0" and px[4:8] == bytes((255, 0, 0, 255)) and px[8:12] == bytes((0, 255, 0, 255))
    assert px[12:16] == b"\0\0\0\0"


def test_rgba5551():
    assert pr.rgba5551(0xFFFF) == (255, 255, 255, 255) and pr.rgba5551(0xFFFE)[3] == 0


@pytest.mark.skipif(not ROM.exists(), reason="owned Paper Mario z64 not available")
def test_real_rom_probe():
    rom = ROM.read_bytes()
    assert rom[0x20:0x2B] == b"PAPER MARIO"
    for i in range(13):  # cache_pos rule holds for every player sprite
        s = pr.player_sprite(rom, i)
        assert all(r["size"] <= 0xFFF0 and len(r["pixels"]) == r["w"] * r["h"] // 2 for r in s["rasters"])
    m = pr.player_sprite(rom, 0)
    assert len(m["rasters"]) == 87
    (w, h, *_), raw = _decode(pr.raster_png(m, 0))
    assert (w, h) == (m["rasters"][0]["w"], m["rasters"][0]["h"]) and len(raw) == h * (1 + 4 * w)
    g = pr.npc_sprite(rom, 0)
    assert len(g["rasters"]) > 0
    _decode(pr.raster_png(g, 0))
    out = Path(os.environ.get("PM_PROBE_OUT", "")) if os.environ.get("PM_PROBE_OUT") else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
        (out / "Mario1_raster0.png").write_bytes(pr.raster_png(m, 0))
        (out / "WorldGoombario_raster0.png").write_bytes(pr.raster_png(g, 0))
