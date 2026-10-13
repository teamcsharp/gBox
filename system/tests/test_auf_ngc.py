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
