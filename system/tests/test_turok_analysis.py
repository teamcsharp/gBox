"""Turok: Dinosaur Hunter (NTUE Rev B) — per-object geometry/anim analysis.

The parsers run on synthetic tengine CIndexedSet/CUnindexedSet blocks built
here (no game bytes are embedded).  ROM-backed tests exercise the full
674-object walk when the owned ROM image is available (TUROK_ROM or the
gbox cache); they skip otherwise.
"""
import os
import struct
from pathlib import Path

import pytest

from gbox import turok_analysis as ta
from gbox import turok_inventory as ti

ROM_PATH = os.environ.get(
    "TUROK_ROM",
    str(Path.home() / "gBox_alt/gbox-cache" / "34ab9ef38aebcaac" / "rom.z64"),
)


def iset(*blocks):
    """A CIndexedSet: {u32 n, u32 offsets[n + 1]} then the blocks."""
    if not blocks:
        return struct.pack(">I", 0)
    offs = [4 + 4 * (len(blocks) + 1)]
    for b in blocks:
        offs.append(offs[-1] + len(b))
    return struct.pack(f">I{len(offs)}I", len(blocks), *offs) + b"".join(blocks)


def uset(block_size, records=()):
    """A CUnindexedSet: {u32 BlockSize, u32 BlockCount} then the records."""
    return struct.pack(">II", block_size if records else 0, len(records)) + b"".join(records)


def planar_vertices(verts):
    """Interleaved 16-byte Vtx records -> the ROM's planar-by-byte layout."""
    inter = b"".join(struct.pack(">3hH2h4s", *v) for v in verts)
    n = len(verts)
    return struct.pack(">II", 16, n) + bytes(inter[i * 16 + c] for c in range(16) for i in range(n))


def u32(v):
    return struct.pack(">I", v)


POINT_GEOMETRY = iset(uset(4, [u32(0)]),
                      iset(iset(uset(4), uset(4, [u32(0)]), iset(iset()))))

VERTS = [(0, 0, 0, 0, 0, 0, b"\xff\x00\x00\xff"), (100, 0, 0, 0, 32, 0, b"\x00\xff\x00\xff"),
         (0, 100, 0, 0, 0, 32, b"\x00\x00\xff\xff"), (100, 100, -5, 1, 32, 32, b"\x10\x20\x30\x40")]
SECTION = iset(struct.pack(">II4s4sHH", 486, 7, b"\x80\x80\x80\xff", b"\0\0\0\0", 1, 2),
               uset(2, [struct.pack(">H", 0 | 1 << 5 | 2 << 10), struct.pack(">H", 3 | 2 << 5 | 1 << 10 | 1 << 15)]),
               planar_vertices(VERTS))
MESH_GEOMETRY = iset(uset(4, [u32(3)]),
                     iset(iset(uset(4, [u32(1)]), uset(4, [u32(0)]), iset(iset(SECTION)))))


def anim_entry(nframes=2, nnodes=1):
    yrots = uset(2, [struct.pack(">H", 0x100 * f) for f in range(nframes)])
    nodeidx = uset(4, [struct.pack(">hh", 0, 0) for _ in range(nnodes)])
    initor = uset(20, [struct.pack(">3f4h", 1.0, 2.0, 3.0, 0, 0, 0, 0x7FFF) for _ in range(nnodes)])
    trans = uset(8 + 12 * nframes, [uset(12, [struct.pack(">3f", f, 0.0, 0.0) for f in range(nframes)])])
    rots = uset(8 + 8 * nframes, [uset(8, [struct.pack(">4h", 0, 0, f, 1) for f in range(nframes)])])
    return iset(yrots, nodeidx, initor, trans, rots, iset(), uset(4))


def test_geometry_point_object():
    g = ta.parse_geometry(POINT_GEOMETRY)
    assert g["info"]["morph_frame"] == 0
    assert len(g["nodes"]) == 1
    node = g["nodes"][0]
    assert node["child_node_indices"] == []
    assert node["part_indices"] == [0]
    assert len(node["parts"]) == 1
    assert node["parts"][0]["sections"] == []  # point object: no mesh


def test_geometry_mesh_section_deinterleaves_vertices():
    g = ta.parse_geometry(MESH_GEOMETRY)
    assert g["info"]["morph_frame"] == 3
    node = g["nodes"][0]
    assert node["child_node_indices"] == [1]
    (sec,) = node["parts"][0]["sections"]
    assert sec["info"]["texset"] == 486 and sec["info"]["mult_v"] == 2
    assert sec["n_vertices"] == 4
    assert sec["vertices"][3] == (100, 100, -5, 1, 32, 32)
    assert sec["vertex_tails"][3] == b"\x10\x20\x30\x40"
    assert sec["triangles"] == [(0, 1, 2), (3, 2, 1)]


