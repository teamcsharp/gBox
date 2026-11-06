"""rig_roles.derive: roles found by geometry, on a synthetic humanoid and on a head-first spine."""
from gbox import rig_roles

# A stick figure: arms out at the shoulders, legs down from the hip.
# 0 hip, 1 spine, 2 chest, 3 neck, 4 head, 5 l_upper, 6 l_fore, 7 l_hand,
# 8 r_upper, 9 r_fore, 10 r_hand, 11 l_thigh, 12 l_shin, 13 l_foot, 14 r_thigh, 15 r_shin, 16 r_foot
JOINTS = [
    (0.0, 1.00, 0.0), (0.0, 1.20, 0.0), (0.0, 1.40, 0.0), (0.0, 1.55, 0.0), (0.0, 1.75, 0.0),
    (0.25, 1.40, 0.0), (0.55, 1.40, 0.0), (0.80, 1.40, 0.0),
    (-0.25, 1.40, 0.0), (-0.55, 1.40, 0.0), (-0.80, 1.40, 0.0),
    (0.12, 0.55, 0.0), (0.12, 0.10, 0.0), (0.12, 0.00, 0.10),
    (-0.12, 0.55, 0.0), (-0.12, 0.10, 0.0), (-0.12, 0.00, 0.10),
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


def test_a_spine_that_runs_head_first_still_resolves():
    """Sonic's shape: the highest joints are ears, the head has children, the chest is BELOW the head, and the arms hang
    from the chest while the legs hang from the hip further down the same chain."""
    joints = [
        (0.00, 0.00, 0.0),      # 0 root at the origin (not the hip)
        (0.00, 5.00, 0.0),      # 1 spine
        (0.00, 5.24, 0.0),      # 2 neck-ish
        (0.00, 5.09, 0.0),      # 3
        (0.00, 4.62, 0.0),      # 4 hip
        (0.28, 4.69, 0.0),      # 5 left leg root
        (0.59, 3.28, 0.0),      # 6 left knee
        (0.93, 0.34, 0.0),      # 7 left foot
        (-0.28, 4.69, 0.0),     # 8 right leg root
        (-0.59, 3.28, 0.0),     # 9 right knee
        (-0.93, 0.34, 0.0),     # 10 right foot
        (0.00, 6.63, 0.0),      # 11 chest (above the head's chain)
        (0.82, 6.22, 0.0),      # 12 left arm root
        (1.55, 4.80, 0.0),      # 13 left elbow
        (1.74, 4.27, 0.0),      # 14 left hand
        (-0.65, 6.23, 0.0),     # 15 right arm root
        (-1.40, 4.89, 0.0),     # 16 right elbow
        (-1.53, 4.36, 0.0),     # 17 right hand
        (0.00, 6.47, 0.0),      # 18 head (has children)
        (0.15, 8.20, 0.0),      # 19 ear, a leaf: highest but not the head
        (-0.15, 8.20, 0.0),     # 20 other ear
    ]
    parent = [-1, 0, 1, 2, 4, 4, 5, 6, 4, 8, 9, 3, 11, 12, 13, 11, 15, 16, 3, 18, 18]
    roles = rig_roles.derive(joints, parent)
    assert roles["hip"] == 4, roles
    assert roles["chest"] == 11, roles
    assert roles["head"] == 18, roles
    assert (roles["l_upper"], roles["l_fore"], roles["l_hand"]) == (12, 13, 14), roles
    assert (roles["r_upper"], roles["r_fore"], roles["r_hand"]) == (15, 16, 17), roles
    assert (roles["l_thigh"], roles["l_shin"], roles["l_foot"]) == (5, 6, 7), roles
    assert (roles["r_thigh"], roles["r_shin"], roles["r_foot"]) == (8, 9, 10), roles
