"""Tests for gbox.auf_ngc (007: Agent Under Fire GC .ngc packages / .gcm models).

The synthetic tests pin the formats as read from Bond.elf; the disc test runs
only where the owned GCZ is cached (GBOX_AUF_GCZ or the default cache path).
"""
import os
import struct

import pytest

from gbox import auf_ngc


def test_chunk_id_matches_chunkidtostr():
    # First header of maps/dm1.ngc on the owned disc.
    raw = bytes.fromhex("00626c615f646e73")
    assert auf_ngc.chunk_id(raw) == "snd_alb"
    for name in ("restable", "restxtrs", "shaders", "bspfile", "sndbank", "shockprf"):
        assert auf_ngc.chunk_id(auf_ngc.encode_chunk_id(name)) == name


def test_boa_literals_and_backrefs():
    # flags 0b11110111 LSB first: 3 literals, 1 back-ref, 4 literals
    # back-ref b0=0x31 (len 1+2=3, dist low nibble 3), b1=0 -> dist 3: copies "abc"
    src = bytes([0xF7]) + b"abc" + bytes([0x31, 0x00]) + b"defg"
    out, used = auf_ngc.boa_expand(src, 10)
    assert out == b"abcabcdefg"
    assert used == len(src)


def test_boa_overlapping_run_and_noop_token():
    # literal 'x', no-op token (length nibble 0), run copy dist 1 len 15+2
    src = bytes([0b00000001, ord("x"), 0x00, 0x00, 0x1F, 0x00])
    out, _ = auf_ngc.boa_expand(src, 18)
    assert out == b"x" * 18


def test_boa_rejects_reference_before_start():
    with pytest.raises(ValueError):
        auf_ngc.boa_expand(bytes([0x00, 0x51, 0x00]), 4)


def test_boa_store_roundtrip():
    data = bytes(range(256)) * 3 + b"tail"
    assert auf_ngc.boa_expand(auf_ngc.boa_store(data), len(data))[0] == data


def _chunk(name, payload, compress):
    size = len(payload)
    mem = (size + 31) & ~31
    body = auf_ngc.boa_store(payload) if compress else payload
    hdr = auf_ngc.encode_chunk_id(name) + struct.pack(">IfIIII", size, 1.0, int(compress),
                                                      0xCDCDCDCD, len(body), mem)
    blob = hdr + body
    return blob + b"\0" * (-len(blob) % 32)


def _restable(files):
    n = len(files)
    names = b""
    name_offs = []
    base = 0x10 + 16 * n
    for name, _ in files:
        name_offs.append(base + len(names))
        names += name.encode() + b"\0"
    data_base = (base + len(names) + 15) & ~15
    body = b""
    recs = b""
    for (name, blob), no in zip(files, name_offs):
        recs += struct.pack(">4I", no, data_base + len(body), len(blob), 0x1234)
        body += blob + b"\0" * (-len(blob) % 16)
    head = struct.pack(">4I", n, 0, 0, 0) + recs + names
    return head + b"\0" * (data_base - len(head)) + body


def _gcm():
    """Minimal object: header (byte7=8 -> body at 0x10), NGC block at 0x100."""
    g = bytearray(0x400)
    struct.pack_into(">II", g, 0, 0x48400001, 0x00000008)
    struct.pack_into(">I", g, 0x10 + 0x0C, len(g))
    struct.pack_into(">I", g, 0x10 + 0x80, 0x100)
    struct.pack_into(">II", g, 0x100, 0x3ED, 0x00292008)  # byte7 = 8 -> body 0x110
    body = 0x110
    counts = {"vtx_pos": 3, "vtx_normal": 3, "vtx_st": 3, "ent_vtx": 3, "u16_list": 4,
              "u8_list": 5, "tri_strip": 1, "mtx_map": 1, "geom_group": 1, "geom_section": 1}
    off = 0xA0
    for field, name, esize in auf_ngc.NGC_ARRAYS:
        if name not in counts or esize is None:
            continue
        struct.pack_into(">II", g, body + field, off, counts[name])
        if name == "vtx_pos":
            for i in range(3):
                struct.pack_into(">hhh", g, body + off + 6 * i, i, -i, 100 * i)
        off += counts[name] * esize
        off = (off + 3) & ~3
    return bytes(g)


