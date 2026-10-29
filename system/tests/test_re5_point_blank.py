"""RE5 Switch point-blank aim: shots at a Majini within 1 m must hit, not go past him.

POINT_BLANK fixes the case where the laser's ray terminates short of a point-blank Majini (it hit him, not a
wall), so through()'s have >= want - FIRE_SLACK guard always fails and the bot treats him as not-on even while the
dot sits in front of him. point_blank_on() drops the range guard and instead asks whether the ray's *direction*
intercepts his body. These tests pin that geometry directly.
"""
import math

import pytest

from gbox.mercs.titles import re5_switch as R


def ahead(dist):
    """A Majini feet position straight ahead +z of the origin at the given cm."""
    return (0.0, 0.0, dist)


def ray(origin, dot):
    return origin, dot


def test_point_blank_ray_terminating_short_but_pointing_into_the_chest_is_on():
    """The bug: a 60 cm ray ending just in front of a 90 cm target used to read 'not on' because it terminated
    short. With the direction into his chest, it must read on."""
    origin = (0.0, 140.0, 30.0)          # a muzzle height and a little +z
    foot = ahead(90.0)                   # a Majini 90 cm out (within POINT_BLANK_R == 150)
    # the dot lands 60 cm out along a line heading straight at his chest (y = CHEST_H)
    want = math.dist(origin, (foot[0], foot[1] + R.CHEST_H, foot[2]))
    d = tuple(((foot[0] - origin[0]) / want, (foot[1] + R.CHEST_H - origin[1]) / want,
               (foot[2] - origin[2]) / want))
    dot = tuple(origin[k] + 60.0 * d[k] for k in range(3))   # ray len 60 < POINT_BLANK_RAY == 60? use 40 to be safe
    dot = tuple(origin[k] + 40.0 * d[k] for k in range(3))
    assert R.point_blank_on(origin, dot, foot) is True


def test_point_blank_ray_pointing_past_him_is_off():
    """The original complaint: the aim goes *past* a point-blank Majini. A ray whose direction runs wide of his
    body (angular width BODY_R at his chest distance) must not count as on."""
    origin = (0.0, 140.0, 30.0)
    foot = ahead(90.0)
    # aim wide of him: sharp heading to the side, dot still short but the direction misses his chest entirely
    dot = (-200.0, 140.0 + R.CHEST_H, 90.0)     # 200 cm to the left of his chest axis, clearly outside BODY_R
    assert R.point_blank_on(origin, dot, foot) is False


def test_point_blank_through_the_head_beside_the_chest_still_off():
    """A ray that points over/wide but not through his head-or-body band must not count as on."""
    origin = (0.0, 140.0, 30.0)
    foot = ahead(90.0)
    # dot straight ahead but far above him (well over HEAD_H) at point blank
    dot = (0.0, 400.0, 90.0)
    assert R.point_blank_on(origin, dot, foot) is False


def test_through_still_requires_reaching_him():
    """point_blank_on's sibling through() keeps its FIRE_SLACK reach guard. Beyond FIRE_SLACK short of the chest
    it must NOT read 'on', while point_blank_on (direction-based) still would -- that is the point of the split."""
    origin = (0.0, 140.0, 30.0)
    foot = ahead(90.0)
    want = math.dist(origin, (foot[0], foot[1] + R.CHEST_H, foot[2]))
    d = tuple(((foot[0] - origin[0]) / want, (foot[1] + R.CHEST_H - origin[1]) / want,
               (foot[2] - origin[2]) / want))
    # a direction at him, but terminating way short (more than FIRE_SLACK == 60 before his chest)
    short = max(1.0, want - R.FIRE_SLACK - 20.0)
    dot = tuple(origin[k] + short * d[k] for k in range(3))
    assert R.point_blank_on(origin, dot, foot) is True          # direction-based: the ray points at him
    assert R.through(origin, dot, foot) is False                 # reach-based: far short of his chest


def test_degenerate_ray_is_off():
    """A ray so short it has no meaningful direction (or a coincident target) must never claim on."""
    origin = (0.0, 140.0, 30.0)
    foot = ahead(50.0)
    assert R.point_blank_on(origin, origin, foot) is False       # zero-length dot
    chest = (foot[0], foot[1] + R.CHEST_H, foot[2])
    assert R.point_blank_on(chest, origin, foot) is False        # origin at his chest: want ~ 0
