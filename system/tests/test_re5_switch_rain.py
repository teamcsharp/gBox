"""RE5 Switch "rain fire" (gbox.mercs.titles.re5_switch; operator 2026-10-27: "the bot needs to raise their weapon and
rain fire"): the trigger stays down through the laser's dropout in the shot's motion, a gun coming up is not let go, a
close Majini gets the gun without a body turn, one in front is fought before one beside, a ray ending on the Majini at
the muzzle fires, a far-off aim takes the Majini near the ray instead of lowering, and nothing backs off a crowd."""
import math

import pytest

from gbox.mercs.titles import re5_switch as R

MUZZLE = (0.0, 140.0, 30.0)


@pytest.fixture(autouse=True)
def _no_heal(monkeypatch):
    monkeypatch.setattr(R, "HEAL_ENABLED", False)


def at(dist, deg):
    a = math.radians(deg)
    return (dist * math.sin(a), 0.0, dist * math.cos(a))


def chest(foot, dy=0.0):
    return (foot[0], foot[1] + R.CHEST_H + dy, foot[2])


def snap(enemies, dot=None, motion=0, hp=1000, up=None):
    """Chris at the origin facing +z; enemies [(pos, hp)]; the laser on dot (up unless said), or down."""
    return {"player": {"ptr": 0x5D00001000, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": hp, "hp_max": 1000,
                       "motion": motion},
            "enemies": [{"ptr": 10 + i, "pos": pos, "hp": h, "hp_max": 800} for i, (pos, h) in enumerate(enemies)],
            "inventory": [],
            "laser": {"from": MUZZLE, "at": dot, "up": True if up is None else up} if dot else
                     {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


def firing(b, clock, foe):
    """The gun up and the trigger down on foe (5 m ahead)."""
    b.tick(snap([(foe, 800)], motion=22))
    clock[0] = 0.3
    act = b.tick(snap([(foe, 800)], dot=chest(foe), motion=26))
    assert "zr" in act["hold"] and b.fire_down
    return act


def test_the_trigger_stays_down_through_the_lasers_dropout_in_the_shot():
    b, clock = bot()
    foe = at(500, 0)
    firing(b, clock, foe)
    for k, t in enumerate((0.35, 0.4, 0.5, 0.6, 0.8)):              # 0.5 s of laser reading down in motion 29
        clock[0] = t
        act = b.tick(snap([(foe, 800)], dot=chest(foe, 1.0 + k), motion=29, up=False))
        assert act["hold"] == ("zl", "zr") and b.doing == "fire"
    assert b.stats["reraise"] == 0 and b.stats["shots"] == 1 and b.stats["flicker_s"] > 0
    clock[0] = 0.85
    assert b.tick(snap([(foe, 800)], dot=chest(foe, 9.0), motion=29))["hold"] == ("zl", "zr")   # the laser back


def test_a_dropout_longer_than_flicker_s_waits_with_the_gun_up_and_no_trigger():
    b, clock = bot()
    foe = at(500, 0)
    firing(b, clock, foe)
    clock[0] = 0.3 + R.FLICKER_S + 0.1
    act = b.tick(snap([(foe, 800)], dot=chest(foe), motion=29, up=False))
    assert act["hold"] == ("zl",) and b.doing == "raise" and not b.fire_down and b.stats["reraise"] == 0


def test_the_gun_coming_up_is_not_let_go_until_laser_stuck_s():
    b, clock = bot()
    foe = at(500, 0)
    b.tick(snap([(foe, 800)]))
    clock[0] = R.LASER_WAIT_S + 0.2
    assert b.tick(snap([(foe, 800)], motion=22))["hold"] == ("zl",) and b.stats["reraise"] == 0   # coming up: wait
    clock[0] = R.LASER_STUCK_S + 0.1
    assert b.tick(snap([(foe, 800)], motion=22))["hold"] == () and b.stats["reraise"] == 1      # stuck: again
    b, clock = bot()
    b.tick(snap([(foe, 800)]))
    clock[0] = R.LASER_WAIT_S + 0.1
    assert b.tick(snap([(foe, 800)], motion=0))["hold"] == () and b.stats["reraise"] == 1       # standing: again


@pytest.mark.parametrize("dist,turns", [(80.0, False), (120.0, False), (200.0, True), (600.0, True)])
def test_a_close_majini_twenty_degrees_off_gets_the_gun_without_a_body_turn(dist, turns):
    b, clock = bot()
    act = b.tick(snap([(at(dist, 20), 800)]))
    assert (b.doing == "turn") is turns and (act["hold"] == ("zl",)) is not turns


def test_one_in_front_is_fought_before_a_cheaper_one_beside():
    b, clock = bot()
    ahead, beside = at(900, 5), at(300, 60)                          # costs 925 and 400: the cost picks beside
    b.tick(snap([(ahead, 800), (beside, 800)]))
    assert b.target == 10 and b.doing == "raise"                     # ahead: the gun comes up, no turn


def test_a_ray_ending_on_the_majini_at_the_muzzle_fires():
    b, clock = bot()
    foe = at(80, 10)
    b.tick(snap([(foe, 800)]))
    clock[0] = 0.3
    stub = (MUZZLE[0] - 15.0, MUZZLE[1] - 5.0, MUZZLE[2] + 15.0)    # 0.2 m out, pointing anywhere
    act = b.tick(snap([(foe, 800)], dot=stub, motion=26))
    assert "zr" in act["hold"] and b.doing == "fire" and b.why == "point blank at 0.8 m"
    assert b.stats["look"]["shots"][-1]["gate"] == "point blank"


def test_a_far_off_aim_takes_the_majini_near_the_ray_instead_of_lowering():
    b, clock = bot()
    target, other = at(500, 0), at(600, 50)
    b.tick(snap([(target, 800), (other, 800)]))
    assert b.target == 10
    clock[0] = 0.3
    act = b.tick(snap([(target, 800), (other, 800)], dot=chest(other, 30.0), motion=26))   # the ray near the other
    assert b.target == 11 and b.doing in ("fire", "aim") and "zl" in act["hold"] and b.aim_since is not None
    b, clock = bot()
    b.tick(snap([(target, 800)]))
    clock[0] = 0.3
    b.tick(snap([(target, 800)], dot=chest(other, 30.0), motion=26))   # nobody near the ray: the gun goes down
    assert b.doing == "unaim" and b.aim_since is None


def test_one_close_in_front_gets_the_gun_not_a_back_off_and_a_crowd_no_burst_cut():
    b, clock = bot()
    close = at(100, 0)
    assert b.tick(snap([(close, 800)]))["hold"] == ("zl",) and b.stats["backoffs"] == 0
    crowd = [(at(180, 0), 800), (at(200, 10), 800)]
    b, clock = bot()
    b.tick(snap(crowd, motion=22))
    for k in range(1, 30):                                          # 1.4 s on him with two in front: no back-off
        clock[0] = 0.25 + 0.05 * k
        act = b.tick(snap(crowd, dot=chest(at(180, 0), k * 0.1), motion=29))
        assert "zr" in act["hold"]
    assert b.stats["burst_backoffs"] == 0 and b.stats["shots"] == 1
