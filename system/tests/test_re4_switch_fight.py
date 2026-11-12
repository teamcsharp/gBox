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
    assert b.tick(s, now=10.0 + D.FIRE_GAP_S / 2).get("tap") is None, "inside FIRE_GAP_S: the aim stays, no tap"
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


def test_a_swarm_at_arms_length_is_fired_at_first_the_escape_is_the_rollback(monkeypatch):
    """The operator 2026-11-10 night: "fire and deal with threats before lowering his weapon and fleeing". FIRE_FIRST:
    three on him with clear lines meet the gun (no gun-down run); FIRE_FIRST off is the old quick turn out."""
    b = bot()
    s = snap([((100.0 * math.sin(a), 0.0, 100.0 * math.cos(a)), 400) for a in (0.0, 2.0, 4.0)])
    act = b.tick(s, now=1.0)
    assert b.stats["escapes"] == 0 and D.AIM_BTN in act["hold"], "the gun up at the swarm, not a run"
    monkeypatch.setattr(D, "FIRE_FIRST", False)
    old = bot()
    act = old.tick(s, now=1.0)
    assert old.stats["escapes"] == 1 and old.doing == "escape"
    assert act["hold"] == set(D.QUICK_TURN) or {"lup", D.RUN_BTN} <= act["hold"], "the quick turn, or the run out"


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

    def blocking_wall(self, start, goal):
        return None if self.clear else ((0.0, 0.0, 1000.0, 0.0, 0.0, 3000.0, 0), 0.5, 1300.0)

    def route(self, start, goal, **_):
        return self.waypoints


def test_no_shot_across_a_wall_the_stage_mesh_names(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "SIGHT_LOG", tmp_path / "blocks.jsonl")
    b = bot()
    s = snap([((0.0, 0.0, 500.0), 400)], nav=Mesh(clear=False))
    b.tick(s, now=1.0)
    act = b.tick(s, now=1.0 + D.AIM_READY_S)
    assert act.get("tap") is None and D.AIM_BTN not in act["hold"] and b.doing == "flank", "no shot: round it"
    assert b.stats["sight_block_last"]["wall"] == [0, 0, 1000, 0] and (tmp_path / "blocks.jsonl").exists()


def test_a_held_shot_becomes_a_flank_then_a_try_again(tmp_path, monkeypatch):
    """Live 2026-11-10 21:06: 415 holds and a death. No clear line: the gun down, round it, then the shot again."""
    monkeypatch.setattr(D, "SIGHT_LOG", tmp_path / "blocks.jsonl")
    b = bot()
    s = snap([((0.0, 0.0, 500.0), 400)], nav=Mesh(clear=False, waypoints=[mm((-200.0, 0.0, 300.0))]))
    act = b.tick(s, now=1.0)
    assert b.doing == "flank" and "lup" in act["hold"] and D.AIM_BTN not in act["hold"] and b.stats["flanks"] == 1
    assert b.tick(s, now=1.0 + D.FLANK_S / 2)["hold"] & {"lup"}, "the flank runs FLANK_S"
    clear = snap([((0.0, 0.0, 500.0), 400)], nav=Mesh(clear=True))
    b.tick(clear, now=1.0 + D.FLANK_S + 0.1)
    assert b.doing != "flank", "a clear line: the flank is over, the fight again"


def test_the_run_to_a_ganado_follows_the_mesh_route():
    """Straight ahead is a wall: the route's first waypoint is off to his right, so he turns right while he runs."""
    route = [mm(q) for q in ((0.0, 0.0, 0.0), (-300.0, 0.0, 600.0), (0.0, 0.0, 3000.0))]
    b = bot()
    act = b.tick(snap([((0.0, 0.0, 3000.0), 400)], nav=Mesh(waypoints=route)), now=1.0)
    assert act["hold"] == {"lup", D.TURN["right"], D.RUN_BTN}
    # ...and it was a HUNT, not a coincidental walk: a Ganado 30 m off is past HUNT_RUN_MM, where the shot's 0.05 rad
    # floor is wider than a body, so the fight runs at him instead of standing and firing (the machine-gunner kill).
    assert b.stats.get("hunts") == 1 and b.doing == "hunt", (b.stats.get("hunts"), b.doing)


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


