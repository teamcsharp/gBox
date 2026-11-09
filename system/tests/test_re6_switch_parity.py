"""RE6 Switch bot parity with RE5 Switch (docs/research/re6-parity.md): the doctrine's commands (fight / hunt / score /
mine), the combo clock, the never-stand backstop and the operator's map goals - on synthetic snapshots only."""
import json
import math
import time

import pytest

from gbox.mercs import map_goals, tactical
from gbox.mercs.core import doctrine
from gbox.mercs.titles import re6_switch as R
from test_re6_switch import _fresh_caches, brain, round_guest, run   # noqa: F401 (the autouse cache fixture)


@pytest.fixture(autouse=True)
def goal_log(tmp_path, monkeypatch):
    path = tmp_path / "map-goals.log"
    monkeypatch.setattr(R, "MAP_GOAL_LOG", path)            # never the worker's own log
    return path


def command(bot, cmd, seq="d1", hold=5.0):
    """A command in the live stats as gbox.mercs.core.doctrine.Director issues it (directives.Reader's fallback)."""
    bot.stats.update(doctrine_directive=cmd, doctrine_directive_seq=seq, doctrine_directive_until=time.time() + hold)


def free(bot):
    bot.held = lambda p, now: False                         # (the stick heuristic: the snapshot never moves)
    return bot


def square(half=1000.0, cz=0.0):
    """Open floor: two triangles making a square of side 2 * half around (0, cz)."""
    v = [(-half, 0.0, cz - half), (half, 0.0, cz - half), (half, 0.0, cz + half), (-half, 0.0, cz + half)]
    return R.NavMesh(v, [(0, 1, 2), (0, 2, 3)], [[1], [0]], "test-square")


# --- the doctrine's commands -----------------------------------------------------------------------------------------

def test_hunt_sends_him_after_the_far_one_by_the_mesh_instead_of_raising_the_gun():
    far = ((0.0, 0.0, 1500.0, 700),)                         # 15 m ahead: inside ENGAGE_R, beyond HUNT_R
    bot, clock, snap = brain(round_guest(enemies=far, cam_yaw=0.0))
    act = run(free(bot), snap, clock, 1)[0]
    assert "zl" in act.get("hold", ()) and bot.mode is None  # his own play: the gun comes up for the one in front
    bot, clock, snap = brain(round_guest(enemies=far, cam_yaw=0.0))
    command(free(bot), "hunt")
    act = run(bot, snap, clock, 1)[0]
    assert bot.mode == "hunt" and bot.stats["directive_active"] == "hunt"
    assert bot.stats["act"] == "pursue" and "lup" in act["hold"] and "zl" not in act["hold"]
    assert bot.why.startswith("hunt:") and bot.stats["locates"] == 1 and bot.stats["locate_m"] == 15.0


def test_the_doctrine_issues_hunt_for_enemies_out_of_sight_and_the_bot_takes_it():
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 3000.0, 700),), cam_yaw=0.0))   # 30 m: out of sight
    d = doctrine.Director(bot.stats, weights_of=lambda: doctrine.weights(R))
    now = time.time()
    d.reset(now)
    assert d.observe(doctrine.view(snap, None, R), {"hold": ()}, now) == "locate"
    assert bot.stats["doctrine_directive"] == "hunt"
    run(free(bot), snap, clock, 1)
    assert bot.mode == "hunt" and bot.stats["act"] == "pursue"


def test_fight_takes_no_detour_while_one_is_on_his_floor(monkeypatch):
    calls = []
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 1000.0, 700),), cam_yaw=0.0))   # 10 m: not "hot"
    free(bot)
    monkeypatch.setattr(bot, "_bonus_run", lambda *a: calls.append("run"))
    monkeypatch.setattr(bot, "_green_save", lambda *a: calls.append("green"))
    run(bot, snap, clock, 1)
    assert calls == ["run", "green"]                         # his own play looks at the bonuses
    calls.clear()
    command(bot, "fight")
    run(bot, snap, clock, 2)
    assert calls == [] and bot.mode == "fight"


def side_and_ahead():
    a = math.radians(75)                                     # 7 m, 75 deg off his aim: outside FRONT_CONE
    return ((700.0 * math.sin(a), 0.0, 700.0 * math.cos(a), 700), (0.0, 0.0, 1200.0, 700))