def test_package_walk_restable_and_gcm_tiling():
    gcm = _gcm()
    table = _restable([("models/actors/bond/bond_test_l.gcm", gcm),
                       ("models/anims/idle.gca", b"anim")])
    data = (_chunk("snd_alb", b"\x01" * 40, True) + _chunk("bspfile", b"\x02" * 64, False)
            + _chunk("restable", table, True))
    pkg = auf_ngc.NgcPackage(data)
    assert [c.id for c in pkg.chunks] == ["snd_alb", "bspfile", "restable"]
    assert pkg.chunks[-1].end == len(data)
    assert [r.name for r in pkg.resources()] == ["models/actors/bond/bond_test_l.gcm",
                                                 "models/anims/idle.gca"]
    assert pkg.read("models/anims/idle.gca") == b"anim"
    got = pkg.read("models/actors/bond/bond_test_l.gcm")
    info = auf_ngc.gcm_info(got)
    assert info["ngc_body"] == 0x110
    assert auf_ngc.tile_check(info) == []
    assert auf_ngc.positions(got, info) == [(0, 0, 0), (1, -1, 100), (2, -2, 200)]
    rows = auf_ngc.characters(pkg)
    assert len(rows) == 1 and rows[0]["vtx_pos"] == 3 and rows[0]["tile_problems"] == []


def test_gcm_rejects_non_object():
    with pytest.raises(ValueError):
        auf_ngc.gcm_info(b"\x12\x34" + b"\0" * 0x200)


GCZ = os.environ.get("GBOX_AUF_GCZ",
                     os.path.expanduser("~/gbox-cache/gc/65b7187589166b26/source.gcz"))


@pytest.mark.skipif(not os.path.exists(GCZ), reason="owned AUF GCZ not cached")
def test_owned_disc_dm1_character_models(tmp_path):
    from gbox import au_inventory
    au_inventory.extract(GCZ, ["dm1.ngc"], str(tmp_path))
    data = (tmp_path / "dm1.ngc").read_bytes()
    pkg = auf_ngc.NgcPackage(data)
    assert [c.id for c in pkg.chunks] == ["snd_alb", "sndbank", "restxtrs", "shaders",
                                          "bspfile", "shockprf", "restable"]
    assert pkg.chunks[-1].data_offset + pkg.chunks[-1].disk_size == len(data)
    assert len(pkg.resources()) == 880
    rows = {r["name"]: r for r in auf_ngc.characters(pkg)}
    assert len(rows) == 31
    assert all(not r.get("error") and r["tile_problems"] == [] for r in rows.values())
    bond = rows["models/actors/bond/bond_combat_l.gcm"]
    assert (bond["size"], bond["vtx_pos"], bond["ent_vtx"], bond["tri_strips"],
            bond["sections"], bond["mtx_map"]) == (13824, 263, 387, 204, 3, 67)


# --- reader stage: skeleton, matrix palette, strips -> skinned mesh -------------

def _block(g, at, body_fields=None):
    struct.pack_into(">II", g, at, 0x3E0, 0x00000008)    # byte7 = 8 -> body at +0x10
    return at + 0x10


