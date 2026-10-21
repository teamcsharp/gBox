"""The tactical map (docs/tactical_map.md): gbox.mercs.tactical builds each round's frames and stages on the worker and
posts them off the engine's tick; gbox.tactical_map keeps the newest frame per session and the stages for the panel
(clients/web/viz/tactical-map.js, tests/test_tactical_map.cjs)."""
import json
import math
import struct
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gbox import mercs_bot as MB
from gbox import tactical_map as TM
from gbox.mercs import engine
from gbox.mercs import tactical as T
from gbox.mercs.titles import re5_nav as N
from gbox.mercs.titles import re5_ps3 as R
from test_re5_mercs import GAMESYS, world


def two_levels():
    """A street (y 0, x -400..400, z 0..800: two quads, four triangles) and a roof beside it (y 300, z 800..1200) that
    only a drop link joins: triangle 4 (the roof) -> triangle 3 across an edge the two do not share."""
    pts = [(-400.0, 0.0, 0.0), (400.0, 0.0, 0.0), (-400.0, 0.0, 400.0), (400.0, 0.0, 400.0),
           (-400.0, 0.0, 800.0), (400.0, 0.0, 800.0),
           (-400.0, 300.0, 820.0), (400.0, 300.0, 820.0), (-400.0, 300.0, 1200.0), (400.0, 300.0, 1200.0)]
    tris = [(0, 1, 3), (0, 3, 2), (2, 3, 5), (2, 5, 4), (6, 7, 9), (6, 9, 8)]
    links = [[(1, 2, 1.0)], [(0, 0, 1.0), (2, 1, 1.0)], [(1, 0, 1.0), (3, 2, 1.0)], [(2, 0, 1.0)],
             [(5, 2, 1.0), (3, 0, 1.0)],                                           # 6-7 (the roof's edge) -> the street
             [(4, 0, 1.0)]]
    return N.NavMesh(pts, tris, links, ptr=0x3100_0000)


def snap(player=(0.0, 0.0, 100.0), rot=0.0, enemies=(), bonuses=(), nav=None, timer=88.5, **kw):
    s = {"player": {"pos": player, "rot": rot, "hp": 900, "hp_max": 1000, "state": "aim", "action": 2},
         "enemies": [{"slot": i, "ptr": 0x3070_0000 + i, "pos": p, "hp": hp, "hp_max": hm} for i, (p, hp, hm) in enumerate(enemies)],
         "bonuses": [{"ptr": ptr, "pos": p, "r": 28.0, "kind": k} for ptr, p, k in bonuses],
         "timer": timer, "timer_start": 120.0, "combo": 7, "combo_timer": 3.14159, "score": 12345, "kills": 20}
    if nav is not None:
        s["nav"] = nav
    s.update(kw)
    return s


HG1, HG2, HG3 = 0x3040_1000, 0x3040_2000, 0x3040_3000


# --- the stage ---------------------------------------------------------------------------------------------------------
def test_a_navmesh_becomes_a_stage_with_its_walls_and_crossings():
    st = T.stage_from_navmesh(two_levels(), "BLUS30491", "cm")
    assert st["v"] == 1 and st["kind"] == "mesh" and st["units"] == "cm" and st["view"] == {"x": -1, "z": 1}
    assert len(st["points"]) == 30 and len(st["tris"]) == 18
    assert st["bounds"] == [-400, 0, 400, 1200] and st["y"] == [0, 300]
    walls = {tuple(sorted(st["walls"][i:i + 2])) for i in range(0, len(st["walls"]), 2)}
    cross = {tuple(sorted(st["cross"][i:i + 2])) for i in range(0, len(st["cross"]), 2)}
    assert cross == {(6, 7)}                                    # the roof's edge: a drop, not a wall, not open floor
    assert (0, 1) in walls and (4, 5) in walls and (2, 3) not in walls   # the street's ends walled, its middle open
    assert len(walls) == 6 + 3                                  # the street's outline + the roof's other three sides
    assert st["key"] == T.stage_key("BLUS30491", two_levels()) == st["key"]
    json.dumps(st)


