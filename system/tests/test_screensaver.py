"""Autoplay screensaver (gbox.screensaver): which PCs, which game, and the launch -> play -> rotate / yield cycle."""
import random
from types import SimpleNamespace

from gbox import screensaver as S
from tests.test_inspection_builds import Store as _Store


class Store(_Store):
    def delete(self, kind, key):
        self.docs.pop((kind, key), None)

    def running_sessions(self):
        return [x for x in self.all("session") if x.get("state") == "running"]

GIB = 2**30


def worker(now, name="i9-NUC", idle=3600, os="windows"):
    return {"id": "w1", "name": name, "os": os, "online": True, "idle_seconds": idle, "active_jobs": 0,
            "resources": {"sampled_at": now, "cpu_percent": 10, "memory_percent": 40, "memory_available_bytes": 32 * GIB}}


RUNS = [{"id": "r1", "game_id": "sc", "title": "SoulCalibur", "events": {"pad": 900}, "updated": 5},
        {"id": "r2", "game_id": "pso", "title": "PSO", "events": {"pad": 7000}, "updated": 9},
        {"id": "r3", "game_id": "pso", "title": "PSO", "events": {"pad": 2000}, "updated": 3},
        {"id": "r4", "game_id": "poke", "title": "Poke", "events": {"pad": 20}, "updated": 9},
        {"id": "r5", "game_id": "notes", "title": "Notes", "events": {"mod_action": 3}, "updated": 9}]


def test_played_games_sums_runs_and_drops_test_pokes():
    games = S.played_games(RUNS, 300)
    assert [(g["game_id"], g["pads"], g["last"]) for g in games] == [("pso", 9000, 9), ("sc", 900, 5)]


def test_choose_rests_recent_games_and_honours_pinned():
    games = S.played_games(RUNS, 300)
    rng = random.Random(0)
    assert S.choose(games, {"pso": 1000}, 1000 + 60, rng)["game_id"] == "sc"           # PSO played a minute ago
    assert S.choose(games, {"pso": 1000, "sc": 1000}, 1060, rng) is not None          # all resting: still something
    assert S.choose(games, {}, 0, rng, pinned=["sc"])["game_id"] == "sc"
    assert S.choose([], {}, 0, rng) is None


def test_worker_reason_needs_opt_in_idle_and_a_free_pc():
    s, cfg, now = Store(), S.settings(Store()), 10_000
    assert S.worker_reason(s, worker(now), cfg, [], now) is None
    assert S.worker_reason(s, worker(now, name="JAYBUILTFINALE"), cfg, [], now) is None        # every idle PC by default
    s.put("setting", "background_testing", {"excluded": ["JAYBUILTFINALE"]})                 # unticked in the Tasks menu
    assert "opted in" in S.worker_reason(s, worker(now, name="JAYBUILTFINALE"), cfg, [], now)
    assert "opted in" in S.worker_reason(s, worker(now, name="i9-NUC"), cfg | {"workers": ["lilspark"]}, [], now)
    assert "10 minutes" in S.worker_reason(s, worker(now, idle=120), cfg, [], now)
    assert "already running" in S.worker_reason(s, worker(now), cfg, [{"session_id": "w1-abc"}], now)
    assert S.worker_reason(s, worker(now, name="lilspark", idle=None, os="linux"), cfg, [], now) is None


class Archive:
    def runs(self, limit=200):
        return RUNS


def rig():
    s, clock, calls = Store(), [10_000.0], []
    w = worker(clock[0])

    def submit(req, actor, origin):
        j = {"id": f"job{len(calls)}", "state": "queued", "tool": req.tool, "input": req.input,
             "require_worker": req.require_worker, "agent_use": req.agent_use}
        calls.append(j)
        s.put("job", j["id"], j)
        return SimpleNamespace(**j)                           # the server's submit returns a Job model, not a dict
    saver = S.Screensaver(s, Archive(), submit, lambda: [w], rng=random.Random(1))

    def tick(dt=0):
        clock[0] += dt
        w["resources"]["sampled_at"] = clock[0]
        return saver.tick(clock[0])
    return s, w, saver, calls, tick


