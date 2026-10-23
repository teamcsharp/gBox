import json
import sqlite3

from gbox.mercs.atlas import NavigationAtlas, mesh_geometry
from gbox.mercs.route_trace import Recorder
from gbox.mercs.titles.re5_nav import Learning, NavMesh
from gbox.mercs.tour import GoalCommitment


def mesh():
    return NavMesh([(0.,0.,0.), (1000.,0.,0.), (1000.,0.,1000.), (0.,0.,1000.)],
                   [(0,1,2), (0,2,3)], [[(1,2,1.)], [(0,0,1.)]])


def frame(pos, target=4):
    return {"player": {"pos": pos, "hp": 100}, "plan": {"target": {"id": target}},
            "clock": {"combo": 5, "score": 1000}, "enemies": [{"pos": [20,0,20], "id": 7}]}


def test_stage_atlas_retains_measured_directional_geometry_without_inventing_object_types(tmp_path):
    atlas, nav = NavigationAtlas(tmp_path, "RE5"), mesh()
    key = atlas.stage(nav, {"stage": 0})
    nav.ptr = 0x30004000
    assert atlas.stage(nav) == key
    geometry = json.loads(atlas.db.execute("SELECT geometry FROM stages").fetchone()[0])
    assert geometry["links"] == [[0,1,2,1.], [1,0,0,1.]]
    assert len(geometry["boundaries"]) == 4
    assert geometry["boundary_meaning"] == "no ordinary directed floor link"
    assert geometry["action_links"] == []
    assert not atlas.db.execute("SELECT * FROM landmarks").fetchall()
    assert atlas.landmark(key, "door", (20,0,20), None) is None
    assert atlas.landmark(key, "door", (20,0,20), {"source": "verified_game_object", "label": 1})
    atlas.close()


def test_round_map_and_best_checkpoint_route_require_acquisition_evidence(tmp_path):
    atlas = NavigationAtlas(tmp_path, "RE5")
    key = atlas.stage(mesh())
    atlas.begin("run-one", key, 0, {"character": "Jill"})
    observation = {"kind": "time", "pos": [350,0,100], "evidence": {"source": "ram_bonus_actor"}}
    atlas.sample("run-one", 0., frame([100,0,100]), inputs=["lup"], observations=[observation])
    atlas.sample("run-one", .5, frame([300,0,100]), inputs=["lup"], observations=[observation])
    assert atlas.db.execute("SELECT acquired FROM landmarks").fetchone()[0] == 0
    atlas.sample("run-one", 1., frame([350,0,100]), inputs=["square"],
                 observations=[observation | {"acquired": True}])
    # Repeated taken actor entries do not count another pickup in this round.
    atlas.sample("run-one", 1.5, frame([350,0,100]), observations=[observation | {"acquired": True}])
    result = atlas.finish("run-one", 2, "completed", {"rank": "S"})
    assert result["review"]["time_bonuses_acquired"] == 1
    assert not result["review"]["rank_verified"]
    row = atlas.db.execute("SELECT origin,destination,completed,best_seconds,best_distance,best_path FROM checkpoint_routes").fetchone()
    assert row[:5] == ("spawn:100:0:100", "time:350:0:100", 1, 1., 250.)
    assert len(json.loads(row[5])) == 3
    artifact = json.loads(__import__("pathlib").Path(result["json"]).read_text())
    assert artifact["geometry"]["triangles"] == [[0,1,2],[0,2,3]]
    assert artifact["events"][0]["kind"] == "checkpoint_acquired"
    svg = __import__("pathlib").Path(result["map"]).read_text()
    assert "<svg" in svg and "<title>" in svg and "#42d9f3" in svg
    atlas.close()
    reopened = NavigationAtlas(tmp_path, "RE5")
    assert reopened.db.execute("SELECT rounds FROM stages").fetchone()[0] == 1
    assert reopened.db.execute("SELECT acquired FROM landmarks").fetchone()[0] == 1
    reopened.close()


def test_loading_jump_cannot_become_a_learned_shortcut(tmp_path):
    atlas = NavigationAtlas(tmp_path, "RE5")
    key = atlas.stage(mesh())
    atlas.begin("jump", key, 0)
    atlas.sample("jump", 0, frame([0,0,0]))
    atlas.sample("jump", .5, frame([10000,0,0]))
    atlas.sample("jump", 1, frame([10100,0,0]), observations=[
        {"kind": "time", "pos": [10100,0,0], "evidence": {"source": "ram_actor_removed"}, "acquired": True}])
    row = atlas.db.execute("SELECT completed,best_path FROM checkpoint_routes").fetchone()
    assert row == (0,None)
    atlas.close()


