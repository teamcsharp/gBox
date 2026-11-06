"""The cross-model fitting: roles from a GLB, paired onto an MTF skeleton."""

import pytest

from gbox import mtf_fit


def _gltf(joints):
    """A minimal glTF whose nodes place each joint at a translation, chained through one root."""
    nodes = [{"name": "root", "translation": [0.0, 0.0, 0.0], "children": [i + 1 for i in range(len(joints))]}]
    for x, y, z in joints:
        nodes.append({"translation": [x, y, z]})
    return {"nodes": nodes, "skins": [{"joints": list(range(1, len(joints) + 1))}], "scenes": [{"nodes": [0]}]}


def test_roles_come_from_where_the_joints_are():
    # root at the feet, hips in the middle, a head up top, and hands out to either side
    joints = [(0.0, 0.0, 0.0), (0.0, 90.0, 0.0), (0.0, 180.0, 0.0), (-80.0, 150.0, 0.0), (80.0, 150.0, 0.0)]
    roles = mtf_fit.glb_roles(_gltf(joints))
    assert roles["head"] == 3                      # the node at y 180
    assert roles["lowest"] == 1                    # the node at y 0
    assert roles["left_hand"] == 4                 # the node at x -80
    assert roles["right_hand"] == 5
    assert abs(roles["height"] - 180.0) < 0.001
    assert abs(roles["span"] - 160.0) < 0.001


def test_a_glb_without_a_skin_is_refused():
    with pytest.raises(mtf_fit.FitError):
        mtf_fit.glb_roles({"nodes": [{}], "skins": []})


def test_roles_pair_across_models_and_the_rest_land_on_the_nearest_bone():
    """Measured: Sonic's 62 joints map onto Chris's 130 bones with head->head and left hand->left hand."""
    joints = [(0.0, 0.0, 0.0), (0.0, 90.0, 0.0), (0.0, 180.0, 0.0), (-80.0, 150.0, 0.0), (80.0, 150.0, 0.0)]
    source = mtf_fit.glb_roles(_gltf(joints))
    target_roles = {"head": 26, "left_hand": 64, "right_hand": 84, "lowest": 121, "height": 180.69}
    target_points = [(26, 0.0, 185.1, 3.4), (64, -88.1, 152.4, 0.0), (84, 88.1, 152.4, 0.0),
                     (121, 9.2, 4.4, 0.0), (0, 0.0, 114.0, 0.0)]
    mapping = mtf_fit.match(source, target_roles, target_points)
    assert mapping[source["head"]] == 26
    assert mapping[source["left_hand"]] == 64
    assert mapping[source["right_hand"]] == 84
    assert all(0 <= bone <= 121 for bone in mapping.values())