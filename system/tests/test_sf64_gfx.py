"""Tests for gbox.sf64_gfx (F3DEX1 walker + Arwing OBJ export)."""
import os
import struct

import pytest

from gbox import sf64_gfx as gfx
from gbox import sf64_inventory as inv

ROM = os.environ.get("SF64_ROM") or os.path.expanduser(
    "~/gbox-cache/59a2755566b669ed/rom.z64")
needs_rom = pytest.mark.skipif(not os.path.exists(ROM), reason="owned ROM not cached")


def test_synthetic_dl_vtx_tri():
    seg = bytearray(0x100)
    vt = struct.pack(">hhhHhhBBBB", 1, 2, 3, 0, 32, 64, 255, 0, 0, 255)
    seg[0x80:0x80 + 48] = vt * 3
    cmds = [
        (0x04 << 24 | (0 << 16) | (3 << 10) | (16 * 3 - 1), 0x03000080),
        (0xBF << 24, (0 << 16) | (2 << 8) | 4),
        (0xB8 << 24, 0),
    ]
    for i, (a, b) in enumerate(cmds):
        seg[i * 8:i * 8 + 8] = struct.pack(">II", a, b)
    m = gfx.mesh_from_dl(bytes(seg), 0)
    assert len(m["faces"]) == 1 and m["unknown"] == {}
    assert m["verts"][0]["pos"] == (1, 2, 3) and m["verts"][0]["uv"] == (1.0, 2.0)


@needs_rom
def test_arwing_export(tmp_path):
    rom = inv.load_rom(ROM)
    res = gfx.export_arwing_obj(rom, str(tmp_path / "a.obj"))
    assert res["limbs"] == 18
    dls = {m["dl"]: m for m in res["meshes"]}
    for off in (0x9B60, 0x15D80, 0x16660):  # body, right wing, left wing
        assert off in dls and dls[off]["faces"] > 0
    assert all(not m["unknown_ops"] for m in res["meshes"])
    xs = [float(l.split()[1]) for l in open(tmp_path / "a.obj") if l.startswith("v ")]
    assert abs(min(xs) + max(xs)) < 1.0  # left/right symmetric rest pose


# --- texture decoding: expected values hand-derived from the N64 texel spec ---

def test_rgba16_known_texels():
    # 0xF801 = r31 g0 b0 a1 ; 0x07C1 = g31 ; 0x003F = b31 a1 ; 0x0000 transparent black
    rows = gfx.decode_texture(bytes([0xF8, 0x01, 0x07, 0xC1, 0x00, 0x3F, 0x00, 0x00]),
                              gfx.FMT_RGBA, 2, 2, 2)
    assert rows[0] == [(255, 0, 0, 255), (0, 255, 0, 255)]
    assert rows[1] == [(0, 0, 255, 255), (0, 0, 0, 0)]


def test_ia_i_ci_formats():
    assert gfx.decode_texture(bytes([0x80, 0x40]), gfx.FMT_IA, 2, 1, 1) == [[(128, 128, 128, 64)]]
    assert gfx.decode_texture(bytes([0xA5]), gfx.FMT_IA, 1, 1, 1) == [[(170, 170, 170, 85)]]
    assert gfx.decode_texture(bytes([0x7F]), gfx.FMT_I, 1, 1, 1) == [[(127, 127, 127, 255)]]
    # I4: nibbles 0 and 15 ; IA4: 0b1111 = I7 A1, 0b0000
    assert gfx.decode_texture(bytes([0x0F]), gfx.FMT_I, 0, 2, 1) == [[(0, 0, 0, 255), (255, 255, 255, 255)]]
    assert gfx.decode_texture(bytes([0xF0]), gfx.FMT_IA, 0, 2, 1) == [[(255, 255, 255, 255), (0, 0, 0, 0)]]
    pal = gfx.decode_tlut(bytes([0xF8, 0x01, 0x07, 0xC1]), 2)
    assert gfx.decode_texture(bytes([0x10]), gfx.FMT_CI, 0, 2, 1, pal) == [[pal[1], pal[0]]]
    assert gfx.decode_texture(bytes([1, 0]), gfx.FMT_CI, 1, 2, 1, pal) == [[pal[1], pal[0]]]


def test_texture_bounds_rejected():
    with pytest.raises(ValueError):
        gfx.decode_texture(b"\x00" * 7, gfx.FMT_RGBA, 2, 2, 2)
    with pytest.raises(ValueError):
        gfx.decode_texture(b"\x00" * 4, gfx.FMT_CI, 1, 2, 2, None)
    with pytest.raises(ValueError):
        gfx.decode_texture(b"", gfx.FMT_I, 1, 0, 4)
    with pytest.raises(ValueError):
        gfx.decode_tlut(b"\x00\x00", 2)


def test_walker_records_tile_size_and_tlut():
    seg = bytearray(0x200)
    cmds = [
        (0xFD << 24 | 2 << 21 | 2 << 19, 0x03000100),                # SETTIMG RGBA16
        (0xF5 << 24 | 0 << 21 | 2 << 19, 0),                          # SETTILE tile0 RGBA16
        (0xF2 << 24, (0 << 24) | (28 << 12) | 12),                # SETTILESIZE lrs=7.0 lrt=3.0 (10.2) -> 8x4
        (0xFD << 24 | 0 << 21 | 2 << 19, 0x03000120),                # SETTIMG for tlut
        (0xF0 << 24, (3 << 14)),                                      # LOADTLUT 4 entries
        (0xB8 << 24, 0),
    ]
    for i, (a, b) in enumerate(cmds):
        seg[i * 8:i * 8 + 8] = struct.pack(">II", a, b)
    st = gfx.walk_dl(bytes(seg), 0)
    assert st["unknown"] == {}
    assert (st["timgs"][0]["w"], st["timgs"][0]["h"]) == (8, 4)
    assert st["timgs"][1]["tlut"] == 4


def test_png_roundtrip(tmp_path):
    import zlib
    rows = [[(255, 0, 0, 255), (0, 255, 0, 128)]]
    p = tmp_path / "t.png"
    gfx.write_png(str(p), rows)
    d = p.read_bytes()
    assert d[:8] == b"\x89PNG\r\n\x1a\n"
    i = d.index(b"IDAT")
    ln = struct.unpack(">I", d[i - 4:i])[0]
    assert zlib.decompress(d[i + 4:i + 4 + ln]) == b"\x00" + bytes([255, 0, 0, 255, 0, 255, 0, 128])
