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
    assert "opted in" in S.worker_reason(s, worker(now, name="JAYBUILTFINALE"), cfg, [], now)   # the play PC: never by default
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
    assert calls[1]["tool"] == "autoplay" and calls[1]["input"] == {"session_id": "w1-job0", "op": "start", "mode": "auto",
                                                                    "screensaver": True}
    saver.report("w1-job0", {"mode": "replay", "completed": True})
    tick(60)
    assert len(calls) == 2                                     # still playing
    tick(20 * 60)
    assert calls[2]["tool"] == "session_op" and calls[2]["input"]["op"] == "stop_game"
    log = s.all(S.LOG)
    assert len(log) == 1 and log[0]["why"].startswith("20 minutes") and log[0]["result"]["mode"] == "replay"
    assert s.get(S.STATE, "i9-NUC") is None


def test_operator_coming_back_ends_it_at_once():
    s, w, saver, calls, tick = rig()
    tick()
    gid = calls[0]["input"]["game"]["game_id"]
    s.put("session", "w1-job0", {"session_id": "w1-job0", "game_id": gid, "state": "running"})
    tick(5)
    tick(S.START_GRACE)
    w["idle_seconds"] = 0                                      # the operator is back (worker posts /yield on mouse/pad)
    assert saver.yield_to_operator("w1-job0", "mouse")
    assert calls[-1]["input"]["op"] == "stop_game"
    assert "operator came back (mouse)" in s.all(S.LOG)[0]["why"]
    s.delete("session", "w1-job0")
    tick(30)
    assert len(calls) == 3                                     # no new game while the operator uses the PC


def test_failed_launch_is_logged_and_the_pc_frees_up():
    s, w, saver, calls, tick = rig()
    tick()
    s.put("job", "job0", calls[0] | {"state": "failed", "error": "no emulator"})
    assert tick(5)["i9-NUC"].startswith("ended: launch failed")
    assert s.get(S.STATE, "i9-NUC") is None


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
