"""RE5 Mercenaries: one straight sequence per Majini (gbox.mercs.titles.re5_engage and its use in re5_combat).

Operator 2026-10-26: "he should basically raise his gun, aim it at the target, and shoot the target, but instead he's
waving the gun around randomly and then sometimes shooting the target"; "she lowered her gun, shot at his feet, circled
around him and then shot him"; "They are shooting at walls and just sitting here amongst foes"."""
import math

import pytest

from gbox.mercs.titles import re5_combat as C, re5_engage as E
from tests.test_re5_combat import ENEMY, LASER, PL, snap, supported_laserless, world

P = {"ptr": PL, "pos": (0.0, 0.0, 0.0), "rot": 0.0}


def at(deg, dist, ptr=1, dy=0.0, hp=800, hp_max=800):
    """A Majini at a bearing (degrees, + = to his left: RE5's heading sense) and a ground distance (cm)."""
    a = math.radians(deg)
    return {"slot": ptr, "ptr": ptr, "pos": (dist * math.sin(a), dy, dist * math.cos(a)), "hp": hp, "hp_max": hp_max}


# --- the target -------------------------------------------------------------------------------------------------------
def test_the_majini_under_the_dot_within_reach_is_shot_first():
    dotted, nearer = at(20, 300, 1), at(-10, 200, 2)
    assert E.pick(P, [nearer, dotted], dotted=dotted)[0] is dotted


def test_one_at_arms_length_in_front_comes_before_the_one_under_the_dot():
    dotted, contact = at(5, 300, 1), at(-20, 120, 2)
    target, why = E.pick(P, [dotted, contact], dotted=dotted)
    assert target is contact and "arm's length" in why


def test_a_threat_in_front_comes_before_a_far_one_under_the_dot():
    far_dotted, front = at(0, 1000, 1), at(30, 250, 2)
    assert E.pick(P, [far_dotted, front], dotted=far_dotted)[0] is front
    assert E.pick(P, [far_dotted], dotted=far_dotted)[0] is far_dotted     # nobody nearer in front: the dot's


def test_a_threat_in_front_comes_before_one_at_arms_length_behind_until_he_is_farther_than_front_clear():
    front, behind = at(0, 300, 1), at(180, 60, 2)
    assert E.pick(P, [front, behind])[0] is front                          # the gun never comes down to turn away
    front = at(0, E.FRONT_CLEAR_R + 50, 1)
    target, why = E.pick(P, [front, behind])
    assert target is behind and "turn to him" in why


def test_the_held_target_in_front_is_kept_unless_another_is_much_nearer():
    held, other = at(10, 300, 1), at(-10, 250, 2)
    assert E.pick(P, [held, other], held=1)[0] is held                     # 3.0 m vs 2.5 m: kept (no swinging between)
    other = at(-10, 150, 2)
    assert E.pick(P, [held, other], held=1)[0] is other                    # twice as near: the switch


def test_outside_the_front_the_held_target_is_kept_unless_another_costs_clearly_less():
    held, other = at(90, 800, 1), at(-90, 700, 2)
    assert E.pick(P, [held, other], held=1)[0] is held
    other = at(-90, 400, 2)
    assert E.pick(P, [held, other], held=1)[0] is other


def test_one_on_another_level_is_chosen_only_by_the_dot_or_the_callers_sector():
    roof = at(0, 600, 1, dy=400.0)
    assert E.pick(P, [roof])[0] is None
    assert E.pick(P, [roof], extra_ok=lambda e: True)[0] is roof
    assert E.pick(P, [roof], dotted=roof)[0] is roof


def test_front_threat_is_the_nearest_living_majini_in_the_cone_on_his_level():
    behind, side, far, dead, roof, front = (at(180, 100, 1), at(60, 150, 2), at(0, 600, 3), at(0, 100, 4, hp=0),
                                            at(0, 120, 5, dy=300.0), at(20, 250, 6))
    pool = [behind, side, far, dead, roof, front]
    assert E.front_threat(P, pool) is front
    assert E.front_threat(P, pool, exclude=6) is None


