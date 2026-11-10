"""The RE4 Switch fight on synthetic snapshots: the doctrine's rules as keys (gbox.mercs.core.doctrine).

Distances are written in centimetres and scaled to the game's millimetres by snap(); the player faces rot (0 = +z, + toward +x); an error > 0 turns LEFT (the GameCube RE4 / RE5
convention; the first cut had it the other way round).
"""
import math

import pytest

from gbox.mercs.titles import re4_switch as D


# The tests are written in centimetres; the game is in millimetres (D.MM_PER_CM): snap() scales every position.
def mm(p):
    return tuple(v * D.MM_PER_CM for v in p)


def snap(enemies=(), pos=(0.0, 0.0, 0.0), rot=0.0, hp=1000, **extra):
    return {"player": {"pos": mm(pos), "rot": rot, "hp": hp, "ptr": 1},
            "enemies": [{"pos": mm(p), "hp": h, "ptr": 100 + i} for i, (p, h) in enumerate(enemies)], **extra}


def bot():
    return D.Bot(stats={}, director=False)


def keys(act):
    return set(act.get("hold") or ()) | ({act["tap"]} if act.get("tap") else set())


def test_an_aligned_ganado_in_range_is_shot_with_the_aim_held_and_the_trigger_tapped():
    b = bot()
    s = snap([((0.0, 0.0, 500.0), 400)])
    raised = b.tick(s, now=10.0)
    assert raised == {"hold": {D.AIM_BTN}} and b.doing == "aim", "the gun comes up before the first tap"
    act = b.tick(s, now=10.0 + D.AIM_READY_S)
    assert act["tap"] == D.FIRE_BTN and D.AIM_BTN in act["hold"] and D.FIRE_BTN not in act["hold"]
    assert b.stats["shots"] == 1 and b.doing == "fire"


def test_taps_are_paced_so_each_one_is_a_new_press():
    b = bot()
    s = snap([((0.0, 0.0, 500.0), 400)])
    b.tick(s, now=9.0)                                              # the gun up
    assert b.tick(s, now=10.0).get("tap") == D.FIRE_BTN
    assert b.tick(s, now=10.1).get("tap") is None, "inside FIRE_GAP_S: the aim stays, no tap"
    assert b.tick(s, now=10.0 + D.FIRE_GAP_S + 0.01).get("tap") == D.FIRE_BTN


def test_a_ganado_well_off_the_gun_is_turned_to_with_the_gun_down():
    act = bot().tick(snap([((500.0, 0.0, 0.0), 400)]), now=1.0)
    assert act["hold"] == {D.TURN["left"]} and not act.get("tap")


def test_a_small_error_fine_turns_with_the_gun_up():
    err = (D.RAISE_TOL + D.Bot.TURN_TOL) / 2
    act = bot().tick(snap([((500.0 * math.sin(err), 0.0, 500.0 * math.cos(err)), 400)]), now=1.0)
    assert act["hold"] == {D.AIM_BTN, D.AIM_TURN["left"]} and not act.get("tap"), "the right stick aims (manual)"


def test_no_blind_fire_past_the_range_gate_he_walks_there_instead():
    b = bot()
    act = b.tick(snap([((0.0, 0.0, 3000.0), 400)]), now=1.0)
    assert not act.get("tap") and "lup" in act["hold"] and D.RUN_BTN in act["hold"], "30 m off: he runs to it"
    assert b.doing == "locate" and b.stats["locates"] == 1 and b.stats["locate_m"] == 30.0


def test_locate_turns_toward_the_nearest_ganado_by_the_map_while_walking():
    act = bot().tick(snap([((-1300.0, 0.0, 0.0), 400), ((0.0, 0.0, -5000.0), 400)]), now=1.0)
    assert act["hold"] == {D.TURN["right"]}, "13 m off square to his right: tank controls turn him on the spot first"
    arc = bot().tick(snap([((-500.0, 0.0, 1200.0), 400)]), now=1.0)
    assert arc["hold"] == {"lup", D.TURN["right"], D.RUN_BTN}, "13 m off 23 degrees right: run on a gentle arc"
    ahead = bot().tick(snap([((0.0, 0.0, 1250.0), 400)]), now=1.0)
    assert ahead["hold"] == {"lup", D.RUN_BTN}, "12.5 m straight ahead (past the 12 m engage range): run, no turn"


