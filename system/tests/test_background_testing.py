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