def test_a_turn_that_runs_away_from_its_target_flips_the_sign(monkeypatch):
    """The live check: the error on the same Ganado growing tick after tick flips TURN_SIGN (and the walker's)."""
    from gbox.mercs.titles import re4_walk
    monkeypatch.setattr(D, "TURN_SIGN", 1)
    monkeypatch.setattr(re4_walk, "TURN_POSITIVE", "lleft")
    monkeypatch.setattr(re4_walk, "TURN_NEGATIVE", "lright")
    b = bot()
    first = b.tick(snap([((500.0, 0.0, 0.0), 400)], rot=0.0), now=0.0)["hold"]
    rot = 0.0
    for i in range(1, D.TURN_LEARN_N + 6):
        rot -= 0.05                                         # his facing runs away from the Ganado at +x
        b.tick(snap([((500.0, 0.0, 0.0), 400)], rot=rot), now=0.1 * i)
        if b.stats.get("turn_sign_flips"):
            break
    assert b.stats["turn_sign_flips"] == 1 and D.TURN_SIGN == -1 and b.stats["turn_diverge"] >= 12
    assert re4_walk.TURN_POSITIVE == "lright"
    again = bot().tick(snap([((500.0, 0.0, 0.0), 400)], rot=0.0), now=0.0)["hold"]
    assert again != first, "the flipped sign turns the other way"


def test_a_turn_that_closes_never_flips(monkeypatch):
    monkeypatch.setattr(D, "TURN_SIGN", 1)
    b = bot()
    err = 1.5
    for i in range(40):
        b.tick(snap([((500.0 * math.sin(err), 0.0, 500.0 * math.cos(err)), 400)]), now=0.1 * i)
        err = max(err - 0.03, D.RAISE_TOL + 0.05)
    assert not b.stats.get("turn_sign_flips") and D.TURN_SIGN == 1


def test_holds_say_which_gate_stopped_the_shot(monkeypatch):
    monkeypatch.setattr(D, "CONTROLS_READY", False)
    b = bot()
    s = snap([((0.0, 0.0, 500.0), 400)])
    b.tick(s, now=1.0)
    b.tick(s, now=1.0 + D.AIM_READY_S)
    assert b.stats.get("hold_controls", 0) >= 1 and b.doing == "hold"


def test_a_frozen_scene_gets_a_until_he_moves():
    """Live 2026-11-10 21:00: the round intro after a Continue, the RAM fight turning at it. A never-stand step that
    ran its course without moving or turning him: A taps (the intro's continue, a grab's mash); once he moves, the
    fight again."""
    b = bot()
    s = snap([((500.0, 0.0, 0.0), 400)])                         # a turn is commanded every tick, nothing moves
    assert b.tick(s, now=0.0)["hold"] == {D.TURN["left"]}
    step = b.tick(s, now=D.STAND_MAX_S + 0.1)
    assert b.doing == "step" and "lup" in step["hold"]
    assert b.tick(s, now=D.STAND_MAX_S + 0.1 + D.STAND_STEP_S / 2).get("tap") is None, "the step runs first"
    t0 = D.STAND_MAX_S + 0.2 + D.STAND_STEP_S
    tap = b.tick(s, now=t0)
    assert tap.get("tap") == D.FROZEN_KEY and b.doing == "frozen" and b.stats["frozen_spells"] == 1
    assert b.tick(s, now=t0 + 0.05).get("tap") is None, "taps paced FROZEN_TAP_S"
    assert b.tick(s, now=t0 + D.FROZEN_TAP_S + 0.01).get("tap") == D.FROZEN_KEY
    moved = b.tick(snap([((500.0, 0.0, 0.0), 400)], rot=0.3), now=t0 + 1.0)
    assert moved.get("tap") is None and b.doing != "frozen"