def test_the_stage_key_is_the_same_stage_every_round_and_another_for_another_stage():
    a, b = two_levels(), two_levels()
    b.ptr = 0x3200_0000                                         # the next round: the same mesh somewhere else in RAM
    assert T.stage_key("BLUS30491", a) == T.stage_key("BLUS30491", b)
    b.points[0] = (-401.0, 0.0, 0.0)
    assert T.stage_key("BLUS30491", a) != T.stage_key("BLUS30491", b)
    assert set(T.stage_key("BLUS30491", a)) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")


# --- the frame ---------------------------------------------------------------------------------------------------------
def test_a_frame_carries_the_round_in_the_contracts_shape():
    tr = T.Tracker("BLUS30491")
    f = tr.frame(snap(enemies=[((0.0, 0.0, 900.0), 800, 800), ((50.0, 0.0, 300.0), 0, 800), ((9.0, 400.0, 9.0), 1, 1)],
                      bonuses=[(HG1, (100.0, 13.0, 700.0), "time")], nav=two_levels()), screen="playing", now=1000.0)
    assert f["v"] == 1 and f["title"] == "BLUS30491" and f["units"] == "cm" and f["screen"] == "playing"
    assert f["stage"] == T.stage_key("BLUS30491", two_levels()) and f["stage"] in tr.stages
    assert f["clock"] == {"left": 88.5, "start": 120.0, "combo": 7, "combo_left": 3.14, "score": 12345, "kills": 20}
    assert f["player"] == {"pos": [0, 0, 100], "facing": 0.0, "hp": 900, "hp_max": 1000, "state": "aim", "aim": True}
    assert f["enemies"] == [{"id": 0, "pos": [0, 0, 900], "hp": 800, "hp_max": 800}]   # the dead and the crow left out
    assert f["bonuses"] == [{"id": HG1, "pos": [100, 13, 700], "kind": "time", "taken": False}]
    nb = f["plan"]["nearest_bonus"]                             # no plan(): the navmesh's route at RUN_SPEED, an estimate
    assert nb["id"] == HG1 and nb["est"] is True and nb["pos"] == [100, 13, 700]
    assert 600 <= nb["dist"] <= 700 and nb["eta_s"] == round(nb["dist"] / T.RUN_SPEED["cm"], 1)
    assert len(json.dumps(f)) < 1500


def test_a_taken_bonus_stays_on_the_map_until_the_round_ends():
    tr = T.Tracker("BLUS30491")
    both = [(HG1, (100.0, 13.0, 700.0), "time"), (HG2, (-300.0, 13.0, 200.0), "combo")]
    tr.frame(snap(bonuses=both), now=1.0)
    f = tr.frame(snap(bonuses=both[1:]), now=2.0)               # HG1 left RAM: taken
    assert [(b["id"], b["kind"], b["taken"]) for b in f["bonuses"]] == [(HG2, "combo", False), (HG1, "time", True)]
    f = tr.frame(snap(bonuses=both), now=3.0)                   # back in RAM (a walk of the unit line that missed it)
    assert all(not b["taken"] for b in f["bonuses"])
    tr.frame(snap(bonuses=both[1:]), now=4.0)
    f = tr.frame({"player": None, "timer": 0.0}, screen="results", now=5.0)    # between rounds: no player, forgotten
    assert "player" not in f and "bonuses" not in f and f["screen"] == "results" and f["clock"]["left"] == 0.0
    f = tr.frame(snap(bonuses=[(HG3, (0.0, 13.0, 500.0), "time")]), now=6.0)
    assert [b["id"] for b in f["bonuses"]] == [HG3]


