"""RE5 Switch proximity bombs left behind (gbox.mercs.titles.re5_switch_mines), on the live facts of 2026-10-27: one
every EVERY_S of the round, never with a Majini within FOE_CLEAR_CM or beside a bomb still down, the pad neutral
before the D-pad, ZL tapped (held, a second bomb), confirmed by a new uWp0a unit near him, the
placing motion played out, the run out of the blast (never back over the bomb), the gun back; the blast guard; the
fight never raising a bomb (re5_switch.Bot._gun_back); the ground bombs read from sUnit's line 11."""
import math
import struct

import pytest

from gbox.mercs.titles import re5_switch_mines as MN

GUN = {"slot": 3, "id": 0x102, "type": 1, "item": 0x02, "rounds": 50, "cap": 50, "grid": 3, "hand": True}
BOMB = {"slot": 1, "id": 0x10A, "type": 1, "item": 0x0A, "rounds": 5, "cap": 5, "grid": 1, "hand": False}
STACK = [{"ptr": 0x5D4C7E4280, "pos": (-3000.0, -8.0, -2000.0)}, {"ptr": 0x5D4C8DCF80, "pos": (557.0, 158.0, 1409.0)}]


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


def dwelt(m, ptr=0x77):
    """He has stood beside that quiet bomb CALM_DWELL_S already (walking past one is no concern of the guard)."""
    m.__dict__.setdefault("_calm_since", {})[ptr] = -1e9


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
    assert m.tick(p(), snap(), foes((400, 0)), MN.EVERY_S + 1) is None           # blocked: the fight keeps the pad
    assert m.state == "idle" and m.stats["mine_blocked_reason"] == "enemy too close"
    # an unconfirmed press may have left a bomb nobody saw: its site keeps the spacing for UNCONFIRMED_SITE_S
    m.last_at, m.last_pos, m._site_until = 0.0, (500.0, 0.0, 0.0), MN.EVERY_S + 5
    assert m.tick(p(), snap(), foes((1200, 0)), MN.EVERY_S + 1) is None
    assert m.state == "idle" and m.stats["mine_blocked_reason"] == "last bomb too close"
    m._site_until = None
    m.last_pos, m.bombs = (900.0, 0.0, 0.0), {0x77: (0.0, 0.0, -300.0)}
    # a quiet bomb of his 3 m off (nobody near it): no guard run while he only passes it (CALM_DWELL_S), and no
    # placement starts beside it (SPACING_CM) - the pad stays the fight's
    act = m.tick(p(), snap(ground=[{"ptr": 0x77, "pos": (0.0, 0.0, -300.0)}]), foes((1200, 0)), MN.EVERY_S + 1)
    assert act is None and m.state == "idle" and m.stats["mine_blocked_reason"] == "last bomb too close"
    # ... a Majini nearing that bomb: out to the standoff
    near_it = [{"ptr": 31, "pos": (0.0, 0.0, -900.0), "hp": 800}]
    act = m.tick(p(), snap(ground=[{"ptr": 0x77, "pos": (0.0, 0.0, -300.0)}]), near_it, MN.EVERY_S + 1.1)
    assert act is not None and act["hold"][:2] == MN.RUN
    assert m.stats["mine_status"] == "a Majini nearing his bomb: out to the standoff"
    m.bombs = {}
    assert m.tick(p(), snap(), foes((1200, 0)), MN.EVERY_S + 1) == {"hold": ()} and m.state == "neutral"
    assert MN.Mines({}).tick(p(), {"inventory": [GUN]}, [], 99.0) is None        # no bomb in the inventory


def test_default_mine_cadence_waits_thirty_seconds_and_can_be_explicitly_configured():
    from gbox.mercs.titles import re5_switch as R
    from gbox.mercs.titles import re5_switch_mods as SM

    assert MN.EVERY_S == R.MINE_EVERY_S == SM.MINE_EVERY_DEFAULT == 30.0
    m = MN.Mines({})
    m.new_round(0.0)
    for now in (9.0, 29.9):
        assert m.tick(p(), snap(), [], now) is None
    assert m.tick(p(), snap(), [], 30.0) == {"hold": ()} and m.state == "neutral"
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
    assert m.tick(p(pos=(-800.0, 0.0, 0.0)), held(ground=[bomb]), live, t0 + 2.3)["hold"][:2] == MN.RUN   # 8 m: on
    off = -(MN.RETREAT_CM + 50.0)                                                # the operator's 15 m standoff
    assert m.tick(p(pos=(off, 0.0, 0.0)), held(ground=[bomb]), live, t0 + 2.6) == {"hold": ()}
    assert m.stats["mine_retreats_completed"] == 1 and m.state == "rearm"
    assert m.tick(p(), held(ground=[bomb]), live, t0 + 3.0) == {"tap": "dleft"}  # the M92F back
    assert m.tick(p(), snap(ground=[bomb]), live, t0 + 3.2) is None and m.state == "idle"
    assert m.tick(p(pos=(off - 50.0, 0.0, 0.0)), snap(ground=[bomb]), live, t0 + 4.0) is None   # the next waits EVERY_S


def tick_until(m, live, start, end, *, held_inv=None, step=0.5):
    """Tick at the engine's real cadence (it ticks every 0.05 s; GAP_S keeps test gaps inside one active window)."""
    t = start
    inv = held_inv
    while t < end:
        t = min(end, t + step)
        m.tick(p(), inv if inv is not None else held(), live, t)
    return t


def test_an_unconfirmed_press_still_leaves_when_the_placing_motion_was_seen_and_rearms_when_not():
    t = MN.EVERY_S
    m = MN.Mines({})
    m.new_round(0.0)
    to_place(m, [], t)
    t0 = t + MN.NEUTRAL_S + 0.2
    m.tick(p(motion=29), held(), [], t0 + 0.1)
    tick_until(m, [], t0 + 0.1, t0 + MN.PLACE_S + 0.1)
    act = m.tick(p(), held(), [], t0 + MN.PLACE_S + 0.2)
    assert m.stats["mine_unconfirmed"] == 1 and m.stats["mines_placed"] == 0
    assert m.state == "retreat" and act["hold"][:2] == MN.RUN and m.last_pos == (0.0, 0.0, 0.0)
    m = MN.Mines({})
    m.new_round(0.0)
    to_place(m, [], t)
    tick_until(m, [], t0, t0 + MN.PLACE_S + 0.1)
    assert m.tick(p(), held(), [], t0 + MN.PLACE_S + 0.2) == {"hold": ()}
    assert m.stats["mine_unconfirmed"] == 1 and m.state == "rearm"
    m = MN.Mines({})
    m.new_round(0.0)
    m.tick(p(), snap(), [], t)
    assert m.tick(p(), snap(), [], t + 0.1, busy=True) is None and m.state == "rearm"   # grabbed before the press