def test_aiming_still_is_never_frozen():
    b = bot()
    s = snap([((0.0, 0.0, 500.0), 400)])                         # straight ahead: the gun up, taps of the trigger
    for i in range(40):
        act = b.tick(s, now=0.1 * i)
        assert act.get("tap") != D.FROZEN_KEY
    assert b.stats.get("frozen_taps", 0) == 0


def test_a_clock_that_falls_faster_than_time_is_dropped():
    import struct

    class M:
        def __init__(self):
            self.v = 100.0

        def rd(self, a, n):
            return struct.pack("<f", self.v)

    c = D.ClockFinder()
    c.addr, m = 0x1000, M()
    assert c.observe(m, 0, 0.0) == 100.0
    m.v = 99.0
    assert c.observe(m, 0, 1.0) == 99.0
    m.v = 60.0                                                 # 39 s gone in 1 s: not the clock
    assert c.observe(m, 0, 2.0) is None and c.addr is None and c.rejects == 1
    c.addr, m.v = 0x1000, 90.0
    c.observe(m, 0, 3.0)
    m.v = 120.0                                                # a bonus adds time: kept
    assert c.observe(m, 0, 4.0) == 120.0


def test_any_characters_unit_through_the_player_pointer_is_the_player():
    """Live 2026-11-10 21:46: Ada's class is not Leon's; the pointer's unit is the player while its vtable is a unit
    class (PLAYER_VTABLE_RANGE) that is no Ganado's and no set object's."""
    import struct
    base = 0x3CA7C04000
    unit_at = 0x5D50010000

    class M:
        def __init__(self, cls):
            self.cls = cls

        def rd(self, a, n):
            if a == base + D.S_PLAYER or a == base + D.S_PLAYER_2:
                return struct.pack("<Q", unit_at)
            raw = bytearray(n)
            struct.pack_into("<Q", raw, 0, base + self.cls)
            struct.pack_into("<3f", raw, D.U_POS, 1000.0, 0.0, 2000.0)
            return bytes(raw)

    ada = D.player_unit(M(0xB0F000), base)
    assert ada is not None and ada["class"] == 0xB0F000 and D.SEEN_PLAYER_CLASSES.get(0xB0F000)
    assert D.player_unit(M(D.ENEMY_CLASSES[0]), base) is None, "a Ganado's unit is never the player"
    assert D.player_unit(M(0x123450), base) is None, "a vtable outside the unit classes is not a unit"



class SightMesh(Mesh):
    """Mesh whose shot line is blocked to the Ganados listed in blocked (by their x position in cm)."""

    def __init__(self, blocked_x=(), waypoints=None):
        super().__init__(clear=True, waypoints=waypoints)
        self.blocked_x = {round(x * D.MM_PER_CM) for x in blocked_x}

    def clear_segment(self, a, b):
        return round(b[0]) not in self.blocked_x


def test_a_ganado_with_a_clear_line_is_taken_before_a_nearer_one_behind_a_wall():
    """Live 2026-11-10 21:53: 48 shots held at Ganados behind real walls while others stood round him."""
    b = bot()
    behind = ((0.0, 0.0, 300.0), 400)                       # nearest, behind a wall
    clear = ((10.0, 0.0, 700.0), 400)                       # farther, in the open
    s = snap([behind, clear], nav=SightMesh(blocked_x=(0.0,)))
    b.tick(s, now=1.0)
    assert b.target == 101 and b.stats["visible_picks"] >= 1


def test_with_everyone_behind_walls_he_goes_round_instead_of_aiming():
    b = bot()
    s = snap([((0.0, 0.0, 500.0), 400)], nav=SightMesh(blocked_x=(0.0,), waypoints=[mm((-300.0, 0.0, 300.0))]))
    act = b.tick(s, now=1.0)
    assert b.doing == "flank" and D.AIM_BTN not in act["hold"] and "lup" in act["hold"] and b.stats["blocked_picks"] == 1