def test_the_bots_plan_goes_on_the_frame():
    class Bot:
        route = [(1.0, 2.0, 3.0)]

        def plan(self):
            return {"phase": "combo_bonus", "target": {"kind": "enemy", "id": 1},
                    "route": self.route, "stand": {"pos": (10.4, 0.0, 20.6), "r": 300},
                    "nearest_bonus": {"id": HG2, "kind": "combo", "dist": 1234.5, "eta_s": 2.75},
                    "enemy_flags": {0: ["no_los"], "1": ["attacking", "blocking", "attacking"]}, "note": "x" * 200}
    bot = Bot()
    plan = T.take_plan(bot)
    bot.route.pop()                                             # the bot walks on: the plan taken keeps its copy
    f = T.Tracker("BLUS30491").frame(snap(enemies=[((0.0, 0.0, 900.0), 800, 800), ((500.0, 0.0, 900.0), 700, 700)],
                                          bonuses=[(HG2, (-300.0, 13.0, 200.0), "combo")]), plan, now=1.0)
    p = f["plan"]
    assert p["phase"] == "combo_bonus" and p["route"] == [[1, 2, 3]] and p["stand"] == {"pos": [10, 0, 21], "r": 300}
    assert p["target"] == {"kind": "enemy", "id": 1, "pos": [500, 0, 900]}       # its place filled in from the frame
    assert p["nearest_bonus"] == {"id": HG2, "kind": "combo", "pos": [-300, 13, 200], "dist": 1234, "eta_s": 2.8}
    assert len(p["note"]) == T.MAX_NOTE and "enemy_flags" not in p
    assert [e.get("flags") for e in f["enemies"]] == [["no_los"], ["attacking", "blocking", "target"]]


def test_without_a_plan_the_target_and_route_come_from_the_bot_it_has():
    bot = R.Bot(clock=lambda: 50.0)
    bot.target, bot.route, bot.route_for = f"bonus {HG1:#x}", [(0.0, 0.0, 400.0), (100.0, 13.0, 700.0)], HG1
    plan = T.take_plan(bot)
    assert plan["fallback"] and plan["target"] == {"kind": "bonus", "id": HG1} and len(plan["route"]) == 2
    f = T.Tracker("BLUS30491").frame(snap(bonuses=[(HG1, (100.0, 13.0, 700.0), "time")]), plan, now=1.0)
    assert f["plan"]["target"] == {"kind": "bonus", "id": HG1, "pos": [100, 13, 700]}
    assert f["plan"]["route"] == [[0, 0, 400], [100, 13, 700]] and "phase" not in f["plan"]
    bot.target = 3                                              # shooting a Majini (slot 3): no route shown
    assert T.take_plan(bot) == {"fallback": True, "target": {"kind": "enemy", "id": 3}}
    assert T.take_plan(None) == {}


def test_a_plan_that_raises_is_no_plan():
    class Bad:
        target = None

        def plan(self):
            raise RuntimeError("boom")
    assert T.take_plan(Bad()) == {"fallback": True}


def test_the_nearest_bonus_by_route_is_not_the_nearest_in_a_straight_line():
    tr = T.Tracker("BLUS30491")
    mesh = two_levels()
    roof = (HG2, (0.0, 313.0, 900.0), "time")                  # 2 m away up on the roof: no way up there
    street = (HG1, (300.0, 13.0, 750.0), "time")                # further, but on his street
    f = tr.frame(snap(player=(0.0, 0.0, 700.0), bonuses=[roof, street], nav=mesh), now=10.0)
    assert f["plan"]["nearest_bonus"]["id"] == HG1
    f = tr.frame(snap(player=(0.0, 0.0, 700.0), bonuses=[roof, street], nav=mesh), now=10.2)   # within ROUTE_EVERY_S:
    assert f["plan"]["nearest_bonus"]["id"] == HG1                                            # the routes kept


# --- posting -----------------------------------------------------------------------------------------------------------
class Sink:
    def __init__(self, have=(), fail=0):
        self.frames, self.stages, self.have, self.fail = [], {}, set(have), fail

    def frame(self, body):
        if self.fail:
            self.fail -= 1
            raise OSError("control plane away")
        self.frames.append(json.loads(json.dumps(body)))
        return {"ok": True, "seq": len(self.frames), "need_stage": bool(body.get("stage")) and body["stage"] not in self.have}

    def stage(self, key, body):
        self.stages[key] = body
        self.have.add(key)
        return {"ok": True}


