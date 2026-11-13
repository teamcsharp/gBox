"""The RE4 Switch walker (gbox.mercs.titles.re4_walk) on the synthetic stage (re4_nav_fixture): tank-control steering,
the route by the mesh, crossings with the action pulse, the never-stand backstop, the operator's map marks through
the decorated re4_switch.Bot, and the tactical map's frames and stage for RE4 Switch."""
import inspect
import math

import pytest

import re4_nav_fixture as F
from gbox import re4switch_bot
from gbox.mercs import tactical as T
from gbox.mercs.titles import re4_switch, re4_walk as W


def _snap(pos, rot=0.0, enemies=(), mesh=None):
    return {"player": {"pos": tuple(pos), "rot": rot, "hp": 1000, "hp_max": 1000}, "enemies": list(enemies),
            "nav": mesh if mesh is not None else F.mesh(), "timer": 90.0, "kills": 0, "combo": 0, "combo_timer": 0.0}


def _walker(pos, rot=0.0, now=0.0, mesh=None):
    w = W.Walker({})
    w.observe(_snap(pos, rot, mesh=mesh), now)
    return w


EAST = math.pi / 2                       # heading atan2(dx, dz): facing +x


def test_shortcut_preserves_the_floor_of_an_overhead_waypoint(monkeypatch):
    w = _walker((4500., 0., 3300.))
    monkeypatch.setattr(W.re4_room_map, 'for_snap', lambda s: None)
    assert w._open(w._pos(), 4700., 3300.)
    assert not w._open(w._pos(), 4700., 3300., F.PLATFORM_Y)
    assert w._shortcut(w._pos(), [(4500., 0., 2700.), (4700., F.PLATFORM_Y, 3300.)]) == 0


def test_flat_proximity_does_not_complete_waypoint_on_floor_above(monkeypatch):
    w = _walker((4500., 0., 3300.))
    goal = (4800., F.PLATFORM_Y, 3500.)
    pts = [(4500., F.PLATFORM_Y, 3300.), goal]
    w._route.update(cell=(round(goal[0]/W.GOAL_CELL_MM), round(goal[1]/W.GOAL_CELL_Y_MM),
                          round(goal[2]/W.GOAL_CELL_MM)), at=w.now, sig=w.mesh.sig, pts=pts, cut_at=w.now)
    w._waypoint(goal)
    assert len(w._route['pts']) == 2


def test_route_owned_ticks_publish_the_current_action():
    bot = re4_switch.Bot(stats={}, director=False)
    goals = W.goals_of(bot)
    bot.receive_map_goal({'id':'bonus-test', 'round':goals.round, 'kind':'point',
                         'entity_id':0, 'pos':[5000., 0., 2600.], 'label':'bonus'})
    goals.goal.update(source='time_bonus', floor_y=0.)
    bot.stats.update(doing='fire', why='stale combat action')
    bot.tick(_snap((1000., 0., 2600.)), now=1.)
    assert bot.stats['doing'] == 'bonus_run'
    assert bot.stats['why'] != 'stale combat action'


def test_distance_keeps_normal_running_and_does_not_erase_history_on_discontinuity():
    stats = {'rounds':1}
    for i in range(6):
        re4switch_bot.walk_track(stats, _snap((i*800., 0., 2600.)), i*.2)
    assert stats['navigation_distance_m'] == 4.
    re4switch_bot.walk_track(stats, _snap((80000., 0., 2600.)), 1.2)
    assert stats['navigation_distance_m'] == 4.
    assert stats['walk_discontinuities'] == 1
    stats['rounds'] = 2
    re4switch_bot.walk_track(stats, _snap((80000., 0., 2600.)), 1.4)
    assert stats['navigation_distance_m'] == 0.


def test_blocked_forward_leg_tries_two_distinct_y_presses_then_continues():
    w = _walker((0., 0., 0.))
    pos = w._pos()
    assert w._door_step(('lup', 'b'), pos) is None
    presses = []
    for t in (.81, .89, .97, 1.05, 2.5):
        w.now = t
        presses.append(w._door_step(('lup', 'b'), pos))
    assert presses[:4] == [('lup', 'y'), ('lup',), ('lup', 'y'), ('lup',)]
    assert presses[4] is None and w.stats['door_attempt_no_progress'] == 1
    w.now = 2.6
    assert w._door_step(('lup',), pos) is None  # no endless kick loop


def test_successful_door_movement_cancels_kicking_and_turning_is_not_a_stall():
    w = _walker((0., 0., 0.)); pos = w._pos()
    w._door_step(('lup',), pos)
    w.now = 1.
    assert w._door_step(('lup', 'lleft'), pos) is None
    w.now = 1.9
    assert w._door_step(('lup',), pos) == ('lup', 'y')
    w.now = 2.
    assert w._door_step(('lup',), (0., 0., 500.)) is None
    assert w.stats['door_progress_after_action'] == 1