def test_nobody_on_the_map_he_sweeps_the_level_and_never_stands():
    b = bot()
    act = b.tick(snap([]), now=1.0)
    assert "lup" in act["hold"] and b.doing == "sweep"
    later = b.tick(snap([], pos=(0.0, 0.0, 300.0)), now=1.0 + D.SWEEP_S + 0.1)    # he walked 3 m meanwhile
    assert later["hold"] != act["hold"] and "lup" in later["hold"], "the sweep turns the other way after SWEEP_S"
    stuck = b.tick(snap([], pos=(0.0, 0.0, 300.0)), now=1.0 + 2 * D.SWEEP_S)
    assert b.doing == "step" and "lup" in stuck["hold"], "walking into a wall is standing: never-stand steps away"


def test_a_mob_takes_the_ganado_on_the_guns_line_not_the_nearest():
    near_but_off = ((350.0, 0.0, 100.0), 400)                       # nearest, but far off the gun's line
    on_line = [((0.0, 0.0, 450.0 + 10 * i), 400) for i in range(4)]
    b = bot()
    b.tick(snap([near_but_off] + on_line), now=1.0)
    act = b.tick(snap([near_but_off] + on_line), now=1.0 + D.AIM_READY_S)
    assert act.get("tap") == D.FIRE_BTN and b.stats["crowd_picks"] == 2
    assert b.target in (101, 102, 103, 104)


def test_a_swarm_at_arms_length_is_escaped_with_the_quick_turn():
    b = bot()
    act = b.tick(snap([((100.0 * math.sin(a), 0.0, 100.0 * math.cos(a)), 400) for a in (0.0, 2.0, 4.0)]), now=1.0)
    assert act["hold"] == set(D.QUICK_TURN) and b.stats["escapes"] == 1


def test_dead_ganados_are_neither_targets_nor_obstacles():
    act = bot().tick(snap([((0.0, 0.0, 300.0), 0), ((500.0, 0.0, 0.0), 400)]), now=1.0)
    assert act["hold"] == {D.TURN["left"]}, "the dead one in front is skipped"


def test_kills_are_counted_from_the_census_and_the_combo_falls_due():
    b = bot()
    alive = snap([((0.0, 0.0, 500.0), 400), ((0.0, 0.0, 900.0), 400)])
    b.tick(alive, now=0.0)
    one_down = snap([((0.0, 0.0, 500.0), 0), ((0.0, 0.0, 900.0), 400)])
    b.tick(one_down, now=1.0)
    assert b.stats["kills_seen"] == 1 and b.stats["kills_source"] == "census"
    assert b.combo_owed(1.0 + D.KILL_PACE_S - 0.1) is None
    assert b.combo_owed(1.0 + D.KILL_PACE_S + 0.5) == pytest.approx(D.KILL_PACE_S + 0.5)


def test_the_games_own_kill_counter_wins_when_it_is_mapped():
    b = bot()
    b.tick(snap([((0.0, 0.0, 500.0), 400)], kills=3), now=0.0)
    assert b.stats["kills_seen"] == 3 and b.stats["kills_source"] == "game"


def test_when_the_combo_is_owed_the_quickest_kill_is_taken():
    b = bot()
    b._kill_at = 0.0
    weak_far = ((0.0, 0.0, 700.0), 50)
    strong_near = ((0.0, 0.0, 600.0), 1200)
    b.tick(snap([strong_near, weak_far]), now=D.KILL_PACE_S + 1.0)
    assert b.target == 101 and "combo" in b.why