def test_a_falling_count_is_not_actor_proof_and_a_failed_equip_retries_without_satisfying_the_cadence():
    t = MN.EVERY_S
    m = MN.Mines({})
    m.new_round(0.0)
    to_place(m, [], t)
    t0 = t + MN.NEUTRAL_S + 0.2
    far = {"ptr": 0x5D778D13B0, "pos": (3000.0, 0.0, 400.0)}                     # a new uWp0a far off: not his
    m.tick(p(motion=29), held(ground=[far]), [], t0 + 0.3)
    assert m.stats["mines_placed"] == 0
    m.tick(p(motion=29), held(rounds=4, ground=[far]), [], t0 + 0.57)            # the flag off: the count falls
    assert m.stats["mines_placed"] == 0 and m.bombs == {} and m.state == "place"
    tick_until(m, [], t0 + 0.57, t0 + MN.PLACE_S + 0.1, held_inv=held(rounds=4))
    assert m.tick(p(), held(rounds=4), [], t0 + MN.PLACE_S + 0.2)["hold"][:2] == MN.RUN
    assert m.stats["mine_unconfirmed"] == 1 and m.state == "retreat"
    m = MN.Mines({})
    m.new_round(0.0)
    m.tick(p(), snap(), [], t)
    m.tick(p(), snap(), [], t + MN.NEUTRAL_S)
    tick_until(m, [], t + MN.NEUTRAL_S, t + MN.NEUTRAL_S + MN.EQUIP_S + 0.1, held_inv=snap())
    assert m.tick(p(), snap(), [], t + MN.NEUTRAL_S + MN.EQUIP_S + 0.2) is None
    assert m.stats["mine_equip_failures"] == 1 and m.last_at is None
    failed_at = t + MN.NEUTRAL_S + MN.EQUIP_S + 0.2
    assert t + MN.NEUTRAL_S + MN.EQUIP_S <= m._retry_at - MN.RETRY_S <= failed_at
    m.tick(p(), snap(), [], failed_at + .1)  # the gun was still in hand: rearm finishes
    assert m.tick(p(), snap(), [], failed_at + MN.RETRY_S) == {"hold": ()}
    assert m.state == "neutral"


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
    assert m.tick(p(pos=(0.0, 0.0, -600.0)), snap(ground=[bomb]), live, 1.4)["hold"][:2] == MN.RUN   # 9 m: not yet
    assert m.tick(p(pos=(0.0, 0.0, 250.0 - MN.BLAST_CM)), snap(ground=[bomb]), live, 1.6) is None   # out of BLAST_CM
    far = [{"ptr": 10, "pos": (0.0, 0.0, 1500.0), "hp": 800}]
    assert m.tick(p(), snap(ground=[bomb]), far, 2.0) is None                   # nobody at it: he may pass it
    act = m.tick(p(), snap(ground=[bomb]), far, 2.1 + MN.CALM_DWELL_S)          # ... standing by it: off it
    assert act is not None and act["hold"][:2] == MN.RUN
    assert m.stats["mine_status"] == "in his own bomb's blast: out before it detonates"
    assert m.tick(p(), snap(), far, 2.1) is None                                 # it left line 11: it went off
    assert m.stats["mines_gone"] == 1 and m.bombs == {}


