"""retire_unrunnable_jobs reassignment (#7968): a queued job pinned to a worker id that died when its PC
restarted must move to the online registration of the same machine (same worker name) instead of failing
with 'assigned worker is no longer available' at created+3600s. Worker ids are per-registration; names are
the stable machine identity. With no same-name worker online the job still fails as before."""
import time

from fastapi.testclient import TestClient

from gbox.config import Config
from gbox.server import create_app

def fresh():
    return {"sampled_at": time.time(), "cpu_percent": 10, "memory_percent": 40,
            "memory_available_bytes": 32 << 30, "gpus": []}

def rig(tmp_path):
    cfg = Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache")
    app = create_app(cfg)
    store = app.state.store
    now = time.time()
    # i9-NUC as it was at the incident: a stale registration from before the reboot...
    store.put("worker", "wdead", {"id": "wdead", "name": "i9-NUC", "os": "windows", "last_seen": now - 7200,
                                  "tools": ["echo_artifact"], "unavailable": {}, "idle_seconds": 0,
                                  "resources": fresh()})
    # ...and its post-restart registration, online under a new id
    store.put("worker", "wnew", {"id": "wnew", "name": "i9-NUC", "os": "windows", "last_seen": now,
                                 "tools": ["echo_artifact"], "unavailable": {}, "idle_seconds": 0,
                                 "resources": fresh()})
    return app, store, {"Authorization": f"Bearer {cfg.token()}"}

def test_a_pinned_queued_job_moves_to_the_same_machines_new_registration(tmp_path):
    app, store, h = rig(tmp_path)
    with TestClient(app) as c:
        jid = c.post("/api/jobs", headers=h, json={"tool": "echo_artifact", "input": {"message": "hi"},
                                                   "require_worker": "wdead"}).json()["id"]
        j = store.get("job", jid)
        store.put("job", jid, j | {"created": time.time() - 3700})          # past the 3600s retire horizon
        c.get("/api/jobs", headers=h)                                       # triggers retire_unrunnable_jobs
        j = store.get("job", jid)
        assert j["state"] == "queued" and j["require_worker"] == "wnew", (j["state"], j.get("error"))
        claimed = c.post("/api/workers/wnew/claim", headers=h, json={"idle_seconds": 0, "active_jobs": 0}).json()
        assert claimed["id"] == jid, "the reassigned job is claimable by the restarted worker"

def test_it_still_fails_when_no_same_name_worker_is_online(tmp_path):
    app, store, h = rig(tmp_path)
    with TestClient(app) as c:
        jid = c.post("/api/jobs", headers=h, json={"tool": "echo_artifact", "input": {"message": "hi"},
                                                   "require_worker": "ghost"}).json()["id"]
        j = store.get("job", jid)
        store.put("job", jid, j | {"created": time.time() - 3700})
        c.get("/api/jobs", headers=h)
        j = store.get("job", jid)
        assert j["state"] == "failed" and j["error"] == "assigned worker is no longer available"

def test_a_freshly_pinned_job_is_never_retired(tmp_path):
    app, store, h = rig(tmp_path)
    with TestClient(app) as c:
        jid = c.post("/api/jobs", headers=h, json={"tool": "echo_artifact", "input": {"message": "hi"},
                                                   "require_worker": "wdead"}).json()["id"]
        c.get("/api/jobs", headers=h)
        assert store.get("job", jid)["state"] == "queued"
