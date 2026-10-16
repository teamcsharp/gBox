"""GoldenEye 007 (Europe) model reader tests.

Run from the repository root (system/):
    python -m pytest tests/test_goldeneye_reader.py -v

Requires the normalised PAL z64 (sha256 40ff3643...) at
artifacts/source/007_GoldenEye_Europe_norm.z64 (created by the inventory
stage; see gbox/goldeneye_inventory.py).
"""
import hashlib
import json
import struct
from pathlib import Path

import pytest

from gbox.goldeneye_files import GoldenEyeROM, GoldenEyeFormatError
from gbox import goldeneye_reader as gr

ROM = Path(__file__).resolve().parent.parent / "artifacts" / "source" / "007_GoldenEye_Europe_norm.z64"

pytestmark = pytest.mark.skipif(not ROM.exists(), reason="normalised PAL z64 not present")


@pytest.fixture(scope="module")
def ge():
    rom = ROM.read_bytes()
    assert hashlib.sha256(rom).hexdigest() == gr.PAL_Z64_SHA256
    return GoldenEyeROM.from_bytes(rom)


def test_csuitbondz_full_decode(ge):
    doc = gr.read_character(ge, "CsuitbondZ")
    assert doc["node_count"] == 79
    assert doc["opcode_nodes"] == {"0x01": 1, "0x02": 15, "0x08": 20, "0x09": 1,
                                   "0x0A": 15, "0x0D": 1, "0x17": 1, "0x18": 25}
    skel = doc["skeleton"]
    assert skel is not None and skel["num_joints"] == 16
    assert skel["vram"] == "0x80037190"
    assert len(skel["joints"]) == 16
    # every joint carries an animation bit-stream offset pair
    assert all(j["mtx_a"] >= 0 and j["mtx_b"] >= 0 for j in skel["joints"])
    assert doc["num_switches"] == 7
    assert len(doc["textures"]) == 14


def test_csuitbondz_position_records(ge):
    doc = gr.read_character(ge, "CsuitbondZ")
    pos = [n for n in doc["nodes"] if int(n["opcode"], 16) & 0xFF == 0x02]
    assert len(pos) == 15
    first = pos[0]
    assert first["record"]["origin"] == [0.0, 0.0, 0.0]  # root bone at origin
    assert first["record"]["joint_id"] == 1
    # position chains branch (legs/arms); each branch tail legitimately has
    # no child group (pointer 0 -> None).  At least two thirds name a child.
    with_child = sum(1 for n in pos if n["record"]["child_group_node"] is not None)
    assert with_child >= 10
    # payload records are 28-byte structs; chain runs are contiguous in the
    # file but different branches are not, so only check distinctness.
    offs = sorted(n["data_offset"] for n in pos)
    assert len(set(offs)) == 15


def test_csuitbondz_vertex_nodes(ge):
    doc = gr.read_character(ge, "CsuitbondZ")
    vnodes = [n for n in doc["nodes"] if int(n["opcode"], 16) & 0xFF == 0x18]
    assert len(vnodes) == 25
    total_verts = sum(n["record"]["num_vertices"] for n in vnodes)
    total_coll = sum(n["record"]["num_collision_vertices"] for n in vnodes)
    assert total_verts > 100 and total_coll > 100
    # every vertex array pointer resolves inside the file and yields records
    model = ge.read_file("CsuitbondZ")
    for n in vnodes:
        assert len(n.get("vertices", [])) == n["record"]["num_vertices"]
        assert len(n["record"]["texture_ids"]) >= 0
    # the two DLs we pinned carry the expected global texture ids
    texture_ids = sorted({t for n in vnodes for t in n["record"]["texture_ids"]})
    assert 1631 in texture_ids and 1643 in texture_ids
    # vertex records decode to plausible 16-bit coordinates
    v = vnodes[0]["vertices"][0]
    assert -1000 < v["xyz"][0] < 1000 and -1000 < v["xyz"][1] < 1000
    assert 0 <= v["rgba"][0] <= 255


def test_all_body_files_parse(ge):
    bodies = ge.body_table()
    assert len(bodies) == 80
    ok = 0
    for b in bodies:
        doc = gr.read_character(ge, b.filename)
        assert doc["node_count"] >= 1
        if doc["skeleton"]:
            assert 0 < doc["skeleton"]["num_joints"] <= 64
        ok += 1
    assert ok == 80


def test_triangle_index_space(ge):
    """The F3D_OLD GBI index space is pinned: every decoded triangle's
    node-local vertex indices fall inside the node's own vertex array."""
    doc = gr.read_character(ge, "CsuitbondZ")
    nodes = gr.parse_nodes(ge.read_file("CsuitbondZ"), doc["root_offset"])
    vnodes = [n for n in nodes if n.op == 0x18]
    total = 0
    for n in vnodes:
        nv = n.record["num_vertices"]
        assert all(0 <= i < nv for t in n.triangles for i in t), \
            f"triangle index out of range at node 0x{n.offset:04X}"
        total += len(n.triangles)
    assert total == 619  # pinned for CsuitbondZ: 619 render triangles
    # the two 64-vertex nodes use G_TRI1 (0xBF) 8-bit x10 indices too
    assert any(n.record["num_vertices"] == 64 and n.triangles for n in vnodes)


def test_gltf_export(ge, tmp_path):
    out = tmp_path / "CsuitbondZ.gltf"
    stats = gr.to_gltf(ge, "CsuitbondZ", out)
    assert stats["joints"] == 15  # 15 position (joint) nodes
    assert stats["meshes"] == 25
    assert stats["triangles"] == 619  # real triangles, not a point cloud
    gltf = json.loads(out.read_text())
    assert gltf["asset"]["version"] == "2.0"
    assert (tmp_path / "CsuitbondZ.bin").stat().st_size == gltf["buffers"][0]["byteLength"]
    # every mesh primitive is at least a valid point cloud with colours
    for m in gltf["meshes"]:
        prim = m["primitives"][0]
        for attr in ("POSITION", "COLOR_0", "TEXCOORD_0"):
            assert attr in prim["attributes"]
    # meshes carry real indexed geometry (triangles, mode 4)
    assert any(m["primitives"][0]["mode"] == 4 for m in gltf["meshes"])
    assert any("indices" in m["primitives"][0] for m in gltf["meshes"])
    # joints carry translations
    assert all("translation" in n for n in gltf["nodes"][:stats["joints"]])


def test_rejects_foreign_rom():
    with pytest.raises(GoldenEyeFormatError):
        GoldenEyeROM.from_bytes(b"\x80\x37\x12\x40" + b"\0" * 1024)