def test_round_review_identifies_stationary_commands_and_goal_reversals():
    samples = [{"at": i*.5, "frame": frame([100 if i%2 else 220,0,100], i%2), "inputs": ["lup"]}
               for i in range(8)]
    samples += [{"at": 4+i*.5, "frame": frame([100,0,100]), "inputs": ["lup"]} for i in range(6)]
    result = NavigationAtlas.review(samples, [{"kind": "hits_taken", "at": 5, "value": 1}], {})
    assert result["oscillations"] >= 1 and result["commanded_stationary_s"] >= 2.
    assert result["target_changes"] >= 1 and len(result["next_round_actions"]) >= 2
    assert result["events"] == {"hits_taken": 1}


def test_recorder_writes_atlas_off_input_thread_and_confirms_clock_gained_pickups(tmp_path):
    class Bot:
        def plan(self): return {"phase": "gather_time"}
    rec = Recorder(lambda *a,**kw: None, atlas_root=tmp_path, title="RE5", round_id="shared-round")
    snap = {"player": {"pos": [100,0,100], "hp": 100}, "nav": mesh(), "timer": 100, "kills": 0,
            "bonuses": [{"ptr": 123, "pos": [300,0,100], "kind": "time"}]}
    rec.observe(snap, Bot(), {}, 0, ["lup"], "before_decision")
    rec.observe(snap | {"bonuses": [], "timer": 129}, Bot(), {}, 1, ["square"], "before_decision")
    rec.observe(snap | {"bonuses": [], "timer": 128.5}, Bot(), {}, 1.5, [], "before_decision")
    status = rec.finish(2, "completed", {"rank_verified": True, "rank": "S"}, wait_s=5)
    assert not status.get("navigation_atlas_error"), status
    assert status["navigation_atlas_review"]["time_bonuses_acquired"] == 1
    db = sqlite3.connect(tmp_path / "RE5" / "atlas.sqlite")
    assert db.execute("SELECT id FROM rounds").fetchone()[0].startswith("shared-round:")
    db.close()


def test_old_disappeared_bonus_is_not_credited_for_a_later_unrelated_kill_clock_gain(tmp_path):
    class Bot:
        def plan(self): return {}
    rec = Recorder(lambda *a,**kw: None, atlas_root=tmp_path, title="RE5")
    snap = {"player": {"pos": [100,0,100], "hp": 100}, "nav": mesh(), "timer": 100, "kills": 0,
            "bonuses": [{"ptr": 123, "pos": [300,0,100], "kind": "time"}]}
    rec.observe(snap, Bot(), {}, 0, ["lup"], "before_decision")
    rec.observe(snap | {"bonuses": [], "timer": 99}, Bot(), {}, 1, [], "before_decision")
    rec.observe(snap | {"bonuses": [], "timer": 108}, Bot(), {}, 3, [], "before_decision")
    status = rec.finish(4,"completed",{},wait_s=5)
    assert status["navigation_atlas_review"]["time_bonuses_acquired"] == 0


def test_round_artifacts_retain_new_mine_events_once_and_never_attribute_explosion_kills(tmp_path):
    class Controller:
        events = []
    class Bot:
        mines = Controller()
        def plan(self): return {"phase":"leave_proximity_bomb"}
    rows, stats, bot = [],{},Bot()
    rec = Recorder(lambda kind,**kw:rows.append({"kind":kind,**kw}), atlas_root=tmp_path, title="RE5")
    ground = {123:{"pos":[100,0,100],"arming_s":0.,"detonating":False}}
    snap = {"player":{"pos":[100,0,100],"hp":100},"nav":mesh(),"ground_mines":ground,"timer":100.}
    rec.observe(snap,bot,stats,0.,["lup"],"before_decision")
    bot.mines.events.append({"kind":"placement_verified","at":.1,"actor":123,"pos":[100,0,100],"combo":5,"score":1000})
    stats["mines_placed"] = 1
    rec.observe(snap,bot,stats,.1,[],"decision")
    before = len(rows)
    rec.observe(snap,bot,stats,.2,[],"decision")
    assert len(rows) == before  # a retained Controller history cannot create repeated event frames
    bot.mines.events.append({"kind":"detonation_observed","at":.3,"actor":123,"pos":[100,0,100],"owned":True,"combo":8,"score":1500})
    stats["mine_detonations_observed"] = 1
    rec.observe(snap | {"ground_mines":{123:ground[123] | {"detonating":True}}},bot,stats,.3,["lup"],"decision")
    rec.observe(snap,bot,stats,.4,["lup"],"decision")
    bot.mines.events.append({"kind":"retreat_complete","at":1.,"actor":123,"distance":650.,"elapsed_s":.9})
    stats["mine_retreats_completed"] = 1
    rec.observe(snap | {"player":{"pos":[750,0,100],"hp":100}},bot,stats,1.,["lup"],"decision")
    status = rec.finish(2.,"completed",{"mines_placed":1,"kills":99},wait_s=5)
    assert not status.get("navigation_atlas_error"),status
    artifact = json.loads(__import__("pathlib").Path(status["navigation_atlas_round"]).read_text())
    events = [event for event in artifact["events"] if event["kind"] in
              ("mine_placement_verified","mine_detonation_observed","mine_retreat_complete")]
    assert len(events) == 3
    assert [event["kind"] for event in events] == ["mine_placement_verified","mine_detonation_observed","mine_retreat_complete"]
    assert events[1]["kill_attribution"] == "unverified" and events[1]["combo"] == 8
    assert events[2]["pos"] == [750.,0.,100.]
    assert artifact["samples"][0]["frame"]["mines"][0]["actor"] == 123
    assert sum(len(sample["frame"].get("mine_events",[])) for sample in artifact["samples"]) == 3
    review = artifact["review"]["mines"]
    assert review["placements_verified"] == review["detonation_events_observed"] == review["retreats_completed"] == 1
    assert review["kills_attributed"] is None and review["damage_attributed"] is None
    svg = __import__("pathlib").Path(status["navigation_atlas_map"]).read_text()
    for kind in ("proximity-bomb","mine-retreat","mine_placement_verified","mine_detonation_observed","mine_retreat_complete"):
        assert 'data-kind="'+kind+'"' in svg


