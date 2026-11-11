"""Per-PC availability for automated background testing (#1383)."""
import time

from fastapi.testclient import TestClient

from gbox import background_testing
from gbox.server import create_app


class FakeStore:
    def __init__(self):
        self.rows = {}

    def get(self, kind, id):
        return self.rows.get((kind, id))

    def put(self, kind, id, body):
        self.rows[(kind, id)] = body


def test_setting_round_trip():
    s = FakeStore()
    assert background_testing.excluded(s) == set()
    assert background_testing.set_available(s, "JAYBUILTFINALE", False) == {"JAYBUILTFINALE"}
    assert background_testing.set_available(s, "i9-NUC", False) == {"JAYBUILTFINALE", "i9-NUC"}
    assert background_testing.set_available(s, "JAYBUILTFINALE", True) == {"i9-NUC"}
    ex = background_testing.excluded(s)
    assert background_testing.allowed({"id": "abc", "name": "JAYBUILTFINALE"}, ex)
    assert not background_testing.allowed({"id": "def", "name": "i9-NUC"}, ex)


def test_routes_flag_workers_and_exclude_them_from_other_pc_testing(cfg):
    app = create_app(cfg)
    store = app.state.store
    now = time.time()
    for wid, name, idle in (("w1", "i9-NUC", 5), ("w2", "JAYBUILTFINALE", 900)):      # the operator plays on i9-NUC
        store.put("worker", wid, {"id": wid, "name": name, "os": "windows", "last_seen": now, "tools": ["launch_game"],
                                  "unavailable": {}, "idle_seconds": idle, "active_jobs": 0})
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    assert all(w["background_testing"] for w in client.get("/api/workers").json())

    r = client.post("/api/testing/workers/JAYBUILTFINALE", json={"available": False})
    assert r.status_code == 200, r.text
    flags = {w["name"]: w["background_testing"] for w in r.json()["workers"]}
    assert flags == {"i9-NUC": True, "JAYBUILTFINALE": False} and r.json()["excluded"] == ["JAYBUILTFINALE"]
    assert {w["name"]: w["background_testing"] for w in client.get("/api/workers").json()} == flags

    # the other-PC chooser never picks an unticked PC, even when it is the idle one
    refused = client.get("/api/workers/idle")
    assert refused.status_code == 409, refused.text
    by_id = client.post("/api/testing/workers/w2", json={"available": True})           # by worker id works too
    assert by_id.json()["excluded"] == []
    idle = client.get("/api/workers/idle")
    assert idle.status_code == 200 and idle.json()["name"] == "JAYBUILTFINALE", idle.text
    client.post("/api/testing/workers/i9-NUC", json={"available": False})
    assert client.get("/api/workers/idle").json()["name"] == "JAYBUILTFINALE"        # the operator PC was never a candidate
    client.post("/api/testing/workers/JAYBUILTFINALE", json={"available": False})
    none = client.get("/api/workers/idle")
    assert none.status_code == 409 and "background testing" in none.json()["detail"]
    assert client.post("/api/testing/workers/nobody", json={"available": True}).status_code == 404


def _busy_worker(now):
    return {"id": "w1", "name": "i9-NUC", "os": "windows", "idle_seconds": 5,
            "resources": {"sampled_at": now, "cpu_percent": 10, "memory_percent": 40,
                          "memory_available_bytes": 8 * 1024 ** 3, "gpus": []}}


def test_a_pc_the_operator_dedicated_skips_the_idle_wait_but_keeps_the_budgets():
    """2026-11-10, the operator: "play PSO on the i9 despite me being on the PC" - a per-PC designation of the
    background-testing policy, not a bypass of the CPU/GPU/memory budget."""
    now = time.time()
    s = FakeStore()
    s.running_sessions = lambda: []
    worker = _busy_worker(now)
    assert background_testing.guarded_reason(s, worker, now=now) == "Waiting for five minutes without operator input."
    s.put("setting", background_testing.SETTING, {"policies": {"i9-NUC": {"allow_while_active": True}}})
    assert background_testing.policy(s, "i9-NUC")["allow_while_active"] is True
    assert background_testing.guarded_reason(s, worker, now=now) is None
    hot = _busy_worker(now) | {"resources": _busy_worker(now)["resources"] | {"cpu_percent": 95}}
    assert "CPU is at 95%" in (background_testing.guarded_reason(s, hot, now=now) or ""), "the budget still applies"
    assert background_testing.guarded_reason(s, worker, now=now, allow_active=False) == \
        "Waiting for five minutes without operator input.", "an explicit False still forces the wait"


def test_the_route_stores_the_designation_without_forgetting_the_budget(cfg):
    app = create_app(cfg)
    store = app.state.store
    now = time.time()
    store.put("worker", "w1", {"id": "w1", "name": "i9-NUC", "os": "windows", "last_seen": now,
                               "tools": ["launch_game"], "unavailable": {}, "idle_seconds": 5, "active_jobs": 0})
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    assert client.post("/api/testing/workers/i9-NUC", json={"budget_percent": 80}).status_code == 200
    r = client.post("/api/testing/workers/i9-NUC", json={"allow_while_active": True})
    assert r.status_code == 200, r.text
    row = next(w for w in r.json()["workers"] if w["name"] == "i9-NUC")
    assert row["allow_while_active"] is True and row["budget_percent"] == 80, "both parts of the policy kept"
    off = client.post("/api/testing/workers/i9-NUC", json={"allow_while_active": False})
    row = next(w for w in off.json()["workers"] if w["name"] == "i9-NUC")
    assert row["allow_while_active"] is False and row["budget_percent"] == 80

def test_a_dedicated_pc_runs_file_work_while_the_operator_plays_but_never_input_jobs(monkeypatch):
    """Operator 2026-11-10: "the PSO task uses gBox to handle modding and loading the game ... play it despite me being
    on the PC". allow_while_active lets a PC's non-pad jobs through while they play; a launch/session job still waits."""
    now = time.time()
    s = FakeStore()
    s.running_sessions = lambda: [{"session_id": "sid-1"}]
    s.put("setting", background_testing.SETTING, {"policies": {"i9-NUC": {"allow_while_active": True}}})
    from gbox import operator_guard, screensaver
    monkeypatch.setattr(operator_guard, "operator_sessions", lambda *a, **k: [{"session_id": "sid-1"}])
    monkeypatch.setattr(screensaver, "telemetry_get", lambda sid, now=None: {})
    worker = _busy_worker(now)
    assert background_testing.guarded_reason(s, worker, now=now, job={"tool": "file_mod"}) is None
    assert "Human gameplay" in (background_testing.guarded_reason(s, worker, now=now, job={"tool": "launch_game"}) or "")
    assert "Human gameplay" in (background_testing.guarded_reason(s, worker, now=now) or ""), \
        "a caller with no job keeps ownership authoritative"
    s.put("setting", background_testing.SETTING, {"policies": {}})
    assert "Human gameplay" in (background_testing.guarded_reason(s, worker, now=now, job={"tool": "file_mod"}) or ""), \
        "a PC not designated still waits"