def test_launch_then_autoplay_then_rotate_after_session_minutes():
    s, w, saver, calls, tick = rig()
    out = tick()
    assert out["i9-NUC"].startswith("launching") and calls[0]["tool"] == "launch_game" and calls[0]["agent_use"]
    gid = calls[0]["input"]["game"]["game_id"]
    s.put("session", "w1-job0", {"session_id": "w1-job0", "game_id": gid, "state": "running"})
    tick(5)                                                     # session up: labelled agent-owned, autoplay waits for boot
    assert s.get("slabel", "w1-job0")["owner"] == "agent" and len(calls) == 1
    tick(S.START_GRACE)
    from gbox import imitate
    assert calls[1]["tool"] == "autoplay" and calls[1]["input"] == {"session_id": "w1-job0", "op": "start", "mode": "auto",
                                                                    "screensaver": True, "style": imitate.DEFAULT_KNOBS}
    saver.report("w1-job0", {"mode": "replay", "completed": True})
    tick(60)
    assert len(calls) == 2                                     # still playing
    tick(20 * 60)
    assert calls[2]["tool"] == "session_op" and calls[2]["input"]["op"] == "stop_game"
    log = s.all(S.LOG)
    assert len(log) == 1 and log[0]["why"].startswith("20 minutes") and log[0]["result"]["mode"] == "replay"
    assert s.get(S.STATE, "i9-NUC") is None


def test_operator_coming_back_takes_the_game_over_and_it_plays_on():
    s, w, saver, calls, tick = rig()
    tick()
    gid = calls[0]["input"]["game"]["game_id"]
    s.put("session", "w1-job0", {"session_id": "w1-job0", "game_id": gid, "state": "running"})
    tick(5)
    tick(S.START_GRACE)
    w["idle_seconds"] = 0                                      # the operator is back (worker posts /yield on mouse/pad)
    assert saver.yield_to_operator("w1-job0", "mouse")
    assert all(c["input"].get("op") != "stop_game" for c in calls)   # never closed: it plays on until they press Stop
    assert "handed to the operator (mouse)" in s.all(S.LOG)[0]["why"] and s.get(S.STATE, "i9-NUC") is None
    assert s.get("slabel", "w1-job0")["owner"] == "you"         # theirs: nothing automated closes or resets it
    w["idle_seconds"] = 3600
    tick(20 * 60)
    tick(20 * 60)
    assert len(calls) == 2 and all(c["input"].get("op") != "stop_game" for c in calls)   # no rotation, no new game


def test_failed_launch_is_logged_and_the_pc_frees_up():
    s, w, saver, calls, tick = rig()
    tick()
    s.put("job", "job0", calls[0] | {"state": "failed", "error": "no emulator"})
    assert tick(5)["i9-NUC"].startswith("ended: launch failed")
    assert s.get(S.STATE, "i9-NUC") is None


def test_status_says_why_each_pc_starts_no_game_yet():
    # the Sessions view's "Nothing is playing; the screensaver starts on <PC> after N min idle" (session-follow.js)
    s, w, saver, calls, tick = rig()
    w["idle_seconds"] = 4 * 60                                # the operator touched this PC 4 minutes ago
    [pc] = saver.status()["pcs"]
    assert (pc["name"], pc["online"], pc["demo"]) == ("i9-NUC", True, False)
    assert "10 minutes without operator input" in pc["reason"] and pc["starts_in_s"] == 6 * 60
    w["idle_seconds"] = 3600
    tick()                                                    # idle long enough: a demo starts there
    s.put(S.STATE, "i9-NUC", s.get(S.STATE, "i9-NUC") | {"title": "SoulCalibur"})
    [pc] = saver.status()["pcs"]
    assert pc["demo"] and pc["reason"] == "playing SoulCalibur" and pc["starts_in_s"] == 0
    s.put("setting", S.SETTING, S.settings(s) | {"enabled": False})
    s.delete(S.STATE, "i9-NUC")
    assert saver.status()["pcs"][0]["reason"] == "the autoplay screensaver is off"


def test_turning_it_off_stops_running_games_and_starts_none():
    s, w, saver, calls, tick = rig()
    tick()
    gid = calls[0]["input"]["game"]["game_id"]
    s.put("session", "w1-job0", {"session_id": "w1-job0", "game_id": gid, "state": "running"})
    tick(5)
    s.put("setting", S.SETTING, S.settings(s) | {"enabled": False})
    tick(5)
    assert calls[-1]["input"]["op"] == "stop_game"
    s.delete("session", "w1-job0")
    tick(60)
    assert calls[-1]["input"]["op"] == "stop_game"


