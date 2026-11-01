"""#5054, RE5 Switch's crowd's own near cover: the cluster (262-505 hits per turn, the aim always on the front
one, 26-57 cm at his side, motion 46-58 cm/s) is the one OUT of its facing (side or behind) landing on the bot
while the bot's trigger is down on the one in front - the trigger never stops and never turns. While crowd
fire is on (CROWD_FIRE, the shotgun up on 3+ within 5 m or 1 within 2 m) and a nearest one inside
CROWD_BACK_R (150 cm) is OUT of its facing, the crowd's fire stops and the gun drops first; the trigger only
comes back when it faces one again or one leaves the ring. Built from the request's example fields: a front
one in CROWD_FRONT and a side/behind one at 0.26-0.57 m out of facing (the recorded 26-57 cm at his side)."""
import math

import pytest

from gbox.mercs.titles import re5_switch as R

MUZZLE = (0.0, 140.0, 30.0)
SHOTGUN = {"slot": 1, "id": 0x104, "type": 1, "item": 0x04, "rounds": 6, "cap": 6, "grid": 5, "hand": False}
M92F = {"slot": 0, "id": 0x102, "type": 1, "item": 0x02, "rounds": 15, "cap": 15, "grid": 3, "hand": True}


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    monkeypatch.setattr(R, "MINES", False)
    monkeypatch.setattr(R, "CALM", False)
    monkeypatch.setattr(R, "QUICK_TURN", False)      # the quiet turn's tests opt in


def at(dist, deg, y=0.0):
    a = math.radians(deg)
    return (dist * math.sin(a), y, dist * math.cos(a))


def chest(foot):
    return (foot[0], foot[1] + R.CHEST_H, foot[2])


def snap(enemies, dot=None, motion=0, inv=None, kills=0):
    return {"player": {"ptr": 0x5D00001000, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000,
                       "motion": motion, "aim_pitch": None},
            "enemies": [{"ptr": 10 + i, "pos": x, "hp": 800, "hp_max": 800} for i, x in enumerate(enemies)],
            "inventory": inv if inv is not None else [], "kills": kills,
            "laser": {"from": MUZZLE, "at": dot, "up": True} if dot else {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


HOLD = [dict(M92F), dict(SHOTGUN, hand=True)]

# the cluster's field: a front one in CROWD_FRONT (the trigger on it), a side one 0.40 m out of its
# facing - inside CROWD_BACK_R (150 cm) AND GRAB_THREAT_R (120 cm) - and a third within RAMPAGE_R (500)
# so the crowd fire is on (CROWD_FIRE_N=3).
CROWD3 = [at(300, 10), at(100, 120), at(400, -120)]


def test_a_side_one_inside_crowd_back_r_drops_the_gun_and_stops_the_trigger():
    # the example's field: a front one in CROWD_FRONT (the trigger on it, the aim on it), a side one 0.40 m
    # out of its facing - inside CROWD_BACK_R (150 cm) AND GRAB_THREAT_R (120 cm). Once the trigger is down
    # on the front one, the next tick stops the fire: no ZL, no ZR, the gun dropped.
    front, side, far = at(300, 10), at(100, 120), at(400, -120)
    b, clock = bot()
    b.tick(snap([front, side, far], inv=[M92F, SHOTGUN]))            # the crowd on, the shotgun raised
    clock[0] = 0.2
    b.tick(snap([front, side, far], dot=chest(front), motion=26, inv=HOLD))  # trigger down (fire)
    clock[0] = 0.4
    act = b.tick(snap([front, side, far], dot=chest(front), motion=26, inv=HOLD))  # the backoff fires
    assert b.doing == "crowd-back" and b.aim_since is None
    assert "zr" not in act["hold"] and "zl" not in act["hold"] and act["hold"] == ()
    assert b.stats["crowd_backoffs"] == 1 and b.stats["crowd_back_s"] == 0.2


def test_the_behind_one_does_the_same():
    # a one behind (0.40 m, out of facing) inside CROWD_BACK_R: the crowd's fire stops the same way.
    front, behind, far = at(300, 5), at(100, -160), at(400, -90)
    b, clock = bot()
    b.tick(snap([front, behind, far], inv=[M92F, SHOTGUN]))
    clock[0] = 0.2
    b.tick(snap([front, behind, far], dot=chest(front), motion=29, inv=HOLD))
    clock[0] = 0.4
    act = b.tick(snap([front, behind, far], dot=chest(front), motion=29, inv=HOLD))
    assert b.doing == "crowd-back" and "zr" not in act["hold"] and b.stats["crowd_backoffs"] == 1


def test_a_front_one_inside_crowd_back_r_is_no_cover():
    # one inside CROWD_BACK_R but IN its facing (CROWD_FRONT) is not out of its facing: no backoff.
    near, far1, far2 = at(100, 10), at(300, 60), at(400, -60)
    b, clock = bot()
    b.tick(snap([near, far1, far2], inv=[M92F, SHOTGUN]))
    clock[0] = 0.2
    b.tick(snap([near, far1, far2], dot=chest(near), motion=26, inv=HOLD))
    clock[0] = 0.4
    act = b.tick(snap([near, far1, far2], dot=chest(near), motion=26, inv=HOLD))
    assert "zr" in act["hold"] and b.stats.get("crowd_backoffs", 0) == 0


def test_outside_crowd_back_r_is_no_cover():
    # the one 200 cm out of its facing (beyond CROWD_BACK_R's 150): not near enough to back off for.
    front, far_side, far2 = at(300, 10), at(200, 120), at(400, -120)
    b, clock = bot()
    b.tick(snap([front, far_side, far2], inv=[M92F, SHOTGUN]))
    clock[0] = 0.2
    b.tick(snap([front, far_side, far2], dot=chest(front), motion=26, inv=HOLD))
    clock[0] = 0.4
    act = b.tick(snap([front, far_side, far2], dot=chest(front), motion=26, inv=HOLD))
    assert "zr" in act["hold"] and b.stats.get("crowd_backoffs", 0) == 0


def test_the_trigger_comes_back_when_the_cover_leaves_the_ring():
    front, side, far = at(300, 10), at(100, 120), at(400, -120)
    b, clock = bot()
    b.tick(snap([front, side, far], inv=[M92F, SHOTGUN]))
    clock[0] = 0.2
    b.tick(snap([front, side, far], dot=chest(front), motion=26, inv=HOLD))            # trigger down (fire)
    clock[0] = 0.4
    b.tick(snap([front, side, far], dot=chest(front), motion=26, inv=HOLD))            # the backoff (gun down)
    assert b.aim_since is None
    clock[0] = 0.6
    act = b.tick(snap([front, far], dot=chest(front), motion=26, inv=HOLD))           # cover gone, fire resumes
    assert b.aim_since is not None and "zr" in act["hold"] and b.doing == "fire"
    assert b.stats["crowd_backoffs"] == 1