def test_score_takes_the_quickest_kill_not_the_one_ahead():
    bot, clock, snap = brain(round_guest(enemies=side_and_ahead(), cam_yaw=0.0))
    run(free(bot), snap, clock, 1)
    side, ahead = snap["enemies"][0]["ptr"], snap["enemies"][1]["ptr"]
    assert bot.target == ahead                               # his own pick: the one in front
    bot, clock, snap = brain(round_guest(enemies=side_and_ahead(), cam_yaw=0.0))
    command(free(bot), "score")
    run(bot, snap, clock, 1)
    assert bot.mode == "score" and bot.target == snap["enemies"][0]["ptr"] and bot.stats["combo_pace_picks"] >= 1


def test_the_mine_command_puts_the_bomb_down_with_nobody_coming():
    bot, clock, snap = brain(round_guest(enemies=()))
    snap["player"].update(equipped=0, bomb={"count": 5, "out": False})
    command(free(bot), "mine")
    act = run(bot, snap, clock, 1)[0]
    assert bot.stats["mine_commands"] == 1 and bot.stats["mine_command_bombs"] == 1 and bot.mine_due is None
    assert bot.bomb_phase == "equip" and act == {"tap": "up"}        # the wheel's up: one press from a gun to it
    assert bot.bomb_why.startswith("the mine command")


def test_the_mine_command_with_one_on_him_drops_it_at_his_feet():
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 250.0, 700),)))
    snap["player"].update(equipped=0, bomb={"count": 5, "out": False})
    command(free(bot), "mine")
    run(bot, snap, clock, 1)
    assert bot.bomb_drop and bot.bomb_phase == "equip" and bot.stats["mine_command_bombs"] == 1


def test_the_mine_command_without_a_bomb_says_so_and_fights_on():
    bot, clock, snap = brain(round_guest(enemies=()))
    snap["player"].update(equipped=0, bomb={"count": 0, "out": False})
    command(free(bot), "mine")
    run(bot, snap, clock, 1)
    assert bot.stats["directive_status"] == "no remote bomb in this loadout" and bot.bomb_phase is None


def test_the_wall_command_is_read_once_by_the_shared_reader():
    from gbox.mercs import directives as D
    bot, clock, snap = brain(round_guest(enemies=()))
    D.apply_to_stats(bot.stats, D.post("test-re6-parity-wall", "next_area"))
    run(free(bot), snap, clock, 3)
    assert bot.stats["wall_reports"] == 1 and bot.mode is None    # a one-shot: no standing mode


# --- the combo clock -------------------------------------------------------------------------------------------------

def test_the_combo_clock_reads_the_window_at_the_refill_and_owes_a_kill_three_seconds_after_it():
    bot, clock, snap = brain(round_guest(enemies=()))
    run(free(bot), snap, clock, 1)                           # combo 2 just rose: the full window read, 14.75 s
    assert bot.stats["combo_window_full"] == pytest.approx(14.75, abs=0.06) and not bot.combo_pace
    snap["combo_timer"] = 12.0                               # 2.75 s since the kill
    run(bot, snap, clock, 1)
    assert not bot.combo_pace and bot.stats["combo_since_kill_s"] == pytest.approx(2.75, abs=0.06)
    snap["combo_timer"] = 11.5                               # 3.25 s: the next kill is owed
    run(bot, snap, clock, 1)
    assert bot.combo_pace and bot.stats["combo_left_s"] == 11.5 and bot.stats["combo_pace_s"] > 0
    snap["combo"] = 0
    run(bot, snap, clock, 1)
    assert not bot.combo_pace and bot.stats["combo_left_s"] is None


def test_without_a_refill_seen_the_measured_fifteen_seconds_stand_in():
    bot, clock, snap = brain(round_guest(enemies=()))
    bot.combo_prev = 2                                       # joined mid-combo: no rise seen this round
    snap["combo_timer"] = 11.5
    run(free(bot), snap, clock, 1)
    assert bot._combo_full is None and bot.combo_pace       # 15 - 11.5 = 3.5 s since the kill
    assert R.COMBO_WINDOW_S == 15.0


def test_a_kill_owed_takes_the_quickest_kill_and_holds_back_the_time_bonus_run():
    bot, clock, snap = brain(round_guest(enemies=side_and_ahead(), cam_yaw=0.0))
    free(bot)
    bot.combo_prev, bot._combo_full = 2, 14.75
    snap["combo_timer"] = 10.0                               # 4.75 s since the kill
    run(bot, snap, clock, 1)
    assert bot.combo_pace and bot.target == snap["enemies"][0]["ptr"]
    snap["timer"] = 300.0                                    # the clock well above BONUS_CLOCK_LOW_S
    assert bot._bonus_wait(snap) and bot.stats["bonus_waits"] == 1
    snap["timer"] = 90.0                                     # running low: the bonuses again
    assert not bot._bonus_wait(snap)