def test_the_publisher_keeps_ten_a_second_and_sends_the_stage_when_asked():
    t = [0.0]
    sink = Sink()
    pub = T.Publisher(sink, "BLUS30491", clock=lambda: t[0], threaded=False)
    for i in range(30):                                         # 30 engine ticks in a second
        t[0] = i / 30
        pub(snap(nav=two_levels()), None, "playing")
    assert len(sink.frames) == 10 and pub.stats["sent"] == 10
    assert list(sink.stages) == [sink.frames[0]["stage"]] and pub.stats["stages"] == 1   # once: then the plane has it
    t[0] = 5.0
    assert pub.idle("results") and not pub.idle("results")      # between rounds: a frame a second
    assert sink.frames[-1]["screen"] == "results" and "player" not in sink.frames[-1]
    pub.close()
    assert sink.frames[-1]["screen"] == "stopped"
    assert not pub(snap(), None, "playing")                     # closed: nothing more


def test_a_control_plane_that_is_away_never_stops_the_round():
    t = [0.0]
    sink = Sink(fail=1)
    pub = T.Publisher(sink, "BLUS30491", clock=lambda: t[0], threaded=False)
    pub(snap(), None, "playing")                                # fails: backs off a moment
    assert pub.stats["errors"] == 1 and "control plane away" in pub.stats["last_error"]
    t[0] = 0.5
    pub(snap(), None, "playing")                                # still backing off: built, not posted
    assert sink.frames == []
    t[0] = 2.5
    pub(snap(), None, "playing")
    assert len(sink.frames) == 1


def test_the_publisher_posts_on_its_own_thread():
    sink = Sink()
    pub = T.Publisher(sink, "BLUS30491")
    assert pub(snap(), None, "playing")
    pub.close()                                                 # the thread drains, posts "stopped" and ends
    assert [f["screen"] for f in sink.frames][-1] == "stopped" and len(sink.frames) >= 1
    assert pub._thread is not None and not pub._thread.is_alive()


def test_the_engine_hands_every_tick_to_the_map_and_shrugs_off_its_failures():
    mem = world(action=2, enemies=[((0.0, 0.0, 1000.0), 800, 800)])
    seen, n = [], [0]

    def stopped():
        n[0] += 1
        if n[0] == 6:
            mem.put(GAMESYS + 0x3E0, struct.pack(">f", 0.0))     # the clock runs out: the results
        return n[0] > 40

    def hook(s, bot, where):
        seen.append((where, s["player"] is not None, type(bot).__name__))
        raise RuntimeError("a broken map")
    why = engine.play_round({"driver": "gbox.mercs.titles.re5_ps3"}, mem, lambda rows: None, stopped, {},
                            sleep=lambda s: None, clock=lambda: n[0] * 0.5, tick_s=0.0, tactical=hook)
    assert why == "round"
    assert seen[0] == ("playing", True, "Bot") and ("results", True, "Bot") in seen


def test_the_deployment_makes_a_publisher_only_with_a_sink():
    assert MB.tactical_publisher(None, {"map_id": "BLUS30491"}) is None
    pub = MB.tactical_publisher(Sink(), {"map_id": "BLUS30491"})
    assert isinstance(pub, T.Publisher) and pub.tracker.units == "cm"
    assert MB.tactical_publisher(Sink(), {"map_id": "G4BE08"}).tracker.units == "mm"


# --- the control plane -------------------------------------------------------------------------------------------------
def test_the_store_keeps_the_newest_frame_and_answers_same_when_nothing_moved():
    t = [100.0]
    s = TM.Store(clock=lambda: t[0])
    r = s.put_frame("w-1", {"v": 1, "stage": "BLUS30491.nav6.0000abcd", "screen": "playing"})
    assert r == {"ok": True, "seq": 1, "need_stage": True}
    assert s.put_stage("BLUS30491.nav6.0000abcd", {"v": 1, "kind": "mesh", "points": []}) == {"ok": True}
    assert s.put_frame("w-1", {"v": 1, "stage": "BLUS30491.nav6.0000abcd"})["need_stage"] is False
    t[0] = 101.0
    f = s.get_frame("w-1")
    assert f["seq"] == 2 and f["age_s"] == 1.0 and f["live"] is True and f["stage"] == "BLUS30491.nav6.0000abcd"
    assert s.get_frame("w-1", after=2) == {"seq": 2, "age_s": 1.0, "live": True, "same": True}
    assert s.get_frame("w-1", after=1)["seq"] == 2             # any other seq (an older one, a restart's): the frame
    t[0] = 105.0
    assert s.get_frame("w-1")["live"] is False
    t[0] = 100.0 + TM.TTL_S + 1
    assert s.get_frame("w-1") == {} and s.get_frame("nobody") == {}
    assert s.get_stage("BLUS30491.nav6.0000abcd")["key"] == "BLUS30491.nav6.0000abcd" and s.get_stage("x") is None