def test_the_fire_window_narrows_with_distance_and_the_deadband_is_a_share_of_it():
    near, far = E.window(150.0), E.window(1000.0)
    assert near[0] > far[0] and near[1] > far[1] and far[0] >= E.WINDOW_MIN
    assert math.degrees(E.window(300.0)[0]) == pytest.approx(9.65, abs=0.1)
    dby, _ = E.deadband(300.0)
    assert dby == pytest.approx(E.DEADBAND_SHARE * E.window(300.0)[0])


@pytest.mark.parametrize("ray,ok", [
    (((0.0, 149.0, 46.0), (0.0, 110.0, 400.0)), True),            # his gun, ahead
    (((900.0, 149.0, 46.0), (900.0, 110.0, 400.0)), False),       # an origin 9 m off: another unit's fields
    (((0.0, 149.0, 46.0), (0.0, -300.0, 60.0)), False),           # straight into the ground at his feet
    (((0.0, 149.0, 46.0), (0.0, 140.0, -800.0)), False),          # behind him
    (((0.0, 149.0, 46.0), (400.0, 149.0, 100.0)), False),         # 82 deg off his heading, the dot on nobody
    (((0.0, 149.0, 46.0), (3.0, 100.0, 47.0)), True),             # a dot at the muzzle: its direction is never checked
])
def test_a_laser_read_is_his_guns_only_when_it_starts_at_him_and_points_where_he_faces(ray, ok):
    assert E.plausible(ray, P)[0] is ok


def test_a_ray_far_off_his_heading_is_kept_when_its_dot_sits_on_a_majini():
    ray = ((0.0, 149.0, 46.0), (400.0, 110.0, 100.0))
    assert not E.plausible(ray, P)[0] and E.plausible(ray, P, on_majini=True)[0]


def test_what_the_dot_is_on_majini_wall_floor_nothing_or_no_ray():
    foot, origin = (0.0, 0.0, 600.0), (0.0, 149.0, 46.0)
    other = {"ptr": 9, "pos": (0.0, 0.0, 300.0), "hp": 800, "hp_max": 800}
    cls = lambda dot, enemies=(): E.dot_class((origin, dot), foot, P, list(enemies), C.dot_on)
    assert cls((0.0, 110.0, 600.0), [{"ptr": 1, "pos": foot, "hp": 800, "hp_max": 800}]) == "target"
    assert cls((0.0, 110.0, 300.0), [other]) == "target"                   # another Majini under the dot
    assert cls((0.0, 120.0, 250.0)) == "wall"
    assert cls((0.0, 10.0, 250.0)) == "floor"
    assert cls((80.0, 120.0, 900.0)) == "none"                            # beside / past him
    assert E.dot_class(None, foot, P, [], C.dot_on) == "off"


# --- the combat layer ---------------------------------------------------------------------------------------------------
def combat(m, tmp_path):
    return C.Combat(m, {}, clock=lambda: 0.0, learn_dir=tmp_path, lessons=lambda e: None)


def test_the_trigger_waits_while_the_gun_comes_up_except_at_arms_length_in_front(tmp_path):
    """2026-10-26: the shots fired while the gun was still coming up hit 13 of 141 ("shot at his feet")."""
    m = world(aiming=False, act_vt=0)
    bot = combat(m, tmp_path)
    s = snap(m, enemy=(0.0, 0.0, 250.0))
    s["laser"] = None
    keys = bot.tick(s, s["player"], s["enemies"][0], 1.0)["hold"]
    assert "l1" in keys and "r1" not in keys and bot.stats["fire_gate"] == "gun coming up: hold fire"
    s = snap(m, enemy=(10.0, 0.0, 90.0))                                  # 0.9 m, faced: nothing fits between
    s["laser"] = None
    assert {"l1", "r1"} <= bot.tick(s, s["player"], s["enemies"][0], 1.1)["hold"]
    assert bot.stats["fire_gate"] == "point blank"