def _skinned_gcm():
    """Two bones (root at z=10, child +5 z and turned 90 deg about z), a 0.5-scale
    dequant matrix, one strip whose last two vertices use the child's matrix slot."""
    g = bytearray(0x600)
    struct.pack_into(">II", g, 0, 0x48400001, 0x00000008)
    h = 0x10
    struct.pack_into(">I", g, h + 0x0C, len(g))
    struct.pack_into(">3f", g, h + 0x20, 0.5, 1.0, 12.5)      # bbox centre
    struct.pack_into(">3f", g, h + 0x30, 1.5, 1.0, 2.5)       # half extents
    struct.pack_into(">H", g, h + 0x50, 2)                    # bones
    struct.pack_into(">H", g, h + 0x54, 2)                    # palette records
    for field, at in ((0x74, 0x200), (0x78, 0x220), (0x7C, 0x280), (0x80, 0x300)):
        struct.pack_into(">I", g, h + field, at)
        _block(g, at)
    struct.pack_into(">iIiI", g, 0x210, 0, 0x13C6700F, 0, 0x02489002)
    s = 0.5 ** 0.5
    struct.pack_into(">8f", g, 0x230, 0, 0, 10, 0, 0, 0, 0, 1)
    struct.pack_into(">8f", g, 0x250, 0, 0, 5, 0, 0, 0, s, s)
    struct.pack_into(">hhfhhf", g, 0x290, 0, -2, 1.0, 1, -2, 1.0)
    body = 0x310
    struct.pack_into(">12f", g, body, 0.5, 0, 0, 1.0, 0, 0.5, 0, 0, 0, 0, 0.5, 0)
    data = {
        "vtx_pos": struct.pack(">12h", 0, 0, 0, 2, 0, 0, 0, 2, 0, 2, 2, 0),
        "vtx_normal": struct.pack(">3b", 0, 0, 64),
        "vtx_st": struct.pack(">2h", 2048, 1024),
        "ent_vtx": struct.pack(">12H", 0, 0, 0, 1, 0, 0, 2, 0, 0, 3, 0, 0),
        "u16_list": struct.pack(">4H", 0, 1, 2, 3),
        "u8_list": bytes([0, 0, 3, 3]),
        "tri_strip": struct.pack(">HHHBB", 0, 4, 0, 0, 0xFF),
        "mtx_map": bytes([0, 0, 1, 3]),
        "geom_group": struct.pack(">4H", 0, 2, 0, 1),
        "geom_section": struct.pack(">IIHHI", 0, 0xABCD1234, 0, 1, 0),
    }
    off = 0xA0
    for field, name, esize in auf_ngc.NGC_ARRAYS:
        if name not in data:
            continue
        raw = data[name]
        struct.pack_into(">II", g, body + field, off, len(raw) // esize)
        g[body + off:body + off + len(raw)] = raw
        off = (off + len(raw) + 3) & ~3
    return bytes(g)


def test_skeleton_chains_parent_relative_rest_pose():
    g = _skinned_gcm()
    bones = auf_ngc.skeleton(g)
    assert [b["parent"] for b in bones] == [-1, 0]
    assert bones[1]["world_pos"] == pytest.approx([0, 0, 15])
    assert auf_ngc.matrix_records(g) == [(0, -2, 1.0), (1, -2, 1.0)]


def test_mesh_applies_dequant_palette_slots_and_strip_winding():
    g = _skinned_gcm()
    m = auf_ngc.mesh(g)
    assert [tuple(round(c, 4) for c in p) for p in m["positions"]] == [
        (1, 0, 10), (2, 0, 10), (-1, 1, 15), (-1, 2, 15)]
    # GX strips are clockwise-front: even triangles are flipped to CCW.
    assert [f[:3] for f in m["faces"]] == [(1, 0, 2), (1, 2, 3)]
    assert m["uvs"][0] == pytest.approx([1.0, 0.5])
    assert m["normals"][0] == pytest.approx([0, 0, 1])
    assert m["joints"][2][0] == 1 and m["weights"][2] == [1.0, 0.0]
    assert m["shaders"] == [0xABCD1234]
    err, frame = auf_ngc.bbox_error(g, m)
    assert err < 1e-4 and frame == "exact"


def test_slerp_blend_matches_endpoints():
    q = [0, 0, 0.5 ** 0.5, 0.5 ** 0.5]
    assert auf_ngc._slerp([0, 0, 0, 1], q, 1.0) == pytest.approx(q)
    assert auf_ngc._slerp([0, 0, 0, 1], q, 0.0) == pytest.approx([0, 0, 0, 1])


def test_obj_and_glb_export(tmp_path):
    m = auf_ngc.mesh(_skinned_gcm())
    auf_ngc.to_obj(m, tmp_path / "t.obj", "t")
    text = (tmp_path / "t.obj").read_text()
    assert text.count("\nv ") == 4 and "usemtl shader_abcd1234" in text and "f 2/2/2 1/1/1 3/3/3" in text
    pytest.importorskip("numpy")
    from gbox import characters
    st = characters.model_stats(auf_ngc.to_glb(m, tmp_path / "t.glb", "t"))
    assert st["triangles"] == 2 and st["rig"]["skinned"] and st["rig"]["joints"] == 2


@pytest.mark.skipif(not os.path.exists(GCZ), reason="owned AUF GCZ not cached")
def test_owned_disc_dm1_meshes_match_header_bounds(tmp_path):
    from gbox import au_inventory
    au_inventory.extract(GCZ, ["dm1.ngc"], str(tmp_path))
    pkg = auf_ngc.NgcPackage((tmp_path / "dm1.ngc").read_bytes())
    for r in auf_ngc.characters(pkg):
        g = pkg.read(r["name"])
        m = auf_ngc.mesh(g)
        err, _frame = auf_ngc.bbox_error(g, m)
        assert err < 0.25, r["name"]
        assert auf_ngc.winding_agreement(m) > 0.95, r["name"]
    bond = auf_ngc.mesh(pkg.read("models/actors/bond/bond_combat_l.gcm"))
    assert (len(bond["positions"]), len(bond["faces"]), len(bond["bones"])) == (387, 510, 35)
    zs = [p[2] for p in bond["positions"]]
    assert min(zs) == pytest.approx(0.0, abs=0.01) and max(zs) == pytest.approx(86.6, abs=0.05)  # feet on the floor, Z up


# --- textures / shaders (restxtrs, shaders chunks) ---------------------------

def test_gx_chain_size_matches_owned_record():
    # dm1 restxtrs record 0: CMPR 128x128, maxLOD 5 (6 levels), +0x14 = 0x2ac0
    assert auf_ngc.gx_chain_size(auf_ngc.GX_CMPR, 128, 128, 6) == 0x2AC0
    # record 3: CMPR 64x64 one level (+0x14 = 0x800), second plane I8 64x64 (+0x20 = 0x1000)
    assert auf_ngc.gx_chain_size(auf_ngc.GX_CMPR, 64, 64, 1) == 0x800
    assert auf_ngc.gx_chain_size(auf_ngc.GX_I8, 64, 64, 1) == 0x1000


def test_decode_cmpr_block_order_and_palette():
    red, blue = 0xF800, 0x001F
    # 8x8 block = four 4x4 DXT1 sub-blocks (TL, TR, BL, BR); c0 > c1 -> opaque 4-colour
    sub_tl = struct.pack(">HHI", red, blue, 0)            # all index 0 -> red
    sub_tr = struct.pack(">HHI", red, blue, 0x55555555)   # all index 1 -> blue
    sub_bl = struct.pack(">HHI", blue, red, 0xFFFFFFFF)   # c0 <= c1, index 3 -> transparent
    sub_br = struct.pack(">HHI", red, blue, 0x40000000)   # pixel 0 index 1, rest 0
    rgba = auf_ngc.decode_gx(auf_ngc.GX_CMPR, 8, 8, sub_tl + sub_tr + sub_bl + sub_br)

    def px(x, y):
        return tuple(rgba[(y * 8 + x) * 4:(y * 8 + x) * 4 + 4])
    assert px(0, 0) == (255, 0, 0, 255)
    assert px(5, 2) == (0, 0, 255, 255)
    assert px(1, 6)[3] == 0
    assert px(4, 4) == (0, 0, 255, 255) and px(5, 4) == (255, 0, 0, 255)


def test_decode_rgba8_two_plane_tile_and_i8():
    ar = bytes(v for i in range(16) for v in (0x80, i))          # A=0x80, R=i
    gb = bytes(v for i in range(16) for v in (2 * i, 3 * i))     # G=2i, B=3i
    rgba = auf_ngc.decode_gx(auf_ngc.GX_RGBA8, 4, 4, ar + gb)
    assert tuple(rgba[5 * 4:5 * 4 + 4]) == (5, 10, 15, 0x80)
    i8 = auf_ngc.decode_gx(auf_ngc.GX_I8, 8, 4, bytes(range(32)))
    assert tuple(i8[(1 * 8 + 2) * 4:(1 * 8 + 2) * 4 + 4]) == (10, 10, 10, 255)
    with pytest.raises(ValueError):
        auf_ngc.decode_gx(auf_ngc.GX_CMPR, 8, 8, b"\0" * 8)


class _Pkg:
    def __init__(self, **payloads):
        self.p = payloads

    def payload(self, cid):
        return self.p[cid]


def _restxtrs():
    img = struct.pack(">HHI", 0xF800, 0x001F, 0) * 4
    rec = struct.pack(">IHHIIIIIII", 14, 8, 8, 1, 0, 0x60, len(img), 0, 0, 0)
    rec += b"\0" * 4 + struct.pack(">IIff", 0, 1, 0.0, 0.0) + bytes([0, 0, 0, 0]) + b"\0" * 8
    assert len(rec) == 0x44
    head = struct.pack(">fIII", 1.2, 1, 0x10, 0x14) + struct.pack(">I", 0xABCD0001)
    body = head + rec
    return body + b"\0" * (0x60 - len(body)) + img


def _shaders():
    # header, 2 shaders at 0x5c: one textured, one with the 0xCCDDCCDD no-texture id
    s = bytearray(0x100)
    struct.pack_into(">fII", s, 0, 0.945, 0x5C, 2)
    struct.pack_into(">IB", s, 0x5C, 0x11111111, 1); struct.pack_into(">I", s, 0x5C + 12, 0x80)
    struct.pack_into(">IB", s, 0x6C, 0x22222222, 1); struct.pack_into(">I", s, 0x6C + 12, 0x94)
    struct.pack_into(">IH", s, 0x80, 0xA8, 1)
    struct.pack_into(">IH", s, 0x94, 0xBC, 1)
    struct.pack_into(">II", s, 0xA8, 0, 0xABCD0001)
    struct.pack_into(">II", s, 0xBC, 0, auf_ngc.NO_TEXTURE)
    return bytes(s)


def test_restxtrs_shaders_resolve_section_textures():
    pkg = _Pkg(restxtrs=_restxtrs(), shaders=_shaders())
    tex = auf_ngc.textures(pkg)
    t = tex[0xABCD0001]
    assert (t.fmt, t.width, t.height, t.wrap_s, t.levels) == (14, 8, 8, 1, 1)
    assert auf_ngc.texture_check(pkg) == []
    shd = auf_ngc.shaders(pkg)
    assert shd[0x11111111] == [[(0, 0xABCD0001)]]
    got = auf_ngc.section_textures(pkg, {"shaders": [0x11111111, 0x22222222, 0x33333333]})
    assert got[0] == t and got[1] is None and got[2] is None
    assert auf_ngc.texture_rgba(pkg, t)[:4] == bytes((255, 0, 0, 255))


def test_glb_add_materials_one_primitive_per_section(tmp_path):
    import json as _json
    pytest.importorskip("numpy")
    m = auf_ngc.mesh(_skinned_gcm())
    path = tmp_path / "m.glb"
    auf_ngc.to_glb(m, path, "m")
    png = auf_ngc.png_bytes(bytes((255, 0, 0, 255)) * 4, 2, 2)
    assert png.startswith(b"\x89PNG")
    auf_ngc.glb_add_materials(path, m, [(png, 1, 0, False)] + [None] * (len(m["shaders"]) - 1))
    data = path.read_bytes()
    gl = _json.loads(data[20:20 + struct.unpack_from("<I", data, 12)[0]])
    used = {f[3] for f in m["faces"]}
    assert len(gl["meshes"][0]["primitives"]) == len(used)
    assert gl["images"][0]["mimeType"] == "image/png"
    assert gl["samplers"][0]["wrapS"] == 10497 and gl["samplers"][0]["wrapT"] == 33071


@pytest.mark.skipif(not os.path.exists(GCZ), reason="owned AUF GCZ not cached")
def test_owned_disc_dm1_textures_and_bond_materials(tmp_path):
    from gbox import au_inventory
    au_inventory.extract(GCZ, ["dm1.ngc"], str(tmp_path))
    pkg = auf_ngc.NgcPackage((tmp_path / "dm1.ngc").read_bytes())
    tex = auf_ngc.textures(pkg)
    assert len(tex) == 358 and auf_ngc.texture_check(pkg) == []
    m = auf_ngc.mesh(pkg.read("models/actors/bond/bond_combat_l.gcm"))
    st = auf_ngc.section_textures(pkg, m)
    assert ["%08x" % t.id for t in st] == ["90055abf", "76df3706", "af2b5dea"]
    assert [(t.fmt, t.width) for t in st] == [(14, 128), (14, 128), (14, 64)]
    import hashlib
    png = auf_ngc.png_bytes(auf_ngc.texture_rgba(pkg, st[0]), 128, 128)
    assert hashlib.sha256(png).hexdigest() == "e8e98b385732d3b42055788b5e66fc3654a9b706f8bff221e8597d26b9424a31"
