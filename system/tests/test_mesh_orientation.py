"""Donor surfaces reach the RE writers facing outward, with normals that agree (gbox.mesh_orientation).

The fixtures are closed meshes whose outside is known by construction. The inside-out variants are the ones the
library's exporters write (measured 2026-11-10): FF7 / Stranglehold turn the winding and the normals together,
Smash Melee / SoulCalibur II turn the winding only, and a mirrored node or joint turns the winding of its own part.
"""
from __future__ import annotations

import numpy as np
import pytest

from gbox import mesh_orientation as O
from gbox import mtf_materials
from gbox import re6_switch_models as S


def cube(centre=(0., 0., 0.), size=1.):
    """(8 corners, 12 triangles wound counter-clockwise seen from outside, outward radial normals)."""
    centre = np.asarray(centre, float)
    points = np.array([(x, y, z) for x in (-.5, .5) for y in (-.5, .5) for z in (-.5, .5)]) * size + centre
    faces = []
    for axis in range(3):
        for side in (-.5, .5):
            ids = [i for i, p in enumerate(points - centre) if np.isclose(p[axis], side * size)]
            ring = sorted(ids, key=lambda i: np.arctan2(*np.delete(points[i] - centre, axis)[::-1]))
            for tri in ((ring[0], ring[1], ring[2]), (ring[0], ring[2], ring[3])):
                a, b, c = points[list(tri)]
                outward = np.zeros(3)
                outward[axis] = side
                if np.cross(b - a, c - a) @ outward < 0:
                    tri = (tri[0], tri[2], tri[1])
                faces.append(tri)
    normals = (points - centre) / np.linalg.norm(points - centre, axis=1)[:, None]
    return points, np.array(faces, np.int64), normals


def outward_share(points, faces):
    """Share of triangles facing away from their own cube's centre (each cube = 12 consecutive faces)."""
    points, faces = np.asarray(points, float), np.asarray(faces, int)
    good = 0
    for start in range(0, len(faces), 12):
        part = faces[start:start + 12]
        centre = points[np.unique(part)].mean(0)
        a, b, c = points[part[:, 0]], points[part[:, 1]], points[part[:, 2]]
        good += int((np.einsum("ij,ij->i", np.cross(b - a, c - a), (a + b + c) / 3 - centre) > 0).sum())
    return good / len(faces)


def agree(points, faces, normals):
    points, faces, normals = np.asarray(points, float), np.asarray(faces, int), np.asarray(normals, float)
    a, b, c = points[faces[:, 0]], points[faces[:, 1]], points[faces[:, 2]]
    return float((np.einsum("ij,ij->i", normals[faces].sum(1), np.cross(b - a, c - a)) > 0).mean())


# ------------------------------------------------------------------------------------------- the decision itself

def test_an_outward_closed_mesh_is_kept():
    points, faces, normals = cube()
    turned, new_normals, report = O.orient(points, faces, normals)
    assert report["before"]["verdict"] == "outward" and not report["winding_turned"] and not report["normals_negated"]
    assert np.array_equal(turned, faces) and np.allclose(new_normals, normals)


def test_an_inside_out_mesh_whose_normals_follow_its_winding_is_turned_and_its_normals_negated():
    """FF7 / Stranglehold: winding and stored normals both inward, so a winding-vs-normals check sees nothing."""
    points, faces, normals = cube()
    inside_out, inward = faces[:, [0, 2, 1]], -normals
    assert agree(points, inside_out, inward) == 1.0          # consistent with each other: the old checks pass it
    turned, new_normals, report = O.orient(points, inside_out, inward)
    assert report["before"]["verdict"] == "inside_out" and report["winding_turned"] and report["normals_negated"]
    assert outward_share(points, turned) == 1.0 and agree(points, turned, new_normals) == 1.0
    assert np.allclose(new_normals, normals)


def test_an_inside_out_winding_with_outward_normals_is_turned_and_its_normals_kept():
    """Smash Melee / SoulCalibur II ('cw' in the RE5 survey): only the winding is inside-out."""
    points, faces, normals = cube()
    turned, new_normals, report = O.orient(points, faces[:, [0, 2, 1]], normals)
    assert report["winding_turned"] and not report["normals_negated"]
    assert outward_share(points, turned) == 1.0 and np.allclose(new_normals, normals)


def test_outward_winding_with_inward_normals_negates_only_the_normals():
    points, faces, normals = cube()
    turned, new_normals, report = O.orient(points, faces, -normals)
    assert not report["winding_turned"] and report["normals_negated"]
    assert np.array_equal(turned, faces) and np.allclose(new_normals, normals)


def test_nan_normals_stay_nan_for_the_callers_face_normal_fallback():
    points, faces, normals = cube()
    normals = -normals
    normals[0] = np.nan
    _, new_normals, report = O.orient(points, faces[:, [0, 2, 1]], normals)
    assert report["winding_turned"] and report["normals_negated"] and np.isnan(new_normals[0]).all()