def test_the_dot_on_another_majini_is_a_shot_at_him_and_he_becomes_the_target(tmp_path):
    m = world(laser_dot=(0.0, 110.0, 300.0))                              # the dot on the one in front ...
    bot = combat(m, tmp_path)
    s = snap(m, enemy=(0.0, 0.0, 700.0))                                  # ... of the target 7 m off
    s["enemies"].append({"slot": 1, "ptr": ENEMY + 0x40, "pos": (0.0, 0.0, 300.0), "hp": 800, "hp_max": 800})
    keys = bot.tick(s, s["player"], s["enemies"][0], 1.0)["hold"]
    assert {"l1", "r1"} <= keys and bot.stats["fire_gate"] == "on another Majini"
    assert bot.target_key == ENEMY + 0x40 and not bot.blocked_until      # he is no cover for the one behind him
    assert not keys & {"lleft", "lright"}                                 # no sidestep among foes


def test_the_gun_never_comes_down_to_turn_away_from_a_threat_in_front(tmp_path):
    """16:00-19:30: at 94 of 162 hits taken in a gun-down swing a Majini stood within 4 m and 35 deg in front."""
    m = world(laser_dot=(60.0, 110.0, 200.0))                             # the dot just beside the one 2 m in front
    bot = combat(m, tmp_path)
    s = snap(m, enemy=(300.0, 0.0, 0.0))                                  # the target 90 deg to his left
    s["enemies"].append({"slot": 1, "ptr": ENEMY + 0x40, "pos": (0.0, 0.0, 200.0), "hp": 800, "hp_max": 800})
    keys = bot.tick(s, s["player"], s["enemies"][0], 1.0)["hold"]
    assert "l1" in keys and "rright" in keys and "swinging" not in bot.stats["combat"]   # up, slewing onto him
    assert bot.target_key == ENEMY + 0x40 and bot.stats["front_first"] == 1
    s["enemies"].pop()                                                    # the front clear: the gun-down swing
    keys = bot.tick(s, s["player"], s["enemies"][0], 1.1)["hold"]
    assert not keys & {"l1", "r1"} and "rleft" in keys and "swinging" in bot.stats["combat"]


def test_a_gun_down_swing_goes_on_until_he_is_within_swing_done(tmp_path):
    m = world(aiming=False, act_vt=0)
    bot = combat(m, tmp_path)
    s = snap(m, enemy=(300.0, 0.0, 0.0))
    s["laser"] = None
    assert "rleft" in bot.tick(s, s["player"], s["enemies"][0], 1.0)["hold"]   # 90 deg: the swing starts
    s["player"]["rot"] = math.radians(60)                                 # 30 deg left: inside SWING_TURN, outside DONE
    keys = bot.tick(s, s["player"], s["enemies"][0], 1.2)["hold"]
    assert keys == {"rleft"} and "swinging" in bot.stats["combat"]      # still gun down (the aim turns 5x slower)
    s["player"]["rot"] = math.radians(80)                                 # 10 deg: done, the gun comes up
    keys = bot.tick(s, s["player"], s["enemies"][0], 1.4)["hold"]
    assert "l1" in keys and bot.swing_key is None


def test_a_dot_on_a_wall_or_the_floor_short_of_him_never_fires_even_within_the_blast_radius(tmp_path):
    """The dot well short of a Majini 4 m off (not aligned enough to claim cover): a wall or the floor in the way."""
    for dot, gate in (((60.0, 120.0, 150.0), "wall in front: hold fire"), ((40.0, 5.0, 200.0), "floor short of him: hold fire")):
        m = world(laser_dot=dot)
        bot = combat(m, tmp_path)
        s = snap(m, enemy=(0.0, 0.0, 400.0))
        keys = bot.tick(s, s["player"], s["enemies"][0], 1.0)["hold"]
        assert "l1" in keys and "r1" not in keys and not bot.blocked_until, dot
        assert bot.stats["fire_gate"] == gate, dot