def test_tank_steering_walks_arcs_turns_on_the_spot_and_quick_turns():
    w = _walker((1000.0, 0.0, 2600.0))
    assert w.steer(0.0) == ("lup", "b") and w.steer(0.0, run=False) == ("lup",)
    assert w.steer(math.radians(25)) == ("lup", "lleft", "b")          # + = his left (the tactical VIEW convention)
    assert w.steer(math.radians(-40)) == ("lup", "lright")             # an arc, no B while it is this tight
    assert w.steer(math.radians(100)) == ("lleft",)                    # on the spot
    assert w.steer(math.radians(170)) == ("ldown", "b")                # the 180 turn (B + down) ...
    assert w.steer(math.radians(170)) == ("lleft",)                    # ... at most once a second
    flipped = W.Walker({}, turn_positive="lright")
    assert flipped.steer(math.radians(25), run=False) == ("lup", "lright")


def test_the_walk_goes_round_the_wall_by_the_door():
    w = _walker((1000.0, 0.0, 2600.0), rot=EAST)
    keys = w.approach((5000.0, 0.0, 2600.0))
    assert w.how == "the stage mesh"
    assert w.wp is not None and abs(w.wp[0] - 3000.0) < 1.0 and abs(w.wp[1] - 1900.0) < 1.0     # the door's middle
    assert "lup" in keys and "lleft" in keys        # facing +x, -z is on his left: the door (z 1900) is
    assert w.stats["mesh_routes"] == 1 and w.stats["nav_status"] == "route"
    near = _walker((2000.0, 0.0, 3500.0), rot=EAST)
    near.approach((2800.0, 0.0, 3500.0))
    assert near.how == "the line"                    # near, open floor between: straight at it


def test_a_near_goal_behind_the_wall_still_goes_by_the_mesh():
    w = _walker((2700.0, 0.0, 3000.0), rot=EAST)
    w.approach((3500.0, 0.0, 3000.0))
    assert w.how == "the stage mesh" and w.stats.get("nav_near_walled") == 1


def test_a_fence_is_jumped_with_the_action_button_and_passed_once_he_is_over():
    mesh = F.mesh()
    w = W.Walker({})
    w.observe(_snap((1500.0, 0.0, 600.0), rot=0.0, mesh=mesh), 0.0)       # below the fence, facing +z
    keys = w.approach((1500.0, 0.0, 2400.0))
    assert w.at_link and "y" in keys and "b" not in keys and "lup" in keys
    w.observe(_snap((1500.0, 0.0, 600.0), rot=0.0, mesh=mesh), 0.4)
    assert "y" not in w.approach((1500.0, 0.0, 2400.0))                  # pulsed: up again
    w.observe(_snap((1500.0, 0.0, 1150.0), rot=0.0, mesh=mesh), 0.9)     # over it (before the 1 s replan)
    w.approach((1500.0, 0.0, 2400.0))
    assert w.stats["mesh_links_taken"] == 1 and not w.at_link


def test_a_crossing_that_never_lets_him_through_is_refused_and_another_way_planned():
    mesh = F.mesh()
    w = W.Walker({})
    for k in range(12):
        w.observe(_snap((1500.0 + 300.0 * (k % 2), 0.0, 650.0), rot=0.0, mesh=mesh), 0.5 * k)
        w.approach((1500.0, 0.0, 2400.0))
    assert w.stats["mesh_links_refused"] >= 1
    assert "never let him through" in w.stats["mesh_refused_last"]
    assert w.no_exit()                                # the strip below the fence has no other way out


def test_never_stand_steps_after_three_seconds_without_ground():
    w = W.Walker({})
    for k in range(9):
        w.observe(_snap((1000.0, 0.0, 2600.0), rot=EAST), 0.5 * k)
        keys = w.approach((5000.0, 0.0, 2600.0))
    assert w.stats["stand_breaks"] == 1 and keys
    w2 = W.Walker({})
    for k in range(9):
        w2.observe(_snap((1000.0, 0.0, 2600.0), rot=EAST), 0.5 * k)
        act = w2.never_stand({"hold": {"zl"}})                          # aiming is not standing
    assert act == {"hold": {"zl"}} and "stand_breaks" not in w2.stats