def test_the_shot_waits_for_the_angle_the_ganado_covers():
    """Live 2026-11-10 22:07: 11 hits from 166 shots with a flat 7-degree tolerance. At 10 m a Ganado covers ~1.7
    degrees: 4 degrees off is a nudge of the right stick (a tap), not a shot."""
    b = bot()
    err = math.radians(4.0)
    s = snap([((1000.0 * math.sin(err), 0.0, 1000.0 * math.cos(err)), 400)])
    b.tick(s, now=0.0)
    act = b.tick(s, now=D.AIM_READY_S + 0.1)
    assert act.get("tap") == D.AIM_TURN["left"] and D.AIM_BTN in act["hold"] and b.stats["shots"] == 0
    near = math.radians(1.0)
    s2 = snap([((1000.0 * math.sin(near), 0.0, 1000.0 * math.cos(near)), 400)])
    b2 = bot()
    b2.tick(s2, now=0.0)
    assert b2.tick(s2, now=D.AIM_READY_S + 0.1).get("tap") == D.FIRE_BTN and b2.stats["fire_err_deg"] == 1.0



def test_the_kill_count_candidate_is_retracted():
    """Measured on two live rounds 2026-11-10: module + 0x12010c4 counts the round's kills (the census misses a melee
    kill whose unit is freed between reads)."""
    assert D.MERC_KILLS is None and 0x12010C4 in D.KILL_CANDIDATES, "retracted: the HUD read 0 while it read 8"



def test_a_heavy_at_arms_length_is_shot_first_the_run_is_the_rollback(monkeypatch):
    """Live 2026-11-10 23:21: Unlimited life undid 26 hits, then one blow took him from 1560 to 0 - a heavy's. The
    operator's next round: "fire and deal with threats before lowering his weapon and fleeing" - FIRE_FIRST: a heavy on
    him with a clear line meets the gun; the run from it is the rollback (FIRE_FIRST off)."""
    b = bot()
    s = snap([((0.0, 0.0, 200.0), 3500)])
    s["enemies"][0]["hp_max"] = 3500
    act = b.tick(s, now=1.0)
    assert D.AIM_BTN in act["hold"] and b.doing in ("turn", "aim", "fire") and b.stats.get("heavy_escapes", 0) == 0
    monkeypatch.setattr(D, "FIRE_FIRST", False)
    old = bot()
    act = old.tick(s, now=1.0)
    assert act["hold"] == set(D.QUICK_TURN) and old.doing == "evade" and old.stats["heavy_escapes"] == 1
    far = snap([((0.0, 0.0, 800.0), 3500)])
    far["enemies"][0]["hp_max"] = 3500
    b2 = bot()
    b2.tick(far, now=1.0)
    assert b2.doing != "evade", "beyond HEAVY_KEEP_MM he is a target"


def test_firing_into_a_screen_that_takes_no_input_taps_a():
    """Live 2026-11-10 03:52: Krauser on Waterworld's intro card ("Eliminate as many Ganados ..."), the bot "crowd
    fire" for minutes - 620 shots, 0 hits - and nothing pressed A. Firing never steps, so only this rule sees it."""
    b = bot()
    p = {"pos": (0.0, 0.0, 0.0), "rot": 0.0}
    b.stats["shots"] = 0
    assert b._frozen(p, 10.0) is None                      # the first read: he "moved" (nothing known yet)
    b.stats["shots"] = 4
    assert b._frozen(p, 13.0) is None                      # firing, not yet long enough
    b.stats["shots"] = 12
    act = b._frozen(p, 15.5)
    assert act == {"hold": set(), "tap": D.FROZEN_KEY} and b.doing == "frozen"
    assert b.stats["frozen_fire_spells"] == 1
    b2 = bot()
    b2.stats["shots"] = 0
    b2._frozen(p, 10.0)
    b2._hit_at[123] = 12.0                                 # a hit landed: a real fight
    b2.stats["shots"] = 12
    assert b2._frozen(p, 15.5) is None