def test_inside_his_window_the_stick_is_left_alone_and_outside_it_slews(tmp_path):
    """No waving: a 2 deg error on a Majini 2 m off is inside his window's deadband; 20 deg is steered (and held)."""
    origin = (0.0, 149.0, 46.0)
    for deg, steer in ((2.0, False), (20.0, True)):
        a = math.radians(deg)
        dot = (300.0 * math.sin(-a), 110.0, 46.0 + 300.0 * math.cos(a))    # past him, deg to his right
        m = world(laser_dot=dot)
        bot = combat(m, tmp_path)
        s = snap(m, enemy=(0.0, 0.0, 200.0))
        s["player"]["pitch"] = 0.0
        keys = bot.tick(s, s["player"], s["enemies"][0], 1.0)["hold"]
        assert bool(keys & {"rleft", "rright"}) is steer, (deg, keys)
        assert ("r1" in keys) is (not steer), (deg, keys)
        assert origin                                                     # (the world's muzzle)


def test_a_ray_error_that_jumps_further_than_the_stick_can_move_is_not_steered_or_fired_on(tmp_path):
    m = world(laser_dot=(0.0, 110.0, 1200.0))                             # on line to a Majini 10 m off
    bot = combat(m, tmp_path)
    s = snap(m, enemy=(0.0, 0.0, 1000.0))
    assert "r1" in bot.tick(s, s["player"], s["enemies"][0], 1.0)["hold"]
    m.put(LASER + C.LASER_DOT, ">3f", -500.0, 110.0, 600.0)               # 40 deg away 0.1 s later: a torn read
    keys = bot.tick(s, s["player"], s["enemies"][0], 1.1)["hold"]
    assert "r1" not in keys and not keys & {"rleft", "rright"} and bot.stats["aim_guard"].startswith("jump")
    keys = bot.tick(s, s["player"], s["enemies"][0], 1.2)["hold"]       # it holds: a real error, steered
    assert keys & {"rleft", "rright"} and "aim_guard" not in bot.stats


def test_a_torn_laser_read_is_dropped_and_counted(tmp_path):
    m = world(laser_dot=(0.0, 110.0, 400.0))
    m.put(LASER + C.LASER_ORIGIN, ">3f", 2000.0, 149.0, 2000.0)           # another unit's fields 28 m away
    bot = combat(m, tmp_path)
    s = snap(m)                                                           # (the ray read from RAM)
    s["player"]["pitch"] = 0.0
    keys = bot.tick(s, s["player"], s["enemies"][0], 1.0)["hold"]
    assert bot.stats["laser_rejected"] >= 1 and "origin" in bot.stats["laser_rejected_why"]
    assert bot.stats["aim_feedback"] == "no laser ray yet; body direction" and "l1" in keys


def test_a_gun_whose_ray_has_not_shown_is_not_laserless_and_fires_on_his_window_at_close_range(tmp_path):
    m = world()
    bot = combat(m, tmp_path)
    s = supported_laserless(snap(m, enemy=(0.0, 0.0, 250.0)))
    s["laser"] = None
    keys = bot.tick(s, s["player"], s["enemies"][0], 1.0)["hold"]
    assert {"l1", "r1"} <= keys and not bot.laserless_now(0x12)
    assert "laserless" not in bot.stats["combat"] and bot.stats["aim_feedback"] == "no laser ray yet; body direction"
    s = supported_laserless(snap(m, enemy=(0.0, 0.0, 1500.0)))            # 15 m: no guess, the gun waits for its ray
    s["laser"] = None
    keys = bot.tick(s, s["player"], s["enemies"][0], 1.1)["hold"]
    assert "l1" in keys and "r1" not in keys


def test_measured_cover_on_one_target_turns_to_another_in_sight_at_once(tmp_path):
    m = world(laser_dot=(0.0, 135.0, 400.0))                              # a wall 3.5 m off, straight at the target
    bot = combat(m, tmp_path)
    s = snap(m, enemy=(0.0, 0.0, 1000.0))
    other = {"slot": 1, "ptr": ENEMY + 0x40, "pos": (150.0, 0.0, 300.0), "hp": 800, "hp_max": 800}
    s["enemies"].append(other)
    keys = bot.tick(s, s["player"], s["enemies"][0], 1.0)["hold"]
    assert bot.blocked_until.get(ENEMY, 0) > 1.0 and bot.target_key == other["ptr"]
    assert bot.stats["blocked_switches"] == 1 and "reposition" not in bot.stats["combat"] and "l1" in keys


