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


def test_arrival_is_not_misreported_as_collecting_a_bonus():
    b = D.Bot(stats={}, director=False)
    s = snap_at(VILLAGE_FIRST)
    assert B.bonus_goal(b, s, 10.0) is True
    re4_walk.goals_of(b).goal["state"] = "completed"
    B.bonus_goal(b, s, 20.0)                  # the next tick sees it completed and takes the next nearest
    assert b.stats["bonus_approaches"] == 1
    assert b.stats["bonus_unconfirmed"] == 1
    assert not b.stats.get("bonuses_taken") and not b.stats.get("bonus_s")


def test_native_bonus_preserves_the_upper_floor_height():
    from types import SimpleNamespace
    b = D.Bot(stats={}, director=False)
    s = snap_at((0, 0, 0))
    s["nav"] = SimpleNamespace(bonuses=[{"source": "upper", "stand": [2000, 4500, 3000], "seconds": 30}])
    assert B.bonus_goal(b, s, 10)
    assert re4_walk.goals_of(b).goal["floor_y"] == 4500
    g = re4_walk.goals_of(b)
    s["player"]["pos"] = [2000, 0, 3000]
    assert g.resolve(s, g.received_at + 1) is not None
    assert g.goal["state"] == "active", "standing underneath is not arrival on the upper floor"


def test_fresh_runtime_snapshot_gets_its_mesh_before_bonus_selection(monkeypatch):
    from types import SimpleNamespace
    b = D.Bot(stats={}, director=False)
    snap = {'module_base': 100, 'player': {'pos': (0, 0, 0), 'ptr': 1}}
    def attach(s):
        s['nav'] = SimpleNamespace(bonuses=[{'source': 'native', 'stand': [1000, 0, 0], 'seconds': 30}])
        return s
    monkeypatch.setattr(re4_nav, 'attach', attach)
    assert B.bonus_goal(b, snap, 10)
    assert re4_walk.goals_of(b).goal['source'] == 'time_bonus'


def test_automatic_weapon_pool_has_no_pistols_and_riot_gun_uses_shotgun_aim():
    from gbox.mercs.titles import re4_weapons as W
    assert not set(W.HIGH_POWER) & W.PISTOL_ITEMS
    assert {0x29, 0x2A, 0x37, 0x2C, 0x2D, 0x94} <= set(W.HIGH_POWER)
    assert D.CLASS_FAMILY[W.CLASS_OF[0x94]] == 'shotgun'


def test_arrival_activates_bonus_and_waits_for_clock_evidence():
    b = D.Bot(stats={}, director=False)
    s = snap_at(VILLAGE_FIRST) | {'timer': 100., 'kills': 0}
    B.bonus_goal(b, s, 10.)
    g = re4_walk.goals_of(b)
    now = g.received_at + 1
    action = re4_walk.operator_goal_act(b, s, now, lambda _: {})
    assert action.get('tap') == D.ACTION_BTN and g.goal['state'] == 'active'
    assert g.resolve(s | {'timer': 189.5}, now + .5) is None
    assert g.goal['confirmation'] == 'clock_gain_without_kills'


def test_kill_time_gain_cannot_confirm_a_bonus_pickup():
    b = D.Bot(stats={}, director=False)
    s = snap_at(VILLAGE_FIRST) | {'timer': 100., 'kills': 0}
    B.bonus_goal(b, s, 10.)
    g = re4_walk.goals_of(b)
    now = g.received_at + 1
    g.resolve(s, now)
    assert g.resolve(s | {'timer': 190., 'kills': 1}, now + .5) is not None
    assert not g.goal.get('confirmation')
