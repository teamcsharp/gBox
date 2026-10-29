"""Unit tests for the _threat wide-cone fix (request #5127, re5_ps3 back_2 cluster).

Examples from the cluster: player walking, enemies 40-80 deg off his heading at 1.5-2 m, no laser, no combo.
With the old code (FIGHT_CONE = 40 deg) those enemies were NOT threats — the bot kept walking and got hit
from behind. With the fix (CLOSE_THREAT_R = 250 cm, REAR_WIDE_CONE = 130 deg) they ARE threats within
2.5 m, so the bot turns and fights before they strike.

Geometry used in tests: player at origin facing +x (rot=0). Enemy at (d*cos θ, d*sin θ) has bearing θ.
- 50 deg at 200 cm → old: off=50°>40° → not threat; new: 50°<130° AND d<250 → threat
- 50 deg at 300 cm → old: not threat; new: 50°<130° BUT d=300>250 → not threat (far edge)
- 140 deg at 200 cm → old: not threat; new: 140°>130° → not threat (cone edge)
- 30 deg at 300 cm → old: 30°<40° → threat; new: 30°<130° → threat (front, unchanged)
"""
import math

import pytest

from gbox.mercs.titles.re5_ps3 import (
    Bot,
    CLOSE_THREAT_R,
    FIGHT_CONE,
    FIGHT_R,
    LEVEL_DY,
    REAR_WIDE_CONE,
    ON_TOP_R,
    heading,
    wrap,
)


def _bot():
    b = object.__new__(Bot)
    b.stats = {}
    return b


def _p(px=0.0, pz=0.0, py=100.0, rot=None):
    """rot defaults to pi/2 = facing +x (the heading convention: heading(dx,dz)=atan2(dx,dz))."""
    if rot is None:
        rot = math.pi / 2
    return {"pos": (px, py, pz), "rot": rot}


def _enemy_at_bearing(bearing_deg, dist_cm, key="E", level_dy=0.0):
    """Enemy at bearing `bearing_deg` measured from facing +x (positive = toward +z)."""
    br = math.radians(bearing_deg)
    x = dist_cm * math.cos(br)   # cos(0)=1 → +x, the facing direction
    z = dist_cm * math.sin(br)   # sin(90°)=1 → +z, 90° to the right
    return {"ptr": key, "slot": key, "pos": (x, 100.0 + level_dy, z), "hp": 100}


def _p_facing(rot_deg):
    return _p(rot=math.radians(rot_deg))


# --- Constants match the cluster example fields ---

def test_constants_match_cluster_example_fields():
    """CLOSE_THREAT_R = 250 cm covers the 150-200 cm examples; REAR_WIDE_CONE = 130 deg covers the 40-80 deg off-axis."""
    assert CLOSE_THREAT_R == 250.0
    assert REAR_WIDE_CONE == math.radians(130)
    assert FIGHT_R == 350.0
    assert FIGHT_CONE == math.radians(40)


# --- Core: close rear/side threat is now a threat ---

def test_close_50deg_right_is_now_threat():
    """50 deg to the right at 200 cm: old code off=50>40 → not threat; new code off=50<130 AND d=200<250 → threat."""
    b = _bot()
    p = _p()
    e = _enemy_at_bearing(50, 200.0)
    # Old behaviour: off = 50° > FIGHT_CONE (40°) → False
    # New behaviour: d=200 < CLOSE_THREAT_R(250) → cone=130°, off=50° < 130° → True
    assert b._threat(p, e) is True, "a 50-deg-right enemy at 2 m must be a threat now"


def test_close_70deg_left_is_now_threat():
    """70 deg to the left at 180 cm: within CLOSE_THREAT_R, within REAR_WIDE_CONE → threat."""
    b = _bot()
    p = _p()
    e = _enemy_at_bearing(-70, 180.0)
    assert b._threat(p, e) is True, "a 70-deg-left enemy at 1.8 m must be a threat"


def test_close_80deg_is_now_threat():
    """80 deg off at 200 cm: within both limits → threat (the worst-case example angle)."""
    b = _bot()
    p = _p()
    e = _enemy_at_bearing(80, 200.0)
    assert b._threat(p, e) is True, "an 80-deg-off enemy at 2 m must be a threat"


# --- Boundary: just beyond CLOSE_THREAT_R keeps old narrow cone ---

def test_just_beyond_close_r_far_threat_keeps_narrow_cone():
    """50 deg at 300 cm (beyond CLOSE_THREAT_R 250): uses FIGHT_CONE (40°), off=50>40 → not a threat."""
    b = _bot()
    p = _p()
    e = _enemy_at_bearing(50, 300.0)
    assert b._threat(p, e) is False, "beyond CLOSE_THREAT_R the narrow 40-deg cone still applies"


def test_just_beyond_cone_close_not_threat():
    """140 deg at 200 cm: within CLOSE_THREAT_R but off=140 > REAR_WIDE_CONE (130) → not a threat."""
    b = _bot()
    p = _p()
    e = _enemy_at_bearing(140, 200.0)
    assert b._threat(p, e) is False, "140 deg off exceeds REAR_WIDE_CONE even at close range"


# --- Old behaviour preserved: front threats still caught ---

def test_front_threat_still_threat():
    """30 deg right at 300 cm (beyond CLOSE_THREAT_R): within FIGHT_CONE (40°) → threat, as before."""
    b = _bot()
    p = _p()
    e = _enemy_at_bearing(30, 300.0)
    assert b._threat(p, e) is True, "a front-facing enemy within the old 40-deg cone is still a threat"


def test_front_close_threat():
    """20 deg at 150 cm: within both CLOSE_THREAT_R and REAR_WIDE_CONE → threat."""
    b = _bot()
    p = _p()
    e = _enemy_at_bearing(20, 150.0)
    assert b._threat(p, e) is True


# --- ON_TOP_R still overrides ---

def test_on_top_still_threat():
    """100 deg at 100 cm: beyond ON_TOP_R(160)? No, 100<160 → ON_TOP_R catch → threat regardless of cone."""
    b = _bot()
    p = _p()
    e = _enemy_at_bearing(100, 100.0)
    assert b._threat(p, e) is True, "within ON_TOP_R is always a threat"


# --- Level check still applies ---

def test_off_level_not_threat():
    """Enemy 300 cm above (>= LEVEL_DY 150): not a threat even at close range and in-cone."""
    b = _bot()
    p = _p()
    e = _enemy_at_bearing(50, 200.0, level_dy=300.0)
    assert b._threat(p, e) is False, "an enemy on another level is never a threat"


def test_same_level_close_is_threat():
    """Enemy 50 cm above (< LEVEL_DY 150) at 200 cm, 50 deg: same level, close, in wide cone → threat."""
    b = _bot()
    p = _p()
    e = _enemy_at_bearing(50, 200.0, level_dy=50.0)
    assert b._threat(p, e) is True
