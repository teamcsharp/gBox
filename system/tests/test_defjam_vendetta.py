"""Def Jam: Vendetta (GDTE69) native mesh/texture reader: synthetic format tests plus the owned-disc check."""
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import defjam_vendetta as D

ISO = Path.home() / "gbox-cache/modbase/8b37766f557e1f5f/Def Jam - Vendetta (USA).iso"


def _pad(b: bytearray, a=32):
    b.extend(bytes(-len(b) % a))


def make_gpl(pos, nrm, uvs, dl: bytes, vcd: int, frac=6, tex="t_m0.tpl", mesh="t_m0-body") -> bytes:
    """Same layout as the disc files: rel offsets from 0x1C, vertex header at 0x34, data at 0x40."""
    b = bytearray(0x40)
    struct.pack_into(">IIIII", b, 0, D.GPL_MAGIC, 0, 0, 1, 0x14)
    struct.pack_into(">IHBB", b, 0x34, 0x40 - D.BASE, len(pos), 0x3A, frac)
    for p, n in zip(pos, nrm):
        b += struct.pack(">6h", *[int(round(v * (1 << frac))) for v in p], *[int(round(v * 1024)) for v in n])
    _pad(b)
    uh = len(b)
    b += struct.pack(">IHHII", uh + 0x10 - D.BASE, len(uvs), 0x4002, 0, 0)
    for u in uvs:
        b += struct.pack(">ff", *u)
    dh = len(b)
    b += bytes(0x54)
    dl_off = len(b)
    b += dl
    _pad(b)
    struct.pack_into(">I", b, dh, 42)
    struct.pack_into(">IIII", b, dh + 0x38, 0x03000000, vcd, dl_off - D.BASE, len(b) - dl_off)
    b += tex.encode() + b"\0" + mesh.encode() + b"\0"
    struct.pack_into(">III", b, 0x1C, 0x34 - D.BASE, 0, uh - D.BASE)
    struct.pack_into(">I", b, 0x28, dh - D.BASE)
    return bytes(b)


QUAD = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)]
UP = [(0, 0, -1)] * 4                     # GX front faces are clockwise: this strip faces -Z when read CCW


def test_decode_dl_strip_triangles_and_index_widths():
    strip = bytes([0x98, 0, 4]) + bytes(sum(([i, i, i] for i in range(4)), []))
    tris, prims = D.decode_dl(strip + b"\0\0", 0x0828, 4, 4)
    assert prims == 1 and [[c[0] for c in t] for t in tris] == [[0, 1, 2], [2, 1, 3]]
    wide = bytes([0x90, 0, 3]) + struct.pack(">9H", 0, 0, 1, 1, 1, 2, 2, 2, 3)
    tris, _ = D.decode_dl(wide, 0x0C3C, 3, 4)
    assert tris == [((0, 0, 1), (1, 1, 2), (2, 2, 3))]
    mixed = bytes([0x90, 0, 3]) + b"".join(struct.pack(">HHB", i, i, i + 1) for i in range(3))   # pos/nrm 16, tex 8
    tris, _ = D.decode_dl(mixed, 0x083C, 3, 4)
    assert tris == [((0, 0, 1), (1, 1, 2), (2, 2, 3))]
    with pytest.raises(D.FormatError, match="index"):
        D.decode_dl(bytes([0x90, 0, 3, 0, 0, 0, 1, 1, 1, 9, 9, 9]), 0x0828, 4, 4)
    with pytest.raises(D.FormatError, match="opcode"):
        D.decode_dl(bytes([0x61, 0, 0, 0, 0]), 0x0828, 4, 4)


def test_parse_gpl_synthetic_matches_disc_layout():
    strip = bytes([0x98, 0, 4]) + bytes(sum(([i, i, i] for i in range(4)), []))
    m = D.parse_gpl(make_gpl(QUAD, UP, [(0, 0), (1, 0), (0, 1), (1, 1)], strip, 0x0828))
    assert m["vertex_count"] == 4 and m["uv_count"] == 4 and m["bones"] == 42 and len(m["triangles"]) == 2
    assert np.allclose(m["positions"], QUAD) and np.allclose(m["normals"], UP)
    assert m["texture"] == "t_m0.tpl" and m["mesh_name"] == "t_m0-body"
    assert D.winding(m) == 0.0                 # clockwise (GX) -> the exporter flips it
    with pytest.raises(D.FormatError):
        D.parse_gpl(b"\0" * 64)


