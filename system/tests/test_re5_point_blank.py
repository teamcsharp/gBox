"""RE5 Switch point blank: a Majini within ~1.5 m in front must be fired on, whatever the laser dot says.

The dot is unreliable at the muzzle: at 0.8 m the enemy fills the screen, so `_decide`'s old guard
`ray_len < POINT_BLANK_RAY` wrongly demoted a point-blank enemy whose ray happened to terminate past him
(on the wall behind) into `far_off`, the gun went down and the aim swung away -- the "shots go past a
point-blank Majini" bug. The fix drops the ray-length requirement: point blank is `dist <= POINT_BLANK_R`
and the body already facing him, exactly as `_rampage` has always done. These tests pin that at the Bot
level, alongside the existing muzzle test in test_re5_switch_rain.py.
"""
import pytest

from gbox.mercs.titles import re5_switch as R

from test_re5_switch_rain import MUZZLE, at, bot, chest, snap


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    """Drive the Switch's own fight (Bot._decide): PS3_BRAIN=False and CROWD_FIRE=False, matching the rain-fire tests."""
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "CROWD_FIRE", False)


@pytest.fixture(autouse=True)
def _no_heal(monkeypatch):
    monkeypatch.setattr(R, "HEAL_ENABLED", False)


def test_point_blank_fires_when_the_ray_terminates_past_him():
    """The reported bug: enemy at 0.8 m, the dot lands on the wall *behind* him. The old `ray_len < POINT_BLANK_RAY`
    guard made this `far_off` and the gun went down. It must fire 'point blank' instead."""
    b, clock = bot()
    foe = at(80, 10)
    b.tick(snap([(foe, 800)]))
    clock[0] = 0.3
    past = (MUZZLE[0] + 20.0, MUZZLE[1] + 40.0, MUZZLE[2] + 350.0)   # ~3.5 m out, well past his chest
    act = b.tick(snap([(foe, 800)], dot=past, motion=26))
    assert "zr" in act["hold"] and b.doing == "fire" and b.why.startswith("point blank")
    assert b.stats["look"]["shots"][-1]["gate"] == "point blank"


def test_point_blank_fires_when_the_ray_ends_short_but_wide_of_him():
    """A dot that stops short and wide of him is just as un-steerable at the muzzle: proximity and facing alone
    decide point blank, not where the dot landed."""
    b, clock = bot()
    foe = at(80, 10)
    b.tick(snap([(foe, 800)]))
    clock[0] = 0.3
    wide = (MUZZLE[0] - 200.0, MUZZLE[1] + 60.0, MUZZLE[2] + 30.0)   # short, but ~2 m to the side
    act = b.tick(snap([(foe, 800)], dot=wide, motion=26))
    assert "zr" in act["hold"] and b.doing == "fire" and b.why.startswith("point blank")


def test_point_blank_needs_the_body_facing_him():
    """Proximity alone is not enough: a Majini within 1.5 m but well off the body axis (beyond raise_tol) is not
    point blank -- the body must first turn, so the blast is not sprayed into empty space beside him."""
    b, clock = bot()
    foe = at(100, 70)                                              # 1 m, 70 deg off the facing axis
    act = b.tick(snap([(foe, 800)]))
    assert "zr" not in act["hold"] or b.doing != "fire"


def test_point_blank_needs_him_near():
    """Beyond POINT_BLANK_R (150 cm) the point-blank shortcut no longer applies; the normal reach-based path rules."""
    b, clock = bot()
    foe = at(200, 5)
    b.tick(snap([(foe, 800)]))
    clock[0] = 0.3
    act = b.tick(snap([(foe, 800)], dot=chest(foe, 30.0), motion=26))
    # 2 m out with the dot actually on him: fires through the normal path, never 'point blank'
    assert act["hold"] and "zr" in act["hold"] and not b.why.startswith("point blank")