# --- never stand -----------------------------------------------------------------------------------------------------

def test_he_never_stands_three_seconds_and_steps_along_open_floor():
    bot, clock, snap = brain(round_guest(enemies=()))
    acts = run(free(bot), snap, clock, int(R.STAND_MAX_S / 0.05) + 2)
    assert acts[0] == {"hold": ()} and bot.stats["stand_breaks"] == 1
    assert set(acts[-1]["hold"]) & {"lup", "ldown", "lleft", "lright"}
    step = run(bot, snap, clock, int(R.STAND_STEP_S / 0.05) - 2)
    assert all(a["hold"] == acts[-1]["hold"] for a in step) and bot.stats["stand_breaks"] == 1   # one step, to its end


def test_the_step_takes_the_mesh_open_way_not_the_wall():
    bot, clock, snap = brain(round_guest(enemies=(), cam_yaw=0.0))
    snap["navmesh"] = square()
    snap["player"]["pos"] = (0.0, 0.0, 900.0)                # 1 m from the floor's +z edge, facing it
    acts = run(free(bot), snap, clock, int(R.STAND_MAX_S / 0.05) + 2)
    assert bot.stats["stand_breaks"] == 1 and acts[-1]["hold"] == ("lleft",)   # +90 deg: the nearest open way


def test_held_or_aiming_is_never_a_stand():
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 100.0, 700),), state=8))
    run(bot, snap, clock, int(R.STAND_MAX_S / 0.05) + 5)
    assert not bot.stats.get("stand_breaks")
    bot, clock, snap = brain(round_guest(enemies=()))
    out = {"hold": ("zl",)}
    for _ in range(int(R.STAND_MAX_S / 0.05) + 5):
        clock[0] += 0.05
        assert bot._never_stand(out, snap, clock[0]) is out
    assert not bot.stats.get("stand_breaks")


# --- the operator's map goals ----------------------------------------------------------------------------------------

def mark(bot, kind, entity_id, pos, gid="mark-1"):
    g = bot._goals()
    bot.receive_map_goal({"id": gid, "round": g.round, "stage": "s", "kind": kind, "entity_id": entity_id,
                          "pos": list(pos), "label": "the mark", "state": "queued"})
    return g


def test_the_tactical_map_takes_the_goal_round_and_what_a_click_may_ask():
    bot, _clock, _snap = brain(round_guest())
    assert isinstance(bot._goals(), map_goals.Goals)        # the title-agnostic goals, RE5's own
    plan = tactical.take_plan(bot)
    assert plan["goal_round"] == bot._goals().round and plan["goal_capabilities"] == ["enemy", "point"]
    assert plan["operator_goal"] is None


