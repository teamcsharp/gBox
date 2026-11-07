"""The hide operation: a material collapses onto its own centroid and nothing else moves.

The synthetic case pins the arithmetic (only the named material's vertices change, the centroid is theirs, every triangle
index is identical). The second runs on a real RE4 Switch pack when one is extracted, because the material records there are
what the feature will actually be pointed at - and they are what corrected the first version of this module, whose
expectation that `Mat.start` was a vertex index the real data refused.
"""
import os

import numpy as np
import pytest

from gbox import re4hd_hide as H
from gbox.re4hd_models import BINError, Bin, Mat

PACK = os.path.join(os.path.expanduser("~/gBox_alt/switch/romfs"), "010099A00BC1E000", "bio4", "em", "pl00.udas")


def mat(index: int, triangles: int) -> Mat:
    return Mat(index=index, start=0, uv_set=0, material_id=index, dl_size=0, triangle_count=triangles,
               pairs=[(6, triangles * 3)], triangles=triangles)


def mesh_with_two_materials():
    pos = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0],      # material 0
                    [5.0, 5.0, 5.0], [6.0, 5.0, 5.0], [5.0, 6.0, 5.0]],    # material 1
                   dtype=np.float32)
    tris = np.array([[0, 1, 2], [3, 4, 5]], dtype=np.uint16)
    return Bin(header=b"", info={}, pos=pos, tris=tris, mats=[mat(0, 1), mat(1, 1)])


def test_material_triangle_spans_run_in_order():
    mesh = mesh_with_two_materials()
    assert H.material_triangle_span(mesh, 0) == (0, 1)
    assert H.material_triangle_span(mesh, 1) == (1, 2)


def test_only_the_named_material_collapses():
    mesh = mesh_with_two_materials()
    original = mesh.pos.copy()
    report = H.hide_materials(mesh, [1])
    assert report["vertices_changed"] == 3
    assert report["hidden"][0]["centroid"] == [5.3333, 5.3333, 5.0]
    assert np.array_equal(mesh.pos[:3], original[:3]), "material 0 must not move"
    assert np.allclose(mesh.pos[3:], [5.3333, 5.3333, 5.0]), "material 1 collapses onto its own centroid"


def test_topology_is_untouched():
    mesh = mesh_with_two_materials()
    before = mesh.tris.copy()
    report = H.hide_materials(mesh, [0, 1])
    assert report["triangles_unchanged"] is True
    assert np.array_equal(before, mesh.tris)
    assert report["n_tris"] == 2 and report["n_verts"] == 6


def test_a_bad_material_index_is_refused():
    mesh = mesh_with_two_materials()
    with pytest.raises(BINError):
        H.hide_materials(mesh, [2])
    with pytest.raises(BINError):
        H.hide_materials(mesh, [-1])


def test_a_mesh_without_materials_is_refused():
    mesh = mesh_with_two_materials()
    mesh.mats = []
    with pytest.raises(BINError):
        H.hide_materials(mesh, [0])


def test_a_mesh_without_triangles_is_refused():
    mesh = mesh_with_two_materials()
    mesh.tris = None
    with pytest.raises(BINError):
        H.hide_materials(mesh, [0])


@pytest.mark.skipif(not os.path.isfile(PACK), reason="the RE4 Switch RomFS is not extracted on this machine")
def test_a_real_pack_material_collapses_and_its_triangles_survive():
    from gbox import re4gc_inventory as INV
    from gbox import re4hd_models as R
    data = open(PACK, "rb").read()
    entry = next(e for e in INV.udas_entries(data, endian="<") if e["type"] == 0 and e["size"])
    blob = data[entry["offset"]:entry["offset"] + entry["size"]]
    slots = INV.dat_entries(blob, endian="<")
    ext, offset, size = next(s for s in slots if s[0].strip("\0").upper() == "BIN" and s[2])
    mesh = R.bin_read(blob[offset:offset + size])
    assert mesh.mats, "the real pack must carry material records"
    assert sum(m.triangle_count for m in mesh.mats) == len(mesh.tris), \
        "triangles are stored in material order (the property this operation relies on)"
    before = np.array(mesh.tris, copy=True)
    report = H.hide_materials(mesh, [len(mesh.mats) - 1])
    assert report["vertices_changed"] > 0
    assert report["triangles_unchanged"] is True
    assert np.array_equal(before, mesh.tris)
    again = R.bin_read(R.bin_write(mesh))
    assert np.array_equal(np.array(again.tris), before), "a write round-trip keeps every triangle"
