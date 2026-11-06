"""re4gc_zombies: target-side roles and the unusable-skeleton guard."""
from gbox import re4gc_zombies


class _Template:
    def __init__(self, bones, world):
        self.bones = bones                  # [(id, parent | 0xFF, ...)]
        self._world = world

    def bone_world(self):
        return self._world


def _humanoid():
    # a small humanoid: pelvis 17, hip 1, chest 2, neck 3, head 4, arms out at 5/8, legs down at 11/14
    bones = [(17, 0xFF), (1, 17), (2, 1), (3, 2), (4, 3),
             (5, 2), (6, 5), (8, 2), (9, 8), (11, 1), (12, 11), (14, 1), (15, 14)]
    world = {
        17: (0.0, 1000.0, 0.0), 1: (0.0, 1100.0, 0.0), 2: (0.0, 1300.0, 0.0), 3: (0.0, 1500.0, 0.0),
        4: (0.0, 1700.0, 0.0), 5: (250.0, 1300.0, 0.0), 6: (500.0, 1300.0, 0.0),
        8: (-250.0, 1300.0, 0.0), 9: (-500.0, 1300.0, 0.0),
        11: (120.0, 600.0, 0.0), 12: (120.0, 100.0, 0.0), 14: (-120.0, 600.0, 0.0), 15: (-120.0, 100.0, 0.0),
    }
    return _Template(bones, world)


def test_target_roles_are_keyed_by_the_skeletons_own_bone_ids():
    roles = re4gc_zombies.target_roles(_humanoid())
    assert roles["head"] == 4 and roles["chest"] == 2
    assert roles["l_upper"] == 5 and roles["r_upper"] == 8
    assert roles["l_thigh"] == 11 and roles["r_thigh"] == 14


def test_the_root_is_aliased_to_pelvis():
    """The retargeter's own map names the root both "pelvis" and "hip"; a derived map must too."""
    roles = re4gc_zombies.target_roles(_humanoid())
    assert roles["pelvis"] == roles["hip"]


def test_an_unusable_skeleton_is_described_not_crashed():
    flat = _Template([(0, 0xFF), (1, 0), (2, 1), (3, 2)], {0: (0.0, 0.0, 0.0), 1: (0.0, 0.0, 0.0),
                                                            2: (0.0, 0.0, 0.0), 3: (0.0, 0.0, 0.0)})
    assert "no height" in re4gc_zombies.degenerate(flat)
    nan = _Template([(0, 0xFF), (1, 0), (2, 1), (3, 2)],
                    {0: (0.0, 0.0, 0.0), 1: (float("nan"), 1.0, 0.0), 2: (0.0, 2.0, 0.0), 3: (0.0, 3.0, 0.0)})
    assert "non-finite" in re4gc_zombies.degenerate(nan)
    assert re4gc_zombies.degenerate(_humanoid()) == ""
