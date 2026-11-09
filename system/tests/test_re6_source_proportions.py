"""RE6's scale-exact replacement path: the RE5 'source proportions' fix, ported to the Xbox 360 .mod writer.

The fixture is synthetic (three bones, one primitive), so these run without the game: they exercise the real
quantisation transform, bind-pose repositioning, writer and decoder.
"""
import struct
from types import SimpleNamespace

import numpy as np
import pytest

from gbox import re6_models as M


def synthetic_mod():
    """Three bones (root at y=100, hip at 60, head at 120) and one rigid triangle in a 200-unit box."""
    D = np.eye(4)
    D[0, 0] = D[1, 1] = D[2, 2] = 200.0
    D[3, :3] = (-50.0, 0.0, -50.0)
    local = np.array([np.eye(4), np.eye(4), np.eye(4)], float)
    local[0][3, :3] = (0.0, 100.0, 0.0)
    local[1][3, :3] = (0.0, -40.0, 0.0)
    local[2][3, :3] = (0.0, 60.0, 0.0)
    parents = [255, 0, 1]
    world = np.zeros_like(local)
    for i, parent in enumerate(parents):
        world[i] = local[i] if parent == 255 else local[i] @ world[parent]
    bones = [[i, parents[i], 0, 0, 0.0, float(np.linalg.norm(local[i][3, :3])), *local[i][3, :3]] for i in range(3)]
    inv = np.array([D @ np.linalg.inv(world[i]) for i in range(3)])
    P = np.array([[0.0, 60.0, 0.0], [10.0, 60.0, 0.0], [0.0, 120.0, 0.0]])
    B = np.array([1, 1, 2])
    vb = M._rigid_vb(P, np.tile([0.0, 1.0, 0.0], (3, 1)), np.zeros((3, 2)), B, np.linalg.inv(D))
    centre = (P.min(0) + P.max(0)) / 2
    info = bytearray(0x40)
    info[0:48] = struct.pack(">12f", *centre, float(np.linalg.norm(P - centre, axis=1).max()),
                             *P.min(0), 0, *P.max(0), 0)
    prim = {"draw": 65015, "nverts": 3, "data0": (1 << 8) | 0xFF, "data1": (1 << 31) | (20 << 8) | (3 << 2),
            "vstart": 0, "vbo": 0, "fmt": M.RIGID, "istart": 0, "icount": 3, "ivo": 0, "skin_begin": 0, "nenv": 2,
            "mesh_id": 7, "vmin": 0, "vmax": 2, "rt": 0,
            "envelopes": [M._envelope(1, P[B == 1], world[1]), M._envelope(2, P[B == 2], world[2])]}
    stub = SimpleNamespace(bones=bones, local=local, inv=inv, remap=bytes(256), groups=bytes(32), ng=1,
                           mat_hashes=[0xABCD], prims=[prim], vb=vb, ib=np.array([0, 1, 2]), info=info,
                           tail=b"\0" * 4)
    return M.Mod(M.Mod.serialize(stub))


def synthetic_rig():
    return {"joints": np.array([[0.0, 60.0, 0.0], [0.0, 120.0, 0.0]]), "parent": [-1, 0],
            "roles": {"hip": 0, "head": 1},
            "prims": [{"pos": np.array([[0.0, 60.0, 0.0], [10.0, 60.0, 0.0], [0.0, 120.0, 0.0]]),
                       "nrm": np.tile([0.0, 1.0, 0.0], (3, 1)), "uv": np.zeros((3, 2)),
                       "tris": np.array([[0, 1, 2]]), "owner": np.array([0, 0, 1])}]}


def test_the_native_transform_is_a_uniform_scale_box():
    m = synthetic_mod()
    box = M.quantisation_box(m)
    assert box["scale"] == pytest.approx(200.0)
    assert np.allclose(box["lo"], [-50.0, 0.0, -50.0])
    assert np.allclose(box["hi"], [150.0, 200.0, 150.0])
    assert np.allclose(BOX(m), np.linalg.inv(box["transform"]))


def BOX(m):
    return np.linalg.inv(np.asarray(m.dequant()))