def bot_snap(inv, enemies=((0.0, 0.0, 900.0),), motion=0):
    return {"player": {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000, "motion": motion},
            "enemies": [{"ptr": 10 + i, "pos": e, "hp": 800, "hp_max": 800} for i, e in enumerate(enemies)],
            "inventory": inv, "ground_mines": list(STACK), "timer": 100.0, "timer_start": 120.0,
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


def test_a_close_majini_outranks_the_blast_run_he_lets_go_and_the_fight_unloads_on_the_threat():
    # The cluster's remaining incidents (2026-10-31, bomb_cm 8-95, 4 of the 6 within 2 m of a Majini, 12 within 4 m,
    # one of them a death): he stood in the old bomb's blast while a Majini was right on him - the blast ran through
    # him and the crowd fire finished it. A run through a close crowd is a death: the bomb's timer is already
    # running, so the mine's own clear gives the pad up first (the gun goes back and the fight unloads on the threat,
    # re5_combat's within-5-m rule), instead of trying to run the gap with the crowd on him.
    m = MN.Mines({})
    m.new_round(0.0)
    bomb = {"ptr": 0x77, "pos": (0.0, 0.0, 300.0)}
    m.bombs = {0x77: bomb["pos"]}
    m.last_pos = (0.0, 0.0, -2000.0)                                # the old bomb, not the one he just placed
    live = [{"ptr": 10, "pos": (200.0, 0.0, 100.0), "hp": 800}]     # 2.2 m from him: within CLOSE_MAJINI_CM, in the blast
    act = m.tick(p(), snap(ground=[bomb]), live, 1.0)
    assert act is None                                              # combat really owns the next action
    assert m.stats["mine_status"] == "in the blast and a close Majini first: the gun up"
    assert m.state == "idle"                                         # no mine cycle started
    # The same bomb, a close Majini only beyond FOE_CLEAR_CM: the old guard still runs him out of the blast.
    far = [{"ptr": 10, "pos": (0.0, 0.0, 1500.0), "hp": 800}]
    dwelt(m)
    act = m.tick(p(pos=(0.0, 0.0, -50.0)), snap(ground=[bomb]), far, 1.4)    # 3.5 m from the old bomb: too near it
    assert act is not None and act["hold"][:2] == MN.RUN
    assert m.stats["mine_status"] == "in his own bomb's blast: out before it detonates"


def test_the_2026_10_30_cluster_in_own_blast_runs_out_even_with_no_majini_at_the_bomb():
    # The live cluster (186 hits, bomb_cm 26-416): his own proximity mine detonated while he stood in its blast, with
    # no Majini close enough to trigger it (the mine detonates on its own timer, so the old guard - Majini within
    # TRIGGER_CM of the bomb - never fired). He has already retreated from the bomb he just placed (last_pos points
    # to that other site); this is an *old* bomb still down, and he has drifted back into its radius on a later
    # cycle. The _clear guard fires whenever he is in an old bomb's blast, so he runs out before the detonation.
    # Built from the example fields: hp 1520 -> 1020/1420/1390, motion 20/96 (not the placing motion 29), held ()
    # (no ZL at the hit).
    m = MN.Mines({})
    m.new_round(0.0)
    bomb = {"ptr": 0x77, "pos": (0.0, 0.0, 300.0)}
    m.bombs = {0x77: bomb["pos"]}
    m.last_pos = (0.0, 0.0, -2000.0)                        # the bomb he just placed is far off; this one is old
    # The Majini is 1200 cm from the old bomb - well past TRIGGER_CM (350) - so it
    # neither triggers the mine nor is it the old guard's case. He is 300 cm from the old bomb: inside the blast.
    live = [{"ptr": 10, "pos": (0.0, 0.0, 1500.0), "hp": 800}]
    dwelt(m)                                                # (he stood there: passing it is CALM_DWELL_S's case)
    act = m.tick(p(), snap(ground=[bomb]), live, 1.0)
    assert act["hold"][:2] == MN.RUN and m.stats["mine_clear_runs"] == 1
    assert m.stats["mine_status"] == "in his own bomb's blast: out before it detonates"
    # He runs until he is out of the blast (RETREAT_CM from the site), then the guard stands down.
    m.tick(p(pos=(0.0, 0.0, -200.0)), snap(ground=[bomb]), live, 1.2)
    assert m.stats["mine_clear_runs"] == 1                                       # the same run, still in the blast
    assert m.tick(p(pos=(0.0, 0.0, 250.0 - MN.BLAST_CM)), snap(ground=[bomb]), live, 1.6) is None   # past BLAST_CM: out
    # Outside the blast the guard does not fire: no run, and a bomb with nobody near is left alone.
    m2 = MN.Mines({})
    m2.new_round(0.0)
    m2.bombs = {0x77: bomb["pos"]}
    m2.last_pos = (0.0, 0.0, -2000.0)
    assert m2.tick(p(pos=(0.0, 0.0, 250.0 - MN.BLAST_CM)), snap(ground=[bomb]), live, 2.0) is None   # past BLAST_CM
    # No enemies at all (the cluster's held=() / nearest-enemy-3m-on-far-side case): the guard still fires when he
    # is in an old bomb's blast, because the mine detonates on its own timer - no Majini trigger needed.
    m3 = MN.Mines({})
    m3.new_round(0.0)
    m3.bombs = {0x77: bomb["pos"]}
    m3.last_pos = (0.0, 0.0, -2000.0)
    dwelt(m3)
    act3 = m3.tick(p(), snap(ground=[bomb]), [], 1.0)
    assert act3["hold"][:2] == MN.RUN and m3.stats["mine_clear_runs"] == 1
    assert m3.stats["mine_status"] == "in his own bomb's blast: out before it detonates"


def test_the_old_guard_still_fires_on_a_majini_at_the_bomb_and_the_status_differs():
    # Regression: the original guard case (a Majini within TRIGGER_CM of the bomb while he is in the blast) still
    # fires, and reports its own distinct status, so the two cases are not conflated.
    m = MN.Mines({})
    m.new_round(0.0)
    bomb = {"ptr": 0x77, "pos": (0.0, 0.0, 300.0)}
    m.bombs = {0x77: bomb["pos"]}
    live = [{"ptr": 10, "pos": (0.0, 0.0, 450.0), "hp": 800}]                    # 150 cm from the bomb: at it
    act = m.tick(p(), snap(ground=[bomb]), live, 1.0)
    assert act["hold"][:2] == MN.RUN and m.stats["mine_clear_runs"] == 1
    assert m.stats["mine_status"] == "a Majini at his bomb: out of its blast"


def test_incident_replay_runs_out_of_own_bombs_blast_from_the_recorded_fields():
    # #5068: replay the recorded cluster incident (bot 221 cm from his own mine, no Majini at the mine) through the
    # incident_replay harness. Before the fix the old guard only fired when a Majini was within TRIGGER_CM of the
    # bomb, so the bot stood in the blast and took the hit; the fix runs him out whenever he is in an old bomb's
    # blast, regardless of Majini proximity.
    from pathlib import Path
    from gbox.mercs import incident_replay
    path = Path(__file__).parent / "fixtures" / "mercs_incidents" / "re5_switch_own_bomb_in_blast.json"
    fixture = __import__("json").loads(path.read_text(encoding="utf-8"))
    res = incident_replay.replay(fixture, ticks=1)
    b = res["bot"]
    # the bot has this bomb down from an earlier cycle this round (seed from the fixture's ground_mines)
    for g in fixture["snapshot"]["ground_mines"]:
        b.mines.bombs[g["ptr"]] = tuple(g["pos"])
    scene = __import__("copy").deepcopy(fixture["snapshot"])
    act = b.tick(scene)
    assert b.doing == "mine" and act["hold"][:2] == MN.RUN
    assert b.stats["mine_clear_runs"] == 1
    assert b.stats["mine_status"] in ("in his own bomb's blast: out before it detonates",
                                       "a Majini nearing his bomb: out to the standoff",
                                       "a Majini at his bomb: out of its blast")


def test_mid_cycle_guard_aborts_place_when_in_old_bomb_blast():
    # #5068 third fix: the cluster's remaining incidents (2026-10-31, rate 1.131 vs baseline 0.833) show
    # held=['zl'] - the bot was mid-place (bomb in hand) when the blast hit him. The idle-only _clear never
    # fires during a cycle, so he stands in an old bomb's blast while placing a new one. This guard aborts
    # the place cycle and runs him out before the detonation.
    m = MN.Mines({})
    m.new_round(0.0)
    # An old bomb from a previous cycle, 300 cm from him (inside BLAST_CM=800)
    old_bomb = {"ptr": 0x77, "pos": (300.0, 0.0, 0.0)}
    # The bomb is in the snapshot's ground_mines (the real source), not necessarily in self.bombs
    snap = {"ground_mines": [old_bomb]}
    m.last_pos = None  # no recent placement
    # He is at origin, mid-place cycle (bomb in hand, held=['zl'])
    live = []  # no Majini
    act = m._clear_mid_cycle({"pos": (0.0, 0.0, 0.0), "rot": 0.0}, snap, live, 100.)
    assert act is not None
    assert act["hold"][:2] == MN.RUN
    assert m.stats["mine_clear_runs"] == 1
    assert m.state == "retreat"
    assert m.stats["mine_status"] == "in an old bomb's blast mid-cycle: aborting and running out"


def test_mid_cycle_guard_fires_for_unconfirmed_mines_not_in_self_bombs():
    # #5068 fourth fix (this one): the incident replay fixtures (2026-10-31) show mines 8-285 cm from the
    # bot with held=['zl'] (mid-place). Those mines are in the snapshot's ground_mines but NOT in
    # self.bombs - they were unconfirmed placements or from a prior round. The previous mid-cycle guard
    # only checked self.bombs, so it never fired for them. Now the guard checks ground_mines directly.
    m = MN.Mines({})
    m.new_round(0.0)
    # A mine 100 cm from the bot, in ground_mines but NOT in self.bombs (unconfirmed placement)
    unconfirmed = {"ptr": 0x99, "pos": (100.0, 0.0, 0.0)}
    snap = {"ground_mines": [unconfirmed]}
    assert m.bombs == {}  # not tracked
    m.last_pos = None
    live = []
    act = m._clear_mid_cycle({"pos": (0.0, 0.0, 0.0), "rot": 0.0}, snap, live, 100.)
    assert act is not None
    assert act["hold"][:2] == MN.RUN
    assert m.state == "retreat"
    assert m.stats["mine_clear_runs"] == 1


def test_mid_cycle_guard_skips_the_bomb_just_placed():
    # The bomb he just placed (last_pos) is skipped by the mid-cycle guard - the retreat state machine
    # already handles that one.
    m = MN.Mines({})
    m.new_round(0.0)
    # The bomb he just placed is 300 cm from him (inside blast), but last_pos points to it
    just_placed = {"ptr": 0x77, "pos": (300.0, 0.0, 0.0)}
    snap = {"ground_mines": [just_placed]}
    m.last_pos = (300.0, 0.0, 0.0)  # this is the one he just placed
    act = m._clear_mid_cycle({"pos": (0.0, 0.0, 0.0), "rot": 0.0}, snap, [], 100.)
    assert act is None  # skipped: last_pos matches


def test_mid_cycle_guard_fires_outside_blast_radius():
    # No guard when outside BLAST_CM.
    m = MN.Mines({})
    m.new_round(0.0)
    far = {"ptr": 0x77, "pos": (MN.BLAST_CM + 100.0, 0.0, 0.0)}  # outside BLAST_CM
    snap = {"ground_mines": [far]}
    act = m._clear_mid_cycle({"pos": (0.0, 0.0, 0.0), "rot": 0.0}, snap, [], 100.)
    assert act is None


def test_the_sidebar_cadence_and_clearance_reach_a_running_bot_every_tick(monkeypatch):
    """Operator 2026-10-31 ("I want to see them dropping more mines in RE5"): MINE_EVERY_S set from the sidebar after the
    bot was built still shortens its cadence, and the driver's MINE_FOE_CLEAR_CM / MINE_SPACING_CM are what due() uses."""
    m = MN.Mines({}, every_s=120.0)
    m.configure({"enabled": True, "interval_s": 60.0})
    m.every_s = min(m.every_s, 5.0)                       # what the driver does each tick with MINE_EVERY_S = 5
    m.foe_clear_cm, m.spacing_cm = 400.0, 450.0
    m.new_round(0.0)
    assert m.every_s == 5.0
    assert m.due(p(), snap(), foes((420, 0)), 5.0) == "due"           # a Majini at 4.2 m: placed now (was 5 m)
    assert m.due(p(), snap(), foes((380, 0)), 5.0) is None            # ... at 3.8 m: not yet


def test_a_blocked_due_bomb_never_takes_the_pad_and_goes_down_once_the_site_is_clear():
    """Until 2026-11-09 a due bomb that was blocked ran him "to a clear placement site" 1.5 s of every 4.5, away from
    the last bomb into whatever wall stood there, against the fight's own heading: the standing the operator watched
    ("the bot should not sit idle and let these enemies sit idle"). The fight and the map move him now."""
    assert MN.RELOCATE_RUN is False
    m = MN.Mines({})
    m.new_round(0.0)
    live = foes((200, 0))                                    # inside the floor: no overdue time makes this plantable
    now = MN.EVERY_S + 7.0
    for dt in (0.0, 0.5, 1.5, 3.0, 4.5):
        assert m.tick(p(), snap(), live, now + dt) is None
    assert m.stats["mine_overdue_s"] == 11.5 and not m.stats["mine_relocating"]
    assert m.stats["mine_attempts"] == 0 and m.last_at is None      # still due
    # Two metres on (the fight moved him) the Majini is outside the margin an overdue bomb accepts.
    assert m.tick(p(pos=(0., 0., -200.)), snap(), live, now + 5.0) == {"hold": ()}
    assert m.state == "neutral" and not m.stats["mine_relocating"]


def combo(left, n=12, **kw):
    return dict(snap(**kw), combo=n, combo_timer=left)


def test_a_due_bomb_waits_for_the_window_right_after_a_kill_while_a_combo_runs():
    """Operator 2026-11-09: "it is important to never ever lose the combo ... the amount of time left in it at all times
    and manage it" - and "I want the bot always placing mines". A plant takes the gun away for seconds, so it starts
    with most of the window left, and only a bomb long overdue goes down regardless."""
    m = MN.Mines({})
    m.new_round(0.0)
    far = foes((1200, 0))
    t = MN.EVERY_S + 1.0
    assert m.tick(p(), combo(5.0), far, t) is None and m.state == "idle"          # the window half gone: not now
    assert m.stats["mine_blocked_reason"] == "the combo's window: after the next kill"
    assert m.stats["mine_combo_waits"] == 1
    assert m.tick(p(), combo(9.6), far, t + 0.5) == {"hold": ()} and m.state == "neutral"   # he just killed: now
    m2 = MN.Mines({})
    m2.new_round(0.0)
    late = MN.EVERY_S + MN.COMBO_WAIT_S + 0.1                                     # that long overdue: whatever the window
    assert m2.tick(p(), combo(5.0), far, late) == {"hold": ()} and m2.state == "neutral"
    m3 = MN.Mines({})
    m3.new_round(0.0)
    assert m3.tick(p(), snap(), far, t) == {"hold": ()}                           # no combo: on time


def test_the_run_out_ends_for_the_combo_once_he_is_out_of_the_blast():
    m = MN.Mines({})
    m.new_round(0.0)
    m.state, m.t, m.site = "retreat", 100.0, (0.0, 0.0, 0.0)
    out = p(pos=(0.0, 0.0, MN.COMBO_STANDOFF_CM + 50.0))
    assert MN.COMBO_STANDOFF_CM < MN.RETREAT_CM
    assert m.tick(out, combo(8.0), [], 100.5)["hold"][:2] == MN.RUN and m.state == "retreat"   # time in hand: on to 15 m
    assert m.tick(out, combo(MN.COMBO_CUT_S), [], 101.0) == {"hold": ()} and m.state == "rearm"
    assert m.stats["mine_combo_cuts"] == 1
    m.state, m.t = "retreat", 102.0
    inside = p(pos=(0.0, 0.0, MN.COMBO_STANDOFF_CM - 100.0))
    assert m.tick(inside, combo(1.0), [], 102.5)["hold"][:2] == MN.RUN            # still in the blast: the run goes on


def test_the_guard_asks_the_shorter_standoff_while_the_combo_window_runs_out():
    m = MN.Mines({})
    m.new_round(0.0)
    m.bombs = {0x77: (0.0, 0.0, 0.0)}
    ground = [{"ptr": 0x77, "pos": (0.0, 0.0, 0.0)}]
    him = p(pos=(0.0, 0.0, 1000.0))                                               # 10 m off his bomb
    at_it = [{"ptr": 31, "pos": (0.0, 0.0, -500.0), "hp": 800}]                   # a Majini nearing it
    m.last_at = 0.0
    assert m.tick(him, combo(9.0, ground=ground), at_it, 5.0)["hold"][:2] == MN.RUN      # 15 m while there is time
    assert m.tick(him, combo(MN.COMBO_CUT_S - 0.5, ground=ground), at_it, 5.1) is None   # 8 m with the window short


def test_an_overdue_bomb_accepts_a_closer_crowd_down_to_the_floor_whatever_his_health():
    """lilspark 2026-11-09, No Mercy: a Majini stood inside the 4 m margin for 195 s on end and one bomb went down in 11
    minutes. The margin shrinks over RELAX_S of overdue time to FOE_FLOOR_CM. No health condition: asked whether to
    plant less when it hurts him, the operator said "mines are non negotiable ... I want the bot always placing mines"."""
    m = MN.Mines({})
    m.new_round(0.0)
    m.foe_clear_cm = 400.0
    live = foes((300, 0))
    live = foes((MN.FOE_FLOOR_CM + 20, 0))                                       # just outside the floor
    assert m.tick(p(), snap(), live, MN.EVERY_S + 1.0) is None                    # 1 s overdue: still blocked
    assert m.stats["mine_blocked_reason"] == "enemy too close"
    assert m.stats["mine_clearance_cm"] == round(400.0 - (400.0 - MN.FOE_FLOOR_CM) / MN.RELAX_S, 1)
    m = MN.Mines({})
    m.new_round(0.0)
    m.foe_clear_cm = 400.0
    assert m.tick(p(), snap(), live, MN.EVERY_S + MN.RELAX_S) == {"hold": ()}    # the floor: 250 cm, 300 is clear
    assert m.state == "neutral" and m.stats["mine_clearance_cm"] == MN.FOE_FLOOR_CM
    m = MN.Mines({})
    m.new_round(0.0)
    m.foe_clear_cm = 400.0
    assert m.tick(p(), snap(), foes((MN.FOE_FLOOR_CM - 10, 0)), MN.EVERY_S + 60.0) is None   # never inside the floor
    assert m.state == "idle" and m.stats["mine_blocked_reason"] == "enemy too close"
    hurt = dict(p(), hp=400)
    m = MN.Mines({})
    m.new_round(0.0)
    m.foe_clear_cm = 400.0
    assert m.tick(hurt, snap(), live, MN.EVERY_S + 60.0) == {"hold": ()} and m.state == "neutral"   # hurt: still planting
    assert MN.RELAX_HP == 0.0 and m.stats["mine_clearance_cm"] == MN.FOE_FLOOR_CM


def test_the_site_of_a_bomb_that_went_off_no_longer_blocks_the_next_one():
    """2026-11-09: 40 s of a round "moving away from the last bomb" whose blast was long over."""
    m = MN.Mines({})
    m.new_round(0.0)
    t = MN.EVERY_S
    to_place(m, [], t)
    t0 = t + MN.NEUTRAL_S + 0.2
    bomb = {"ptr": 0x5D4D7ABC10, "pos": (-3.0, 3.0, 57.0)}
    m.tick(p(motion=29), held(ground=[bomb]), [], t0 + 0.69)
    assert m.stats["mines_placed"] == 1 and m.last_pos == bomb["pos"] and m._site_until is None
    m.state = "idle"                                          # (the retreat and the rearm are other tests')
    due = t0 + 0.69 + MN.EVERY_S + 0.1
    # still down and he is beside it: the spacing holds (the guard runs him out of its blast first)
    assert m.tick(p(), snap(ground=[bomb]), [], due) is None and m.state == "idle"
    # it went off: he may plant right there
    assert m.tick(p(), snap(), [], due + 0.05) is None or m.state == "neutral"
    assert m.stats["mines_gone"] == 1
    assert m.tick(p(), snap(), [], due + 1.0) == {"hold": ()} and m.state == "neutral"


def test_overdue_close_crowd_seeks_space_without_planting_and_yields_to_explicit_emergency():
    m = MN.Mines({})
    m.new_round(0.)
    now = MN.EVERY_S + 1
    assert m.tick(p(), snap(), foes((200, 0)), now) is None      # blocked: the fight makes the space (RELOCATE_RUN)
    assert m.state == "idle" and m.stats["mine_attempts"] == 0
    assert m.tick(p(), snap(), [], now + 1, busy=True) is None
    assert m.stats["mine_blocked_reason"] == "emergency action" and not m.stats["mine_relocating"]
    assert m.tick(p(pos=(0., 0., -400.)), snap(), foes((200, 0)), now + 2) == {"hold": ()}
    assert m.state == "neutral" and m.stats["mine_attempts"] == 0


def test_enemy_closing_during_equip_prevents_press_and_missing_ground_scan_cannot_start():
    m = MN.Mines({})
    m.new_round(0.)
    now = MN.EVERY_S
    missing = snap()
    missing.pop("ground_mines")
    assert m.tick(p(), missing, [], now) is None
    assert m.stats["mine_blocked_reason"] == "ground mine observation unavailable"
    assert m.tick(p(), snap(), [], now + 1) == {"hold": ()}
    assert m.tick(p(), snap(), [], now + 1 + MN.NEUTRAL_S) == {"tap": "dup"}
    assert m.tick(p(), held(), foes((200, 0)), now + 1 + MN.NEUTRAL_S + .2) == {"hold": ()}
    assert m.state == "rearm" and m.stats["mines_placed"] == 0
    assert m.stats["mine_blocked_reason"] == "enemy too close"


def test_inventory_disappearance_or_count_drop_never_counts_as_a_native_bomb_actor():
    m = MN.Mines({})
    m.new_round(0.)
    to_place(m, [], MN.EVERY_S)
    now = MN.EVERY_S + MN.NEUTRAL_S + .2
    for offset, inventory in ((.3, []), (.5, [dict(BOMB, rounds=4)]), (.6, [dict(BOMB, rounds=0)])):
        m.tick(p(motion=29), {"inventory": inventory, "ground_mines": STACK}, [], now + offset)
        assert m.stats["mines_placed"] == 0 and "mine_last_confirmation" not in m.stats
        assert m.stats["mine_last_actor"] == 0 and m.stats["mine_last_placed_at"] == 0.0
    actor = {"ptr": 0x123456, "pos": (0., 3., 57.)}
    m.tick(p(motion=29), held(ground=[actor]), [], now + .7)
    assert m.stats["mines_placed"] == 1
    assert m.stats["mine_last_confirmation"] == {"source": "native_uWp0a_actor", "ptr": actor["ptr"],
        "pos": list(actor["pos"]), "at": now + .7}
    assert m.stats["mine_last_actor"] == actor["ptr"] and m.stats["mine_last_placed_at"] == now + .7
    m.tick(p(motion=29), held(ground=[actor]), [], now + .8)
    assert m.stats["mines_placed"] == 1
    m.new_round(now + 5.)
    assert "mine_last_confirmation" not in m.stats
    assert m.stats["mine_last_actor"] == 0 and m.stats["mine_last_placed_at"] == 0.0


def test_an_existing_actor_or_new_actor_on_another_floor_is_not_placement_proof():
    m = MN.Mines({})
    m.new_round(0.)
    to_place(m, [], MN.EVERY_S)
    now = MN.EVERY_S + MN.NEUTRAL_S + .2
    reused = dict(STACK[0], pos=(0., 0., 57.))
    upper_floor = {"ptr": 0x123456, "pos": (0., 400., 57.)}
    m.tick(p(motion=29), held(ground=[reused, upper_floor]), [], now + .7)
    assert m.stats["mines_placed"] == 0 and "mine_last_confirmation" not in m.stats


def test_mid_cycle_escape_keeps_actual_bomb_site_and_current_clock_on_later_ticks():
    m = MN.Mines({})
    m.new_round(0.)
    m.state, m.t, m.site = "place", 99., (0., 0., -1000.)
    bomb = {"ptr": 0x77, "pos": (300., 0., 0.)}
    state = held(ground=[bomb])
    assert m.tick(p(), state, [], 100.)["hold"][:2] == MN.RUN
    assert m.state == "retreat" and m.t == 100. and m.site == bomb["pos"]
    # The player has no timestamp field, and is far from the abandoned planting
    # site but only 3 m from the real hazard. Neither may end the escape early.
    assert m.tick(p(), state, [], 100.1) == m._run(p(), [], bomb["pos"])
    assert m.state == "retreat" and m.stats["mine_retreats_completed"] == 0
    assert m.tick(p(pos=(-600., 0., 0.)), state, [], 100.3)["hold"][:2] == MN.RUN   # 9 m from it: on
    assert m.tick(p(pos=(250. - MN.RETREAT_CM, 0., 0.)), state, [], 100.5) == {"hold": ()}
    assert m.state == "rearm" and m.stats["mine_retreats_completed"] == 1


def test_close_blast_guard_yields_to_gun_before_due_then_due_mine_seeks_clearance(switch_bot):
    R, bot, clock = switch_bot
    state = bot_snap([dict(GUN), dict(BOMB)], enemies=((200., 0., 100.),))
    bot.tick(state)
    bomb = {"ptr": 0x77, "pos": (0., 0., 300.)}
    bot.mines.bombs = {bomb["ptr"]: bomb["pos"]}
    bot.mines.last_pos = (0., 0., -2000.)
    state["ground_mines"] = list(STACK) + [bomb]
    state["inventory"] = [dict(GUN, hand=False), dict(BOMB, hand=True)]
    assert bot.mines._clear(state["player"], state, state["enemies"]) is None
    clock[0] = 1.
    assert bot.tick(state) == {"tap": "dleft"}
    assert bot.doing == "rearm" and bot.mines.state == "idle"
    assert bot.stats["mine_attempts"] == bot.stats["mines_placed"] == 0
    clock[0] = R.MINE_EVERY_S + 1
    bot.tick(state)                                          # due and blocked: the fight keeps the pad, no plant
    assert bot.doing != "mine" and bot.mines.state == "idle"
    assert bot.stats["mine_blocked_reason"] in ("enemy too close", "last bomb too close")
    assert bot.stats["mine_attempts"] == bot.stats["mines_placed"] == 0

def test_a_long_tick_gap_pauses_the_equip_clock_instead_of_failing_the_attempt():
    """Live 2026-11-09: the first round after the supply change counted mine_attempts 1 / mine_equip_failures 1 -
    the tap was correct but the bot was grabbed by a Majini, and the wall clock ran the equip window out while the
    controller was not ticking. A gap longer than GAP_S pauses the cycle's clock instead."""
    m = MN.Mines({})
    m.new_round(0.0)
    live = []
    assert m.tick(p(), snap(), live, MN.EVERY_S) == {"hold": ()} and m.state == "neutral"
    assert m.tick(p(), snap(), live, MN.EVERY_S + MN.NEUTRAL_S) == {"tap": "dup"} and m.state == "equip"
    # a 4 s grab: no tick during it, the bomb still comes to hand just after
    t_after = MN.EVERY_S + MN.NEUTRAL_S + 4.0
    assert m.tick(p(), held(), live, t_after) == {"hold": ("zl",)} and m.state == "place"
    assert m.stats["mine_equip_failures"] == 0


def test_failed_rearm_cannot_renew_its_own_deadline_with_every_tap():
    m = MN.Mines({})
    m.new_round(0.0)
    m.state, m.t, m.gun_grid = 'rearm', 10.0, GUN['grid']
    actions = []
    for i in range(1, 26):
        actions.append(m.tick(p(), held(), [], 10.0 + i * .05))
    assert m.state == 'idle' and actions[-1] is None
    assert 1 <= sum(bool(a and a.get('tap')) for a in actions) <= 3
    assert m.stats['mines_placed'] == 0


def test_enemy_closing_during_equip_gives_combat_a_retry_window():
    m = MN.Mines({})
    m.new_round(0)
    m.state, m.t = 'equip', 40.0
    assert m.tick(p(), held(), foes((100, 0)), 40.1) == {'hold': ()}
    assert m.state == 'rearm' and m._retry_at == 40.1 + MN.RETRY_S
    assert m.tick(p(), snap(), [], 40.2) is None and m.state == 'idle'
    assert m.tick(p(), snap(), [], 40.3) is None  # even if the crowd briefly clears
    assert m.stats['mines_placed'] == 0


def test_a_bomb_in_hand_with_no_quick_grid_still_plants():
    """The equip press can leave the item's grid record outside QUICK: the hand flag alone is the plant's proof."""
    m = MN.Mines({})
    m.new_round(0.0)
    live = []
    m.state, m.t = "equip", MN.EVERY_S
    hand_only = dict(BOMB, grid=0, hand=True)
    inv = [dict(GUN, hand=False), hand_only]
    assert m.stack(inv) is None and m.equipped(inv) is hand_only
    act = m.tick(p(), {"inventory": inv, "ground_mines": STACK}, live, MN.EVERY_S + 0.2)
    assert act == {"hold": ("zl",)} and m.state == "place"
    assert m.stats["mine_equip_failures"] == 0


def test_an_empty_in_hand_stack_is_not_equipment():
    m = MN.Mines({})
    assert m.equipped([dict(BOMB, rounds=0, hand=True)]) is None
    assert m.equipped([dict(BOMB, rounds=5, hand=False)]) is None
    assert m.equipped([dict(BOMB, rounds=5, hand=True)]) is not None


def test_he_leaves_his_own_bomb_by_the_operators_fifteen_metres():
    """Operator 2026-11-09: "the bot should place themself at least 15 meters from the mine to avoid hurting
    themselves" - the universal doctrine's MINE_STANDOFF_M is both the run out and the stay-clear radius."""
    from gbox.mercs.core import doctrine
    assert doctrine.MINE_STANDOFF_M == 15.0
    assert MN.RETREAT_CM == MN.BLAST_CM == 1500.0
    assert MN.RETREAT_S * 400.0 >= MN.RETREAT_CM            # the cap leaves room for 15 m at a 4 m/s run


def test_the_stacks_dormant_unit_is_never_run_from_or_a_reason_to_give_up_a_plant():
    """The bomb stack keeps a uWp0a of its own on the line all round (STACK: Public Assembly's sits at 557, 158, 1409).
    Before the round's first plant - and after a bot reload - nothing had recorded it, and inside BLAST_CM of it he ran
    from "his own bomb" and gave up the placements he started (lilspark 2026-11-09: three attempts, none planted)."""
    m = MN.Mines({})
    m.new_round(0.0)
    near_it = (557.0 - 600.0, 0.0, 1409.0)                              # 6 m from the dormant unit, nobody about
    assert m.tick(p(pos=near_it), snap(), [], 1.0) is None              # no run: it was there before he planted anything
    assert m.stats["mine_clear_runs"] == 0 and m.baseline == {g["ptr"] for g in STACK}
    t = MN.EVERY_S
    assert m.tick(p(pos=near_it), snap(), [], t) == {"hold": ()} and m.state == "neutral"
    assert m.tick(p(pos=near_it), snap(), [], t + MN.NEUTRAL_S) == {"tap": "dup"}
    assert m.tick(p(pos=near_it), held(), [], t + MN.NEUTRAL_S + 0.2) == {"hold": ("zl",)} and m.state == "place"
    # a bomb that appears during the round is his to keep clear of, baseline or not
    bomb = {"ptr": 0x5D4D7ABC10, "pos": (near_it[0], 0.0, near_it[2] + 57.0)}
    m.tick(p(pos=near_it, motion=29), held(ground=[bomb]), [], t + MN.NEUTRAL_S + 0.9)
    assert m.stats["mines_placed"] == 1 and bomb["ptr"] not in m.baseline


def test_a_bomb_nobody_is_near_only_keeps_him_a_few_metres_off_and_one_a_majini_nears_the_whole_standoff():
    """lilspark 2026-11-09: a bomb lay in a trench for two minutes with no Majini coming; at the 15 m standoff the guard
    held him "in his own bomb's blast", turning on the spot beside it, for 116 s (three kills in six minutes)."""
    bomb = {"ptr": 0x77, "pos": (0.0, 0.0, 600.0)}
    nobody = [{"ptr": 10, "pos": (0.0, 0.0, 4000.0), "hp": 800}]             # 34 m from the bomb
    m = MN.Mines({})
    m.new_round(0.0)
    m.bombs = {0x77: bomb["pos"]}
    m.last_pos = (0.0, 0.0, -9000.0)
    assert m.tick(p(), snap(ground=[bomb]), nobody, 1.0) is None            # 6 m from a quiet bomb: free to fight
    assert m.stats["mine_clear_runs"] == 0
    assert m.tick(p(pos=(0.0, 0.0, 300.0)), snap(ground=[bomb]), nobody, 1.1) is None    # 3 m: passing it
    assert m.tick(p(pos=(0.0, 0.0, 300.0)), snap(ground=[bomb]), nobody, 1.2 + MN.CALM_DWELL_S)["hold"][:2] \
        == MN.RUN                                                              # standing by it: off it
    coming = [{"ptr": 10, "pos": (0.0, 0.0, 600.0 + MN.DANGER_CM - 50.0), "hp": 800}]   # a Majini nearing the bomb
    m2 = MN.Mines({})
    m2.new_round(0.0)
    m2.bombs = {0x77: bomb["pos"]}
    m2.last_pos = (0.0, 0.0, -9000.0)
    act = m2.tick(p(), snap(ground=[bomb]), coming, 1.0)                    # the same 6 m, now it may go off: out
    assert act["hold"][:2] == MN.RUN and m2.stats["mine_status"] == "a Majini nearing his bomb: out to the standoff"
    assert m2.tick(p(pos=(0.0, 0.0, 550.0 - MN.BLAST_CM)), snap(ground=[bomb]), coming, 1.2) is None   # past 15 m: done


def test_a_guard_run_that_gains_no_ground_gives_the_pad_back():
    """A wall or a dead end between him and the standoff: the run is given up for CLEAR_YIELD_S (the fight and the map
    move him), never turned on the spot for minutes."""
    bomb = {"ptr": 0x77, "pos": (0.0, 0.0, 300.0)}
    coming = [{"ptr": 10, "pos": (0.0, 0.0, 900.0), "hp": 800}]
    m = MN.Mines({})
    m.new_round(0.0)
    m.bombs = {0x77: bomb["pos"]}
    m.last_pos = (0.0, 0.0, -9000.0)
    t = 1.0
    assert m.tick(p(), snap(ground=[bomb]), coming, t)["hold"][:2] == MN.RUN
    while t < 1.0 + MN.CLEAR_STUCK_S:                                       # he does not move: a wall
        t += 0.05
        m.tick(p(), snap(ground=[bomb]), coming, t)
    assert m.tick(p(), snap(ground=[bomb]), coming, t + 0.1) is None       # given up: the fight has the pad
    assert m.stats["mine_clear_stuck"] == 1
    assert m.tick(p(), snap(ground=[bomb]), coming, t + MN.CLEAR_YIELD_S - 0.5) is None
    assert m.tick(p(), snap(ground=[bomb]), coming, t + MN.CLEAR_YIELD_S + 0.2)["hold"][:2] == MN.RUN   # tried again


def test_a_plant_already_in_hand_goes_down_unless_a_majini_is_inside_the_floor():
    """lilspark 2026-11-09: eight attempts for one bomb - the gun came down, the bomb came to hand, and the plant was
    given up because a Majini had stepped inside the on-time margin. With the bomb in hand only the floor stops it."""
    m = MN.Mines({})
    m.new_round(0.0)
    m.foe_clear_cm = 400.0
    t = MN.EVERY_S
    clear = foes((900, 0))
    assert m.tick(p(), snap(), clear, t) == {"hold": ()} and m.state == "neutral"
    assert m.tick(p(), snap(), clear, t + MN.NEUTRAL_S) == {"tap": "dup"}
    stepped_in = foes((320, 0))                                      # inside the 4 m margin, outside the 2.5 m floor
    assert m.tick(p(), held(), stepped_in, t + MN.NEUTRAL_S + 0.2) == {"hold": ("zl",)} and m.state == "place"
    m = MN.Mines({})
    m.new_round(0.0)
    m.foe_clear_cm = 400.0
    m.tick(p(), snap(), clear, t)
    m.tick(p(), snap(), clear, t + MN.NEUTRAL_S)
    on_him = foes((200, 0))                                          # inside the floor: not now
    assert m.tick(p(), held(), on_him, t + MN.NEUTRAL_S + 0.2) == {"hold": ()} and m.state == "rearm"


def test_after_a_flash_at_his_feet_nobody_near_him_blocks_the_plant():
    """Operator 2026-11-09: "I want it placing mines. Then flashbanging and running away and getting distance ... have
    him force his way out." While the Majini reel from his flash (flash_until) the bomb goes down among them."""
    m = MN.Mines({})
    m.new_round(0.0)
    on_him = foes((120, 0), (150, 90), (180, 200))                      # a crowd inside the floor
    t = MN.EVERY_S + MN.RELAX_S
    assert m.tick(p(), snap(), on_him, t) is None and m.state == "idle"                 # no flash: blocked
    m.flash_until = t + MN.FLASH_S
    assert m.tick(p(), snap(), on_him, t + 0.1) == {"hold": ()} and m.state == "neutral"
    assert m.tick(p(), snap(), on_him, t + 0.1 + MN.NEUTRAL_S) == {"tap": "dup"}
    assert m.tick(p(), held(), on_him, t + 0.3 + MN.NEUTRAL_S) == {"hold": ("zl",)} and m.state == "place"
    assert m.stats["mine_clearance_cm"] == 0.0


def test_the_bot_flashes_the_moment_a_bomb_is_down_and_to_open_the_way_for_an_overdue_one(switch_bot):
    R, bot, clock = switch_bot
    asked = []
    bot._native_flash = lambda snap_, now, reason, counter: asked.append(counter) or True
    state = bot_snap([dict(GUN), dict(BOMB)])
    bot.stats["mines_placed"] = 0
    bot._mine_flash(state, 100.0)
    assert asked == []                                                   # nothing down, nothing blocked
    bot.stats["mines_placed"] = 1                                        # the controller confirmed a bomb
    bot._mine_flash(state, 100.1)
    assert asked == ["mine_flashes"] and bot.mines.flash_until == 100.1 + MN.FLASH_S
    bot._mine_flash(state, 100.2)
    assert asked == ["mine_flashes"]                                     # once a bomb
    # an overdue bomb with the crowd inside the floor: a flash opens the way, MINE_FLASH_GAP_S apart
    bot.mines.state = "idle"
    bot.stats.update(mine_blocked_reason="enemy too close", mine_overdue_s=R.MINE_FLASH_OVERDUE_S + 1.0)
    bot._mine_flash(state, 200.0)
    assert asked == ["mine_flashes", "mine_preflashes"] and bot.mines.flash_until == 200.0 + MN.FLASH_S
    bot._mine_flash(state, 201.0)
    assert len(asked) == 2                                               # inside the gap: not again
    bot._mine_flash(state, 200.0 + R.MINE_FLASH_GAP_S + 0.1)
    assert len(asked) == 3


def test_a_bomb_laid_on_his_way_with_nobody_near_needs_no_run_out():
    """Operator 2026-11-09: "as the bot is walking the level without enemies around, they need to be placing mines as
    they are navigating to the enemies to dispatch them." Nobody within TRAIL_CM of the bomb: the gun back and on along
    his route; a Majini that near: the run out to the standoff as ever."""
    m = MN.Mines({})
    m.new_round(0.0)
    m.state, m.t, m.site = "settle", 50.0, (0.0, 0.0, 57.0)
    assert m.tick(p(), snap(), foes((MN.TRAIL_CM + 300, 0)), 50.0 + MN.SETTLE_S) == {"hold": ()}
    assert m.state == "rearm" and m.stats["mine_trail_plants"] == 1
    m.state, m.t, m.site = "settle", 60.0, (0.0, 0.0, 57.0)
    assert m.tick(p(), snap(), foes((900, 0)), 60.0 + MN.SETTLE_S)["hold"][:2] == MN.RUN
    assert m.state == "retreat" and m.stats["mine_trail_plants"] == 1


def test_the_bomb_press_repeats_until_it_is_in_hand_and_outlasts_the_native_equip_fallback():
    """Live 2026-11-09: 36 of 88 attempts "the bomb did not come to hand" - the bot swallows the D-pad press for a native
    equip request and lets a press through only after NATIVE_EQUIP_GIVEUP_S (2.0 s); one press in a 1.2 s window never
    reached that point."""
    from gbox.mercs.titles import re5_switch as R
    assert MN.EQUIP_S > R.NATIVE_EQUIP_GIVEUP_S
    m = MN.Mines({})
    m.new_round(0.0)
    t = MN.EVERY_S
    assert m.tick(p(), snap(), [], t) == {"hold": ()} and m.state == "neutral"
    assert m.tick(p(), snap(), [], t + MN.NEUTRAL_S) == {"tap": "dup"} and m.state == "equip"
    t0 = t + MN.NEUTRAL_S
    assert m.tick(p(), snap(), [], t0 + 0.2) == {"hold": ()}                           # waiting on the first press
    assert m.tick(p(), snap(), [], t0 + MN.EQUIP_RETAP_S + 0.01) == {"tap": "dup"}     # not in hand: again
    assert m.tick(p(), snap(), [], t0 + 2.2) == {"tap": "dup"}                         # (past the native give-up)
    assert m.stats["mine_equip_retaps"] == 2
    assert m.tick(p(), held(), [], t0 + 2.3) == {"hold": ("zl",)} and m.state == "place"   # in hand: the plant
    assert m.stats["mine_equip_failures"] == 0
