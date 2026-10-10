import time

from fastapi.testclient import TestClient

from gbox.server import create_app


def test_other_pc_selection_and_agent_job_routing(cfg):
    app = create_app(cfg)
    now = time.time()
    tools = ["get_frame", "launch_game"]
    app.state.store.put("worker", "main", {"id": "main", "name": "Main PC", "os": "windows",
        "tools": tools, "unavailable": {}, "last_seen": now, "idle_seconds": 2, "active_jobs": 0})
    app.state.store.put("worker", "other", {"id": "other", "name": "Test PC", "os": "windows",
        "tools": tools, "unavailable": {}, "last_seen": now, "idle_seconds": 600, "active_jobs": 0})
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    picked = client.get("/api/workers/idle", params={"tool": "get_frame"})
    assert picked.status_code == 200 and picked.json()["id"] == "other"
    job = client.post("/api/jobs", json={"tool": "get_frame", "input": {},
                                         "require_worker": "idle", "agent_use": True})
    assert job.status_code == 200, job.text
    assert job.json()["require_worker"] == "other" and job.json()["agent_use"]
    claim = client.post("/api/workers/other/claim", json={"idle_seconds": 599, "active_jobs": 1})
    assert claim.status_code == 200 and claim.json()["id"] == job.json()["id"]
    assert client.get("/api/workers").json()[1]["active_jobs"] == 1
    assert client.get("/api/workers/other/desktop/watch").json()["watch"] is False
    frame = client.post("/api/workers/other/desktop/frame", content=b"\xff\xd8test-frame\xff\xd9")
    assert frame.status_code == 200
    assert client.get("/api/workers/other/desktop/status").json()["frames"] == 1


def test_other_pc_is_not_selected_when_someone_uses_it(cfg):
    app = create_app(cfg)
    now = time.time()
    for wid, idle in (("main", 1), ("other", 2)):
        app.state.store.put("worker", wid, {"id": wid, "name": wid, "os": "windows",
            "tools": ["get_frame"], "unavailable": {}, "last_seen": now, "idle_seconds": idle, "active_jobs": 0})
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    assert client.get("/api/workers/idle", params={"tool": "get_frame"}).status_code == 409
