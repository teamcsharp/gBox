"""RE4: the bot goes after the stage's time bonuses (gbox.re4switch_bot.bonus_goal).

The operator: "traversing the level, going after the objectives ... going for all of the time bonuses". Nothing had to
be built for the walking - re4_walk.attach already routes a 'point' map goal and fights the enemies on the way - but
nobody issued the mark, so the bonuses (8 in the Village, 47 across the four stages) were never targeted.
"""
import pytest

from gbox import re4switch_bot as B
from gbox.mercs.titles import re4_nav, re4_switch as D, re4_walk

VILLAGE_FIRST = (-22700.0, 0.0, -2700.0)          # the first bonus's `stand` in r400


def snap_at(pos):
    return {"player": {"pos": tuple(pos), "rot": 0.0, "hp": 1000, "ptr": 1}, "enemies": [],
            "nav": re4_nav.load("r400"), "weapon_class": 0x08}


def test_the_nearest_time_bonus_is_marked_as_a_point_goal():
    b = D.Bot(stats={}, director=False)
    assert B.bonus_goal(b, snap_at(VILLAGE_FIRST), 10.0) is True
    g = re4_walk.goals_of(b)
    assert g.goal is not None and g.goal["kind"] == "point", "the walker routes points"
    assert g.goal["label"].startswith("time bonus +")
    assert b.stats["bonus_goals"] == 1


def test_a_live_mark_is_not_replaced():
    b = D.Bot(stats={}, director=False)
    s = snap_at(VILLAGE_FIRST)
    assert B.bonus_goal(b, s, 10.0) is True
    assert B.bonus_goal(b, s, 10.1) is False, "an outstanding mark stands"
    assert b.stats["bonus_goals"] == 1


def test_after_one_completes_the_next_nearest_is_taken():
    b = D.Bot(stats={}, director=False)
    s = snap_at(VILLAGE_FIRST)
    assert B.bonus_goal(b, s, 10.0) is True
    re4_walk.goals_of(b).goal["state"] = "completed"
    assert B.bonus_goal(b, s, 20.0) is True
    assert b.stats["bonus_goals"] == 2, "a completed row is not retried and the next one is taken"


def test_no_nav_or_no_player_marks_nothing():
    b = D.Bot(stats={}, director=False)
    assert B.bonus_goal(b, {"player": {"pos": VILLAGE_FIRST, "ptr": 1}, "enemies": []}, 1.0) is False
    assert B.bonus_goal(b, {"nav": re4_nav.load("r400")}, 1.0) is False
    assert not b.stats.get("bonus_error")