def test_the_walk_turn_does_not_flutter_when_the_error_sits_near_the_tolerance():
    """Operator 2026-11-11: the walking twitched ("vibrating ... not walking forward in a linear fashion"). A step
    error just past TURN_TOL must keep its direction when the error flips slightly; only a clear reversal turns back."""
    b = bot()
    p = {"pos": mm((0.0, 0.0, 0.0)), "rot": 0.0}

    def goal(angle):
        return mm((1000.0 * math.sin(angle), 0.0, 1000.0 * math.cos(angle)))

    first = b._step_keys(p, {"goal": goal(0.13)})
    assert "lup" in first and 0.13 > b.TURN_TOL
    assert b._step_keys(p, {"goal": goal(0.13)}) == first
    assert b._step_keys(p, {"goal": goal(-0.125)}) == first, "a small opposite error keeps the turn (no flutter)"
    assert b._step_keys(p, {"goal": goal(-0.5)}) != first, "a clear reversal turns the other way"

# --- the shot's tolerance is the body's angle at THAT distance (live 2026-11-12, the operator's frame: the bot pressed
# into a Ganado at 01'56" with 0 kills, doing=turn). The turn used the flat FIRE_TOL_MIN (2.86 deg) at every range while
# the shot's real tolerance is atan2(half, dist) capped at TURN_TOL (6.9 deg): at arm's length the bot demanded
# precision the shot did not need and turned instead of firing.

def test_a_ganado_at_two_metres_is_shot_not_turned_at_five_degrees():
    b = bot()
    off = 200.0 * math.tan(math.radians(5.0))          # 2 m out, 5 deg off the gun's line
    s = snap([((off, 0.0, 200.0), 400)])
    b.tick(s, now=10.0)
    assert b.doing != "turn", "5 deg at 2 m is inside the body's 6.9 deg: it shoots, it does not turn"


def test_a_ganado_at_twelve_metres_is_not_shot_at_five_degrees():
    b = bot()
    off = 1200.0 * math.tan(math.radians(5.0))         # 12 m out: the body covers 1.4 deg, so 5 deg is a miss
    s = snap([((off, 0.0, 1200.0), 400)])
    for i in range(4):
        b.tick(s, now=10.0 + i * 0.1)
    assert b.doing in ("turn", "locate"), "at 12 m the same 5 deg is outside the body: it turns or acquires"
    assert not b.stats.get("shots"), "and it must not have fired a shot 5 deg wide at 12 m"


def test_a_flank_budget_ends_the_sight_gate():
    b = bot()
    e = {"ptr": 7, "pos": (0.0, 0.0, 1000.0), "hp": 100}
    assert b._sight_given_up(e) is False, "nothing flanked yet: the gate still holds"
    b._flank_spent = {7: 1.0}
    assert b._sight_given_up(e) is False, "under the budget: the gate still holds"
    b._flank_spent = {7: D.FLANK_GIVE_UP_S}
    assert b._sight_given_up(e) is True, "a budget's worth of walking: he shoots it"
    assert b.stats.get("sight_given_up") == 1
    assert b._sight_given_up({"ptr": 8}) is False, "another Ganado gets its own budget"


def test_walled_in_he_steps_forward_instead_of_standing():
    """Live 2026-11-12 on Base (r403): every planned direction was refused for brushing a wall ("115 mm, margin 300"),
    and the never-stand rule stood and re-tried, so the round read walk_m 0.0 while the Ganados closed. A refused
    destination is not a reason to stand."""
    b = bot()
    s = snap([])
    b._walk_test = lambda snap: (lambda a, bb: False)          # the room map refuses every planned direction
    b.tick(s, now=0.0)
    act = b.tick(s, now=D.STAND_MAX_S + 0.2)
    assert "lup" in (act.get("hold") or ()), "walled in is still a step, not standing"
    assert b.stats.get("steps_walled_in")
