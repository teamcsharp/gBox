"""RE5 Switch aim smoothness (operator 2026-10-27: "the bot in RE5 is aiming spasticly"): no flip back to the Majini he
just left within FLIP_S, the dot taking another Majini only after DOT_SWITCH_TICKS, the gun lowered for a far-off aim
only after UNAIM_HOLD_S (never within MIN_UP_S of coming up), the gun raised again inside RERAISE_FRAC of the raise
tolerance once turning, and the motion counters (target switches and flips, stick onsets, aim reversals, raises,
unaims) in the round's counters."""
import math

import pytest

from gbox.mercs.titles import re5_switch as R


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    monkeypatch.setattr(R, "SMOOTH", True)                      # these test the smoothing (off by default since 13:00)


def at(dist, deg):
    a = math.radians(deg)
    return (dist * math.sin(a), 0.0, dist * math.cos(a))


def p(rot=0.0):
    return {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": rot, "hp": 1000, "hp_max": 1000, "motion": 0}


def foes(*specs):
    return [{"ptr": 10 + i, "pos": at(d, a), "hp": 800, "hp_max": 800} for i, (d, a) in enumerate(specs)]


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


def test_no_flip_back_to_the_majini_he_just_left_unless_one_is_about_to_grab_him():
    b, clock = bot()
    live = foes((1500, 100), (500, -100))                         # nobody in front or near: the cost decides
    first = b._choose(p(), live, 0.0)
    assert first["ptr"] == 11                                      # the near one, far cheaper
    other = live[0]
    b.target_at = -10.0
    b._set_target(other["ptr"], 2.0)                               # he moved on to the other one
    assert b.prev_target == first["ptr"] and b.stats["target_switches"] == 1
    b.target_at = -10.0
    assert b._choose(p(), live, 2.5)["ptr"] == other["ptr"]        # the first is cheaper again, 0.5 s on: kept
    assert b.stats["target_flips"] == 0
    b.target_at = -10.0
    assert b._choose(p(), live, 4.0)["ptr"] == first["ptr"]        # past FLIP_S: free to go back
    grab = foes((1500, 100), (500, -100), (100, 170))
    b._set_target(grab[0]["ptr"], 5.0)
    b.target_at = -10.0
    assert b._choose(p(), grab, 5.2)["ptr"] == 12                  # one about to grab him wins at once


def test_turning_with_the_gun_down_raises_it_only_well_inside_the_raise_tolerance():
    b, clock = bot()
    tol = b.raise_tol(800)
    s = {"player": p(), "enemies": foes((800, math.degrees(tol) * 1.5)), "inventory": [],
         "laser": {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}
    b.tick(s)
    assert b.doing == "turn" and b.turning
    s["enemies"] = foes((800, math.degrees(tol) * 0.9))            # inside the tolerance, outside RERAISE_FRAC: on
    clock[0] = 0.1
    b.tick(s)
    assert b.doing == "turn"
    s["enemies"] = foes((800, math.degrees(tol) * 0.6))
    clock[0] = 0.2
    b.tick(s)
    assert b.doing == "raise" and b.stats["raises"] == 1 and not b.turning


def test_the_stick_counters_count_onsets_and_quick_reversals():
    b, clock = bot()
    for t, keys in ((0.0, ("rleft",)), (0.05, ("rleft",)), (0.1, ()), (0.15, ("rright",)), (0.9, ("rleft",)),
                    (1.0, ("rleft", "rup"))):
        b._count_sticks({"hold": keys}, t)
    assert b.stats["stick_onsets"] == 4                            # rleft, rright, rleft, rup
    assert b.stats["aim_reversals"] == 1                           # left -> right in 0.15 s; right -> left after 0.75 s


def test_smoothness_off_keeps_the_old_immediate_dot_switch(monkeypatch):
    monkeypatch.setattr(R, "SMOOTH", False)
    b, clock = bot()
    a, near = at(500, 0), at(200, 3)
    chest = lambda f: (f[0], f[1] + R.CHEST_H, f[2])
    snap = lambda dot: {"player": p(), "enemies": [{"ptr": 10, "pos": a, "hp": 800, "hp_max": 800},
                                                   {"ptr": 11, "pos": near, "hp": 800, "hp_max": 800}],
                        "inventory": [], "laser": {"from": (0.0, 140.0, 30.0), "at": dot, "up": True}}
    b.tick({**snap(chest(a)), "laser": {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}})
    clock[0] = 0.3
    b.tick(snap(chest(near)))
    assert b.target == 11
    for k in R.MOTION_COUNTERS:
        assert k in R.RE5Switch.round_counters


def test_up_close_the_gun_goes_down_for_a_far_off_aim_at_once_as_before():
    b, clock = bot()
    target, behind = at(200, 0), at(180, 120)                     # one in front, one at arm's length behind
    chest = lambda f, dx=0.0: (f[0] + dx, f[1] + R.CHEST_H, f[2])
    s = lambda dot, enemies: {"player": p(), "enemies": [{"ptr": 10 + i, "pos": e, "hp": 800, "hp_max": 800}
                                                         for i, e in enumerate(enemies)],
                              "inventory": [], "laser": {"from": (0.0, 140.0, 30.0), "at": dot, "up": dot is not None},
                              "motion": 26}
    b.tick({**s(None, [at(600, 0)]), "laser": {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}})
    clock[0] = 0.3                                                 # just raised, the aim 50 deg off a target 2.5 m out
    far = at(250, 50)
    b.tick(s(chest(at(600, 0)), [far, behind]))
    assert b.doing == "unaim"                                      # one within THREAT_R: no hold
    b2, clock2 = bot()
    R_thr = R.THREAT_R
    try:
        R.THREAT_R = 100.0                                         # nobody "close": the hold applies (the control case)
        b2.tick({**s(None, [at(600, 0)]), "laser": {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}})
        clock2[0] = 0.3
        b2.tick(s(chest(at(600, 0)), [far, behind]))
        assert b2.doing != "unaim"
    finally:
        R.THREAT_R = R_thr


def test_the_dot_on_another_majini_fires_at_him_at_once_without_taking_him_as_the_target():
    b, clock = bot()
    a, other = at(600, 0), at(500, 4)
    chest = lambda f: (f[0], f[1] + R.CHEST_H, f[2])
    snap = lambda dot: {"player": p(), "enemies": [{"ptr": 10, "pos": a, "hp": 800, "hp_max": 800},
                                                   {"ptr": 11, "pos": other, "hp": 800, "hp_max": 800}],
                        "inventory": [], "laser": {"from": (0.0, 140.0, 30.0), "at": dot, "up": dot is not None}}
    b.target = 10
    b.tick({**snap(None), "laser": {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}})
    assert b.target == 10
    clock[0] = 0.3
    act = b.tick(snap(chest(other)))                               # one tick under the dot: shot, not yet the target
    assert "zr" in act["hold"] and b.target == 10 and b.stats["dot_shots"] == 1
    assert not set(act["hold"]) & {"rleft", "rright", "rup", "rdown"}   # the aim held still


def test_his_own_level_comes_first_no_pitching_up_at_a_roof_while_ground_majini_come():
    b, clock = bot()
    roof = {"ptr": 10, "pos": (0.0, 280.0, 700.0), "hp": 800}     # in front, on a roof 2.8 m up
    ground = {"ptr": 11, "pos": (60.0, 0.0, 900.0), "hp": 800}    # in front too, farther, on his level
    assert b._choose(p(), [roof, ground], 0.0)["ptr"] == 11
    side_roof = {"ptr": 12, "pos": (500.0, 280.0, 0.0), "hp": 800}
    side_ground = {"ptr": 13, "pos": (-700.0, 0.0, -100.0), "hp": 800}
    b2, _ = bot()
    assert b2._choose(p(), [side_roof, side_ground], 0.0)["ptr"] == 13   # nobody in front: the roof costs more


def test_no_pitch_swing_to_a_steep_majini_while_one_on_his_level_is_within_six_metres():
    b, clock = bot()
    roof = {"ptr": 10, "pos": (0.0, 300.0, 400.0), "hp": 800}     # in front, 34 deg up to his chest
    ground = {"ptr": 11, "pos": (550.0, 0.0, 0.0), "hp": 800}     # 5.5 m to the side, on his level
    assert b._choose(p(), [roof, ground], 0.0)["ptr"] == 11
    far_ground = {"ptr": 12, "pos": (900.0, 0.0, 0.0), "hp": 800}
    b2, _ = bot()
    assert b2._choose(p(), [roof, far_ground], 0.0)["ptr"] == 10   # nobody on his level within 6 m: the roof is fine
    b3, _ = bot()
    b3._set_target(12, 0.0)
    b3._choose(p(), [roof, far_ground], 5.0)
    assert b3.stats["off_level_picks"] == 1 and b3.stats["pitch_swings"] == 1


def test_up_close_he_keeps_his_target_until_it_dies_or_leaves_unless_a_grab_comes_nearer():
    b, clock = bot()
    cur = {"ptr": 10, "pos": at(200, 150), "hp": 800}              # within THREAT_R, behind-ish
    other = {"ptr": 11, "pos": at(180, 0), "hp": 800}              # in front, as close: no re-pick
    b._set_target(10, 0.0)
    b.target_at = -10.0
    assert b._choose(p(), [cur, other], 1.0)["ptr"] == 10 and b.stats["close_keeps"] == 1
    grab = {"ptr": 12, "pos": at(100, -20), "hp": 800}             # within GRAB_THREAT_R and much nearer: him
    assert b._choose(p(), [cur, other, grab], 1.1)["ptr"] == 12
    for k in R.LEVEL_COUNTERS:
        assert k in R.RE5Switch.round_counters