def test_the_guard_turns_him_off_a_wall_he_walks_at():
    w = _walker((2850.0, 0.0, 3000.0), rot=EAST)                          # 150 mm short of the wall, facing it
    act = w.guard({"hold": {"lup", "b"}})
    assert "lup" not in act["hold"] or {"lleft", "lright"} & set(act["hold"])
    assert w.stats.get("mesh_steers", 0) + w.stats.get("mesh_blocked", 0) == 1


# --- the decorated bot: map marks, plan ---

def _bot():
    bot = re4_switch.Bot(clock=lambda: 100.0)
    return bot


def test_the_bot_takes_the_operators_spot_and_walks_there_by_the_mesh():
    bot = _bot()
    plan = bot.map_goal_plan()
    assert plan["goal_capabilities"] == ["enemy", "point"] and plan["operator_goal"] is None
    bot.receive_map_goal({"id": "g1", "round": plan["goal_round"], "stage": "s", "kind": "point", "entity_id": 0,
                          "pos": [5000.0, 0.0, 2600.0], "label": "Go to the marked spot"})
    act = bot.tick(_snap((1000.0, 0.0, 2600.0), rot=EAST))
    assert act["hold"] == set(bot.walker.approach((5000.0, 0.0, 2600.0)))
    assert bot.stats["map_goal_walk_ticks"] == 1 and bot.map_goal_plan()["operator_goal"]["state"] == "active"
    act = bot.tick(_snap((4000.0, 0.0, 2600.0), rot=EAST))              # 1 m off: arrived (2 m, RE4's mm)
    assert bot.map_goal_plan()["operator_goal"]["state"] == "completed"


def test_a_marked_enemy_in_range_is_fought_alone_and_one_far_off_is_walked_to():
    bot = _bot()
    round_id = bot.map_goal_plan()["goal_round"]
    near = {"slot": 4, "ptr": 0x40, "pos": (2500.0, 0.0, 2600.0), "hp": 300, "hp_max": 300}
    other = {"slot": 6, "ptr": 0x60, "pos": (2200.0, 0.0, 3800.0), "hp": 300, "hp_max": 300}
    bot.receive_map_goal({"id": "g2", "round": round_id, "stage": "s", "kind": "enemy", "entity_id": 4,
                          "pos": list(near["pos"]), "label": "Dispatch"})
    snap = _snap((1000.0, 0.0, 2600.0), rot=EAST, enemies=[near])
    act = bot.tick(snap)
    plain = re4_switch.Bot(clock=lambda: 100.0)
    assert act == re4_switch.Bot.tick.__wrapped__(plain, dict(snap, enemies=[near]))
    assert bot.stats["map_goal_fight_ticks"] == 1
    bot2 = _bot()
    bot2.receive_map_goal({"id": "g3", "round": bot2.map_goal_plan()["goal_round"], "stage": "s", "kind": "enemy",
                           "entity_id": 5, "pos": [5200.0, 0.0, 600.0], "label": "Dispatch"})
    far = {"slot": 5, "ptr": 0x50, "pos": (5200.0, 0.0, 600.0), "hp": 300, "hp_max": 300}
    act = bot2.tick(_snap((1000.0, 0.0, 2600.0), rot=EAST, enemies=[far, other]))
    assert bot2.stats["map_goal_fight_ticks"] == 1                       # the one on the way (1.6 m) first
    act = bot2.tick(_snap((1000.0, 0.0, 2600.0), rot=EAST, enemies=[far]))
    assert bot2.stats["map_goal_walk_ticks"] == 1 and bot2.walker.how == "the stage mesh"


def test_a_mark_from_another_round_is_ignored_and_the_bot_plays_on():
    bot = _bot()
    bot.receive_map_goal({"id": "x", "round": "stale", "stage": "s", "kind": "point", "entity_id": 0,
                          "pos": [5000.0, 0.0, 2600.0], "label": "Go"})
    assert bot.map_goal_plan()["operator_goal"] is None
    snap = _snap((1000.0, 0.0, 2600.0), rot=EAST)
    assert bot.tick(snap) == re4_switch.Bot.tick.__wrapped__(re4_switch.Bot(clock=lambda: 100.0), _snap((1000.0, 0.0, 2600.0), rot=EAST))


def test_plan_carries_the_route_target_and_goal_fields_for_the_map():
    bot = _bot()
    enemy = {"slot": 7, "ptr": 0x70, "pos": (5000.0, 0.0, 2600.0), "hp": 300, "hp_max": 300}
    snap = _snap((1000.0, 0.0, 2600.0), rot=EAST, enemies=[enemy])
    bot.tick(snap)
    bot.target = 0x70
    bot.walker.approach(enemy["pos"])
    plan = T.take_plan(bot)
    assert plan["route_source"] == "room_collision" and plan["route"][-1] == (5000.0, 0.0, 2600.0)
    assert plan["target"]["id"] == 7 and plan["goal_capabilities"] == ["enemy", "point"]


