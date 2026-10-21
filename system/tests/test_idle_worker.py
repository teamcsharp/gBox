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


def test_operator_play_boots_on_the_pc_it_came_from(cfg):
    """#2386: a Play from the NUC with node=windows booted on the other PC; the requesting PC is pinned."""
    app = create_app(cfg)
    now = time.time()
    tools = ["get_frame", "launch_game"]
    app.state.store.put("worker", "jay", {"id": "jay", "name": "JAYBUILTFINALE", "os": "windows", "tools": tools,
        "unavailable": {}, "last_seen": now, "idle_seconds": 600, "active_jobs": 0, "address": "10.89.1.13"})
    app.state.store.put("worker", "nuc", {"id": "nuc", "name": "i9-NUC", "os": "windows", "tools": tools,
        "unavailable": {}, "last_seen": now, "idle_seconds": 600, "active_jobs": 0})
    app.state.store.upsert_catalog([{"game_id": "g" * 16, "title": "Jet Set Radio Future (USA)", "platform": "xbox",
                                     "source_paths": ["jsrf.iso"], "format": "iso", "profile_id": "g" * 16,
                                     "launch": {"kind": "emulator", "path": "jsrf.iso"}}])
    headers = {"Authorization": f"Bearer {cfg.token()}"}
    nuc = TestClient(app, headers=headers, client=("10.89.1.43", 50000))
    beat = nuc.post("/api/workers/nuc/claim", json={"idle_seconds": 600, "active_jobs": 0})
    assert beat.status_code in (200, 204)              # 204: nothing queued for it to claim
    assert app.state.store.get("worker", "nuc")["address"] == "10.89.1.43"
    job = nuc.post(f"/api/games/{'g' * 16}/launch", params={"node": "windows"})
    assert job.status_code == 200, job.text
    assert job.json()["require_worker"] == "nuc", "the Play from the NUC stays on the NUC"
    other = TestClient(app, headers=headers, client=("10.89.1.99", 50000))
    job = other.post(f"/api/games/{'g' * 16}/launch", params={"node": "windows"})
    assert job.status_code == 200 and job.json()["require_worker"] is None and job.json()["require_os"] == "windows"


def test_a_failed_task_is_retried_as_a_linked_new_job(cfg):
    """#2398: right-click a failed task, Retry: dispatched again with the same tool, input and pins; running tasks are not duplicated."""
    app = create_app(cfg)
    now = time.time()
    app.state.store.put("worker", "testpc", {"id": "testpc", "name": "Test PC", "os": "windows", "tools": ["get_frame"],
        "unavailable": {}, "last_seen": now, "idle_seconds": 600, "active_jobs": 0})
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    posted = client.post("/api/jobs", json={"tool": "get_frame", "input": {}, "require_worker": "testpc", "agent_use": True})
    assert posted.status_code == 200, posted.text
    job = posted.json()
    assert client.post(f"/api/jobs/{job['id']}/retry").status_code == 409, "a queued task is not duplicated"
    app.state.store.put("job", job["id"], app.state.store.get("job", job["id"]) | {"state": "failed", "error": "worker restarted"})
    r = client.post(f"/api/jobs/{job['id']}/retry")
    assert r.status_code == 200, r.text
    new = r.json()
    assert new["id"] != job["id"] and new["tool"] == "get_frame" and new["input"] == job["input"]   # the stored (normalised) input
    assert new["require_worker"] == "testpc" and new["agent_use"] is True and new["state"] == "queued"
    assert new["origin"]["via"] == "retry" and new["origin"]["retry_of"] == job["id"]
    assert app.state.store.get("job", job["id"])["retried_by"] == new["id"]


def test_collect_runs_on_the_requesting_pc_only_when_the_spark_cannot_take_it():
    """#2407: a collect queues for the Linux collection worker; when none is online and admitted, the PC it was
    asked from collects (it ships the entries back), and only when that PC carries the characters tool."""
    from gbox import job_routing as JR
    spark = {"id": "s", "os": "linux", "online": True, "tools": ["characters"], "admission": {"allowed": True}}
    pc = {"id": "p", "name": "JAYBUILTFINALE", "os": "windows", "online": True, "tools": ["characters", "launch_game"],
          "address": "10.0.0.5"}
    origin = {"remote": "10.0.0.5"}
    assert JR.collect_here([spark, pc], origin) is None, "the Spark takes it"
    busy = spark | {"admission": {"allowed": False, "reason": "the operator is playing on it"}}
    assert JR.collect_here([busy, pc], origin)["id"] == "p"
    assert JR.collect_here([spark | {"online": False}, pc], origin)["id"] == "p"
    assert JR.collect_here([busy, pc | {"tools": ["launch_game"]}], origin) is None, "no characters tool there"
    assert JR.collect_here([busy, pc], {"remote": "10.0.0.9"}) is None, "not from a PC gBox knows"
    assert JR.collect_here([busy], {}) is None and JR.collect_here([], None) is None


def test_an_operator_collect_is_pinned_to_the_requesting_pc_when_the_spark_is_away(cfg):
    """#2407 end to end at submit: the Spark offline, a collect from the PC runs there with deliver=True; from a PC
    gBox does not know it queues for the Spark as before."""
    app = create_app(cfg)
    now = time.time()
    app.state.store.put("worker", "spark", {"id": "spark", "name": "lilspark", "os": "linux", "tools": ["characters"],
        "unavailable": {}, "last_seen": now - 3600, "idle_seconds": 600, "active_jobs": 0})
    app.state.store.put("worker", "jay", {"id": "jay", "name": "JAYBUILTFINALE", "os": "windows",
        "tools": ["characters", "launch_game"], "unavailable": {}, "last_seen": now, "idle_seconds": 600,
        "active_jobs": 0, "address": "10.89.1.13"})
    headers = {"Authorization": f"Bearer {cfg.token()}"}
    body = {"tool": "characters", "input": {"op": "collect", "game_id": "g" * 16}}
    jay = TestClient(app, headers=headers, client=("10.89.1.13", 50000))
    job = jay.post("/api/jobs", json=body)
    assert job.status_code == 200, job.text
    assert job.json()["require_worker"] == "jay" and job.json()["require_os"] == "windows"
    assert job.json()["input"]["deliver"] is True, "the PC ships its entries back"
    other = TestClient(app, headers=headers, client=("10.89.1.99", 50000))
    job = other.post("/api/jobs", json=body).json()
    assert job["require_worker"] is None and job["require_os"] == "linux" and job["input"]["deliver"] is False