def test_tpl_palette_and_cmpr_decode():
    b = bytearray(struct.pack(">III", D.TPL_MAGIC, 2, 12))
    b += struct.pack(">IIII", 0x40, 0x2C, 0x60, 0)
    b += bytes(0x2C - len(b)) + struct.pack(">HBBII", 2, 0, 0, 1, 0x38)        # palette: 2 x RGB565
    b += bytes(0x38 - len(b)) + struct.pack(">HH", 0xF800, 0x07E0)
    b += bytes(0x40 - len(b)) + struct.pack(">HHII", 4, 8, 9, 0x80)          # 8x4 C8
    b += bytes(0x60 - len(b)) + struct.pack(">HHII", 8, 8, 14, 0xA0)         # 8x8 CMPR
    b += bytes(0x80 - len(b)) + bytes([0, 1] * 16)
    b += bytes(0xA0 - len(b)) + struct.pack(">HHI", 0x001F, 0xF800, 0) * 4
    imgs = D.parse_tpl(bytes(b))
    c8 = D.decode_image(bytes(b), imgs[0])
    assert c8.shape == (4, 8, 4) and tuple(c8[0, 0]) == (255, 0, 0, 255) and tuple(c8[0, 1]) == (0, 255, 0, 255)
    cm = D.decode_image(bytes(b), imgs[1])
    assert cm.shape == (8, 8, 4) and (cm[..., 2] == 255).all() and (cm[..., 0] == 0).all()


def test_write_glb_roundtrip(tmp_path):
    strip = bytes([0x98, 0, 4]) + bytes(sum(([i, i, i] for i in range(4)), []))
    m = D.parse_gpl(make_gpl(QUAD, UP, [(0, 0), (1, 0), (0, 1), (1, 1)], strip, 0x0828))
    img = np.full((4, 4, 4), 200, np.uint8)
    out = D.write_glb(tmp_path / "t.glb", [{"name": "t_body", "mesh": m, "flip": True, "image": img}], "t")
    raw = out.read_bytes()
    magic, ver, total = struct.unpack_from("<III", raw, 0)
    jl = struct.unpack_from("<I", raw, 12)[0]
    gl = json.loads(raw[20:20 + jl])
    assert magic == 0x46546C67 and ver == 2 and total == len(raw)
    prim = gl["meshes"][0]["primitives"][0]
    assert gl["accessors"][prim["indices"]]["count"] == 6 and "TEXCOORD_0" in prim["attributes"]
    assert gl["images"][0]["mimeType"] == "image/png" and gl["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"]


def test_normal_scale_accepts_1024_and_2048_fixed_point():
    assert D.normal_scale_ok(1023.3) and D.normal_scale_ok(2047.7) and D.normal_scale_ok(954.1)
    assert not D.normal_scale_ok(805.3) and not D.normal_scale_ok(0) and not D.normal_scale_ok(1.0)


def test_registered_reader_and_roster():
    from gbox import characters as C
    r = next(r for r in C.DEDICATED if r[0] == "defjam_vendetta")
    assert r[1]("def jam - vendetta (usa)", "gamecube") and not r[1]("def jam - fight for ny (usa)", "gamecube")
    ros = r[2]()
    assert len(ros) == 58 and len({e["slug"] for e in ros}) == 58


@pytest.mark.skipif(not ISO.is_file(), reason="owned Def Jam Vendetta ISO is not unpacked on this node")
def test_owned_disc_s000a(tmp_path):
    from gbox.gcdisc import GCDisc
    ident = D.identify(ISO)
    assert ident["game_id"] == "GDTE69" and ident["revision"] == 0 and ident["exact_build"]
    disc = GCDisc(ISO)
    inv = D.inventory(disc)
    assert [f["dir"] for f in inv["fighter_dirs"]] == D.FIGHTER_DIRS
    assert len(inv["crowd"]) == 23 and len(inv["stages"]) == 16
    r = D.extract_model(disc, "data/s000a", "s000a", tmp_path / "s000a.glb")
    assert r["verified"] and len(r["parts"]) == 5
    body = r["parts"][0]
    assert body["mesh_name"] == "s000a_m0-body" and body["triangles"] == 1277 and body["winding"] > 0.99
    assert body["texture_file"] == "data/s000a/s000a_m0.tpl" and Path(r["glb"]).stat().st_size > 100000
