from fastapi.testclient import TestClient
import time

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


def test_unrunnable_queued_jobs_leave_active_queue(cfg):
    app = create_app(cfg)
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    store = app.state.store
    store.put("session", "ended-game", {"session_id": "ended-game", "state": "ended"})
    store.put("job", "old-session", {"id": "old-session", "tool": "session_op", "state": "queued",
                                     "created": time.time() - 60, "input": {"session_id": "ended-game"}})
    store.put("job", "gone-worker", {"id": "gone-worker", "tool": "launch_game", "state": "queued",
                                     "created": time.time() - 7200, "require_worker": "old-node", "input": {}})
    store.put("job", "recent-worker", {"id": "recent-worker", "tool": "launch_game", "state": "queued",
                                       "created": time.time(), "require_worker": "old-node", "input": {}})

    active = client.get("/api/jobs?state=queued,running").json()
    assert [j["id"] for j in active] == ["recent-worker"]
    assert "session ended" in store.get("job", "old-session")["error"]
    assert "worker" in store.get("job", "gone-worker")["error"]


def test_stalled_snapshot_fails_without_retiring_live_capture_or_emulation(cfg):
    app = create_app(cfg)
    client = TestClient(app, headers={'Authorization': f'Bearer {cfg.token()}'})
    store = app.state.store
    now = time.time()
    for jid, tool, age in [('stalled', 'get_frame', 180), ('fresh', 'get_frame', 5),
                            ('launch', 'launch_game', 180), ('state', 'session_op', 180)]:
        store.put('job', jid, {'id': jid, 'tool': tool, 'state': 'running', 'worker_id': 'worker',
                               'created': now - 200, 'started': now - age, 'input': {}})
    store.put('session', 'game', {'session_id': 'game', 'state': 'running', 'detail': {'pid': 123}})
    assert {j['id'] for j in client.get('/api/jobs?state=running').json()} == {'fresh', 'launch', 'state'}
    failed = store.get('job', 'stalled')
    assert failed['state'] == 'failed' and 'no screenshot' in failed['error'] and failed['cancel']
    assert store.get('session', 'game')['detail']['pid'] == 123
    late = client.post('/api/workers/worker/result', json={'job_id': 'stalled', 'ok': True, 'output': {}})
    assert late.status_code == 409
    assert store.get('job', 'stalled')['state'] == 'failed'
