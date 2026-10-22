"""gbox.mkgold_geo: MK Gold DC GEO part bodies, ARGB1555 pages and 1ST_READ skeleton node tables."""
import hashlib
import os
import struct
from pathlib import Path

import pytest

from gbox import mkgold_geo as mg
from gbox.mkgold_inventory import geo_records

KEY = 0x8C010000
# Liu Kang's node table A (1ST_READ 0x8C566744): body part and flags per node, as stored
LK_CODES = [0x00400994, 0xFFF00890, 0x00300980, 0x00200980, 0xFFE00898, 0x00500980, 0x00700990, 0x00900998,
            0x00600983, 0x00800991, 0x00A00999, 0xFFD00898, 0x00B00980, 0x00D00990, 0x00F00998, 0x00C00993,
            0x00E00991, 0x01000999]
LK_PARTS = [4, -1, 3, 2, -2, 5, 7, 9, 6, 8, 10, -3, 11, 13, 15, 12, 14, 16]
LK_PARENTS = [None, 0, 1, 2, 3, 2, 5, 6, 2, 8, 9, 2, 1, 12, 13, 1, 15, 16]


def _strip(parity, verts):
    return struct.pack("<IHH24x", 0, parity, len(verts)) + b"".join(struct.pack("<8f", *v) for v in verts)


def _geo(parts):
    """A 0.1v GEO with one flag-1 record per part; parts = [[strip bytes, ...], ...]."""
    count = len(parts)
    body, recs, at = b"", b"", 0x20 + 32 * count
    for i, strips in enumerate(parts):
        rec = 0x20 + 32 * i
        recs += struct.pack("<HHI24x", 1, len(strips), at + len(body) - (rec + 4))
        body += b"".join(strips)
    data = b"0.1v" + struct.pack("<II", 0x20 + len(recs) + len(body), count) + bytes(20) + recs + body
    return data


def _v(p, n=(0.0, 0.0, 1.0), st=(0.25, 0.5)):
    return (*n, *p, *st)


def test_strips_winding_and_degenerates():
    quad = _strip(0, [_v((0, 0, 0)), _v((0, 1, 0)), _v((1, 0, 0)), _v((1, 1, 0))])
    # parity 1 strip with a repeated vertex: triangle 1 (b, c, c) is degenerate and dropped
    swap = _strip(1, [_v((2, 0, 0)), _v((3, 0, 0)), _v((2, 1, 0)), _v((2, 1, 0)), _v((3, 1, 0))])
    data = _geo([[quad, swap]])
    rec = geo_records(data)[0]
    strips = mg.part_strips(data, rec)
    assert [s["parity"] for s in strips] == [0, 1] and [len(s["positions"]) for s in strips] == [4, 5]
    assert mg.strip_triangles(4, 0) == [(0, 2, 1), (1, 2, 3)]
    assert mg.strip_triangles(3, 1) == [(0, 1, 2)]
    mesh = mg.part_mesh(data, rec)
    assert mesh["strips"] == 2 and mesh["tail"] == 0 and len(mesh["positions"]) == 9
    assert mesh["faces"][:2] == [(0, 2, 1), (1, 2, 3)]
    assert all(len({mesh["positions"][k] for k in f}) == 3 for f in mesh["faces"])
    assert mg.facing_ratio({"positions": mesh["positions"], "normals": mesh["normals"], "faces": mesh["faces"][:2]}) == 1.0


def test_bad_strip_header_raises():
    bad = bytearray(_geo([[_strip(0, [_v((0, 0, 0))] * 3)]]))
    bad[0x40 + 6] = 9  # vertex count now overruns the record
    with pytest.raises(ValueError):
        mg.part_strips(bytes(bad), geo_records(bytes(bad))[0])


def test_obj_rotates_to_y_up_and_maps_t_to_u():
    data = _geo([[_strip(1, [_v((1, 2, 3), st=(0.25, 0.5)), _v((0, 1, 0)), _v((1, 0, 0))])]])
    obj = mg.to_obj(mg.part_mesh(data, geo_records(data)[0]), "kl0", "kl.png")
    lines = obj.splitlines()
    assert "v 1.000000 -2.000000 -3.000000" in lines
    assert "vt 0.500000 0.750000" in lines           # (t, 1 - s)
    assert sum(l.startswith("f ") for l in lines) == 1 and "mtllib kl0.mtl" in lines
    assert "map_Kd kl.png" in mg.to_mtl("kl0", "kl.png")


def test_argb1555_png_and_linear_layout():
    assert mg.argb1555(0xFC00) == (255, 0, 0, 255)
    assert mg.argb1555(0x03E0) == (0, 255, 0, 0)
    assert mg.argb1555(0x801F) == (0, 0, 255, 255)
    w, h = 16, 8
    px = [0x8000 | (x << 10) | (y << 5) for y in range(h) for x in range(w)]   # smooth in ARGB1555 only
    img = b"0.1v" + struct.pack("<II", 0x40 + 2 * w * h, 1) + bytes(20) + struct.pack("<HH28x", w, h)
    img += struct.pack(f"<{w * h}H", *px)
    W, H, rgba = mg.img_rgba(img)
    assert (W, H, len(rgba)) == (w, h, w * h * 4) and rgba[:4] == bytes((0, 0, 0, 255))
    png = mg.png_bytes(W, H, rgba)
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", png[16:24]) == (w, h)
    lay = mg.texel_layout(img, step=1)
    assert lay["best"] == "ARGB1555/linear" and lay["alpha_set"] == 1.0
    assert mg.twiddled_index(1, 0, 4, 4) == 2 and mg.twiddled_index(0, 1, 4, 4) == 1
    assert mg.twiddled_index(4, 0, 8, 4) == 16