def test_a_blocked_line_with_nobody_else_is_one_sidestep_in_one_direction(tmp_path):
    bot = combat(world(), tmp_path)
    sides = [next(iter(bot._reposition(t, "reposition: measured obstruction")["hold"])) for t in (1.0, 1.2, 1.5, 1.8)]
    assert len(set(sides[:3])) == 1                                       # 0.7 s one way (was 0.25 s each way)
    assert sides[3] != sides[0]                                           # the next sidestep the other way


def test_no_ray_and_a_known_wall_routes_for_one_far_off_but_faces_one_close(tmp_path):
    from gbox.mercs.titles.re5_nav import NavMesh
    walled = NavMesh([(-1000., 0., -1000.), (1000., 0., -1000.), (1000., 0., 2000.), (-1000., 0., 2000.)],
                     [(0, 1, 2), (0, 2, 3)], [[], []])                    # two triangles, no link: a wall between
    m = world(aiming=False, act_vt=0)
    bot = combat(m, tmp_path)
    s = snap(m, enemy=(800.0, 0.0, 600.0))
    s["laser"], s["nav"], s["player"]["pos"] = None, walled, (-300.0, 0.0, 300.0)
    assert bot.tick(s, s["player"], s["enemies"][0], 1.0)["hold"] == set() and bot.needs_firing_position
    s = snap(m, enemy=(0.0, 0.0, 200.0))
    s["laser"], s["nav"] = None, walled
    keys = bot.tick(s, s["player"], s["enemies"][0], 1.1)["hold"]
    assert "l1" in keys and not bot.needs_firing_position


def test_with_nobody_chosen_the_body_turns_and_the_gun_comes_up_once_he_is_in_front(tmp_path):
    bot = combat(world(), tmp_path)
    p = dict(P, action=0)
    far_off = [at(90, 300, 1)]
    keys = bot.seek_target({"enemies": far_off}, p, far_off, 1.0)["hold"]
    assert keys == {"rleft"}
    in_front = [at(20, 300, 1)]
    keys = bot.seek_target({"enemies": in_front}, p, in_front, 1.1)["hold"]
    assert "l1" in keys and "rleft" in keys                              # the laser confirms or blocks the line


# --- held target kept when the back-door contact candidate is behind/side (5128) ----------------------------------------
def test_held_target_in_front_is_kept_when_a_contact_candidate_is_behind():
    """5128: held target at 0° / 300 cm; contact candidate at 180° / 60 cm.
    Old code picked the contact (behind) via the back-door; new code keeps the held front target."""
    front, behind = at(0, 300, 1), at(180, 60, 2)
    target, why = E.pick(P, [front, behind], held=1)
    assert target is front, f"expected held front target, got {why}"


def test_held_target_in_front_is_kept_when_a_contact_candidate_is_to_the_side():
    """5128: held target at 0° / 300 cm; contact candidate at 90° / 80 cm (side, not in front cone).
    Old code picked the side contact via the back-door; new code keeps the held front target."""
    front, side = at(0, 300, 1), at(90, 80, 2)
    target, why = E.pick(P, [front, side], held=1)
    assert target is front, f"expected held front target, got {why}"


def test_contact_candidate_in_front_still_overrides_a_held_target():
    """5128: held target at 0° / 300 cm; contact candidate at 10° / 80 cm (in front cone).
    A contact candidate that IS in front should still be picked (the back-door is allowed)."""
    front, contact_front = at(0, 300, 1), at(10, 80, 2)
    target, why = E.pick(P, [front, contact_front], held=1)
    assert target is contact_front, f"expected front contact target, got {why}"
