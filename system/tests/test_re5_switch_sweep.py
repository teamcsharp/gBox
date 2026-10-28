"""RE5 Switch turret sweep, keep moving and the aim's own pitch (operator 2026-10-27 17:31: "Chris stand there while
he's just being crowded ... Why is he looking up?"; 17:38: "holding down the trigger and just spinning around getting
all of these people that are ganging up on them"; 17:42: "It is important to continue moving around the level"):
crowded within 5 m the gun comes up, the trigger stays down and the aim pans one way at a steady pace (a dwell on a
Majini, never a reversal) until the circle is clear, then he relocates; no spot is held past DWELL_MAX_S with Majini
about; the aim's own pitch (player +0x3F5C) up at a Majini on his level pushes the aim down, never up."""
import math

import pytest

from gbox.mercs.titles import re5_switch as R

MUZZLE = (0.0, 140.0, 30.0)


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    monkeypatch.setattr(R, "MINES", False)
    monkeypatch.setattr(R, "SWEEP", True)                         # off in MercMode since 18:52 (#1383); the code is kept
    monkeypatch.setattr(R, "SWEEP", True)              # off in MercMode since 18:52 (it spun at ~1300 deg/s); the code is kept


def at(dist, deg, y=0.0):
    a = math.radians(deg)
    return (dist * math.sin(a), y, dist * math.cos(a))


def chest(foot):
    return (foot[0], foot[1] + R.CHEST_H, foot[2])