def test_mine_event_deduplication_and_snapshot_bounds_are_visible(tmp_path):
    class Bot:
        mines = type("Controller",(),{"events":[]})()
        def plan(self): return {}
    rows,bot = [],Bot()
    rec = Recorder(lambda kind,**kw:rows.append({"kind":kind,**kw}))
    snap = {"player":{"pos":[100,0,100],"hp":100},"nav":mesh(),
            "ground_mines":{i:{"pos":[i,0,100]} for i in range(300)}}
    for i in range(550):
        bot.mines.events[:] = [{"kind":"placement_unconfirmed","at":float(i),"pos":[100,0,100]}]
        rec.observe(snap,bot,{},float(i),[],"decision")
    assert len(rec.mine_event_seen) == 512
    assert len(rows[-1]["frame"]["mines"]) == 256
    assert rows[-1]["frame"]["mine_snapshot_truncated"] == 44


def test_checkpoint_goal_holds_through_replans_combat_and_releases_on_real_failure():
    held = GoalCommitment(patience_s=5, improvement=50)
    assert held.choose(1, [1,2], 0) == 1
    assert held.choose(2, [1,2], 1, 1000) == 1
    assert held.choose(2, [1,2], 2, 900) == 1
    assert held.choose(2, [1,2], 10, 900, advancing=False) == 1
    assert held.choose(2, [1,2], 11, 850) == 1
    assert held.choose(2, [1,2], 12, failed=True) == 2
    assert held.choose(1, [1], 13) == 1  # collected/removed goal releases
    assert held.choose(2, [1,2], 14, 800) == 1
    assert held.choose(2, [1,2], 20, 800) == 2  # actual no-progress walking lease expires


def test_navmesh_retreat_uses_supported_directed_floor_and_rejects_action_links():
    nav = mesh()
    start, hazard = (100.,0.,150.), (100.,0.,100.)
    route = nav.retreat(start, hazard, 500.)
    assert route is not None and __import__("math").dist(route[-1], hazard) >= 500.
    assert all(nav.floor_segment(a,b) for a,b in zip([start]+route,route))
    # The only outgoing link is enemy-only, between disjoint floors.
    disjoint = NavMesh([(0.,0.,0.),(100.,0.,0.),(0.,0.,100.),(1000.,0.,0.),(1100.,0.,0.),(1000.,0.,100.)],
                       [(0,1,2),(3,4,5)], [[(1,0,1.)],[]])
    assert disjoint.retreat((20.,0.,20.), (0.,0.,0.), 500.) is None
    assert nav.retreat((2000.,0.,0.), hazard, 500.) == []


def test_route_oscillation_is_persisted_as_soft_cost_without_inventing_walls(tmp_path):
    nav = NavMesh([(0.,0.,0.),(200.,0.,0.),(200.,0.,200.),(0.,0.,200.),(600.,0.,0.),(600.,0.,200.)],
                  [(0,1,2),(0,2,3),(1,4,5)], [[(1,2,1.),(2,1,1.)],[(0,0,1.)],[]])
    learning = Learning(tmp_path / "learning.json")
    learning.begin_route(nav, (150.,0.,50.), (500.,0.,50.))
    for i,pos in enumerate(((150.,0.,50.),(50.,0.,150.),(150.,0.,50.),(50.,0.,150.))):
        learning.observe(nav,pos,i*.5)
    assert learning.link_penalties(nav).get((0,1),0) > 0
    assert nav.route((150.,0.,50.),(50.,0.,150.))
    learning.save()
    assert Learning(tmp_path / "learning.json").link_penalties(nav).get((0,1),0) > 0
    clean = Learning()
    for i,pos in enumerate(((150.,0.,50.),(50.,0.,150.),(150.,0.,50.),(50.,0.,150.))):
        clean.observe(nav,pos,i*.5)
    assert not clean.link_penalties(nav)  # free exploration is not failed checkpoint pursuit