def test_never_stand_a_turn_that_does_not_move_him_becomes_a_step():
    b = bot()
    s = snap([((500.0, 0.0, 0.0), 400)])                             # always turning, never moving
    assert b.tick(s, now=0.0)["hold"] == {D.TURN["left"]}
    assert b.tick(s, now=D.STAND_MAX_S - 0.1)["hold"] == {D.TURN["left"]}
    step = b.tick(s, now=D.STAND_MAX_S + 0.1)
    assert "lup" in step["hold"] and b.stats["stand_breaks"] == 1 and b.doing == "step"
    assert b.tick(s, now=D.STAND_MAX_S + 0.3)["hold"] == step["hold"], "the step runs to its end"


def test_aiming_and_firing_are_not_standing():
    b = bot()
    s = snap([((0.0, 0.0, 500.0), 400)])
    for t in range(0, 40):
        act = b.tick(s, now=t * 0.1)
        assert D.AIM_BTN in act["hold"]
    assert b.stats["stand_breaks"] == 0


def test_an_own_hazard_underfoot_comes_first():
    act = bot().tick(snap([((0.0, 0.0, 500.0), 400)], own_hazards=[{"pos": (10.0, 0.0, 10.0)}]), now=1.0)
    assert "lup" in act["hold"] and not act.get("tap")


def test_the_doctrine_measures_every_tick():
    b = D.Bot(stats={})
    b.tick(snap([((0.0, 0.0, 500.0), 400)]), now=1.0)
    assert "doctrine_played_s" in b.stats and b.stats["doctrine_in_sight"] == 1


def test_no_player_no_keys():
    assert D.Bot(stats={}, director=False).tick({"player": None, "enemies": []}) == {}


def test_the_switch_manuals_controls():
    """Capcom's RE4 Switch manual (docs/research/mercenaries-character-specials.md 1.1): reload is ZL + B - R is "Give
    orders", Krauser's Plaga arm in Mercenaries, which the first cut used as its reload."""
    assert (D.AIM_BTN, D.FIRE_BTN) == ("zl", "zr")
    assert D.RELOAD_KEYS == ("zl", "b") and D.RELOAD_BTN != D.SPECIAL_BTN == "r"
    assert D.ACTION_BTN == "y" and D.KNIFE_BTN == "l"
    assert D.RUN_BTN == "b" and D.QUICK_TURN == ("ldown", "b")
    assert D.AIM_TURN == {"left": "rleft", "right": "rright"} and D.TURN == {"left": "lleft", "right": "lright"}


def test_after_a_magazine_of_shots_he_reloads_at_the_first_quiet_moment():
    b = bot()
    s = snap([((0.0, 0.0, 500.0), 400)])
    t = 0.0
    b.tick(s, now=t)
    while b.stats["shots"] < D.RELOAD_SHOTS:
        t += D.FIRE_GAP_S + 0.01
        b.tick(s, now=t)
    assert b._since_reload == D.RELOAD_SHOTS
    near = snap([((0.0, 0.0, 300.0), 400), ((0.0, 0.0, 2000.0), 400)])
    quiet = bot()
    quiet._since_reload = D.RELOAD_SHOTS
    act = quiet.tick(snap([((0.0, 0.0, 3000.0), 400)]), now=1.0)
    assert act == {"hold": {D.AIM_BTN}, "tap": D.RELOAD_BTN} and quiet.stats["reloads"] == 1
    assert quiet.tick(snap([((0.0, 0.0, 3000.0), 400)]), now=2.0).get("tap") is None, "once, then the run resumes"
    busy = bot()
    busy._since_reload = D.RELOAD_SHOTS
    busy.tick(near, now=1.0)
    assert busy.stats["reloads"] == 0, "never with a Ganado in range: he keeps shooting"


def test_the_reload_goes_in_with_the_aim_down_first():
    from gbox import re4switch_bot as B
    sent = []
    B.Keys(sent.append).apply({"hold": {D.AIM_BTN}, "tap": D.RELOAD_BTN})
    assert sent == [[{"key": "zl", "down": True}, {"key": "b", "down": True}, {"key": "b", "down": False}]]


