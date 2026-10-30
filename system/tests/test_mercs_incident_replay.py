"""Replay test for the frontal-grab fix in re5_ps3.py (request #5135, cluster 16c8292da3adc4a2).

The fixture (tests/fixtures/mercs_incidents/re5_grabbed_front_16c8292da3adc4a2.json) records a bot
standing 100 cm from a Majini who was walking in to grab him. Before the fix, the bot would walk
into the grab during gather_time; after the fix, the grab-front threat gate stops the walk and
transitions to fight.

The fix adds GRAB_FRONT_R / GRAB_FRONT_CONE to re5_ps3.Bot._threat: a Majini within 250 cm and
within 90 degrees of the bot's heading is a threat, so the gather path is interrupted.
"""
import json
import math
import pathlib

import pytest

from gbox.mercs.titles import re5_ps3 as R

FIX = pathlib.Path(__file__).parent / "fixtures" / "mercs_incidents" / "re5_grabbed_front_16c8292da3adc4a2.json"


def _make_bot():
    """A fresh re5_ps3 Bot with minimal state for _threat testing."""
    b = R.Bot(stats={}, clock=lambda: 1000.0)
    return b


def test_grab_front_constants_exist():
    """The new constants are defined and reasonable."""
    assert hasattr(R, "GRAB_FRONT_R") and R.GRAB_FRONT_R > 0
    assert hasattr(R, "GRAB_FRONT_CONE") and R.GRAB_FRONT_CONE > 0
    # The grab-front range should be shorter than the general fight range
    assert R.GRAB_FRONT_R < R.FIGHT_R, f"GRAB_FRONT_R={R.GRAB_FRONT_R} should be < FIGHT_R={R.FIGHT_R}"


def test_majini_at_100cm_in_front_is_threat():
    """A Majini 100 cm directly in front (rot=0, facing +z) is a grab-front threat."""
    b = _make_bot()
    p = {"pos": [1000.0, 550.0, 1000.0], "rot": 0.0}
    e = {"pos": [1000.0, 550.0, 1100.0]}  # 100 cm in front (+z)
    assert R.Bot._threat(p, e), "Majini 100 cm in front should be a grab-front threat"


def test_majini_at_200cm_in_front_is_threat():
    """A Majini 200 cm directly in front is a grab-front threat (within GRAB_FRONT_R=250)."""
    b = _make_bot()
    p = {"pos": [1000.0, 550.0, 1000.0], "rot": 0.0}
    e = {"pos": [1000.0, 550.0, 1200.0]}  # 200 cm in front (+z)
    assert R.Bot._threat(p, e), "Majini 200 cm in front should be a grab-front threat"


def test_majini_at_300cm_in_front_is_not_threat():
    """A Majini 300 cm in front is beyond GRAB_FRONT_R=250 and FIGHT_R=350 with 0 deg off (within FIGHT_CONE=40 deg).
    Actually 300 < FIGHT_R=350 and 0 deg < 40 deg, so it IS a fight threat. Use a distance beyond FIGHT_R."""
    b = _make_bot()
    p = {"pos": [1000.0, 550.0, 1000.0], "rot": 0.0}
    e = {"pos": [1000.0, 550.0, 1400.0]}  # 400 cm in front, beyond FIGHT_R=350
    assert not R.Bot._threat(p, e), "Majini 400 cm in front should not be a threat (beyond FIGHT_R)"


def test_majini_at_200cm_at_50deg_is_threat():
    """A Majini 200 cm at 50 deg off-heading is a grab-front threat (within 250 cm and 90 deg cone)."""
    b = _make_bot()
    p = {"pos": [1000.0, 550.0, 1000.0], "rot": 0.0}
    # 200 cm at 50 deg from heading (heading is +z, so 50 deg toward +x)
    # heading(dx, dz) = atan2(dx, dz); for 50 deg from +z toward +x: dx = 200*sin(50), dz = 200*cos(50)
    ex = 1000.0 + 200 * math.sin(math.radians(50))
    ez = 1000.0 + 200 * math.cos(math.radians(50))
    e = {"pos": [ex, 550.0, ez]}
    assert R.Bot._threat(p, e), "Majini 200 cm at 50 deg should be a grab-front threat"


def test_majini_at_200cm_at_100deg_is_not_threat():
    """A Majini 200 cm at 100 deg off-heading is NOT a grab-front threat (beyond 90 deg cone, and beyond FIGHT_R cone).
    200 > ON_TOP_R=160, 100 deg > GRAB_FRONT_CONE=90, 100 deg > FIGHT_CONE=40."""
    b = _make_bot()
    p = {"pos": [1000.0, 550.0, 1000.0], "rot": 0.0}
    # 200 cm at 100 deg from +z (wraps to 80 deg on the other side via wrap(), but abs is 100 deg)
    # Actually wrap normalizes to [-180, 180], so 100 deg stays 100 deg
    ex = 1000.0 + 200 * math.sin(math.radians(100))
    ez = 1000.0 + 200 * math.cos(math.radians(100))
    e = {"pos": [ex, 550.0, ez]}
    assert not R.Bot._threat(p, e), "Majini 200 cm at 100 deg should not be a grab-front threat"


def test_fixture_snapshot_majini_is_threat():
    """Using the actual fixture: the Majini 100 cm in front of the player is a grab-front threat."""
    fx = json.loads(FIX.read_text())
    p = fx["snapshot"]["player"]
    enemy = fx["snapshot"]["enemies"][0]  # the near one at 100 cm
    assert R.Bot._threat(p, enemy), "Fixture Majini 100 cm in front should be a grab-front threat"