def test_node_table_walk_matches_liu_kang():
    nodes = [{"part": p, "flags": c & 0xFFFFF, "offset": (0.0, 0.0, 0.0)} for p, c in zip(LK_PARTS, LK_CODES)]
    assert mg.node_parents(nodes) == LK_PARENTS
    # the same records in a fake executable: the table ends at the pop on an empty stack
    base, ms = 0x100, KEY + 0xF4
    blob = bytearray(base + 32 * (len(LK_CODES) + 2))
    for i, c in enumerate(LK_CODES + [0x00100980, 0x00100980]):
        struct.pack_into("<III3fII", blob, base + 32 * i, c, ms, 0, 0.0, -0.5 * (i == 7), 0.0, i, 0)
    got = mg.node_table(bytes(blob), KEY + base)
    assert [n["part"] for n in got] == LK_PARTS and [n["index"] for n in got] == list(range(18))
    rest = mg.rest_joints(got, mg.node_parents(got))
    assert rest[7] == (0.0, -0.5, 0.0) and rest[17] == (0.0, 0.0, 0.0)


GDI = Path(os.environ.get("GBOX_MKGOLD_GDI", Path.home() / "gbox-cache/dc/25cfe1a8f7ab69cd/disc.gdi"))


@pytest.mark.skipif(not GDI.exists(), reason="owned MK Gold disc unpack not present")
def test_owned_disc_parts_texels_and_skeletons():
    from gbox.gdrom import GDRom
    g = GDRom(GDI)
    exe = g.read("1ST_READ.BIN")
    assert hashlib.sha256(exe).hexdigest() == mg.BUILD["1st_read_sha256"]
    geo = g.read("KL_GEO.GEO")
    recs = geo_records(geo)
    mesh = mg.part_mesh(geo, recs[0])
    assert (recs[0]["offset"], mesh["strips"], len(mesh["positions"]), mesh["tail"]) == (0x440, 25, 550, 0)
    assert mg.facing_ratio(mesh) > 0.7
    assert all(mg.part_mesh(geo, r)["tail"] == 0 for r in recs)
    lay = mg.texel_layout(g.read("KL_GEO.IMG"))
    assert (lay["width"], lay["height"], lay["best"]) == (512, 256, "ARGB1555/linear")
    table = mg.character_table(exe)
    assert table["addr"] == f"0x{mg.BUILD['character_table']:08X}" and len(table["characters"]) == 23
    lk = table["characters"][3]
    assert lk["name"] == "liu kang" and lk["variants"][0]["geo"] == "lk_geo.geo"
    assert lk["variants"][0]["nodes_a"] == "0x8C566744"
    nodes = mg.node_table(exe, 0x8C566744)
    assert [n["part"] for n in nodes] == LK_PARTS and mg.node_parents(nodes) == LK_PARENTS
    kl = table["characters"][21]
    assert kl["variants"][0]["geo"] == "kl_geo.geo"
    for c in table["characters"]:
        sk = mg.node_table(exe, int(c["variants"][0]["nodes_a"], 16))
        assert sk and sk[0]["flags"] & mg.ROOT, c["name"]



def _tri(off):
    return _strip(0, [_v((off[0] + x, off[1] + y, off[2]), st=(0.25, 0.5)) for x, y in ((0, 0), (0, 1), (1, 0))])


def test_part_record_identity_and_joint_only_nodes():
    geo = _geo([[_tri((0, 0, 0))], [_tri((0, 0, 0))], [_tri((0, 0, 0))]])
    nodes = [{"part": 2}, {"part": -1}, {"part": 0}, {"part": 7}]
    assert mg.part_record(geo, nodes) == [2, None, 0, None]


def test_rig_obj_places_parts_at_rest_joints_y_up():
    geo = _geo([[_tri((0, 0, 0))], [_tri((0, 0, 0))]])
    nodes = [{"part": 0, "offset": (0.0, 1.0, 0.0)}, {"part": 1, "offset": (0.5, 2.0, 0.0)}]
    parents = [None, 0]
    assert mg.rest_joints(nodes, parents) == [(0.0, 1.0, 0.0), (0.5, 3.0, 0.0)]
    obj = mg.rig_obj(geo, nodes, parents, "t")
    v = [tuple(map(float, l.split()[1:])) for l in obj.splitlines() if l.startswith("v ")]
    assert len(v) == 6
    # y-down joint offsets are flipped to y-up: part 1 translated by (0.5, -3, 0) relative to local -y
    assert v[3] == (0.5, -3.0, -0.0) and v[4] == (0.5, -4.0, -0.0)
    assert sum(l.startswith("o ") for l in obj.splitlines()) == 2
    faces = [l for l in obj.splitlines() if l.startswith("f ")]
    assert faces[-1].split()[1].split("/")[0] in {"4", "5", "6"}  # indices offset by earlier part
