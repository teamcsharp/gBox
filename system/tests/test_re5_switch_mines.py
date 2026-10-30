"""RE5 Switch proximity bombs left behind (gbox.mercs.titles.re5_switch_mines), on the live facts of 2026-10-27: one
every EVERY_S of the round, never with a Majini within FOE_CLEAR_CM or beside a bomb still down, the pad neutral
before the D-pad, ZL tapped (held, a second bomb), confirmed by a new uWp0a unit near him or the count falling, the
placing motion played out, the run out of the blast (never back over the bomb), the gun back; the blast guard; the
fight never raising a bomb (re5_switch.Bot._gun_back); the ground bombs read from sUnit's line 11."""
import math
import struct

import pytest

from gbox.mercs.titles import re5_switch_mines as MN

GUN = {"slot": 3, "id": 0x102, "type": 1, "item": 0x02, "rounds": 50, "cap": 50, "grid": 3, "hand": True}
BOMB = {"slot": 1, "id": 0x10A, "type": 1, "item": 0x0A, "rounds": 5, "cap": 5, "grid": 1, "hand": False}
STACK = [{"ptr": 0x5D4C7E4280, "pos": (-3.0, -8.0, -2.0)}, {"ptr": 0x5D4C8DCF80, "pos": (557.0, 158.0, 1409.0)}]


def at(dist, deg):
    a = math.radians(deg)
    return (dist * math.sin(a), 0.0, dist * math.cos(a))


def p(pos=(0.0, 0.0, 0.0), rot=0.0, motion=0):
    return {"ptr": 1, "pos": pos, "rot": rot, "hp": 1000, "hp_max": 1000, "motion": motion}


def snap(gun_hand=True, bomb_hand=False, rounds=5, ground=()):
    """The inventory, and the uWp0a units on line 11: the stack's own two (always there) plus ground."""
    return {"inventory": [dict(GUN, hand=gun_hand), dict(BOMB, hand=bomb_hand, rounds=rounds)],
            "ground_mines": STACK + list(ground)}


def foes(*specs):
    return [{"ptr": 10 + i, "pos": at(d, a), "hp": 800} for i, (d, a) in enumerate(specs)]


def held(**kw):
    return snap(gun_hand=False, bomb_hand=True, **kw)


def to_place(m, live, t):
    """idle -> neutral -> the D-pad -> the bomb in hand: the press starts (returns its first action)."""
    assert m.tick(p(), snap(), live, t) == {"hold": ()} and m.state == "neutral"
    assert m.tick(p(), snap(), live, t + MN.NEUTRAL_S) == {"tap": "dup"}
    return m.tick(p(), held(), live, t + MN.NEUTRAL_S + 0.2)


def test_a_bomb_is_due_every_interval_but_not_with_a_majini_near_or_beside_a_bomb_still_down():
    m = MN.Mines({})
    m.new_round(0.0)
    assert m.tick(p(), snap(), foes((1200, 0)), 5.0) is None                    # too soon
    assert m.tick(p(), snap(), foes((400, 0)), MN.EVERY_S + 1) is None          # one within FOE_CLEAR_CM (his blast)
    assert m.stats["mine_status"] == "a Majini too close to place one"
    m.last_at, m.last_pos = 0.0, (500.0, 0.0, 0.0)
    assert m.tick(p(), snap(), foes((1200, 0)), MN.EVERY_S + 1) is None         # still beside the last site
    m.last_pos, m.bombs = (900.0, 0.0, 0.0), {0x77: (0.0, 0.0, -400.0)}
    assert m.tick(p(), snap(ground=[{"ptr": 0x77, "pos": (0.0, 0.0, -400.0)}]), foes((1200, 0)),
                  MN.EVERY_S + 1) is None                                       # beside a bomb still down
    m.bombs = {}
    assert m.tick(p(), snap(), foes((1200, 0)), MN.EVERY_S + 1) == {"hold": ()} and m.state == "neutral"
    assert MN.Mines({}).tick(p(), {"inventory": [GUN]}, [], 99.0) is None        # no bomb in the inventory


def test_default_mine_cadence_waits_two_minutes_and_can_be_explicitly_configured():
    from gbox.mercs.titles import re5_switch as R
    from gbox.mercs.titles import re5_switch_mods as SM

    assert MN.EVERY_S == R.MINE_EVERY_S == SM.MINE_EVERY_DEFAULT == 120.0
    m = MN.Mines({})
    m.new_round(0.0)
    for now in (9.0, 30.0, 119.9):
        assert m.tick(p(), snap(), [], now) is None
    assert m.tick(p(), snap(), [], 120.0) == {"hold": ()} and m.state == "neutral"
    m = MN.Mines({})
    m.configure({"enabled": True, "interval_s": 180.0})
    m.new_round(0.0)
    assert m.tick(p(), snap(), [], 120.0) is None
    assert m.tick(p(), snap(), [], 180.0) == {"hold": ()}


