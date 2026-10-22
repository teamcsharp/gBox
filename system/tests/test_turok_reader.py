"""Turok NTUE Rev B — native reader focused tests.

The synthetic test builds its own geometry dict (independent of the ROM
parsers) and asserts the exact OBJ text, so it does not merely re-assert the
parser's own assumptions.  The ROM-backed test runs the real export on the
owned build when the image is present and is skipped otherwise.
"""
import json
import os

import pytest

from gbox import turok_reader as tr

ROM_CANDIDATES = [
    os.environ.get("TUROK_ROM", ""),
    "/home/ehm_eckx/gbox-cache/34ab9ef38aebcaac/rom.z64",
    "/home/ehm_eckx/.hermes/cache/scratch/turok/rom.z64",
]


def _rom_path():
    for p in ROM_CANDIDATES:
        if p and os.path.exists(p):
            return p
    return None


def _synthetic_geometry():
    return {
        "info": {"morph_frame": 0},
        "nodes": [
            {
                "child_node_indices": [1],
                "part_indices": [0],
                "parts": [
                    {
                        "sections": [
                            {
                                "info": {"texset": 7, "matflags": 3, "mult_u": 8192, "mult_v": 8192},
                                "n_vertices": 3,
                                "vertices": [(1, 2, 3, 0, 0, 0), (4, 5, 6, 0, 16384, 0),
                                             (7, 8, 9, 0, 0, 16384)],
                                "vertex_tails": [],
                                "polystream": [0, 1, 2],
                                "triangles": [(0, 1, 2)],
                            }
                        ]
                    }
                ],
            },
            {"child_node_indices": [], "part_indices": [], "parts": []},
        ],
    }


def test_build_obj_emits_exact_geometry():
    obj = tr.build_obj(_synthetic_geometry(), "deadbeef")
    assert "# source rom sha256 deadbeef" in obj
    assert "g node_0_part_0_section_0" in obj
    assert "usemtl mat_tex7" in obj
    assert "v 1.0 2.0 3.0" in obj
    assert "v 4.0 5.0 6.0" in obj
    assert "v 7.0 8.0 9.0" in obj
    # one-based face indices, first section starts at 1
    assert "f 1/1 2/2 3/3" in obj
    # uv normalisation: tc 16384 / 32768 = 0.5, v flipped
    assert "vt 0.500000 1.000000" in obj
    assert "vt 0.000000 0.500000" in obj


def test_build_obj_offsets_indices_per_section():
    geom = _synthetic_geometry()
    second = json.loads(json.dumps(geom["nodes"][0]))
    geom["nodes"][1]["parts"] = second["parts"]
    obj = tr.build_obj(geom)
    # second copy of the section starts after the first section's 3 vertices
    assert "f 4/4 5/5 6/6" in obj


def test_no_texture_sentinel_is_none():
    sec = {"info": {"texset": 0xFFFFFFFF}}
    assert tr._texset_id(sec) is None
    assert tr._texset_id({"info": {"texset": 12}}) == 12


def test_build_mtl_lists_each_texset_once():
    mtl = tr.build_mtl(_synthetic_geometry())
    assert mtl.count("newmtl mat_tex7") == 1


@pytest.mark.skipif(_rom_path() is None, reason="owned NTUE Rev B ROM image not present")
def test_export_object_64_on_owned_build(tmp_path):
    from gbox import turok_inventory as ti

    rom = open(_rom_path(), "rb").read()
    import hashlib
    assert hashlib.sha256(rom).hexdigest() == tr.ROM_SHA256_Z64

    inv = ti.inventory(rom)
    summary = tr.export_object(rom, inv, 64, tmp_path)

    assert summary["object"] == 64
    assert summary["n_nodes"] >= 2
    assert summary["total_vertices"] > 0
    assert summary["total_triangles"] > 0
    assert (tmp_path / "object_64.obj").exists()
    assert (tmp_path / "object_64_summary.json").exists()

    for sec in summary["sections"]:
        assert sec["n_vertices"] >= 0
        if sec["n_triangles"]:
            assert sec["triangle_max_index"] < sec["n_vertices"], sec
        assert sec["texset"] is None or 0 <= sec["texset"] < inv["texture_sets"]["total"]

    text = (tmp_path / "object_64.obj").read_text()
    assert text.count("\nv ") == summary["total_vertices"]
    assert text.count("\nf ") == summary["total_triangles"]
