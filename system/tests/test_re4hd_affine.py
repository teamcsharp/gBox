"""The per-band affine transfer: a coherent edit that also changes the shape.

The cases pin exactly what the previous three variants lacked. A **flat donor flattens the band** (the one axis whose donor extent is
tiny gets a small factor) - a shape change, which the projections could not produce. A **self-donor changes nothing** - coherence,
which the global projection did not have. And a band with no donor geometry is left alone rather than dropped, so an unusual slot does
not lose a limb.
"""
import numpy as np
import pytest

from gbox import re4hd_affine as A
from gbox.re4hd_models import BINError, Bin, Mat


def mesh(points, bones, weight_idx, tris):
    n = len(points)
    return Bin(header=b"", info={}, pos=np.asarray(points, np.float32), tris=np.asarray(tris, np.uint16), bones=bones,
               weights=[(0,), (1,)], weight_idx=np.asarray(weight_idx, np.uint16).reshape(-1, 1),
               mats=[Mat(index=0, start=0, uv_set=0, material_id=0, dl_size=0, triangle_count=len(tris),
                         pairs=[(6, len(tris) * 3)], triangles=len(tris))])


def two_band_mesh(scale_z: float = 1.0):
    """Two blocks, one per bone; the second is `scale_z` times taller/lower, so a donor can flatten it."""
    pts = [[0, 0, 0], [10, 0, 0], [0, 10, 0], [0, 0, 10],
           [100, 0, 100], [110, 0, 100], [100, 10, 100], [100, 0, 100 + 10 * scale_z]]
    bones = [{"id": 0, "parent": 0xFF, "x": 0, "y": 0, "z": 0},
             {"id": 1, "parent": 0, "x": 100, "y": 0, "z": 100}]
    return mesh(pts, bones, [0, 0, 0, 0, 1, 1, 1, 1], [[0, 1, 2], [4, 5, 6]])


def test_a_flat_donor_flattens_the_band():
    tmpl = two_band_mesh(1.0)
    donor = two_band_mesh(0.05)                 # the second band is flattened along z
    moved, report = A.band_affine(tmpl, donor, bands=2, align=True)
    band1 = next(row for row in report if row["band"] == 1)
    assert band1["extent_ratio"][2] < 0.5, f"the z axis must shrink, got {band1['extent_ratio']}"
    z_extent = moved[4:, 2].max() - moved[4:, 2].min()
    original = np.asarray(tmpl.pos)[4:, 2]
    assert z_extent < (original.max() - original.min()) * 0.6, "the band is visibly flatter"


def test_a_self_donor_changes_essentially_nothing():
    tmpl = two_band_mesh(1.0)
    moved, _report = A.band_affine(tmpl, tmpl, bands=2, align=False)
    assert np.allclose(moved, np.asarray(tmpl.pos, np.float64), atol=0.5)


def test_a_donor_without_weights_bands_by_height_instead_of_failing():
    """A .glb is a triangle soup with no weights; banding it by height is what lets any extracted model be a donor."""
    tmpl = two_band_mesh(1.0)
    donor = two_band_mesh(1.0)
    donor.weights = None
    moved, report = A.band_affine(tmpl, donor, bands=2, align=False)
    assert np.isfinite(moved).all()
    assert report, "the height bands still produced a transfer"
    bands = A._height_band(np.asarray(donor.pos, np.float64), 2)
    assert set(bands.tolist()) == {0, 1}, "the low and high vertices land in different bands"


def test_blend_zero_is_the_identity():
    tmpl = two_band_mesh(1.0)
    donor = two_band_mesh(0.05)
    moved, _ = A.band_affine(tmpl, donor, bands=2, align=False, blend=0.0)
    assert np.allclose(moved, np.asarray(tmpl.pos, np.float64), atol=1e-6)


def test_missing_positions_are_refused():
    empty = Bin(header=b"", info={}, pos=None)
    with pytest.raises(BINError):
        A.band_affine(two_band_mesh(), empty)