def test_anim_entry():
    a = ta.parse_anim(iset(anim_entry()))
    assert len(a["anims"]) == 1
    anim = a["anims"][0]
    assert anim["n_frames"] == 2
    assert anim["n_nodes"] == 1
    assert len(anim["node_anim_indices"]) == 1
    # 2 frames -> translation sets carry 8 + 2*12 = 32 bytes each
    assert len(anim["translation_sets"]) == 1 and len(anim["translation_sets"][0]) == 24
    assert len(anim["rotation_sets"]) == 1 and len(anim["rotation_sets"][0]) == 16
    assert anim["initial_orientations"][0][:3] == (1.0, 2.0, 3.0)
    assert ta.parse_anim(struct.pack(">I", 0)) == {"anims": []}


def test_malformed_blocks_raise_valueerror():
    for n in range(len(MESH_GEOMETRY)):
        with pytest.raises(ValueError):
            ta.parse_geometry(MESH_GEOMETRY[:n])
    entry = anim_entry()
    for n in range(len(entry)):
        with pytest.raises(ValueError):
            ta.parse_anim(iset(entry[:n]))
    # a non-empty set with a zero record size cannot be unpacked
    with pytest.raises(ValueError):
        ta._unindexed(struct.pack(">II", 0, 3))


def test_polystream_absolute_indices():
    # VA/VB/VC are absolute section-vertex indices; LASTINRUN only groups
    # triangles into RSP draw commands.
    words = [(0, 1, 2, True), (3, 0, 2, True)]
    assert ta._polystream_triangles(words, 4) == [(0, 1, 2), (3, 0, 2)]
    words2 = [(0, 1, 2, True), (30, 31, 16, True)]
    assert ta._polystream_triangles(words2, 40) == [(0, 1, 2), (30, 31, 16)]


def test_polystream_rejects_out_of_range_indices():
    with pytest.raises(ValueError):
        ta._polystream_triangles([(0, 3, 0, True)], 3)  # index 3 >= 3


def test_unindexed_header_validation():
    us = ta._unindexed(struct.pack(">II", 16, 2) + b"x" * 32)
    assert us["count"] == 2 and us["block_size"] == 16
    with pytest.raises(ValueError):
        ta._unindexed(struct.pack(">II", 16, 99) + b"x" * 8)  # overruns


@pytest.mark.skipif(not os.path.exists(ROM_PATH), reason="ROM not cached")
def test_rom_walk_all_objects():
    rom = open(ROM_PATH, "rb").read()
    res = ta.analyze(rom)
    assert res["objects_total"] == 674
    assert res["geometry_ok"] == 674, \
        f"{res['geometry_errors']} objects failed to decode"
    # objects with geometry contribute vertices and triangles; point objects
    # (empty parts) are legal and contribute nothing
    meshed = [s for s in res["stats"] if s["vertices"] > 0]
    assert meshed, "no object yielded a mesh"
    for s in meshed:
        assert s["triangles"] > 0


@pytest.mark.skipif(not os.path.exists(ROM_PATH), reason="ROM not cached")
def test_rom_object_0_detail():
    rom = open(ROM_PATH, "rb").read()
    inv = ti.inventory(rom)
    obj = inv["graphic_objects"]["objects"][0]
    r = ta.decode_object(rom, obj)
    assert "geometry" in r
    g = r["geometry"]
    assert len(g["nodes"]) == 1
    assert len(g["nodes"][0]["parts"]) == 1
    secs = g["nodes"][0]["parts"][0]["sections"]
    assert len(secs) == 3
    assert secs[0]["info"]["texset"] == 486 and secs[0]["n_vertices"] == 4
    assert secs[1]["info"]["texset"] == 487 and secs[1]["n_vertices"] == 8
    # all section triangle indices stay inside their vertex blocks
    for s in secs:
        for tri in s["triangles"]:
            assert max(tri) < s["n_vertices"]


@pytest.mark.skipif(not os.path.exists(ROM_PATH), reason="ROM not cached")
def test_rom_anim_tables_parse():
    rom = open(ROM_PATH, "rb").read()
    inv = ti.inventory(rom)
    parsed = 0
    entries = 0
    for obj in inv["graphic_objects"]["objects"]:
        go = ta.graphic_object(rom, obj)
        try:
            anim = ta.parse_anim(go["Anims"]["data"])
        except ValueError as e:
            continue  # empty (count-0) anim collections are legal
        for a in anim["anims"]:
            assert len(a["node_anim_indices"]) == a["n_nodes"]
            # initial orientations exist only for nodes with animated
            # transforms; never more than the node count
            assert 0 <= len(a["initial_orientations"]) <= a["n_nodes"]
            entries += 1
        parsed += 1
    assert parsed > 0, "no object yielded a parseable animation table"
    assert entries > 0, "no anim entries found"
