"""The coherent morph: the bone decides where a vertex may land, the surface decides the shape.

The two failed extremes are pinned here as behaviour, not as prose: a vertex must move *towards* the donor's surface (so the shape
changes, unlike bone transfer) and it must land near its own body band's part of the donor (so the arm does not land on the leg,
unlike the global surface morph). A mesh without bone weights still works - it falls back to a global nearest surface - because a
probe should not crash on an unusual slot.
"""
import os

import numpy as np
import pytest

from gbox import re4hd_coherent as C
from gbox.re4hd_models import BINError, Bin, Mat

PACK = os.path.join(os.path.expanduser("~/gBox_alt/switch/romfs"), "010099A00BC1E000", "bio4", "em", "em16.udas")


def mesh(points, bones, weights_records, weight_idx, tris, mats=None):
    return Bin(header=b"", info={}, pos=np.asarray(points, np.float32), tris=np.asarray(tris, np.uint16),
               bones=bones, weights=weights_records, weight_idx=np.asarray(weight_idx, np.uint16).reshape(-1, 1),
               mats=mats or [Mat(index=0, start=0, uv_set=0, material_id=0, dl_size=0, triangle_count=len(tris),
                                 pairs=[(6, len(tris) * 3)], triangles=len(tris))])


def donor_two_parts():
    """A donor shaped like two blocks far apart: a 'head' block at z=100 and a 'legs' block at z=0."""
    points = [[0, 0, 100], [10, 0, 100], [0, 10, 100],
              [100, 0, 0], [110, 0, 0], [100, 10, 0]]
    bones = [{"id": 0, "parent": 0xFF, "x": 0, "y": 0, "z": 0},
             {"id": 1, "parent": 0, "x": 0, "y": 0, "z": 100}]
    weights = [(0,), (1,)]
    # the z=100 block is weighted to bone 1 and the z=0 block to bone 0: each block belongs to its own bone, which is what
    # the band logic is entitled to assume (the first version of this fixture weighted both to the root and the test read
    # that as a code bug)
    return mesh(points, bones, weights, [1, 1, 1, 0, 0, 0], [[0, 1, 2], [3, 4, 5]])


def template_with_bands():
    """Two vertices, one in each band, that start between the donor's two blocks."""
    points = [[50, 0, 50], [50, 0, 60]]
    bones = [{"id": 0, "parent": 0xFF, "x": 0, "y": 0, "z": 0},
             {"id": 1, "parent": 0, "x": 0, "y": 0, "z": 100}]
    weights = [(0,), (1,)]
    return mesh(points, bones, weights, [0, 1], [[0, 1, 0]], mats=None)


def test_a_vertex_lands_on_its_own_band_not_the_nearest_surface_anywhere():
    tmpl, donor = template_with_bands(), donor_two_parts()
    moved = C.coherent_surface(tmpl, donor, bands=2, align=False)
    # vertex 0 is band 0 (the legs block at z=0), vertex 1 is band 1 (the head block at z=100)
    assert moved[0][2] < 10, f"the band-0 vertex must land on the low block, got z={moved[0][2]}"
    assert moved[1][2] > 90, f"the band-1 vertex must land on the high block, got z={moved[1][2]}"


def test_the_global_surface_morph_would_have_put_both_on_the_same_block():
    """The contrast that motivates the module: ignoring bones, both vertices choose the same nearest block."""
    tmpl, donor = template_with_bands(), donor_two_parts()
    from gbox.re4hd_models import _closest_on_triangles
    tri = np.asarray(donor.tris, np.int64)
    moved, _ = _closest_on_triangles(np.asarray(tmpl.pos, np.float64),
                                     np.asarray(donor.pos, np.float64)[tri[:, 0]],
                                     np.asarray(donor.pos, np.float64)[tri[:, 1]],
                                     np.asarray(donor.pos, np.float64)[tri[:, 2]])
    assert abs(moved[0][2] - moved[1][2]) < 20, "without bones the two vertices end up together"


def test_a_mesh_without_weights_falls_back_to_the_global_surface():
    tmpl, donor = template_with_bands(), donor_two_parts()
    tmpl.weights = None
    moved = C.coherent_surface(tmpl, donor, bands=2, align=False)
    assert np.isfinite(moved).all()


def test_a_donor_without_geometry_is_refused():
    empty = Bin(header=b"", info={}, pos=None, tris=None)
    with pytest.raises(BINError):
        C.coherent_surface(template_with_bands(), empty)


@pytest.mark.skipif(not os.path.isfile(PACK), reason="the RE4 Switch RomFS is not extracted on this machine")
def test_a_real_pack_survives_the_coherent_morph_and_keeps_its_topology():
    """The writer validates what it emits, so this is the test that matters for a build: a real slot, morphed and re-read."""
    data = open(PACK, "rb").read()
    from gbox import re4gc_inventory as INV
    from gbox import re4hd_models as R
    slot = INV.bin_slots(data, endian="<")[0]
    mesh = R.bin_read(data[slot["offset"]:slot["offset"] + slot["size"]])
    moved = C.coherent_surface(mesh, mesh, bands=6, align=False)
    assert moved.shape == np.asarray(mesh.pos).shape
    assert np.isfinite(moved).all()
    assert np.allclose(moved, np.asarray(mesh.pos, np.float64), atol=1.0), \
        "morphing a mesh onto itself must leave it essentially where it was"
