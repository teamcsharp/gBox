from fastapi.testclient import TestClient

from gbox.server import create_app
from gbox.store import Store


def test_active_job_filter_applies_before_limit_and_rejects_unknown_states(cfg):
    client = TestClient(create_app(cfg), headers={"Authorization": f"Bearer {cfg.token()}"})
    store = Store(cfg.data_dir)
    store.put("job", "running", {"id": "running", "state": "running"})
    store.put("job", "queued", {"id": "queued", "state": "queued"})
    store.put("job", "finished", {"id": "finished", "state": "succeeded"})
    assert client.get("/api/jobs?limit=1").json()[0]["id"] == "finished"
    active = client.get("/api/jobs?state=queued,running&limit=1")
    assert active.status_code == 200
    assert [job["id"] for job in active.json()] == ["queued"]
    assert len(client.get("/api/jobs?state=running,queued").json()) == 2
    assert client.get("/api/jobs?state=not_a_state").status_code == 422
    store.db.close()
