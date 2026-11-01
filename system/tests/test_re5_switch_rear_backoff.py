"""RE5 Switch: the damage batch's 'grabbed from behind' cluster (request #5046). One Majini closes from behind while
he aims ahead; the quick turn only starts within 3 m at 90 deg, so the grab reaches arm's length first. The one logic
change: back off from the closing threat (the rear back-off) so it cannot grab him - before the turn-round would walk
into the one he is aiming at. Built from the cluster's recorded example fields: a held motion, a target in front, and
one Majini closing from behind (its bearing > QUICK_ERR = 120 deg from his heading)."""
import math

import pytest

from gbox.mercs.titles import re5_switch as R


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "CROWD_FIRE", False)


def snap(hp=1000, motion=0, enemies=()):
    return {"player": {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": hp, "hp_max": 1000,
                       "motion": motion},
            "enemies": [{"ptr": 10 + i, "pos": pos, "hp": 800, "hp_max": 800} for i, pos in enumerate(enemies)],
            "inventory": [],
            "laser": None}


FRONT = (800.0, 0.0, 0.0)                 # the target he aims at, 8 m in front
REAR_135 = (240 * math.sin(math.radians(135)), 0.0, 240 * math.cos(math.radians(135)))   # one closing from behind


def rear_backoff_triggered(b):
    return b.stats.get("rear_backoffs", 0)


def test_it_backs_off_from_a_majini_closing_from_behind_while_aiming_ahead():
    # the cluster's example: aiming at one 8 m in front, a Majini closing at ~2.4 m from the right-back (135 deg).
    b = R.Bot(stats={}, clock=lambda: 0.0)
    b.tick(snap(enemies=(FRONT, REAR_135)))
    # the rear back-off fires (the threat is within BEHIND_R and > QUICK_ERR from his heading)
    assert rear_backoff_triggered(b) == 1
    # the bot is backing away (either the rear back-off or the quick turn's stick-back step - both step back)
    assert b.doing in ("backoff", "quick_turn")
    act = b.tick(snap(enemies=(FRONT, REAR_135)))
    assert "ldown" in act.get("hold", ())   # stick back, away from the threat's bearing


def test_it_does_not_back_off_when_the_threat_is_beyond_the_grab_band():
    # a Majini 12 m out is not about to grab: no rear back-off (the band is BEHIND_R = 3 m)
    b = R.Bot(stats={}, clock=lambda: 0.0)
    b.tick(snap(enemies=(FRONT, (1200.0, 0.0, 0.0))))
    assert rear_backoff_triggered(b) == 0


def test_it_does_not_back_off_when_the_threat_is_in_front_not_behind():
    # 45 deg is in front (within QUICK_ERR of his heading): the normal fight handles it, not the rear back-off
    b = R.Bot(stats={}, clock=lambda: 0.0)
    near45 = (240 * math.sin(math.radians(45)), 0.0, 240 * math.cos(math.radians(45)))
    b.tick(snap(enemies=(FRONT, near45)))
    assert rear_backoff_triggered(b) == 0


def test_it_does_not_back_off_when_already_held():
    # already grabbed (held motion): break-free owns the stick, the rear back-off stays quiet
    b = R.Bot(stats={}, clock=lambda: 0.0)
    b.tick(snap(motion=106, enemies=(FRONT, REAR_135)))
    assert rear_backoff_triggered(b) == 0


def test_it_does_not_back_off_when_the_threat_is_further_around_than_behind():
    # 150 deg is behind but the rear band is BEHIND_R; a threat at exactly the edge still backs off, but one just
    # outside (behind band) does not. The quick turn / normal fight owns it.
    b = R.Bot(stats={}, clock=lambda: 0.0)
    far = (300.0, 0.0, -300.0)   # 225 deg, 4.2 m: outside BEHIND_R
    b.tick(snap(enemies=(FRONT, far)))
    assert rear_backoff_triggered(b) == 0


def test_it_resumes_fighting_after_the_back_off_ends():
    # after BACKOFF_S the rear back-off clears and he returns to the normal fight (no ldown stick-back)
    b = R.Bot(stats={}, clock=lambda: 0.0)
    b.tick(snap(enemies=(FRONT, REAR_135)))
    assert rear_backoff_triggered(b) == 1
    # advance past the back-off window
    b._rear_backoff_until = 0.0
    b.quick = 0
    b.aim_since = None
    b.turning = False
    b.quick_at = -1e9
    act = b.tick(snap(enemies=(FRONT, REAR_135)))
    # the quick turn or normal fight resumes; no ldown from the rear back-off
    assert "ldown" not in act.get("hold", ()) or b.stats.get("quick_turns", 0) >= 1