def test_a_marked_enemy_across_the_stage_comes_first_and_is_fought_alone_until_down(goal_log):
    enemies = ((0.0, 0.0, 1000.0, 700), (-2500.0, 0.0, -1500.0, 700))   # 10 m ahead; the marked one 29 m behind
    bot, clock, snap = brain(round_guest(enemies=enemies, cam_yaw=0.0))
    free(bot)
    marked = snap["enemies"][1]
    g = mark(bot, "enemy", marked["slot"], marked["pos"])
    act = run(bot, snap, clock, 1)[0]
    assert bot.stats["map_goals_taken"] == 1 and g.goal["state"] == "active"
    assert bot.stats["act"] == "map_goal_walk" and "zl" not in act["hold"] and bot.stats["map_goal_walk_ticks"] == 1
    marked["pos"] = (0.0, 0.0, -1200.0)                      # 12 m behind him on his floor: the fight, on him alone
    run(bot, snap, clock, 3)
    assert bot.target == marked["ptr"] and bot.stats["map_goal_fight_ticks"] >= 1
    marked["hp"] = 0                                         # down: closed after ENEMY_GONE_S, his own play again
    run(bot, snap, clock, int((map_goals.ENEMY_GONE_S + R.QUICK_SETTLE_S + 0.5) / 0.05))   # (a quick turn settles first)
    assert g.goal["state"] == "completed"
    lines = [json.loads(x) for x in goal_log.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["event"] == "received" and {x["title"] for x in lines} == {"re6_switch"}
    assert "completed" in {x["goal"]["state"] for x in lines} and bot.stats["map_goal_trace"]


def test_a_marked_enemy_with_no_health_reading_is_alive():
    enemies = ((0.0, 0.0, 1000.0, 700), (-2500.0, 0.0, -1500.0, 700))
    bot, clock, snap = brain(round_guest(enemies=enemies, cam_yaw=0.0))
    marked = snap["enemies"][1]
    g = mark(free(bot), "enemy", marked["slot"], marked["pos"])
    marked["hp"] = None                                      # far or not yet active: no reading
    run(bot, snap, clock, int(map_goals.ENEMY_GONE_S / 0.05) + 5)
    assert g.goal["state"] == "active" and bot.stats["act"] == "map_goal_walk"


def test_the_way_to_the_mark_is_fought():
    enemies = ((0.0, 0.0, 400.0, 700), (-2500.0, 0.0, -1500.0, 700))    # one 4 m ahead, in his way
    bot, clock, snap = brain(round_guest(enemies=enemies, cam_yaw=0.0))
    marked = snap["enemies"][1]
    g = mark(free(bot), "enemy", marked["slot"], marked["pos"])
    run(bot, snap, clock, 1)
    assert bot.stats["map_goal_fight_ticks"] == 1 and bot.stats["act"] != "map_goal_walk"
    assert g.goal["state"] == "deferred" and g.goal["reason"] == "Fighting through 1 on the way"
    assert bot.why.startswith("the operator's mark, fighting through")


def test_a_marked_spot_is_walked_to_and_his_own_play_resumes_there():
    bot, clock, snap = brain(round_guest(enemies=(), cam_yaw=0.0))
    g = mark(free(bot), "point", 0, (0.0, 0.0, 2000.0))
    act = run(bot, snap, clock, 1)[0]
    assert bot.stats["act"] == "map_goal_walk" and act["hold"] == ("lup",)   # straight ahead: the stick forward
    snap["player"]["pos"] = (0.0, 0.0, 1900.0)               # within map_goals.ARRIVE of it
    run(bot, snap, clock, 1)
    assert g.goal["state"] == "completed" and bot.stats["act"] != "map_goal_walk"


def test_a_spot_with_no_mesh_route_closes_unavailable_and_he_plays_on():
    mesh = R.NavMesh([(-500.0, 0.0, -500.0), (500.0, 0.0, -500.0), (0.0, 0.0, 500.0),
                      (-500.0, 0.0, 4500.0), (500.0, 0.0, 4500.0), (0.0, 0.0, 5500.0)],
                     [(0, 1, 2), (3, 4, 5)], [[], []], "two-islands")
    bot, clock, snap = brain(round_guest(enemies=(), cam_yaw=0.0))
    snap["navmesh"] = mesh
    g = mark(free(bot), "point", 0, (0.0, 0.0, 5000.0))
    run(bot, snap, clock, int(R.GOAL_NO_ROUTE_S / 0.05) + 3)
    assert g.goal["state"] == "unavailable" and bot.stats["map_goals_no_route"] == 1
    assert bot.stats["nav_fails"] >= 1


def test_a_critical_tablet_and_a_throw_in_hand_come_before_the_mark():
    bot, clock, snap = brain(round_guest(enemies=(), cam_yaw=0.0, hp=200))   # 22 % with tablets: the tablet first
    g = mark(free(bot), "point", 0, (0.0, 0.0, 2000.0))
    run(bot, snap, clock, 1)
    assert g.goal["state"] == "deferred" and bot.stats["act"] != "map_goal_walk"
    bot, clock, snap = brain(round_guest(enemies=(), cam_yaw=0.0))
    g = mark(free(bot), "point", 0, (0.0, 0.0, 2000.0))
    bot.bomb_phase = "aim"
    assert bot._operator_goal(snap["player"], snap, [], lambda e: 0.0, clock[0]) is None
    assert g.goal["reason"] == "Finishing the throw in his hand first"


def test_a_replayed_round_forgets_the_marks():
    bot, clock, snap = brain(round_guest(enemies=()))
    g = mark(free(bot), "point", 0, (0.0, 0.0, 2000.0))
    first = g.round
    bot.died, bot.continued = True, "yes"
    snap["timer"] = R.ROUND_TIME_S                           # a fresh round's clock
    run(bot, snap, clock, 1)
    assert g.round != first and g.goal is None