def test_a_synthetic_snapshot_keeps_the_nav_it_carries():
    bot = _bot()
    snap = {"player": {"pos": (1000.0, 0.0, 2600.0), "rot": 0.0, "hp": 1}, "enemies": []}
    bot.tick(snap)
    assert "nav" not in snap                                            # only a game snapshot (module_base) is fitted


# --- the tactical map for RE4 Switch ---

def test_the_tracker_draws_an_re4_frame_and_stage_in_mm():
    bot = _bot()
    enemy = {"slot": 3, "ptr": 0x30, "pos": (5000.0, 0.0, 2600.0), "hp": 400, "hp_max": 400}
    snap = _snap((1000.0, 0.0, 2600.0), rot=EAST, enemies=[enemy, {"slot": 9, "pos": (0.0, 0.0, 0.0), "hp": 0}])
    bot.tick(snap)
    bot.walker.approach(enemy["pos"])
    tr = T.Tracker(re4_switch.MAP_ID)
    f = tr.frame(snap, T.take_plan(bot), "playing", now=10.0)
    assert f["units"] == "mm" and f["geometry"]["source"] == "room_collision" and f["stage"]
    assert f["player"]["pos"] == [1000, 0, 2600] and f["player"]["facing"] == pytest.approx(EAST, abs=1e-3)
    assert [e["id"] for e in f["enemies"]] == [3]                         # the dead one is left out
    assert f["plan"]["route_source"] == "room_collision" and f["clock"]["left"] == 90.0
    assert f["goal_round"] and f["goal_capabilities"] == ["enemy", "point"]
    st = tr.stages[f["stage"]]
    assert st["units"] == "mm" and st["source"] == "room_collision" and st["name"] == "Village"
    assert st["climbs"] == [[4500, 2700, 0, 3000]]
    assert len(st["tris"]) == 3 * len(F.mesh().tris) and st["walls"] and st["cross"]


class _Sink:
    def __init__(self, reply):
        self.reply, self.frames, self.stages = reply, [], []

    def frame(self, body):
        self.frames.append(body)
        return self.reply(body)

    def stage(self, key, body):
        self.stages.append(key)
        return {"ok": True}


def test_the_publisher_posts_frames_sends_the_stage_and_hands_the_mark_to_the_bot():
    bot = _bot()
    t = [0.0]
    replies = []

    def reply(body):
        if not replies:
            replies.append(1)
            return {"need_stage": True, "operator_goal": {"id": "g9", "round": body["goal_round"], "stage": body["stage"],
                                                          "kind": "point", "entity_id": 0, "pos": [5000.0, 0.0, 2600.0],
                                                          "label": "Go"}}
        return {}
    sink = _Sink(reply)
    pub = T.Publisher(sink, re4_switch.MAP_ID, "mm", clock=lambda: t[0], threaded=False)
    snap = _snap((1000.0, 0.0, 2600.0), rot=EAST)
    bot.tick(snap)
    W.publish(pub, snap, bot, "playing")
    assert sink.frames[0]["units"] == "mm" and sink.stages == [sink.frames[0]["stage"]]
    t[0] = 1.0
    W.publish(pub, snap, bot, "playing")                                  # the engine-thread hand-over
    assert bot.map_goal_plan()["operator_goal"]["state"] == "queued"
    t[0] = 3.0
    W.publish(pub, {"player": None}, None, "menu")
    assert sink.frames[-1]["screen"] == "menu" and "player" not in sink.frames[-1]


def test_the_rotation_playbook_takes_the_tactical_sink():
    assert "tactical" in inspect.signature(re4switch_bot.play).parameters
    assert W.publisher(None) is None and W.publish(None, {}, None) is None



def test_a_crossing_taken_or_refused_is_logged(tmp_path, monkeypatch):
    """Operator 2026-11-10: doors and windows need a key press; the walk logs each crossing it takes or gives up on."""
    import json as _json
    from gbox.mercs.titles import re4_walk as W

    class Q(tuple):
        portal = (1000.0, 0.0, 2000.0)
        approach = (900.0, 0.0, 1900.0)
    monkeypatch.setattr(W, "CROSSING_LOG", tmp_path / "x.jsonl")
    w = W.Walker({})
    w._log_crossing("taken", Q((1100.0, 0.0, 2100.0)))
    row = _json.loads((tmp_path / "x.jsonl").read_text().splitlines()[0])
    assert row["event"] == "taken" and row["portal"] == [1000, 0, 2000] and row["key"] == W.ACTION
