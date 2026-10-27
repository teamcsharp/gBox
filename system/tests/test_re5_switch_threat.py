"""RE5 Switch threat first (operator 2026-10-27 14:30, watching RE5: "pointing at enemies that are way farther away
despite them being crowded in the same area by enemies that are a much more immediate threat ... I will randomly see
them point just up in the air"): with a Majini on his level within THREAT_NEAR_R, no target beyond THREAT_CAP_R (the
choice, the dot's switch, the nearest to the ray), his level first, the closest and approaching first, the current one
kept within THREAT_KEEP, a grab winning; and every aimed tick pitched over PITCH_UP_LOG counted with its cause."""
import math

import pytest

from gbox.mercs.titles import re5_switch as R

MUZZLE = (0.0, 140.0, 30.0)


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)


def at(dist, deg, y=0.0):
    a = math.radians(deg)
    return (dist * math.sin(a), y, dist * math.cos(a))


def chest(foot):
    return (foot[0], foot[1] + R.CHEST_H, foot[2])


def p():
    return {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000, "motion": 0}


def foes(*pos):
    return [{"ptr": 10 + i, "pos": x, "hp": 800, "hp_max": 800} for i, x in enumerate(pos)]


def snap(enemies, dot=None, motion=0):
    return {"player": {"ptr": 0x5D00001000, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000,
                       "motion": motion},
            "enemies": [{"ptr": 10 + i, "pos": x, "hp": 800, "hp_max": 800} for i, x in enumerate(enemies)],
            "inventory": [],
            "laser": {"from": MUZZLE, "at": dot, "up": True} if dot else {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


def test_no_target_beyond_8_m_while_one_on_his_level_is_within_4_m():
    b, clock = bot()
    live = foes(at(1200, 0), at(350, 80))                          # one far dead ahead, one close beside
    assert b._choose(p(), live, 0.0)["ptr"] == 11
    assert b.stats["threat_caps"] == 1
    far_only = foes(at(1200, 0), at(600, 80))                      # nobody within 4 m: in front first, as before
    b2, _ = bot()
    assert b2._choose(p(), far_only, 0.0)["ptr"] == 10 and b2.stats["threat_ticks"] == 0


def test_the_one_closing_in_is_taken_before_a_nearer_one_standing():
    b, clock = bot()
    standing, coming = at(380, 0), at(600, 10)
    for k in range(6):                                             # 0.1 s ticks: the second closes at 4 m/s
        clock[0] = 0.1 * k
        coming = at(600 - 40 * k, 10)
        b._track_approach(p(), foes(standing, coming), clock[0])
    live = foes(standing, coming)                                  # 3.8 m standing, 4.0 m coming at 4 m/s
    assert b._threat_d(p(), live[1]) < b._threat_d(p(), live[0])
    assert b._choose(p(), live, clock[0])["ptr"] == 11


def test_the_current_one_is_kept_within_threat_keep_and_a_grab_wins():
    b, clock = bot()
    live = foes(at(350, 0), at(330, 20))
    b._set_target(10, 0.0)
    assert b._choose(p(), live, 1.0)["ptr"] == 10                  # 3.3 m vs his 3.5 m: no swing for that
    assert b.stats["threat_switches"] == 0
    grab = foes(at(350, 0), at(330, 20), at(100, 120))
    assert b._choose(p(), grab, 1.1)["ptr"] == 12                  # one at 1 m beside him wins at once


def test_his_own_level_first_when_one_is_near():
    b, clock = bot()
    live = foes(at(250, 0, y=250.0), at(500, 30))                  # one 2.5 m up on a ledge, one on his level
    assert b._choose(p(), live, 0.0)["ptr"] == 11


def test_the_dot_on_a_far_majini_does_not_take_him_while_one_is_near():
    b, clock = bot()
    near, far = at(300, 0), at(1500, 2)
    b.tick(snap([near, far], motion=22))
    assert b.target == 10
    clock[0] = 0.3
    b.tick(snap([near, far], dot=chest(far), motion=26))           # the dot lands on the far one behind him
    assert b.target == 10 and b.stats["far_aim_ticks"] == 0


def test_the_combo_push_takes_the_threat_pick_when_one_is_near(monkeypatch):
    b, clock = bot()
    s = snap([at(350, 60), at(700, 0)])
    s["combo"], s["combo_timer"] = 3, 1.5                          # the window runs down
    b.tick(s)
    assert b.target == 10 and b.stats["combo_pushes"] == 1


def test_an_aim_pitched_up_is_counted_with_its_cause():
    b, clock = bot()
    roof = at(500, 0, y=280.0)                                     # 2.8 m up, nobody near: he aims up at it
    b.tick(snap([roof], motion=22))
    clock[0] = 0.3
    high = (0.0, 140.0 + 400.0, 500.0)                             # the laser 38 deg up
    b.tick(snap([roof], dot=high, motion=26))
    assert b.stats["pitch_up_ticks"] == 1 and b.stats["pitch_up_target_high"] == 1
    b2, clock2 = bot()
    ground = at(500, 0)
    b2.tick(snap([ground], motion=22))
    clock2[0] = 0.3
    b2.tick(snap([ground], dot=high, motion=26))                   # a level target, the laser up: the gun just raised
    assert b2.stats["pitch_up_ticks"] == 1 and b2.stats["pitch_up_target_high"] == 0
    assert b2.stats["pitch_up_last"]["cause"] in ("raise", "retarget", "other")