def test_zl_is_tapped_the_new_bomb_confirms_the_placing_motion_plays_out_he_runs_off_and_rearms():
    m = MN.Mines({})
    m.new_round(0.0)
    t = MN.EVERY_S
    live = foes((1000, 180), (1100, 170))                                        # the crowd far behind him
    assert to_place(m, live, t) == {"hold": ("zl",)} and m.stats["mine_attempts"] == 1
    t0 = t + MN.NEUTRAL_S + 0.2
    assert m.tick(p(motion=29), held(), live, t0 + 0.15) == {"hold": ("zl",)}    # (the placing motion at 0.02-0.17 s)
    assert m.tick(p(motion=29), held(), live, t0 + MN.PRESS_S + 0.01) == {"hold": ()}   # released: one bomb, not two
    bomb = {"ptr": 0x5D4D7ABC10, "pos": (-3.0, 3.0, 57.0)}                       # 0.69 s: ~57 cm ahead of his feet
    assert m.tick(p(motion=29), held(ground=[bomb]), live, t0 + 0.69) == {"hold": ()}
    assert m.stats["mines_placed"] == 1 and m.state == "settle" and m.bombs == {bomb["ptr"]: bomb["pos"]}
    assert m.last_pos == bomb["pos"]
    assert m.tick(p(motion=29), held(ground=[bomb]), live, t0 + 1.2) == {"hold": ()}    # the motion plays out
    act = m.tick(p(), held(ground=[bomb]), live, t0 + 1.35)
    assert m.state == "retreat" and act["hold"][:2] == MN.RUN
    # the gap: the crowd at 170-180 deg and the bomb ahead (0 deg): he turns out to a side, not over the bomb
    assert "rleft" in act["hold"] or "rright" in act["hold"]
    assert m.tick(p(pos=(-500.0, 0.0, 0.0)), held(ground=[bomb]), live, t0 + 2.0)["hold"][:2] == MN.RUN   # 5 m: on
    assert m.tick(p(pos=(-850.0, 0.0, 0.0)), held(ground=[bomb]), live, t0 + 2.6) == {"hold": ()}   # 8 m off
    assert m.stats["mine_retreats_completed"] == 1 and m.state == "rearm"
    assert m.tick(p(), held(ground=[bomb]), live, t0 + 3.0) == {"tap": "dleft"}  # the M92F back
    assert m.tick(p(), snap(ground=[bomb]), live, t0 + 3.2) is None and m.state == "idle"
    assert m.tick(p(pos=(-900.0, 0.0, 0.0)), snap(ground=[bomb]), live, t0 + 4.0) is None   # the next waits EVERY_S


def test_an_unconfirmed_press_still_leaves_when_the_placing_motion_was_seen_and_rearms_when_not():
    t = MN.EVERY_S
    m = MN.Mines({})
    m.new_round(0.0)
    to_place(m, [], t)
    t0 = t + MN.NEUTRAL_S + 0.2
    m.tick(p(motion=29), held(), [], t0 + 0.1)
    act = m.tick(p(), held(), [], t0 + MN.PLACE_S + 0.1)
    assert m.stats["mine_unconfirmed"] == 1 and m.stats["mines_placed"] == 0
    assert m.state == "retreat" and act["hold"][:2] == MN.RUN and m.last_pos == (0.0, 0.0, 0.0)
    m = MN.Mines({})
    m.new_round(0.0)
    to_place(m, [], t)
    assert m.tick(p(), held(), [], t0 + MN.PLACE_S + 0.1) == {"hold": ()}
    assert m.stats["mine_unconfirmed"] == 1 and m.state == "rearm"
    m = MN.Mines({})
    m.new_round(0.0)
    m.tick(p(), snap(), [], t)
    assert m.tick(p(), snap(), [], t + 0.1, busy=True) is None and m.state == "rearm"   # grabbed before the press


def test_a_falling_count_confirms_too_the_stacks_own_units_never_do_and_a_missing_equip_waits_an_interval():
    t = MN.EVERY_S
    m = MN.Mines({})
    m.new_round(0.0)
    to_place(m, [], t)
    t0 = t + MN.NEUTRAL_S + 0.2
    far = {"ptr": 0x5D778D13B0, "pos": (3000.0, 0.0, 400.0)}                     # a new uWp0a far off: not his
    m.tick(p(motion=29), held(ground=[far]), [], t0 + 0.3)
    assert m.stats["mines_placed"] == 0
    m.tick(p(motion=29), held(rounds=4, ground=[far]), [], t0 + 0.57)            # the flag off: the count falls
    assert m.stats["mines_placed"] == 1 and m.last_pos == (0.0, 0.0, 0.0) and m.bombs == {}
    m = MN.Mines({})
    m.new_round(0.0)
    m.tick(p(), snap(), [], t)
    m.tick(p(), snap(), [], t + MN.NEUTRAL_S)
    assert m.tick(p(), snap(), [], t + MN.NEUTRAL_S + MN.EQUIP_S + 0.1) is None
    assert m.stats["mine_equip_failures"] == 1 and m.last_at == pytest.approx(t + MN.NEUTRAL_S + MN.EQUIP_S + 0.1)