def snap(enemies, dot=None, motion=0, kills=None, aim_pitch=None, hp=1000, pos=(0.0, 0.0, 0.0), rot=0.0,
         bonuses=None, timer=None):
    s = {"player": {"ptr": 0x5D00001000, "pos": pos, "rot": rot, "hp": hp, "hp_max": 1000, "motion": motion,
                    "aim_pitch": aim_pitch},
         "enemies": [{"ptr": 10 + i, "pos": x, "hp": 800, "hp_max": 800} for i, x in enumerate(enemies)],
         "inventory": [], "kills": kills, "timer": timer, "timer_start": 120.0,
         "laser": {"from": MUZZLE, "at": dot, "up": True} if dot else {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}
    if bonuses is not None:
        s["bonuses"] = [{"ptr": 900 + i, "pos": b, "secs": 30} for i, b in enumerate(bonuses)]
    return s


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


# --- the sweep ---------------------------------------------------------------------------------------------------------
def test_three_within_5_m_the_gun_up_the_trigger_down_and_the_aim_pans_toward_the_heavier_side():
    b, clock = bot()
    ring = [at(300, 40), at(350, 100), at(250, -60)]               # two on his left (a larger heading), one right
    act = b.tick(snap(ring))
    assert b.doing == "sweep" and {"zl", "rleft"} <= set(act["hold"]) and "rright" not in act["hold"]
    assert "zr" not in act["hold"] and b.stats["sweeps"] == 1      # nobody under the aim yet: panning


def test_the_sweep_keeps_its_way_whatever_the_crowd_does_and_never_reverses():
    b, clock = bot()
    ring = [at(300, 40), at(350, 100), at(250, -60)]
    b.tick(snap(ring))
    for k in range(1, 30):                                         # they all go round to his right
        clock[0] = 0.05 * k
        act = b.tick(snap([at(300, -40), at(350, -100), at(250, -60)], motion=26))
        assert "rright" not in act["hold"] and "rleft" in act["hold"]
    assert b.stats["sweep_reversals"] == 0 and b.stats["sweeps"] == 1 and b.stats["sweep_s"] > 1.0


def test_on_a_majini_the_pan_stops_and_the_trigger_holds():
    b, clock = bot()
    ring = [at(300, 0), at(350, 100), at(250, 60)]
    b.tick(snap(ring))
    for k in range(1, 10):
        clock[0] = 0.05 * k
        act = b.tick(snap(ring, dot=chest(ring[0]), motion=26 if k == 1 else 29))   # the dot on the one ahead
        assert "zr" in act["hold"] and not {"rleft", "rright"} & set(act["hold"])


def test_no_stick_while_the_shot_motion_plays_then_the_pan_goes_on():
    b, clock = bot()
    ring = [at(300, 40), at(350, 100), at(250, -60)]
    b.tick(snap(ring))
    clock[0] = 0.1
    act = b.tick(snap(ring, dot=(0.0, 140.0, 3000.0), motion=29, aim_pitch=-0.4))   # off them, the shot still playing
    assert not {"rleft", "rright", "rup", "rdown", "zr"} & set(act["hold"]) and b.stats["sweep_shot_waits"] == 1
    clock[0] = 0.15
    act = b.tick(snap(ring, dot=(0.0, 140.0, 3000.0), motion=26))
    assert "rleft" in act["hold"] and "zr" not in act["hold"]


def test_one_at_point_blank_in_front_is_fired_on():
    b, clock = bot()
    ring = [at(100, 5), at(350, 100), at(250, -60)]
    b.tick(snap(ring))
    clock[0] = 0.1
    act = b.tick(snap(ring, dot=(0.0, 120.0, 60.0), motion=26))   # the dot at the muzzle: on him
    assert "zr" in act["hold"] and "rleft" not in act["hold"]


def test_the_regular_aim_holds_no_stick_in_the_shot_motion():
    b, clock = bot()
    foe = at(600, 0)
    b.tick(snap([foe]))                                            # the gun comes up
    clock[0] = 0.4
    off = (-300.0, 140.0, 3000.0)                                  # the dot 6 deg off him
    act = b.tick(snap([foe], dot=off, motion=29))
    assert b.doing == "aim" and not {"rleft", "rright", "rup", "rdown"} & set(act["hold"])
    assert b.stats["shot_stick_drops"] == 1
    clock[0] = 0.45
    act = b.tick(snap([foe], dot=off, motion=26))
    assert "rleft" in act["hold"]


def test_one_behind_while_another_is_in_front_sweeps_two_in_front_do_not():
    b, clock = bot()
    b.tick(snap([at(250, 0), at(200, 170)]))
    assert b.doing == "sweep"
    b2, _ = bot()
    b2.tick(snap([at(250, 0), at(300, 20)]))
    assert b2.doing != "sweep"


def test_the_aim_pitch_is_held_on_a_chest_never_the_sky():
    b, clock = bot()
    ring = [at(300, 40), at(350, 100), at(250, -60)]
    b.tick(snap(ring))
    clock[0] = 0.3
    act = b.tick(snap(ring, motion=26, aim_pitch=-0.4))            # 23 deg up
    assert "rdown" in act["hold"] and "rup" not in act["hold"]
    clock[0] = 0.35
    act = b.tick(snap(ring, motion=26, aim_pitch=0.1))             # inside the band: no pitch
    assert not {"rup", "rdown"} & set(act["hold"])
    clock[0] = 0.7
    act = b.tick(snap(ring, motion=26, aim_pitch=0.6))             # far down
    assert "rup" in act["hold"]


def test_a_grab_still_wins():
    b, clock = bot()
    ring = [at(300, 40), at(350, 100), at(250, -60)]
    b.tick(snap(ring))
    clock[0] = 0.1
    b.tick(snap(ring, motion=107))
    assert b.doing == "held"


def test_the_circle_clear_ends_the_sweep_counts_it_and_he_moves_on():
    b, clock = bot()
    ring = [at(300, 40), at(350, 100), at(250, -60)]
    b.tick(snap(ring, kills=3))
    clock[0] = 1.0
    b.tick(snap(ring[:1], kills=5, motion=26))
    assert b.doing == "sweep" and b.stats["sweep_kills"] == 2      # one left inside: still sweeping
    far = [at(1200, 180)]
    clock[0] = 2.0
    b.tick(snap(far, kills=6, motion=26))
    assert b.doing == "sweep"                                      # clear, not for SWEEP_EXIT_S yet
    clock[0] = 2.5
    act = b.tick(snap(far, kills=6, motion=26))
    assert b.stats["sweep_clears"] == 1 and b.stats["crowd_cleared_s"] == 2.0 and b.stats["sweep_kills"] == 3
    assert b.doing in ("relocate", "quick_turn") and b.stats["relocations"] == 1
    assert act["hold"] == ("ldown",) or {"lup", "b"} <= set(act["hold"])


def test_a_sweep_straight_after_the_last_keeps_its_way():
    b, clock = bot()
    b.tick(snap([at(300, 40), at(350, 100), at(250, -60)]))       # left
    clock[0] = 0.5
    b.tick(snap([at(1200, 180)], motion=26))
    clock[0] = 1.0
    b.tick(snap([at(1200, 180)], motion=26))                      # ended
    b._reloc_due, b._reloc = False, None
    clock[0] = 1.5
    act = b.tick(snap([at(300, -40), at(350, -100), at(250, 60)], motion=26))   # now heavier on his right
    assert b.stats["sweeps"] == 2 and "rleft" in act["hold"] and b.stats["sweep_reversals"] == 0


# --- keep moving -------------------------------------------------------------------------------------------------------
def test_no_spot_held_past_the_dwell_limit_with_majini_about_he_runs_away_from_them_turned_to_one_side():
    b, clock = bot()
    foes = [at(900, 0), at(1000, 20)]                              # in front, out of the sweep
    for k in range(0, 71):
        clock[0] = 0.1 * k
        b.tick(snap(foes, motion=0))
    assert b.stats["max_dwell_s"] >= R.DWELL_MAX_S and b.stats["relocations"] == 0
    clock[0] = 7.1
    act = b.tick(snap(foes))
    assert b.stats["relocations"] == 1
    assert b.doing == "relocate" and "ldown" in act["hold"] and b.quick == 0   # the way out behind him: backing toward it, turning
    want = math.degrees(R.wrap(math.pi + math.radians(R.KITE_DEG)))
    assert abs(math.degrees(b._reloc["head"]) - want) < 15


def test_the_run_ends_after_its_distance_and_the_dwell_starts_again():
    b, clock = bot()
    b._reloc_due = True
    foes = [at(900, 180)]                                          # behind him: run ahead
    act = b.tick(snap(foes))
    assert b.doing == "relocate" and {"lup", "b"} <= set(act["hold"])
    for k in range(1, 6):
        clock[0] = 0.4 * k
        act = b.tick(snap(foes, pos=(0.0, 0.0, 200.0 * k)))
    assert b._reloc is None and b.stats["reloc_stuck"] == 0


def test_a_stuck_run_flips_the_kite_side():
    b, clock = bot()
    b._reloc_due = True
    foes = [at(900, 180)]
    b.tick(snap(foes))
    side = b._kite_side
    for k in range(1, 30):
        clock[0] = 0.1 * k
        b.tick(snap(foes))                                         # he does not move: a wall (he breaks free first)
    assert b.stats["reloc_stuck"] == 1 and b._kite_side == -side and b._reloc is None


def test_the_run_goes_to_a_standing_statue_that_way():
    b, clock = bot()
    b._reloc_due = True
    statue = at(1500, 30)
    b.tick(snap([at(900, 180)], bonuses=[statue, at(1500, -150)]))
    assert b._reloc["statue"] and abs(math.degrees(b._reloc["head"]) - 30) < 1


def test_a_majini_in_the_way_ends_the_run():
    b, clock = bot()
    b._reloc_due = True
    b.tick(snap([at(900, 180)]))
    clock[0] = 0.2
    b.tick(snap([at(900, 180), at(120, 10)], pos=(0.0, 0.0, 60.0)))
    assert b._reloc is None and b.doing != "relocate"


# --- the aim's own pitch -------------------------------------------------------------------------------------------------
def test_the_aim_pitch_up_at_one_on_his_level_pushes_down_and_holds_a_sky_shot():
    b, clock = bot()
    foe = at(230, 0)
    b.tick(snap([foe]))                                            # the gun comes up
    clock[0] = 0.3
    sky = (0.0, 140.0 + 4400.0, 2400.0)                            # the laser in the sky
    act = b.tick(snap([foe], dot=sky, motion=26, aim_pitch=-1.08))   # 62 deg up
    assert "rdown" in act["hold"] and "rup" not in act["hold"] and "zr" not in act["hold"]
    assert b.stats["cam_up_fixes"] == 1 and b.stats["cam_up_ticks"] == 1


def test_the_aim_pitch_level_leaves_the_aim_alone():
    b, clock = bot()
    foe = at(230, 0)
    b.tick(snap([foe]))
    clock[0] = 0.3
    act = b.tick(snap([foe], dot=chest(foe), motion=26, aim_pitch=0.1))
    assert "zr" in act["hold"] and b.stats["cam_up_ticks"] == 0


def test_a_high_majini_may_take_the_aim_up():
    b, clock = bot()
    foe = at(230, 0, y=110.0)                                      # on a step (his level), the chest 28 deg up
    b.tick(snap([foe]))
    clock[0] = 0.3
    b.tick(snap([foe], dot=(0.0, 400.0, 3000.0), motion=26, aim_pitch=-0.5))
    assert b.stats["cam_up_ticks"] == 0


def test_the_stick_going_the_wrong_way_stands_the_guard_down():
    b, clock = bot()
    foe = at(230, 0)
    sky = (0.0, 140.0 + 4400.0, 2400.0)
    b.tick(snap([foe]))
    clock[0] = 0.3
    b.tick(snap([foe], dot=sky, motion=26, aim_pitch=-0.6))
    clock[0] = 0.7
    b.tick(snap([foe], dot=sky, motion=26, aim_pitch=-0.9))       # pressed down, went up
    assert b.stats["cam_pitch_inverted"] == 1 and b._cam["off"]


def test_with_the_aim_pitch_read_a_high_first_ray_is_not_lowered_and_raised_again():
    b, clock = bot()
    foe = at(230, 0)
    b.tick(snap([foe]))
    clock[0] = 0.3
    act = b.tick(snap([foe], dot=(0.0, 1500.0, 2400.0), motion=26, aim_pitch=-0.3))
    assert b.stats["raise_rerolls"] == 0 and "zl" in act["hold"] and b.doing != "reraise"


# --- the round's own counters ----------------------------------------------------------------------------------------------
def test_hits_taken_counts_each_fall_once_a_squeeze_once():
    b, clock = bot()
    foes = [at(900, 0)]
    b.tick(snap(foes, hp=1000))
    for k, hp in enumerate((900, 880, 860, 860, 860, 860, 860, 860, 700), start=1):
        clock[0] = 0.1 * k
        b.tick(snap(foes, hp=hp))
    assert b.stats["hits_taken"] == 2


def test_a_replay_starts_the_statues_again_none_counted_taken():
    b, clock = bot()
    b.tick(snap([], bonuses=[at(1000, 0), at(1200, 90)], timer=60.0))
    assert b.stats["bonuses_seen"] == 2
    b.died, b.continued = True, "yes"
    clock[0] = 5.0
    b.tick(snap([], bonuses=[at(1000, 0), at(1200, 90)], timer=119.5))   # new units
    b2 = b.stats
    assert b2["bonuses_taken"] == 0 and b2["time_gained"] == 0 and b2["rounds"] == 1


# --- the heading governor ----------------------------------------------------------------------------------------------
def test_a_heading_turning_faster_than_the_governor_releases_the_turn_stick(monkeypatch):
    monkeypatch.setattr(R, "CALM", False)                         # (the calm budget would coast the tick first)
    b, clock = bot()
    foe = at(600, 90)                                              # off to his left: a body turn
    act = b.tick(snap([foe], rot=0.0))
    assert "rleft" in act["hold"]
    clock[0] = 0.1
    act = b.tick(snap([foe], rot=math.radians(30)))               # 300 deg/s: over the governor
    assert not {"rleft", "rright"} & set(act["hold"]) and b.stats["gov_drops"] == 1
    clock[0] = 0.2
    act = b.tick(snap([foe], rot=math.radians(35)))               # 50 deg/s: the stick back
    assert b.stats["gov_drops"] == 1


def test_no_quick_turn_for_one_behind_the_body_turns_by_the_stick():
    b, clock = bot()
    act = b.tick(snap([at(200, 170)]))
    assert b.quick == 0 and act["hold"] != ("ldown",) and {"rleft", "rright"} & set(act["hold"])
    assert b.stats["quick_turns"] == 0
