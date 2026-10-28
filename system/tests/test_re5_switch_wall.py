"""RE5 Switch wall governor (operator 21:0x: "the bot running with his face in the wall as if he doesn't actually
see"): the forward stick with no progress is a wall - the push stops at once, the spot remembered, a short step back
then the most open known way (his own trail), and no push there again on that heading."""
import math

import pytest

from gbox.mercs.titles import re5_switch as R


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    monkeypatch.setattr(R, "MINES", False)
    monkeypatch.setattr(R, "CALM", False)


def at(dist, deg, y=0.0):
    a = math.radians(deg)
    return (dist * math.sin(a), y, dist * math.cos(a))


def snap(pos=(0.0, 0.0, 0.0), rot=0.0, bonuses=None, enemies=()):
    s = {"player": {"ptr": 0x5D00001000, "pos": pos, "rot": rot, "hp": 1000, "hp_max": 1000, "motion": 4,
                    "aim_pitch": None},
         "enemies": [{"ptr": 10 + i, "pos": x, "hp": 800, "hp_max": 800} for i, x in enumerate(enemies)],
         "inventory": [], "kills": 0, "laser": {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}
    if bonuses is not None:
        s["bonuses"] = [{"ptr": 900 + i, "pos": b, "secs": 30} for i, b in enumerate(bonuses)]
    return s


def bot():
    clock = [0.0]
    b = R.Bot(stats={}, clock=lambda: clock[0])
    b._round_started = b._round_t0 = 0.0
    return b, clock


def test_running_into_a_wall_stops_the_push_and_steps_back_then_takes_his_trail():
    b, clock = bot()
    b._trail = [(-10.0, (-600.0, 0.0, 0.0))]                       # where he came from: 6 m to his right-hand side
    statue = at(1500, 0)
    act = b.tick(snap(bonuses=[statue]))
    assert "lup" in act["hold"]
    for k in range(1, 6):                                          # he does not move: a wall in front
        clock[0] = 0.08 * k
        act = b.tick(snap(bonuses=[statue]))
    assert b.stats["wall_hits"] == 1 and "lup" not in act["hold"] and "ldown" in act["hold"]   # the step back
    assert len(b._walls) == 1 and b.stats["wall_push_s"] <= 0.1
    clock[0] = 0.75
    act = b.tick(snap(bonuses=[statue]))
    assert "lup" in act["hold"] and abs(math.degrees(b._wall_rec["head"]) - (-90)) < 1   # the open way: his trail
    clock[0] = 1.5
    b.tick(snap(pos=(-300.0, 0.0, 0.0), bonuses=[statue]))
    assert b.stats["wall_recoveries"] == 1


def test_no_trail_known_back_the_way_he_came():
    b, clock = bot()
    statue = at(1500, 0)
    b.tick(snap(bonuses=[statue]))
    for k in range(1, 6):
        clock[0] = 0.08 * k
        b.tick(snap(bonuses=[statue]))
    assert abs(abs(math.degrees(b._wall_rec["head"])) - 180) < 1


def test_a_remembered_wall_is_not_pushed_again_on_that_heading():
    b, clock = bot()
    b.wall_memory(0.0, 0.0, 0.0)
    act = b.tick(snap(bonuses=[at(1500, 0)]))
    assert b.stats["wall_preempts"] == 1 and "lup" not in act["hold"] and "ldown" in act["hold"]


def test_moving_freely_is_left_alone():
    b, clock = bot()
    statue = at(3000, 0)
    for k in range(10):
        clock[0] = 0.08 * k
        act = b.tick(snap(pos=(0.0, 0.0, 35.0 * k), bonuses=[statue]))
    assert b.stats["wall_hits"] == 0 and "lup" in act["hold"]


def test_aiming_is_not_movement():
    b, clock = bot()
    foe = at(600, 0)
    for k in range(10):
        clock[0] = 0.08 * k
        b.tick(snap(enemies=[foe]))
    assert b.stats["wall_hits"] == 0
