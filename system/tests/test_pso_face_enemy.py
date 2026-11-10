import math
import pytest
from gbox import pso_coop as C


def test_face_enemy_turns_toward_nearest_and_signs_direction():
    # heading 0 = facing +z (north). Enemy due east (+x) -> +90 -> turn left.
    p = dict(x=0.0, z=0.0, heading_deg=0.0)
    east = [dict(x=100.0, z=0.0)]
    keys, dur, point = C.face_enemy_command(p, east)
    assert keys == ["lleft"]
    assert 0 < dur <= 0.12
    assert point == (100.0, 0.0)

    # Enemy west -> turn right.
    west = [dict(x=-100.0, z=0.0)]
    keys, dur, point = C.face_enemy_command(p, west)
    assert keys == ["lright"]
    assert point == (-100.0, 0.0)


def test_face_enemy_picks_nearest_and_scales_duration():
    p = dict(x=0.0, z=0.0, heading_deg=180.0)  # facing south; nearest is 5m east.
    threats = [dict(x=5.0, z=0.0), dict(x=100.0, z=0.0)]
    keys, dur, point = C.face_enemy_command(p, threats)
    assert point == (5.0, 0.0)
    # Facing south (180) vs east (90): -90deg -> right turn, full .12 duration.
    assert keys == ["lright"] and 0.1 <= dur <= 0.12


def test_face_enemy_no_ops_when_aligned_or_no_threat():
    p = dict(x=0.0, z=0.0, heading_deg=90.0)
    east = [dict(x=100.0, z=0.0)]
    assert C.face_enemy_command(p, east) is None  # already ~aligned
    assert C.face_enemy_command(p, []) is None     # no threats


def test_face_enemy_small_error_emits_tiny_pulse():
    p = dict(x=0.0, z=0.0, heading_deg=0.0)
    # Enemy 20deg off east: still >10deg threshold -> emits, small duration.
    e = [dict(x=math.sin(math.radians(20)), z=math.cos(math.radians(20)))]
    res = C.face_enemy_command(p, e)
    assert res is not None
    keys, dur, point = res
    assert keys == ["lleft"]
    assert 0.02 <= dur < 0.12
