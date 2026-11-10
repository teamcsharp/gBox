"""RE5 Switch low bodies (operator 2026-11-10: "certain enemies like lickers that are lower than normal, so they have to
actually aim at them ... He's shooting directly in front of him at air"): a class in LOW_BODIES is aimed at its own
height and hit-tested with its own body, never a standing Majini's chest 110 cm up."""
import math

from gbox.mercs.titles import re5_switch as R

CRAWLER = {"ptr": 10, "pos": (0.0, 0.0, 200.0), "hp": 300, "hp_max": 300, "class": "uEm32", "motion": 4}
MAJINI = {"ptr": 11, "pos": (0.0, 0.0, 200.0), "hp": 300, "hp_max": 300, "class": "uEm10", "motion": 4}


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0])


def test_a_crawler_is_aimed_at_its_own_height_even_at_arms_length():
    b = bot()
    assert b._aim_h(CRAWLER, 200.0, 1.0) == R.LOW_BODIES["uEm32"].chest < R.KNEE_H
    assert b._aim_h(MAJINI, 200.0, 1.0) == R.CHEST_H, "a standing Majini keeps the chest"


def test_a_dot_on_a_crawlers_back_is_on_him_and_a_dot_at_chest_height_is_air():
    foot = CRAWLER["pos"]
    on_back = (0.0, 30.0, 200.0)
    air = (0.0, 110.0, 200.0)
    assert R.dot_on(on_back, foot, R.body(CRAWLER)) is not None
    assert R.dot_on(air, foot, R.body(CRAWLER)) is None, "the air over his back is a miss"
    assert R.dot_on(on_back, foot) is None, "with a Majini's body this was never a hit"


def test_the_ray_down_to_a_crawler_runs_through_him():
    origin = (0.0, R.MUZZLE_H, 0.0)
    foot = CRAWLER["pos"]
    past = (0.0, 30.0 - (R.MUZZLE_H - 30.0) * 0.3, 260.0)          # the ray on through his back, 60 cm past him
    assert R.through(origin, past, foot, R.body(CRAWLER))
    level = (0.0, R.MUZZLE_H, 400.0)                                 # level, over his back
    assert not R.through(origin, level, foot, R.body(CRAWLER))


def test_the_pitch_wanted_for_a_crawler_points_down():
    p = {"pos": (0.0, 0.0, 0.0)}
    want = math.atan2(CRAWLER["pos"][1] + R.body(CRAWLER).chest - R.MUZZLE_H, 200.0)
    assert want < -0.5 and R.Bot._pitch_to(p, CRAWLER) == abs(want)