def test_an_open_card_is_left_as_it_came():
    points = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [1., 1., 0.]])
    faces = np.array([[0, 2, 1], [1, 2, 3]])                 # facing -z; nothing says which side is out
    turned, normals, report = O.orient(points, faces, np.tile([0., 0., -1.], (4, 1)))
    assert report["before"]["verdict"] == "unclear" and np.array_equal(turned, faces)
    assert not report["normals_negated"] and np.allclose(normals, [0., 0., -1.])


def test_an_inward_cavity_on_an_outward_body_is_not_turned_alone():
    """A mouth or a coat lining faces inward on a correct model: the decision is the whole model's, never a part's."""
    body = cube(size=4.)
    cavity = cube(centre=(0., 1., 1.), size=1.)
    points = np.concatenate([body[0], cavity[0]])
    faces = np.concatenate([body[1], cavity[1][:, [0, 2, 1]] + 8])
    normals = np.concatenate([body[2], -cavity[2]])
    turned, new_normals, report = O.orient(points, faces, normals)
    assert report["before"]["verdict"] == "outward" and not report["winding_turned"]
    assert np.array_equal(turned, faces) and np.allclose(new_normals, normals)


def test_the_whole_model_decides_even_when_a_part_disagrees():
    body = cube(size=4.)
    lining = cube(centre=(0., 1., 1.), size=1.)                # this part is outward on an inside-out model
    points = np.concatenate([body[0], lining[0]])
    faces = np.concatenate([body[1][:, [0, 2, 1]], lining[1] + 8])
    turned, _, report = O.orient(points, faces)
    assert report["winding_turned"]
    assert outward_share(points[:8], turned[:12]) == 1.0      # the body now faces out
    assert outward_share(points, turned) == 0.5               # the lining was turned with it (one convention)


def test_winding_normals_point_out_of_an_outward_mesh():
    points, faces, _ = cube()
    normals = O.winding_normals(points, faces)
    assert np.all(np.einsum("ij,ij->i", normals, points) > 0)


# ------------------------------------------------------------------------- through mtf_materials.source_mesh

def _gltf(monkeypatch, primitives, nodes, world, skins=None):
    """characters._load stub: `primitives` is a list of {name: array}; accessors are numbered in order."""
    arrays, prims = [], []
    for prim in primitives:
        attributes = {}
        for name in ("POSITION", "NORMAL", "JOINTS_0", "WEIGHTS_0"):
            if name in prim:
                attributes[name] = len(arrays)
                arrays.append(prim[name])
        arrays.append(np.asarray(prim["indices"], np.uint16).reshape(-1))
        prims.append({"attributes": attributes, "indices": len(arrays) - 1})
    gl = {"nodes": nodes, "meshes": [{"primitives": prims}], **({"skins": skins} if skins else {})}
    loaded = (gl, lambda i: arrays[i], lambda _i: np.full((2, 2, 4), 255, np.uint8), world)
    monkeypatch.setattr(mtf_materials.characters, "_load", lambda _path: loaded)


def _mesh(path):
    path.write_bytes(b"fixture read through the stubbed glTF loader")
    vertices, triangles, _atlas, report = mtf_materials.source_mesh(path, atlas_size=(32, 32))
    points = np.array([v["position"] for v in vertices])
    normals = np.array([v["normal"] for v in vertices])
    return points, np.array(triangles), normals, report


def test_source_mesh_hands_an_inside_out_donor_over_facing_outward(tmp_path, monkeypatch):
    """The FF7 Aerith case: inward winding with face normals of that winding (what gbox.ff7_models writes)."""
    points, faces, normals = cube()
    _gltf(monkeypatch, [{"POSITION": points, "NORMAL": -normals, "indices": faces[:, [0, 2, 1]]}],
          [{"mesh": 0}], [np.eye(4)])
    out_points, out_faces, out_normals, report = _mesh(tmp_path / "donor.glb")
    assert report["orientation"] == "turned" and report["winding_turned"] and report["normals_negated"]
    assert outward_share(out_points, out_faces) == 1.0 and agree(out_points, out_faces, out_normals) == 1.0
    assert np.all(np.einsum("ij,ij->i", out_normals, out_points) > 0)


def test_source_mesh_turns_a_clockwise_donor_and_keeps_its_normals(tmp_path, monkeypatch):
    points, faces, normals = cube()
    _gltf(monkeypatch, [{"POSITION": points, "NORMAL": normals, "indices": faces[:, [0, 2, 1]]}],
          [{"mesh": 0}], [np.eye(4)])
    out_points, out_faces, out_normals, report = _mesh(tmp_path / "donor.glb")
    assert report["winding_turned"] and not report["normals_negated"]
    assert outward_share(out_points, out_faces) == 1.0 and agree(out_points, out_faces, out_normals) == 1.0


