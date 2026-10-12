"""#1294: /api/workers carries the Spark's running-job count so leaked worker slots are visible."""
import time

from fastapi.testclient import TestClient

from gbox.server import create_app


def test_workers_report_running_jobs_the_spark_has_for_them(cfg):
    app = create_app(cfg)
    now = time.time()
    for wid, name in (("nuc", "i9-NUC"), ("jay", "JAYBUILTFINALE")):
        app.state.store.put("worker", wid, {"id": wid, "name": name, "os": "windows", "tools": ["get_frame"],
                                            "unavailable": {}, "last_seen": now, "idle_seconds": 600, "active_jobs": 4})
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    job = client.post("/api/jobs", json={"tool": "get_frame", "input": {}, "require_worker": "jay"})
    assert job.status_code == 200, job.text
    assert client.post("/api/workers/jay/claim", json={"active_jobs": 1}).json()["id"] == job.json()["id"]
    ws = {w["name"]: w for w in client.get("/api/workers").json()}
    # i9-NUC says 4 slots are busy but the Spark runs nothing there: leaked, it will never claim a launch
    assert ws["i9-NUC"]["active_jobs"] == 4 and ws["i9-NUC"]["running_jobs"] == 0
    assert ws["JAYBUILTFINALE"]["running_jobs"] == 1
    assert app.state.store.running_job_counts() == {"jay": 1}