def test_the_guard_runs_him_out_of_a_bombs_blast_when_a_majini_reaches_it_and_counts_the_bombs_gone():
    m = MN.Mines({})
    m.new_round(0.0)
    bomb = {"ptr": 0x77, "pos": (0.0, 0.0, 300.0)}
    m.bombs = {0x77: bomb["pos"]}
    live = [{"ptr": 10, "pos": (0.0, 0.0, 500.0), "hp": 800}]                    # 2 m from the bomb, him 3 m from it
    act = m.tick(p(), snap(ground=[bomb]), live, 1.0)
    assert act["hold"][:2] == MN.RUN and m.stats["mine_clear_runs"] == 1
    assert m.stats["mine_status"] == "a Majini at his bomb: out of its blast"
    m.tick(p(pos=(0.0, 0.0, -200.0)), snap(ground=[bomb]), live, 1.2)
    assert m.stats["mine_clear_runs"] == 1                                       # the same run
    assert m.tick(p(pos=(0.0, 0.0, -600.0)), snap(ground=[bomb]), live, 1.6) is None   # out of BLAST_CM: done
    far = [{"ptr": 10, "pos": (0.0, 0.0, 1500.0), "hp": 800}]
    assert m.tick(p(), snap(ground=[bomb]), far, 2.0) is None                    # nobody at it: no run
    assert m.tick(p(), snap(), far, 2.1) is None                                 # it left line 11: it went off
    assert m.stats["mines_gone"] == 1 and m.bombs == {}


