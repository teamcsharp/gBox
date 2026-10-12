"""Turok: Dinosaur Hunter (NTUE Rev B) — per-object geometry/anim analysis.

Fixtures are real blocks extracted from the owned ROM (v1.2 z64), embedded
so the parsers run without the ROM present.  ROM-backed tests exercise the
full 674-object walk when the ROM image is available.
"""
import os
import struct

import pytest

from gbox import turok_analysis as ta
from gbox import turok_inventory as ti

ROM_PATH = os.environ.get(
    "TUROK_ROM",
    "/home/ehm_eckx/gbox-cache/34ab9ef38aebcaac/rom.z64",
)

# Graphic object 1 (ROM 0x2C48): Geometry RNC2 72->112 bytes.  Unpacked it is
# an indexed set {info, nodes}; one node with an EMPTY parts set — object 1
# is a point object with no mesh sections.
RNC2_GEOMETRY_POINT_OBJECT = bytes.fromhex(
    "524e4302000000700000002fc341abcf020119000002c703101c031803727003c4"
    "0001c91758930f033823200330e30348d0032b004d0433e7083f189e03130800"
)

# Graphic object 561: Anims collection with ONE anim entry (RNC2-packed
# 7-block CART_ANIM set, 96->160 bytes, 2 frames / 1 node).
RNC2_ANIM_ENTRY = bytes.fromhex(
    "00000001000000100000007000000000524e4302000000a00000004e4f64b5fe"
    "020119000007c703281c03380371480368c703701c037803719803a0c8032600"
    "0203b10004c30301ff9300210f140f0008b7c49ba6094275c29009167fffbd57"
    "0800074b101c0318037a200b1f9e0000"
)


def test_geometry_fixture_point_object():
    g = ta.parse_geometry(ti.decode_rnc(RNC2_GEOMETRY_POINT_OBJECT))
    assert g["info"]["morph_frame"] == 0
    assert len(g["nodes"]) == 1
    node = g["nodes"][0]
    assert node["child_node_indices"] == []
    assert node["part_indices"] == [0]
    assert len(node["parts"]) == 1
    assert node["parts"][0]["sections"] == []  # point object: no mesh


def test_anim_fixture_entry():
    a = ta.parse_anim(RNC2_ANIM_ENTRY)
    assert len(a["anims"]) == 1
    anim = a["anims"][0]
    assert anim["n_frames"] == 2
    assert anim["n_nodes"] == 1
    assert len(anim["node_anim_indices"]) == 1
    # 2 frames -> translation sets carry 8 + 2*12 = 32 bytes each
    assert anim["translation_sets"] is not None
    assert anim["rotation_sets"] is not None
    # initial orientations cover only animated nodes (the 1 node here)
    assert len(anim["initial_orientations"]) == 1


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
