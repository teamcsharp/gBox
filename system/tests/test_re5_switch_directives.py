"""RE5 Switch bot and the operator's instant commands (gbox.mercs.directives, the PS3 bot's set): mine now, a mine trail,
"repetitive" drops the target, hunt walks to the nearest, fight finds one off his level, score shoots the nearest,
next_area / explore say they are not on Switch yet. A command never presses a key itself."""
import time

import pytest

from gbox.mercs.titles import re5_switch as R

GUN = {"slot": 3, "id": 0x102, "type": 1, "item": 0x02, "rounds": 50, "cap": 50, "grid": 3, "hand": True}
BOMB = {"slot": 1, "id": 0x10A, "type": 1, "item": 0x0A, "rounds": 5, "cap": 5, "grid": 1, "hand": False}


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)


def snap(enemies, inv=None):
    """Chris at the origin facing +z; enemies: [(x, y, z)]."""
    return {"player": {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000, "motion": 0},
            "enemies": [{"ptr": 10 + i, "pos": e, "hp": 800, "hp_max": 800} for i, e in enumerate(enemies)],
            "inventory": inv or [dict(GUN)], "timer": 100.0, "timer_start": 120.0,
            "laser": {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


def command(b, cmd, hold=15.0):
    seq = (b.stats.get("directive_seq") or 0) + 1
    b.stats.update(directive=cmd, directive_seq=seq, directive_until=time.time() + hold, directive_at=time.time())


def test_mine_now_makes_the_bomb_due_at_once_and_says_so_when_mines_are_off():
    b, clock = bot()
    s = snap([(0.0, 0.0, 1500.0)], [dict(GUN), dict(BOMB)])
    b.tick(s)                                                        # the round starts
    clock[0] = 1.0
    command(b, "mine", 0)
    assert b.tick(s) == {"hold": ()} and b.doing == "mine"            # due now: the pad rests, then the D-pad
    assert b.stats["directive_status"].startswith("mine due now")
    b2, clock2 = bot()
    b2.tick(s)
    b2.mines.enabled = False
    command(b2, "mine", 0)
    clock2[0] = 1.0
    b2.tick(s)
    assert b2.stats["directive_status"] == "mine placement is switched off (the mines setting)" and b2.doing != "mine"


def test_repetitive_drops_the_target_he_kept_at_for_another():
    b, clock = bot()
    s = snap([(0.0, 0.0, 500.0), (300.0, 0.0, 900.0)])
    b.tick(s)
    first = b.target
    clock[0] = 0.5
    command(b, "repetitive", 8)
    b.tick(s)
    assert b.target != first and b.blocked == {first: pytest.approx(15.5)}
    assert b.stats["directive_status"].startswith("dropped the target")


def test_hunt_walks_to_the_nearest_far_majini_and_fight_finds_one_off_his_level():
    b, clock = bot()
    command(b, "hunt", 20)
    act = b.tick(snap([(0.0, 0.0, 1600.0)]))
    assert b.doing == "walk" and "lup" in act["hold"] and b.why.startswith("hunt")
    b, clock = bot()
    command(b, "fight", 15)
    act = b.tick(snap([(0.0, 600.0, 900.0)]))                       # on the roof above: not on his level
    assert b.doing == "walk" and "lup" in act["hold"] and b.why.startswith("fight")
    b, clock = bot()
    b.tick(snap([(0.0, 600.0, 900.0)]))
    assert b.doing == "no_foes"                                      # without the command: he waits


def test_score_shoots_the_nearest_and_next_area_is_not_on_switch_yet():
    b, clock = bot()
    command(b, "score", 20)
    b.tick(snap([(0.0, 0.0, 1500.0), (400.0, 0.0, 300.0)]))
    assert b.target == 11
    b, clock = bot()
    command(b, "next_area", 0)
    b.tick(snap([(0.0, 0.0, 500.0)]))
    assert b.stats["directive_status"].startswith("not yet on Switch")
