"""RE5 Switch combo pursuit and crowd moves (operator 2026-10-27 15:25: "aware of the locations of any and all enemies
in the level ... go and pursue them and do whatever it takes to maintain the combo"; 15:27: "always keep the crowd
control and be on the move"): the census (every Majini in sEnemy, against the game's unit line), the run to the
census's best when the combo runs down with nobody in reach, the detour when stuck, the kill credited, and the gun
lowered to move out of a crowd."""
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


def snap(enemies, combo=None, window=None, kills=None, dot=None, motion=0, pos=(0.0, 0.0, 0.0), units=None):
    return {"player": {"ptr": 0x5D00001000, "pos": pos, "rot": 0.0, "hp": 1000, "hp_max": 1000, "motion": motion},
            "enemies": [{"ptr": 10 + i, "pos": x, "hp": 800, "hp_max": 800} for i, x in enumerate(enemies)],
            "inventory": [], "combo": combo, "combo_timer": window, "kills": kills, "unit_enemies_alive": units,
            "laser": {"from": MUZZLE, "at": dot, "up": True} if dot else {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


def test_the_combo_running_down_with_nobody_in_reach_he_runs_to_the_census_best():
    b, clock = bot()
    level, high = at(2000, 10), at(1200, -10, y=400.0)             # the level one beats one nearer but 4 m up
    act = b.tick(snap([level, high], combo=4, window=5.0, units=2))
    assert b.doing == "walk" and "pursuit" in b.why and {"lup", "b"} <= set(act["hold"]) and b.target == 10
    assert b.stats["pursuits"] == 1 and b.stats["census_count"] == 2 and b.stats["census_units"] == 2


def test_no_pursuit_with_one_in_reach_or_the_window_still_long():
    b, clock = bot()
    b.tick(snap([at(800, 0), at(2000, 10)], combo=4, window=5.0))
    assert b.stats["pursuits"] == 0
    b2, _ = bot()
    b2.tick(snap([at(2000, 10)], combo=4, window=8.0))
    assert b2.stats["pursuits"] == 0


def test_nobody_on_his_level_at_all_he_still_pursues_from_the_census():
    b, clock = bot()
    act = b.tick(snap([at(1000, 0, y=450.0)], combo=2, window=4.0))
    assert "pursuit" in b.why and "b" in act["hold"] and b.stats["pursuits"] == 1


def test_stuck_he_takes_a_detour_and_a_kill_is_credited():
    b, clock = bot()
    far = at(2000, 0)
    for k in range(20):                                            # no closer for 2 s
        clock[0] = 0.1 * k
        b.tick(snap([far], combo=4, window=5.5 - 0.1 * k, kills=7))
    assert b.stats["pursuit_stuck"] >= 1 and "detour" in b.why
    clock[0] = 2.1
    b.tick(snap([far], combo=5, window=5.0, kills=8))              # a kill while pursuing
    assert b.stats["pursuit_kills"] == 1


def test_three_close_with_the_gun_up_he_lowers_it_and_moves_out(monkeypatch):
    monkeypatch.setattr(R, "SWEEP", False)                         # (three within 5 m sweep now: the crowd move without it)
    b, clock = bot()
    crowd = [at(250, 0), at(300, 30), at(350, -30)]                # all in front
    b.tick(snap(crowd, motion=22))
    for k, t in enumerate((0.3, 0.6, 0.9, 1.2, 1.4)):
        clock[0] = t
        act = b.tick(snap(crowd, dot=(5.0 * k, 150.0, 900.0), motion=26))
        if b.stats["crowd_moves"]:
            break
    assert b.stats["crowd_moves"] == 1 and b.doing == "backoff" and "ldown" in act["hold"]
    clock[0] = 1.5
    act = b.tick(snap(crowd, motion=0))                            # the move goes on, the gun down
    assert "ldown" in act["hold"] and "moving out" in b.why
