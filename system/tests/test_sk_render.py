"""Tests for gbox.sk_render (#1365): S&K player-sprite frame render + writer-room survey."""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from gbox import sk_render, sk_sprites

CACHE = Path.home() / "gBox_alt/gbox-cache" / "668e74c15d61a9a7"
SRC = CACHE / "source.zip"
SOURCE_SHA256 = "777881572e72f50c9868335bddafbdcc140c8772699b266cbcee7f4c3e68b26b"


def _art_tile(color: int) -> bytes:
    return bytes([(color << 4) | color]) * 32


def _dplc_frame(ents) -> bytes:
    return struct.pack(f">H{len(ents)}H", len(ents),
                       *[((k - 1) << 12) | t for t, k in ents])


def _map_frame(ps) -> bytes:
    out = struct.pack(">H", len(ps))
    for p in ps:
        size = ((p["w"] - 1) << 2) | (p["h"] - 1)
        tile = ((p.get("pri", 0) << 15) | (p.get("pal", 0) << 13) | (p.get("vf", 0) << 12)
                | (p.get("hf", 0) << 11) | p["tile"])
        out += struct.pack(">bBHh", p["y"], size, tile, p["x"])
    return bytes(out)


def test_solid_tiles_compose_row_major():
    pal = [sk_render.crgb(0)] * 16
    pal[1], pal[2] = (255, 255, 255), (255, 0, 0)
    d = bytearray(0x1000)
    art = 0x100
    d[art:art + 32] = _art_tile(1)
    d[art + 32:art + 64] = _art_tile(2)
    pieces = [{"y": 0, "w": 2, "h": 1, "tile": 0, "pal": 0, "pri": 0, "hf": 0, "vf": 0, "x": 0}]
    r = sk_render.render_frame(bytes(d), art, [(0, 2)], pieces, pal)

    def px(x, y):
        o = (y * 16 + x) * 4
        return tuple(r["rgba"][o:o + 3]), r["rgba"][o + 3]

    assert (r["w"], r["h"], r["tiles"]) == (16, 8, 2)
    assert px(0, 0) == ((255, 255, 255), 255) and px(7, 7) == ((255, 255, 255), 255)
    assert px(8, 0) == ((255, 0, 0), 255) and px(15, 7) == ((255, 0, 0), 255)


def test_flip_and_transparency():
    pal = [sk_render.crgb(0)] * 16
    pal[3] = (0, 0, 255)
    d = bytearray(0x1000)
    art = 0x100
    t = bytearray(32)
    t[0] = 0x30  # pixel (0,0) = colour 3, pixel (0,1) = colour 0 (transparent)
    d[art:art + 32] = bytes(t)
    pieces = [{"y": 0, "w": 1, "h": 1, "tile": 0, "pal": 0, "pri": 0, "hf": 0, "vf": 1, "x": 0}]
    r = sk_render.render_frame(bytes(d), art, [(0, 1)], pieces, pal)

    def px(x, y):
        o = (y * 8 + x) * 4
        return tuple(r["rgba"][o:o + 3]), r["rgba"][o + 3]

    assert px(0, 0) == ((0, 0, 0), 0)       # vf moved it off the top row
    assert px(0, 7) == ((0, 0, 255), 255)   # bottom-left now
    assert px(1, 7) == ((0, 0, 0), 0)       # low nibble stays transparent


def test_png_roundtrip_header():
    rgba = bytes([255, 0, 0, 255]) * 4
    png = sk_render.png_bytes(rgba, 2, 2)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">I", png[16:20]) == (2,)


@pytest.mark.skipif(not SRC.exists(), reason="owned #1365 build is not cached on this host")
def test_owned_build_sonic_frame_and_writer_room():
    inv = sk_sprites.inventory(SRC)
    assert inv["source"]["sha256"] == SOURCE_SHA256
    d, _ = sk_sprites.read_rom(SRC)

    r = sk_render.render_character(d, inv, "sonic", 1)
    assert (r["w"], r["h"], r["tiles"], r["opaque"]) == (40, 40, 23, 720)
    assert r["bounds"] == [-20, -20, 20, 20] and r["art_base"] == 0x100000

    pal = sk_render.decode_palette(d, inv["characters"]["sonic"]["palette"]["offset"])
    assert pal[0] == (0, 0, 0) and pal[1] == (255, 255, 255) and pal[6] == (255, 0, 0)

    k = sk_render.render_character(d, inv, "knuckles", 1)
    assert (k["w"], k["h"]) == (40, 40) and k["opaque"] > 500 and k["art_base"] == 0x1200E0

    room = sk_render.writer_room(d, inv)
    sb, kb = room["art_banks"]["sonic"], room["art_banks"]["knuckles"]
    assert (sb["base"], sb["bank"], sb["bank_end"]) == (0x100000, 0x100000, 0x120000)
    assert sb["dplc_tiles"] == 3950 and sb["room_tiles_to_bank_end"] == 146
    assert (kb["base"], kb["dplc_tiles"], kb["room_tiles_to_bank_end"]) == (0x1200E0, 4076, 13)
    assert room["tables"]["block"] == [0x146620, 0x14C652]
    assert room["tail"]["last_data"] == 0x1FF419 and room["tail"]["free_tail"] == 0xBE6


def test_cram_primary_channels():
    assert sk_render.crgb(0x000e) == (255, 0, 0)
    assert sk_render.crgb(0x00e0) == (0, 255, 0)
    assert sk_render.crgb(0x0e00) == (0, 0, 255)


@pytest.mark.parametrize("hf,vf", [(0, 0), (1, 0), (0, 1), (1, 1)])
def test_multi_tile_sprite_column_order_and_whole_piece_flips(hf, vf):
    # Four distinct tiles, each with one pixel at its upper-left corner.
    art = b"".join(bytes([color << 4]) + bytes(31) for color in range(1, 5))
    palette = [(i, 0, 0) for i in range(16)]
    piece = dict(x=0, y=0, w=2, h=2, tile=0, hf=hf, vf=vf)
    result = sk_render.render_frame(art, 0, [(0, 4)], [piece], palette)
    expected = bytearray(16 * 16 * 4)
    for x, y, color in [(0, 0, 1), (0, 8, 2), (8, 0, 3), (8, 8, 4)]:
        x = 15 - x if hf else x
        y = 15 - y if vf else y
        offset = (y * 16 + x) * 4
        expected[offset:offset+4] = bytes([color, 0, 0, 255])
    assert result["rgba"] == expected


@pytest.mark.parametrize("rgba,w,h", [(b"", 0, 0), (b"", 1, 1)])
def test_png_rejects_invalid_dimensions(rgba, w, h):
    with pytest.raises(sk_render.SkError):
        sk_render.png_bytes(rgba, w, h)
