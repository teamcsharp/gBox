import httpx
from fastapi.testclient import TestClient

from gbox import worker
from gbox.server import create_app


def test_worker_recovers_after_periodic_registration_timeout(monkeypatch, cfg):
    calls = []
    class Reply:
        status_code = 204
        def raise_for_status(self):
            return self

    class Client:
        def __init__(self, **_):
            self.registers = 0
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def post(self, path, **_):
            calls.append(path)
            if path == "/api/workers/register":
                self.registers += 1
                if self.registers == 2:
                    raise httpx.ReadTimeout("temporary slowdown")
            return Reply()

    class Stop:
        def __init__(self):
            self.waits = 0
        def is_set(self):
            return self.waits >= 3
        def wait(self, _):
            self.waits += 1

    monkeypatch.setattr(worker.httpx, "Client", Client)
    monkeypatch.setattr(worker, "describe", lambda _config, name, wid=None: worker.WorkerInfo(name=name, os="linux", tools=["scan_library"], id=wid or "worker1"))
    monkeypatch.setattr(worker, "REDESCRIBE_S", -1)
    monkeypatch.setattr(worker, '_heartbeat_loop', lambda *_: None)
    monkeypatch.setattr(worker, '_result_delivery_loop', lambda *_: None)
    monkeypatch.setattr(worker._builtin, "reap_orphans", lambda *_: [])
    monkeypatch.setattr("gbox.filemods.push_missing", lambda *_: [])
    worker.run("http://127.0.0.1:8765", "token", cfg, "test", stop=Stop(), poll_s=0.001)
    assert calls.count("/api/workers/register") >= 3
    assert any(path.endswith("/claim") for path in calls)


def test_claim_reads_only_queued_jobs(cfg):
    app = create_app(cfg)
    plane = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    store = app.state.store
    info = worker.WorkerInfo(name="inbox-indexer", os="linux", tools=["scan_library"], id="indexer")
    plane.post("/api/workers/register", json=info.model_dump()).raise_for_status()
    for i in range(200):
        store.put("job", f"done-{i}", {"id": f"done-{i}", "state": "succeeded"})
    for i in range(2):
        store.put("job", f"queued-{i}", {"id": f"queued-{i}", "state": "queued", "tool": "scan_library", "input": {}, "require_os": None, "require_worker": None})
    assert [x["id"] for x in store.queued_jobs()] == ["queued-0", "queued-1"]
    assert plane.post("/api/workers/indexer/claim").json()["id"] == "queued-0"
    assert plane.post("/api/workers/indexer/claim").json()["id"] == "queued-1"
    assert plane.post("/api/workers/indexer/claim").status_code == 204


def test_saturated_worker_heartbeats_without_claiming_more_jobs(monkeypatch):
    active = {'a', 'b', 'c', 'd'}
    posted = []
    class Reply:
        def raise_for_status(self):
            return self
    class Client:
        def __init__(self, **_): pass
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def post(self, path, *, json):
            posted.append((path, json))
            if len(posted) == 1:
                raise httpx.ConnectError('backend refresh')
            return Reply()
    class Stop:
        calls = 0
        def wait(self, _):
            self.calls += 1
            return self.calls > 2
    monkeypatch.setattr(worker.httpx, 'Client', Client)
    monkeypatch.setattr(worker, 'user_idle_seconds', lambda: 120)
    info = worker.WorkerInfo(id='remote', name='test', os='windows', tools=['get_frame'])
    worker._heartbeat_loop(Stop(), lambda: info, active, 'http://fixture', {})
    assert len(posted) == 2
    assert all(path == '/api/workers/register' for path, _ in posted)
    assert posted[-1][1]['id'] == 'remote' and posted[-1][1]['active_jobs'] == 4
    assert posted[-1][1]['idle_seconds'] == 120