def test_source_mesh_without_normals_gets_outward_face_normals(tmp_path, monkeypatch):
    """The Smash Fighting Wire Frames carry no NORMAL: their face normals used to follow the inward winding."""
    points, faces, _ = cube()
    _gltf(monkeypatch, [{"POSITION": points, "indices": faces[:, [0, 2, 1]]}], [{"mesh": 0}], [np.eye(4)])
    out_points, out_faces, out_normals, report = _mesh(tmp_path / "donor.glb")
    assert report["winding_turned"] and report["face_normal_fallback_corners"] == 36
    assert outward_share(out_points, out_faces) == 1.0 and agree(out_points, out_faces, out_normals) == 1.0


def test_source_mesh_keeps_a_mirrored_node_outward(tmp_path, monkeypatch):
    """glTF: a node with a negative determinant draws clockwise; its stored order must be turned back."""
    points, faces, normals = cube()
    mirror = np.diag([-1., 1., 1., 1.])
    mirror[:3, 3] = (5., 0., 0.)
    _gltf(monkeypatch, [{"POSITION": points, "NORMAL": normals, "indices": faces}], [{"mesh": 0}], [mirror])
    out_points, out_faces, out_normals, report = _mesh(tmp_path / "donor.glb")
    assert report["mirrored_faces_turned"] == 12 and not report["winding_turned"]
    assert outward_share(out_points, out_faces) == 1.0 and agree(out_points, out_faces, out_normals) == 1.0


def test_source_mesh_turns_back_a_part_on_a_mirroring_joint(tmp_path, monkeypatch):
    """Two cubes in one skinned primitive; the second rides a joint whose pose mirrors x (negative determinant).

    Half the model inside-out is no whole-model verdict, so only the per-vertex determinant can repair it."""
    left, faces, normals = cube()
    points = np.concatenate([left, left])
    joints = np.zeros((16, 4), np.uint8)
    joints[8:, 0] = 1
    weights = np.zeros((16, 4))
    weights[:, 0] = 1.
    mirrored = np.diag([-1., 1., 1., 1.])
    mirrored[:3, 3] = (4., 0., 0.)
    _gltf(monkeypatch, [{"POSITION": points, "NORMAL": np.concatenate([normals, normals]), "JOINTS_0": joints,
                         "WEIGHTS_0": weights, "indices": np.concatenate([faces, faces + 8])}],
          [{"mesh": 0, "skin": 0}, {}, {}], [np.eye(4), np.eye(4), mirrored], skins=[{"joints": [1, 2]}])
    out_points, out_faces, out_normals, report = _mesh(tmp_path / "donor.glb")
    assert report["mirrored_faces_turned"] == 12
    assert outward_share(out_points, out_faces) == 1.0 and agree(out_points, out_faces, out_normals) == 1.0


# ---------------------------------------------------------------------------- the RE6 untextured loader

def _re6(monkeypatch, gl, arrays, world):
    from gbox import characters
    monkeypatch.setattr(characters, "_load", lambda _path: (gl, lambda i: arrays[i], None, world))


def test_re6_source_geometry_turns_an_inside_out_donor_and_makes_its_missing_normals(tmp_path, monkeypatch):
    points, faces, _ = cube()
    gl = {"nodes": [{"mesh": 0}], "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}]}
    _re6(monkeypatch, gl, [points, faces[:, [0, 2, 1]].reshape(-1).astype(np.uint16)], [np.eye(4)])
    vertices, triangles = S._source_geometry(tmp_path / "donor.glb")
    out_points = np.array([v["position"] for v in vertices])
    out_normals = np.array([v["normal"] for v in vertices])
    assert outward_share(out_points, triangles) == 1.0
    assert np.all(np.einsum("ij,ij->i", out_normals, out_points) > 0)     # never a constant +Y


def test_re6_source_geometry_turns_back_a_mirrored_rigid_node(tmp_path, monkeypatch):
    points, faces, normals = cube()
    gl = {"nodes": [{"mesh": 0}], "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1},
                                                               "indices": 2}]}]}
    mirror = np.diag([-1., 1., 1., 1.])
    _re6(monkeypatch, gl, [points, normals, faces.reshape(-1).astype(np.uint16)], [mirror])
    vertices, triangles = S._source_geometry(tmp_path / "donor.glb")
    out_points = np.array([v["position"] for v in vertices])
    out_normals = np.array([v["normal"] for v in vertices])
    assert outward_share(out_points, triangles) == 1.0 and agree(out_points, triangles, out_normals) == 1.0
    assert np.all(np.einsum("ij,ij->i", out_normals, out_points) > 0)


@pytest.mark.parametrize("share", [0.0, 0.27, 0.34])
def test_the_measured_inside_out_exporters_fall_under_the_threshold(share):
    """The library survey's bands (inside-out exporters <= 0.34, correct donors >= 0.61) sit on either side."""
    assert share <= O.INSIDE_OUT_SHARE < O.OUTWARD_SHARE <= 0.61