def test_the_store_refuses_what_is_not_the_contract():
    s = TM.Store()
    for sid, body in (("w-1", {"v": 2}), ("w-1", []), ("w-1", {"v": 1, "stage": "../etc"}), ("a/b", {"v": 1})):
        with pytest.raises(ValueError):
            s.put_frame(sid, body)
    for key, body in (("k", {"v": 1, "kind": "voxels"}), ("bad key", {"v": 1, "kind": "mesh"})):
        with pytest.raises(ValueError):
            s.put_stage(key, body)
    for i in range(TM.STAGES_KEEP + 3):
        s.put_stage(f"k{i}", {"v": 1, "kind": "grid"})
    assert len(s.stages) == TM.STAGES_KEEP and s.get_stage("k0") is None


def client():
    app = FastAPI()
    TM.install(app, lambda: "agent")
    return TestClient(app), app


def test_the_routes_carry_frames_and_stages_end_to_end():
    c, app = client()
    tr = T.Tracker("BLUS30491")
    f = tr.frame(snap(bonuses=[(HG1, (100.0, 13.0, 700.0), "time")], nav=two_levels()), screen="playing", now=1.0)
    r = c.post("/api/autoplay/tactical/w1-job1", json=f).json()
    assert r["seq"] == 1 and r["need_stage"] is True
    assert c.put(f"/api/autoplay/tactical/stage/{f['stage']}", json=tr.stages[f["stage"]]).json() == {"ok": True}
    got = c.get("/api/autoplay/tactical/w1-job1").json()
    assert got["player"]["pos"] == [0, 0, 100] and got["seq"] == 1 and got["live"] is True
    assert c.get("/api/autoplay/tactical/w1-job1", params={"after": 1}).json()["same"] is True
    st = c.get(f"/api/autoplay/tactical/stage/{f['stage']}").json()
    assert st["tris"] == tr.stages[f["stage"]]["tris"]
    assert c.get("/api/autoplay/tactical/stage/nothing").status_code == 404
    assert c.get("/api/autoplay/tactical/nobody").json() == {}
    assert c.post("/api/autoplay/tactical/w1-job1", json={"v": 9}).status_code == 422
    assert c.post("/api/autoplay/tactical/w1-job1", content=b"{not json").status_code == 422
    big = {"v": 1, "pad": "x" * (TM.FRAME_MAX + 10)}
    assert c.post("/api/autoplay/tactical/w1-job1", json=big).status_code == 413
    assert app.state.tactical_map.get_frame("w1-job1")["seq"] == 1


def test_the_http_sink_posts_where_the_routes_are():
    c, _ = client()
    sink = T.HttpSink("http://testserver", {"x-gbox-actor": "autoplay"}, "w1-job2", client=c)
    tr = T.Tracker("BLUS30491")
    f = tr.frame(snap(nav=two_levels()), now=1.0)
    assert sink.frame(f)["need_stage"] is True
    assert sink.stage(f["stage"], tr.stages[f["stage"]]) == {"ok": True}
    assert sink.frame(f)["need_stage"] is False
    assert c.get("/api/autoplay/tactical/w1-job2").json()["seq"] == 2


def test_the_server_installs_the_routes(cfg):
    from gbox.server import create_app
    app = create_app(cfg)
    c = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}", "x-gbox-actor": "autoplay"})
    assert c.post("/api/autoplay/tactical/w1-j1", json={"v": 1, "screen": "menu"}).json()["need_stage"] is False
    assert c.get("/api/autoplay/tactical/w1-j1").json()["screen"] == "menu"
    assert TestClient(app).get("/api/autoplay/tactical/w1-j1").status_code == 401        # the token, as everywhere
