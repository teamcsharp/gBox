"""rig_roles.derive: joints found by geometry, on a synthetic humanoid."""
import math

from gbox import rig_roles

# A stick figure: spine up the middle, arms out at the shoulders, legs down from the hip.
# indices: 0 hip, 1 spine, 2 chest, 3 neck, 4 head, 5 l_upper, 6 l_fore, 7 l_hand,
#          8 r_upper, 9 r_fore, 10 r_hand, 11 l_thigh, 12 l_shin, 13 l_foot, 14 r_thigh, 15 r_shin, 16 r_foot
JOINTS = [
    (0.0, 1.00, 0.0),      # 0 hip
    (0.0, 1.20, 0.0),      # 1 spine
    (0.0, 1.40, 0.0),      # 2 chest
    (0.0, 1.55, 0.0),      # 3 neck
    (0.0, 1.75, 0.0),      # 4 head
    (0.25, 1.40, 0.0),     # 5 left upper arm (character's left = +X)
    (0.55, 1.40, 0.0),     # 6 left forearm
    (0.80, 1.40, 0.0),     # 7 left hand
    (-0.25, 1.40, 0.0),    # 8 right upper arm
    (-0.55, 1.40, 0.0),    # 9 right forearm
    (-0.80, 1.40, 0.0),    # 10 right hand
    (0.12, 0.55, 0.0),     # 11 left thigh
    (0.12, 0.10, 0.0),     # 12 left shin
    (0.12, 0.00, 0.10),    # 13 left foot
    (-0.12, 0.55, 0.0),    # 14 right thigh
    (-0.12, 0.10, 0.0),    # 15 right shin
    (-0.12, 0.00, 0.10),   # 16 right foot
]
PARENT = [-1, 0, 1, 2, 3, 2, 5, 6, 2, 8, 9, 0, 11, 12, 0, 14, 15]


def test_roles_on_a_plain_humanoid():
    roles = rig_roles.derive(JOINTS, PARENT)
    assert roles["head"] == 4
    assert roles["neck"] == 3
    assert roles["chest"] == 2
    assert roles["hip"] == 0
    assert (roles["l_upper"], roles["l_fore"], roles["l_hand"]) == (5, 6, 7)
    assert (roles["r_upper"], roles["r_fore"], roles["r_hand"]) == (8, 9, 10)
    assert (roles["l_thigh"], roles["l_shin"], roles["l_foot"]) == (11, 12, 13)
    assert (roles["r_thigh"], roles["r_shin"], roles["r_foot"]) == (14, 15, 16)


def test_left_and_right_follow_the_stated_left_sign():
    # Same joints, two conventions: with left = +X the character's left arm is node 5; read as if left were -X, the arm at
    # -X is the left one, which in this mirrored list is still node 5 - and the arm at +X (node 8) becomes the right.
    roles = rig_roles.derive(JOINTS, PARENT)
    assert roles["l_upper"] == 5 and roles["r_upper"] == 8
    folded = rig_roles.derive(JOINTS, PARENT, left_sign=-1.0)
    assert folded["l_upper"] == 8 and folded["r_upper"] == 5


def test_empty_and_shallow_rigs_do_not_raise():
    assert rig_roles.derive([], []) == {}
    roles = rig_roles.derive([(0.0, 0.0, 0.0), (0.0, 1.0, 0.0)], [-1, 0])
    assert roles["head"] == 1 and "l_hand" not in roles


def test_named_maps_indices_to_names():
    names = [f"b{i:03d}" for i in range(len(JOINTS))]
    roles = rig_roles.named(JOINTS, PARENT, names)
    assert roles["head"] == "b004" and roles["l_hand"] == "b007"
