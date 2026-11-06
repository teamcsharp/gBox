"""re4gc_zombies.sanitize_prims: a limb collapsed onto the root must not poison the packer with NaN."""
import json

import numpy as np

from gbox import re4gc_zombies


def test_nan_positions_become_zero_and_stay_finite():
    prims = [{"pos": np.array([[np.nan, 1.0, 2.0], [3.0, np.inf, 4.0]]),
              "nrm": np.array([[0.0, 1.0, 0.0], [0.0, 1.0, 0.0]])}]
    out = re4gc_zombies.sanitize_prims(prims)[0]
    assert np.isfinite(out["pos"]).all()
    assert np.isfinite(out["nrm"]).all()
    json.dumps(out["pos"].tolist())          # what the packer would do next must not raise


def test_a_zero_length_normal_becomes_up():
    prims = [{"pos": np.zeros((2, 3)), "nrm": np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])}]
    out = re4gc_zombies.sanitize_prims(prims)[0]
    assert np.allclose(out["nrm"][0], (0.0, 1.0, 0.0))
    assert np.allclose(out["nrm"][1], (1.0, 0.0, 0.0))


def test_prims_without_normals_are_left_alone():
    prims = [{"pos": np.zeros((1, 3))}]
    out = re4gc_zombies.sanitize_prims(prims)[0]
    assert "nrm" not in out