def test_api_takes_json_bodies():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    s = Store()
    app = FastAPI()
    S.install(app, s, None, lambda: "operator", lambda *a, **k: None, lambda: [], Archive())
    c = TestClient(app)
    r = c.post("/api/autoplay-screensaver", json={"enabled": False, "workers": ["lilspark"]})
    assert r.status_code == 200 and r.json()["settings"]["enabled"] is False
    assert r.json()["settings"]["workers"] == ["lilspark"]
    assert c.post("/api/autoplay-screensaver", json={"idle_minutes": 0}).status_code == 422
    assert c.post("/api/autoplay-screensaver/yield", json={"session_id": "x", "reason": "mouse"}).json() == {"yielded": False}
    assert c.post("/api/autoplay-screensaver/result", json={"session_id": "x", "result": {"a": 1}}).json() == {"saved": False}
    assert [g["game_id"] for g in c.get("/api/autoplay-screensaver").json()["games"]] == ["pso", "sc"]


def test_spark_launch_with_autoplay_starts_it_once_the_game_is_up():
    s, w, saver, calls, tick = rig()
    s.put("setting", S.SETTING, S.settings(s) | {"enabled": False})     # works whether or not the screensaver is on
    S.autoplay_on_launch(s, "L1", "sc")
    s.put("job", "L1", {"id": "L1", "state": "running"})
    tick(5)
    assert not calls                                            # not up yet
    s.put("session", "spark-L1", {"session_id": "spark-L1", "game_id": "sc", "state": "running"})
    tick(5)
    tick(5)
    assert not calls                                            # boot grace
    out = tick(S.START_GRACE)
    assert out["launches"] == ["spark-L1"]
    assert calls[0]["tool"] == "autoplay" and calls[0]["input"]["session_id"] == "spark-L1"
    assert calls[0]["require_worker"] == "spark" and s.all(S.PENDING) == []
    tick(60)
    assert len(calls) == 1                                      # once


def test_every_demo_launch_asks_to_start_in_gameplay():
    s, w, saver, calls, tick = rig()
    tick()
    assert calls[0]["tool"] == "launch_game" and calls[0]["input"]["jump"] is True       # gbox.jumpstate
    assert calls[0]["input"]["memory_cards"] == "operator"     # #2817: the operator's own cards, so their saves load


JUMPED = {"jump": {"booted": True, "file": "sc-stock.state"}}         # launch detail: booted straight into gameplay


def test_a_demo_that_booted_into_gameplay_starts_autoplay_in_the_same_tick():
    s, w, saver, calls, tick = rig()
    tick()
    gid = calls[0]["input"]["game"]["game_id"]
    s.put("session", "w1-job0", {"session_id": "w1-job0", "game_id": gid, "state": "running", "detail": JUMPED})
    assert tick(5)["i9-NUC"].startswith("playing")                    # no START_GRACE: there is no boot to settle
    assert calls[1]["tool"] == "autoplay" and calls[1]["input"]["mode"] == "auto"
    run = s.get(S.STATE, "i9-NUC")
    assert run["phase"] == "playing" and run["jumped"] is True


def test_a_demo_that_booted_the_usual_way_still_waits_for_the_boot():
    s, w, saver, calls, tick = rig()
    tick()
    gid = calls[0]["input"]["game"]["game_id"]
    s.put("session", "w1-job0", {"session_id": "w1-job0", "game_id": gid, "state": "running",
                                 "detail": {"jump": {"booted": False, "why": "no jump state yet"}}})
    tick(5)
    assert len(calls) == 1 and "jumped" not in s.get(S.STATE, "i9-NUC")
    tick(S.START_GRACE)
    assert calls[1]["tool"] == "autoplay"


def test_spark_autoplay_on_launch_starts_at_once_in_a_jump_state():
    s, w, saver, calls, tick = rig()
    s.put("setting", S.SETTING, S.settings(s) | {"enabled": False})
    S.autoplay_on_launch(s, "L3", "sc")
    s.put("job", "L3", {"id": "L3", "state": "succeeded"})
    s.put("session", "spark-L3", {"session_id": "spark-L3", "game_id": "sc", "state": "running", "detail": JUMPED})
    assert tick(5)["launches"] == ["spark-L3"] and calls[0]["input"]["session_id"] == "spark-L3"