class Mesh:
    """re5_nav.NavMesh's two calls the fight uses: floor_segment (line of sight) and route (the run to a Ganado)."""

    def __init__(self, clear=True, waypoints=None):
        self.clear, self.waypoints = clear, waypoints

    def floor_segment(self, start, goal):
        return self.clear

    def route(self, start, goal, **_):
        return self.waypoints


def test_no_shot_across_a_wall_the_stage_mesh_names():
    b = bot()
    s = snap([((0.0, 0.0, 500.0), 400)], nav=Mesh(clear=False))
    b.tick(s, now=1.0)
    act = b.tick(s, now=1.0 + D.AIM_READY_S)
    assert act.get("tap") is None and b.doing == "hold" and b.stats["holds"] >= 1


def test_the_run_to_a_ganado_follows_the_mesh_route():
    """Straight ahead is a wall: the route's first waypoint is off to his right, so he turns right while he runs."""
    route = [mm(q) for q in ((0.0, 0.0, 0.0), (-300.0, 0.0, 600.0), (0.0, 0.0, 3000.0))]
    act = bot().tick(snap([((0.0, 0.0, 3000.0), 400)], nav=Mesh(waypoints=route)), now=1.0)
    assert act["hold"] == {"lup", D.TURN["right"], D.RUN_BTN}


def test_an_attached_walker_steers_the_run():
    from gbox.mercs.titles import re4_walk

    class Walker(re4_walk.Walker):
        def __init__(self):
            super().__init__()
            self.goals = []

        def approach(self, goal, **_):
            self.goals.append(goal)
            return ("lup", "lright")

    b = bot()
    b.walker = Walker()
    act = b.tick(snap([((0.0, 0.0, 3000.0), 400)]), now=1.0)
    assert act["hold"] == {"lup", "lright"} and b.walker.goals == [mm((0.0, 0.0, 3000.0))], "the walker's keys"
    assert "walker" in b.why


def test_a_ganado_just_hit_in_front_gets_the_melee_follow_up():
    """The shot -> stun -> Y loop (specials research 2.1): in to MELEE_REACH_MM, then Y at the prompt."""
    b = bot()
    b.tick(snap([((0.0, 0.0, 200.0), 400)]), now=0.0)
    step = b.tick(snap([((0.0, 0.0, 200.0), 300)]), now=0.1)          # hit: 2 m in front
    assert step["hold"] == {"lup"} and b.doing == "melee" and b.stats["hits"] == 1
    tap = b.tick(snap([((0.0, 0.0, 120.0), 300)]), now=0.2)           # 1.2 m: the prompt
    assert tap.get("tap") == D.ACTION_BTN and b.stats["melee_taps"] == 1
    assert b.tick(snap([((0.0, 0.0, 120.0), 300)]), now=0.3).get("tap") is None, "taps paced MELEE_TAP_S"
    b.tick(snap([((0.0, 0.0, 120.0), 0)]), now=0.6)
    assert b.stats["melee_kills"] == 1


def test_no_melee_with_another_at_arms_reach_or_after_the_window():
    b = bot()
    two = lambda h: snap([((0.0, 0.0, 200.0), h), ((150.0, 0.0, 100.0), 400)])     # noqa: E731
    b.tick(two(400), now=0.0)
    act = b.tick(two(300), now=0.1)
    assert b.doing != "melee" and act.get("tap") != D.ACTION_BTN
    late = bot()
    late.tick(snap([((0.0, 0.0, 200.0), 400)]), now=0.0)
    late.tick(snap([((0.0, 0.0, 200.0), 300)]), now=0.1)
    late.tick(snap([((0.0, 0.0, 200.0), 300)]), now=0.1 + D.MELEE_WINDOW_S + 0.1)
    assert late.doing != "melee"


def test_the_melee_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(D, "MELEE", False)
    b = bot()
    b.tick(snap([((0.0, 0.0, 200.0), 400)]), now=0.0)
    b.tick(snap([((0.0, 0.0, 200.0), 300)]), now=0.1)
    assert b.doing != "melee"