def bot_snap(inv, enemies=((0.0, 0.0, 900.0),), motion=0):
    return {"player": {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000, "motion": motion},
            "enemies": [{"ptr": 10 + i, "pos": e, "hp": 800, "hp_max": 800} for i, e in enumerate(enemies)],
            "inventory": inv, "timer": 100.0, "timer_start": 120.0,
            "laser": {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


@pytest.fixture
def switch_bot(monkeypatch):
    from gbox.mercs.titles import re5_switch as R
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "CROWD_FIRE", False)   # (these test the paths under the crowd fire; tests/test_re5_switch_crowd.py)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    clock = [0.0]
    return R, R.Bot(stats={}, clock=lambda: clock[0]), clock


def test_the_switch_bot_places_a_bomb_between_its_heal_and_its_fight(switch_bot):
    R, b, clock = switch_bot
    s = bot_snap([dict(GUN), dict(BOMB)])
    assert b.tick(s)["hold"] == ("zl",) and b.doing == "raise"            # the fight first ...
    clock[0] = R.MINE_EVERY_S + 0.1
    assert b.tick(s) == {"hold": ()} and b.doing == "mine"                # ... the bomb's turn after MINE_EVERY_S
    for key in ("mines_placed", "mines_gone", "mine_clear_runs", "gun_backs", "t_mine", "t_rearm"):
        assert key in R.RE5Switch.round_counters


def test_the_fight_never_raises_a_bomb_or_a_grenade_the_gun_comes_back_first(switch_bot):
    R, b, clock = switch_bot
    b.mines = None
    for item in (BOMB, dict(BOMB, id=0x106, item=0x06)):                  # the proximity bomb, a hand grenade
        b._gun_back_at = -1e9
        s = bot_snap([dict(GUN, hand=False), dict(item, hand=True)])
        clock[0] += 5.0
        assert b.tick(s) == {"tap": "dleft"} and b.doing == "rearm"       # the M92F's D-pad, never ZL
        clock[0] += 0.2
        assert b.tick(s) == {"hold": ()}                                  # the pad neutral between taps
        clock[0] += R.GUN_BACK_GAP_S
        assert b.tick(s) == {"tap": "dleft"}
    assert b.stats["gun_backs"] == 4
    clock[0] += 1.0
    assert b.tick(bot_snap([dict(GUN), dict(BOMB)]))["hold"] == ("zl",)   # the gun in hand: the fight again


def test_the_ground_bombs_are_the_uwp0a_units_of_sunits_line_11():
    from gbox.mercs.titles import re5_switch as R
    from tests.test_re5_switch import BASE, round_guest
    from tests.test_re5_switch_mods import put_slot
    R._CLASSES.clear()                                                    # (fake guests reuse vtable addresses)
    g = round_guest(units=((R.MINE_LINE, "uWp72"), (R.MINE_LINE, "uWp0a"), (R.MINE_LINE - 1, "uWp0a")))
    su = R.u64(g, BASE + R.S_UNIT)
    first = R.u64(g, su + R.UNIT_LINES + R.LINE_STRIDE * R.MINE_LINE)
    bomb = R.u64(g, first + R.UNIT_NEXT)
    g.put(bomb + R.E_POS, struct.pack("<3f", 1483.0, 553.0, 523.0))
    assert "ground_mines" not in R.snapshot(g)                            # no bomb in the inventory: not read
    put_slot(g, 1, 0x10A, 5, 1)
    assert R.snapshot(g)["ground_mines"] == [{"ptr": bomb, "pos": (1483.0, 553.0, 523.0)}]   # line 11's only
    R._CLASSES.clear()


def test_a_blast_window_counts_the_kills_and_his_health_lost_around_the_bombs_leaving_the_line():
    m = MN.Mines({})
    m.new_round(0.0)
    bomb = {"ptr": 0x77, "pos": (0.0, 0.0, 300.0)}
    m.bombs = {0x77: bomb["pos"]}

    def tick(t, kills, hp, down):
        s = dict(snap(ground=[bomb] if down else []), kills=kills)
        m.watch(dict(p(), hp=hp), s, t)
    tick(1.0, 5, 1000, True)
    tick(1.1, 8, 300, True)                  # live 2026-10-27: the kills and his loss a poll before the units left
    tick(1.2, 8, 300, False)                 # gone: the window opens 0.6 s back
    tick(1.2, 8, 300, False)                 # (the same tick again: counted once)
    assert m.stats["mines_gone"] == 1 and m.stats["mine_blasts"] == 1 and m.stats["mine_kills"] == 0
    tick(1.4, 9, 300, False)
    tick(1.7, 9, 300, False)                 # past BLAST_AFTER_S: closed
    assert m.stats["mine_kills"] == 4 and m.stats["mine_blast_hp_loss"] == 700
    tick(5.0, 12, 200, False)                # later kills and hits are not the bombs'
    assert m.stats["mine_kills"] == 4 and m.stats["mine_blast_hp_loss"] == 700


def test_the_bot_watches_its_bombs_every_tick_even_while_held(switch_bot):
    R, b, clock = switch_bot
    b.tick(bot_snap([dict(GUN), dict(BOMB)]))                            # the round starts (its bombs reset)
    b.mines.bombs = {0x77: (0.0, 0.0, 300.0)}
    s = bot_snap([dict(GUN), dict(BOMB)], motion=106)
    s["ground_mines"], s["kills"] = list(STACK), 3
    clock[0] = 1.0
    b.tick(s)
    assert b.doing == "held" and b.stats["mines_gone"] == 1 and b.stats["mine_blasts"] == 1
    for key in ("mine_blasts", "mine_kills", "mine_blast_hp_loss"):
        assert key in R.RE5Switch.round_counters


def test_the_2026_10_30_cluster_a_majini_in_the_blast_is_blocked_even_when_foeclear_is_clear():
    # The live cluster: the closest Majini 1000-1500 cm away on the flat metric (past FOE_CLEAR_CM=500) but the bomb's
    # blast (BLAST_CM=800, radial on the ground) still reached him. The placement gate now blocks at BLAST_CM, so the
    # bomb is never down while anyone is in it. Built from the example fields: hp_before 1520 -> 1020/1420/1390,
    # motion 20/96 (no placing motion 29), held () (no ZL), plan walk.
    m = MN.Mines({})
    m.new_round(0.0)
    # The Majini is at flat distance 700 cm (inside BLAST_CM=800) but on a roof 50 m above: the bot's live filter
    # (MAX_DY vertical tolerance) would have dropped it, yet the flat (x,z) distance in due() catches it.
    live = [{"ptr": 10, "pos": (700.0, 5000.0, 0.0), "hp": 800}]
    pos = (0.0, 0.0, 0.0)
    snap = {"inventory": [dict(GUN), dict(BOMB)]}
    assert m.due({"pos": pos}, snap, live, MN.EVERY_S + 1) is None
    assert m.stats["mine_status"] == "a Majini in the bomb's blast radius: not placing"


def test_the_blast_gate_does_not_block_when_the_closest_majini_is_far_enough():
    # A Majini at 1500 cm flat (the cluster's upper bound, outside BLAST_CM=800) does not block placement.
    m = MN.Mines({})
    m.new_round(0.0)
    live = [{"ptr": 10, "pos": (1500.0, 0.0, 0.0), "hp": 800}]
    pos = (0.0, 0.0, 0.0)
    snap = {"inventory": [dict(GUN), dict(BOMB)]}
    assert m.due({"pos": pos}, snap, live, MN.EVERY_S + 1) == "due"