def test_a_failed_or_forgotten_launch_drops_its_autoplay_request():
    s, w, saver, calls, tick = rig()
    s.put("setting", S.SETTING, S.settings(s) | {"enabled": False})
    S.autoplay_on_launch(s, "L2", "sc")
    s.put("job", "L2", {"id": "L2", "state": "failed"})
    tick(5)
    assert s.all(S.PENDING) == [] and not calls


def test_the_next_run_of_a_game_uses_its_best_scoring_knobs():
    from gbox import imitate
    s, w, saver, calls, tick = rig()
    good = {"follow": 0.9, "pace": 0.6, "favor": 1.0}
    bad = dict(imitate.DEFAULT_KNOBS)
    for i, (k, score) in enumerate([(good, 2.0), (good, 1.8), (bad, 0.3)]):
        s.put(S.LOG, f"x{i}", {"key": f"x{i}", "game_id": "pso", "started": 1, "result": {"knobs": k, "score": score}})
    s.put(S.LOG, "y", {"key": "y", "game_id": "sc", "started": 1, "result": {"knobs": bad, "score": 9.0}})
    assert sorted(h["score"] for h in saver.history("pso")) == [0.3, 1.8, 2.0]
    saver.rng = random.Random(5)
    picks = [imitate.choose_knobs(saver.history("pso"), random.Random(seed)) for seed in range(40)]
    assert picks.count(good) >= 20                          # mostly the best average so far
    assert any(p != good for p in picks)                    # sometimes a neighbour: it keeps exploring


def test_a_game_autoplay_cannot_press_buttons_in_is_skipped():
    s, w, saver, calls, tick = rig()
    s.put(S.LOG, "m1", {"key": "m1", "game_id": "pso", "started": 1,
                        "result": {"ok": False, "error": "savemgo does not support send_input"}})
    assert S.unplayable(s) == {"pso"}
    tick()
    assert calls[0]["input"]["game"]["game_id"] == "sc"          # PSO had the most play, but it can't take input


def test_server_tags_input_with_its_source(tmp_path):
    from fastapi.testclient import TestClient
    from gbox.config import Config
    from gbox.server import create_app
    cfg = Config(data_dir=tmp_path / "d", cache_dir=tmp_path / "c")
    app = create_app(cfg)
    app.state.store.put("session", "w-s", {"session_id": "w-s", "game_id": "g", "state": "running"})
    c = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    c.post("/api/sessions/w-s/input", json={"events": [{"key": "a", "down": True, "player": 1}]})
    c.post("/api/sessions/w-s/input", json={"events": [{"key": "b", "down": True}]}, headers={"x-gbox-actor": "hermes"})
    got = c.get("/api/sessions/w-s/input").json()
    assert [(e["key"], e["src"]) for e in got] == [("a", "player"), ("b", "agent")]


def test_a_demo_never_adopts_another_launch_of_the_same_game():
    """An agent's session of the same game on that PC is not the demo's: no label, no autoplay started on it."""
    s, w, saver, calls, tick = rig()
    tick()
    gid = calls[0]["input"]["game"]["game_id"]
    s.put("session", "w1-agentjob", {"session_id": "w1-agentjob", "game_id": gid, "state": "running"})
    tick(5)
    tick(S.START_GRACE)
    assert s.get("slabel", "w1-agentjob") is None and len(calls) == 1


def test_claim_drops_a_queued_demo_launch_when_the_pc_already_runs_a_game(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from gbox.config import Config
    from gbox.server import create_app
    cfg = Config(data_dir=tmp_path / "data")
    app = create_app(cfg)
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    store = app.state.store
    store.put("worker", "w1", {"id": "w1", "name": "i9-NUC", "os": "windows", "tools": ["launch_game"], "last_seen": 1})
    store.put("job", "demo1", {"id": "demo1", "tool": "launch_game", "state": "queued", "actor": S.ACTOR,
                               "require_os": None, "require_worker": "w1", "input": {}, "created": 1})
    store.put("session", "w1-agentjob", {"session_id": "w1-agentjob", "state": "running", "worker_id": "w1"})
    r = client.post("/api/workers/w1/claim", json={"idle_seconds": 9999, "active_jobs": 0})
    assert r.status_code == 204, r.text
    job = store.get("job", "demo1")
    assert job["state"] == "failed" and "another game" in job["error"]