def test_reposition_bind_pose_places_anchors_and_keeps_the_root_and_rotations():
    m = synthetic_mod()
    root_before = m.world()[0].copy()
    local_before = m.local.copy()
    receipt = M.reposition_bind_pose(m, {1: (0.0, 50.0, 0.0), 2: (0.0, 110.0, 0.0)})
    W = m.world()
    assert np.allclose(W[1][3, :3], [0.0, 50.0, 0.0], atol=1e-4)
    assert np.allclose(W[2][3, :3], [0.0, 110.0, 0.0], atol=1e-4)
    assert np.allclose(W[0], root_before)
    assert np.allclose(m.local[:, :3, :3], local_before[:, :3, :3])
    assert receipt["root_unchanged"] and not receipt["animation_channels_changed"]
    assert m.bones[1][5] == pytest.approx(np.linalg.norm(m.local[1][3, :3]))
    assert m.bones[2][6:9] == pytest.approx(list(m.local[2][3, :3]))


def test_a_root_anchor_that_moves_is_refused():
    m = synthetic_mod()
    with pytest.raises(ValueError, match="root bone"):
        M.reposition_bind_pose(m, {0: (0.0, 50.0, 0.0)})


def test_source_proportions_scale_uniformly_and_keep_ratios():
    m = synthetic_mod()
    rig = synthetic_rig()
    prims, fit = M.fit_source_proportions(m, rig, {"hip": 1, "head": 2}, height=100.0)
    assert fit["source_height"] == pytest.approx(60.0)
    assert fit["fitted_height"] == pytest.approx(100.0, abs=1e-3)
    assert fit["uniform_scale"] == pytest.approx(100.0 / 60.0)
    assert fit["proportion_error"] < 1e-4
    assert not fit["height_clamped"]
    P = prims[0]["pos"]
    # the pelvis->head span is the whole model: a uniform fit keeps the donor's shape exactly
    assert np.allclose(P[2] - P[0], (rig["joints"][1] - rig["joints"][0]) * fit["uniform_scale"], atol=1e-4)
    assert np.linalg.norm(P[1] - P[0]) == pytest.approx(np.linalg.norm(rig["prims"][0]["pos"][1]
                                                                       - rig["prims"][0]["pos"][0])
                                                        * fit["uniform_scale"], rel=1e-5)
    W = m.world()
    assert np.allclose(W[1][3, :3], P[0], atol=1e-4)      # the hip bone sits on the fitted hip
    assert np.allclose(W[2][3, :3], P[2], atol=1e-4)      # the head bone sits on the fitted head
    assert np.allclose(W[0], np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 100, 0, 1]], float))


def test_the_fitted_surface_stays_inside_the_native_quantisation_box():
    m = synthetic_mod()
    prims, fit = M.fit_source_proportions(m, synthetic_rig(), {"hip": 1, "head": 2}, height=300.0)
    inside = np.c_[np.concatenate([p["pos"] for p in prims]), np.ones(3)] @ BOX(m)
    assert inside[:, :3].min() >= -1e-6 and inside[:, :3].max() <= 1 + 1e-6
    assert fit["height_clamped"]           # 300 cm does not fit a 200-unit box: reduced uniformly
    assert fit["fitted_height"] <= 200.0 + 1e-6


def test_write_body_with_the_native_transform_round_trips_the_fitted_surface():
    m = synthetic_mod()
    box = M.quantisation_box(m)
    prims, fit = M.fit_source_proportions(m, synthetic_rig(), {"hip": 1, "head": 2}, height=100.0)
    data = M.write_body(m, prims, material=0, mesh_id=7, draw=65015, dequant=box["transform"])
    checked = M.Mod(data)
    assert np.allclose(checked.dequant(), box["transform"], atol=1e-5)
    decoded = np.concatenate([g["pos"] for g in (checked.decode(p) for p in checked.prims) if g])
    assert np.allclose(decoded, prims[0]["pos"], atol=0.02)
    assert np.allclose(checked.world()[1][3, :3], m.world()[1][3, :3], atol=1e-4)
    q = np.c_[decoded, np.ones(len(decoded))] @ np.linalg.inv(checked.dequant())
    assert q[:, :3].min() >= -1e-6 and q[:, :3].max() <= 1 + 1e-6


def test_an_unmapped_skeleton_is_refused():
    m = synthetic_mod()
    with pytest.raises(ValueError, match="no role maps"):
        M.fit_source_proportions(m, synthetic_rig(), {"hip": 0}, height=100.0)


def test_a_skeleton_whose_bones_are_not_parents_first_is_refused():
    m = synthetic_mod()
    m.bones[0][1] = 2                                       # root now claims a later bone as its parent
    with pytest.raises(ValueError, match="parents-first"):
        M.reposition_bind_pose(m, {1: (0.0, 50.0, 0.0)})
