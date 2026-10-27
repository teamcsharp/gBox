"""RE5 Switch proximity bombs left behind (gbox.mercs.titles.re5_switch_mines): one every EVERY_S of the round, never
with a Majini at arm's length or on the last site, the pad neutral before the D-pad, ZL to place, a confirmed
placement only, the run away through the widest gap (never back over the bomb), the gun back."""
import math

import pytest

from gbox.mercs.titles import re5_switch_mines as MN

GUN = {"slot": 3, "id": 0x102, "type": 1, "item": 0x02, "rounds": 50, "cap": 50, "grid": 3, "hand": True}
BOMB = {"slot": 1, "id": 0x10A, "type": 1, "item": 0x0A, "rounds": 5, "cap": 5, "grid": 1, "hand": False}


def at(dist, deg):
    a = math.radians(deg)
    return (dist * math.sin(a), 0.0, dist * math.cos(a))


def p(pos=(0.0, 0.0, 0.0), rot=0.0):
    return {"ptr": 1, "pos": pos, "rot": rot, "hp": 1000, "hp_max": 1000, "motion": 0}


def snap(gun_hand=True, bomb_hand=False, rounds=5, ground=()):
    return {"inventory": [dict(GUN, hand=gun_hand), dict(BOMB, hand=bomb_hand, rounds=rounds)],
            "ground_mines": list(ground)}


def foes(*specs):
    return [{"ptr": 10 + i, "pos": at(d, a), "hp": 800} for i, (d, a) in enumerate(specs)]


def test_a_bomb_is_due_every_interval_but_not_at_arms_length_or_on_the_last_site():
    m = MN.Mines({})
    m.new_round(0.0)
    assert m.tick(p(), snap(), foes((600, 0)), 5.0) is None                     # too soon
    assert m.tick(p(), snap(), foes((100, 0)), MN.EVERY_S + 1) is None          # a Majini at arm's length
    assert m.stats["mine_status"] == "a Majini too close to place one"
    m.last_at, m.last_pos = 0.0, (100.0, 0.0, 0.0)
    assert m.tick(p(), snap(), foes((600, 0)), MN.EVERY_S + 1) is None          # still on the last site
    m.last_pos = (900.0, 0.0, 0.0)
    assert m.tick(p(), snap(), foes((600, 0)), MN.EVERY_S + 1) == {"hold": ()} and m.state == "neutral"
    assert MN.Mines({}).tick(p(), {"inventory": [GUN]}, [], 99.0) is None        # no bomb in the inventory


def test_a_confirmed_cycle_places_runs_off_the_bomb_and_brings_the_gun_back():
    m = MN.Mines({})
    m.new_round(0.0)
    t = MN.EVERY_S
    live = foes((700, 180), (800, 170))                                          # the crowd behind him
    assert m.tick(p(), snap(), live, t) == {"hold": ()}                          # the pad rests ...
    assert m.tick(p(), snap(), live, t + 0.2) == {"hold": ()}
    assert m.tick(p(), snap(), live, t + MN.NEUTRAL_S) == {"tap": "dup"}         # ... then the bomb's D-pad slot
    assert m.stats["mine_attempts"] == 1
    assert m.tick(p(), snap(gun_hand=False, bomb_hand=True), live, t + 1.0) == {"hold": ("zl",)}   # ZL: place
    assert m.tick(p(), snap(gun_hand=False, bomb_hand=True), live, t + 1.2) == {"hold": ("zl",)}
    act = m.tick(p(), snap(gun_hand=False, bomb_hand=True, ground=[(10.0, 0.0, 60.0)]), live, t + 1.5)
    assert m.stats["mines_placed"] == 1 and m.state == "retreat" and act["hold"][:2] == MN.RUN
    assert m.last_pos == (10.0, 0.0, 60.0)
    # the gap: the crowd at 170-180 deg and the bomb ahead (6 deg): he runs out to the side, not over the bomb
    assert "rleft" in act["hold"] or "rright" in act["hold"]
    assert m.tick(p(pos=(-360.0, 0.0, 0.0)), snap(gun_hand=False, bomb_hand=True), live, t + 2.6) == {"hold": ()}
    assert m.stats["mine_retreats_completed"] == 1 and m.state == "rearm"
    assert m.tick(p(), snap(gun_hand=False, bomb_hand=True), live, t + 3.0) == {"tap": "dleft"}   # the M92F back
    assert m.tick(p(), snap(), live, t + 3.2) is None and m.state == "idle"
    assert m.tick(p(pos=(900.0, 0.0, 0.0)), snap(), foes((700, 180)), t + 4.0) is None   # the next one waits EVERY_S


def test_an_unconfirmed_press_or_a_grab_gives_up_and_rearms():
    m = MN.Mines({})
    m.new_round(0.0)
    t = MN.EVERY_S
    m.tick(p(), snap(), [], t)
    m.tick(p(), snap(), [], t + MN.NEUTRAL_S)
    m.tick(p(), snap(gun_hand=False, bomb_hand=True), [], t + 1.0)
    assert m.tick(p(), snap(gun_hand=False, bomb_hand=True), [], t + 1.0 + MN.PLACE_S + 0.1) == {"hold": ()}
    assert m.stats["mine_unconfirmed"] == 1 and m.stats["mines_placed"] == 0 and m.state == "rearm"
    m = MN.Mines({})
    m.new_round(0.0)
    m.tick(p(), snap(), [], t)
    assert m.tick(p(), snap(), [], t + 0.1, busy=True) is None and m.state == "rearm"   # grabbed mid-cycle


def test_a_falling_count_confirms_too_and_an_equip_that_never_comes_waits_an_interval():
    m = MN.Mines({})
    m.new_round(0.0)
    t = MN.EVERY_S
    m.tick(p(), snap(), [], t)
    m.tick(p(), snap(), [], t + MN.NEUTRAL_S)
    m.tick(p(), snap(gun_hand=False, bomb_hand=True), [], t + 1.0)
    m.tick(p(), snap(gun_hand=False, bomb_hand=True, rounds=4), [], t + 1.3)
    assert m.stats["mines_placed"] == 1 and m.last_pos == (0.0, 0.0, 0.0)
    m = MN.Mines({})
    m.new_round(0.0)
    m.tick(p(), snap(), [], t)
    m.tick(p(), snap(), [], t + MN.NEUTRAL_S)
    assert m.tick(p(), snap(), [], t + MN.NEUTRAL_S + MN.EQUIP_S + 0.1) is None
    assert m.stats["mine_equip_failures"] == 1 and m.last_at == pytest.approx(t + MN.NEUTRAL_S + MN.EQUIP_S + 0.1)


def test_the_switch_bot_places_a_bomb_between_its_heal_and_its_fight(monkeypatch):
    from gbox.mercs.titles import re5_switch as R
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    clock = [0.0]
    b = R.Bot(stats={}, clock=lambda: clock[0])
    s = {"player": {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000, "motion": 0},
         "enemies": [{"ptr": 10, "pos": (0.0, 0.0, 900.0), "hp": 800, "hp_max": 800}],
         "inventory": [dict(GUN), dict(BOMB)], "timer": 100.0, "timer_start": 120.0,
         "laser": {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}
    assert b.tick(s)["hold"] == ("zl",) and b.doing == "raise"            # the fight first ...
    clock[0] = R.MINE_EVERY_S + 0.1
    assert b.tick(s) == {"hold": ()} and b.doing == "mine"                # ... the bomb's turn after MINE_EVERY_S
    assert "mines_placed" in R.RE5Switch.round_counters and "t_mine" in R.RE5Switch.round_counters
