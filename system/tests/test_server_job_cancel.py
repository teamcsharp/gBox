"""In-server jobs (session_swap) must be cancellable, even after the server restarted under them (#1297)."""
import time

import pytest

from fastapi.testclient import TestClient

from gbox import job_maintenance
from gbox.config import Config
from gbox.models import Job
from gbox.server import create_app

# The exact job the operator could not cancel: running for 6 h, no worker, cancel flag already set.
STUCK = {"tool": "session_swap", "state": "running", "worker_id": None,
         "input": {"session_id": "89206492e649435c-a5c55d89afc64ce3", "game_id": "4187aeab4d67638c",
                   "mod": "jgr_sa2_amy_rose_04_r6", "to": "", "keep_state": False},
         "progress": {"pct": 60, "msg": "That didn't start: putting your game back", "ts": time.time() - 6 * 3600}}


def _app(tmp_path):
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    return cfg, app, app.state.store


def _put(store, **body):
    job = Job(**body)
    store.put("job", job.id, job.model_dump() | {k: v for k, v in body.items() if k not in Job.model_fields})
    return job.id


def test_cancel_finishes_swap_left_running_by_an_earlier_server(tmp_path):
    cfg, app, store = _app(tmp_path)
    jid = _put(store, **STUCK, created=time.time() - 6 * 3600, started=time.time() - 6 * 3600)
    with TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"}) as client:
        r = client.post(f"/api/jobs/{jid}/cancel")
        assert r.status_code == 200, r.text
        assert r.json()["state"] == "failed"
        j = client.get(f"/api/jobs/{jid}").json()
    assert j["state"] == "failed" and j["finished"]
    assert j["error"].startswith("cancelled by the operator")
    assert "restarted" in j["error"]


def test_cancel_still_only_flags_worker_jobs(tmp_path):
    cfg, app, store = _app(tmp_path)
    jid = _put(store, tool="launch_game", state="running", worker_id="w1", input={}, started=time.time())
    with TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"}) as client:
        r = client.post(f"/api/jobs/{jid}/cancel")
    assert r.json() == {"id": jid, "state": "running", "cancel_requested": True}
    assert store.get("job", jid)["state"] == "running"


def test_sweep_retires_orphans_but_never_a_live_thread_or_worker_job(tmp_path):
    _, _, store = _app(tmp_path)
    orphan = _put(store, **(STUCK | {"progress": None}))
    live = _put(store, **(STUCK | {"progress": None}))
    worker = _put(store, tool="launch_game", state="running", worker_id="w1", input={})
    frame = _put(store, tool="get_frame", state="running", worker_id=None, input={}, started=time.time())
    flagged = _put(store, **STUCK, cancel=True)
    assert sorted(job_maintenance.retire_orphaned_server_jobs(store, {live})) == sorted([orphan, flagged])
    assert store.get("job", orphan)["error"] == job_maintenance.ORPHAN_REASON
    assert store.get("job", flagged)["error"] == job_maintenance.CANCELLED_REASON
    for jid in (live, worker, frame):
        assert store.get("job", jid)["state"] == "running"
    assert job_maintenance.retire_orphaned_server_jobs(store, {live}) == []


def test_live_swap_stops_while_its_prepare_step_waits(tmp_path):
    cfg, app, store = _app(tmp_path)
    store.upsert_catalog([{"game_id": "g1", "title": "Test game", "platform": "dreamcast", "source_paths": ["t.gdi"],
                           "format": "gdi", "profile_id": "g1", "core": "flycast",
                           "launch": {"kind": "retroarch", "path": "t.gdi"}}])
    store.put("worker", "w1", {"id": "w1", "name": "TESTPC", "os": "windows", "tools": ["prepare_mod", "launch_game"],
                               "unavailable": {}, "last_seen": time.time() + 3600})
    sid = "w1-s1"
    store.put("session", sid, {"id": sid, "game_id": "g1", "state": "running", "mod": ""})
    with TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"}) as client:
        r = client.post(f"/api/sessions/{sid}/swap", json={"mod": "m1", "keep_state": False})
        assert r.status_code == 200, r.text
        swap = r.json()["id"]
        deadline = time.time() + 5
        while time.time() < deadline and not [j for j in store.all("job") if j["tool"] == "prepare_mod"]:
            time.sleep(0.1)
        child = next(j for j in store.all("job") if j["tool"] == "prepare_mod")
        assert child["state"] == "queued"            # nothing will ever claim it in this test
        assert client.post(f"/api/jobs/{swap}/cancel").json()["cancel_requested"] is True
        deadline = time.time() + 5
        while time.time() < deadline and store.get("job", swap)["state"] == "running":
            time.sleep(0.1)
    j = store.get("job", swap)
    assert j["state"] == "failed", j
    assert j["error"].startswith("cancelled by the operator before the replacement started")
    assert store.get("job", child["id"])["state"] == "failed"
    assert store.get("session", sid)["state"] == "running"       # the operator's game was left alone
    assert not [x for x in store.all("job") if x["tool"] == "launch_game"]
    # an operator cancel is not a failed model mod: no auto report is filed
    assert not [rq for rq in store.all("request") if (rq.get("source") or "") == "automation"]


def _launch_fixture(tmp_path, *, running=False):
    cfg, app, store = _app(tmp_path)
    store.upsert_catalog([{'game_id': 'g1', 'title': 'Synthetic review game', 'platform': 'dreamcast',
                           'source_paths': ['synthetic.gdi'], 'format': 'gdi', 'profile_id': 'g1',
                           'core': 'flycast', 'launch': {'kind': 'retroarch', 'path': 'synthetic.gdi'}}])
    store.put('worker', 'w1', {'id': 'w1', 'name': 'TESTPC', 'os': 'windows',
                              'tools': ['launch_game', 'get_frame', 'state_transfer', 'session_op'],
                              'unavailable': {}, 'last_seen': time.time() + 3600})
    store.put('session', 'w1-s1', {'id': 'w1-s1', 'session_id': 'w1-s1',
                                  'game_id': 'g1', 'state': 'running' if running else 'ended', 'mod': ''})
    return cfg, app, store


def _wait(get, predicate=bool):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        value = get()
        if predicate(value):
            return value
        time.sleep(.02)
    raise RuntimeError('synthetic source-test wait expired')


def _child(store, tool, op=None):
    return _wait(lambda: [j for j in store.all('job') if j['tool'] == tool
                         and j['state'] in ('queued', 'running')
                         and (op is None or j['input'].get('op') == op)])[0]


def _finish(store, job, output):
    with store.lock:
        store.put('job', job['id'], store.get('job', job['id']) |
                  {'state': 'succeeded', 'finished': time.time(), 'output': output})


def test_cancel_queued_launch_prevents_claim_and_native_recovery(tmp_path):
    cfg, app, store = _launch_fixture(tmp_path)
    with TestClient(app, headers={'Authorization': f'Bearer {cfg.token()}'}) as client:
        parent = client.post('/api/sessions/w1-s1/swap', json={'mod': '', 'keep_state': False}).json()['id']
        child = _child(store, 'launch_game')
        assert client.post('/api/jobs/' + parent + '/cancel').json()['cancel_requested'] is True
        done = _wait(lambda: store.get('job', parent), lambda j: j['state'] != 'running')
        assert done['state'] == 'failed' and done['error'].startswith('cancelled by the operator before')
        assert store.get('job', child['id'])['state'] == 'failed'
        assert client.post('/api/workers/w1/claim', json={'idle_seconds': 1000}).status_code == 204
    assert len(store.all('job')) == 2   # no frame query, recovery launch, state import or game stop
    assert store.get('session', 'w1-s1')['state'] == 'ended'


def test_cancel_claimed_launch_defers_and_preserves_checkpoint_handoff(tmp_path, monkeypatch):
    cfg, app, store = _launch_fixture(tmp_path, running=True)
    saved = store.put_artifact(b'owned synthetic checkpoint', 'moment.state', 'application/octet-stream', {}).sha256
    sleep = time.sleep
    monkeypatch.setattr(time, 'sleep', lambda seconds: sleep(min(seconds, .01)))
    with TestClient(app, headers={'Authorization': f'Bearer {cfg.token()}'}) as client:
        parent = client.post('/api/sessions/w1-s1/swap', json={'mod': '', 'keep_state': True}).json()['id']
        _finish(store, _child(store, 'get_frame'), {'mean_luma': 10})
        _finish(store, _child(store, 'state_transfer', 'export'), {'result': {'artifact': saved}})
        child = _child(store, 'launch_game')
        claimed = client.post('/api/workers/w1/claim', json={'idle_seconds': 1000})
        assert claimed.status_code == 200 and claimed.json()['id'] == child['id']
        client.post('/api/jobs/' + parent + '/cancel')
        _wait(lambda: store.get('job', parent), lambda j: 'Cancellation is deferred' in (j.get('progress') or {}).get('msg', ''))
        assert store.get('job', child['id'])['state'] == 'running'
        assert not store.get('job', child['id']).get('cancel')
        assert store.get('session', 'w1-s1')['state'] == 'running'
        store.put('session', 'w1-new', {'session_id': 'w1-new', 'game_id': 'g1', 'state': 'running'})
        _finish(store, child, {'session_id': 'w1-new'})
        restore = _child(store, 'state_transfer', 'import')
        assert restore['input']['artifact'] == saved and restore['input']['session_id'] == 'w1-new'
        _finish(store, restore, {'result': {'load_requested': True, 'load_verified': True, 'loaded': True}})
        close = _child(store, 'session_op', 'stop_game')
        assert close['input']['session_id'] == 'w1-s1'  # ordinary replacement cleanup, never the new native game
        _finish(store, close, {'ended': True})
        for _ in range(2):
            _finish(store, _child(store, 'get_frame'), {'mean_luma': 10})
        done = _wait(lambda: store.get('job', parent), lambda j: j['state'] != 'running')
    assert done['state'] == 'succeeded' and done['cancel'] is True
    assert done['output']['cancel_deferred'] is True and done['output']['state_loaded'] is True
    assert 'allowed to finish' in ' '.join(done['output']['notes'])
    assert store.read_artifact(saved) == b'owned synthetic checkpoint'
    assert store.get('session', 'w1-new')['state'] == 'running'
    assert len([j for j in store.all('job') if j['tool'] == 'launch_game']) == 1


@pytest.mark.parametrize('failure', ['constructor', 'start'])
def test_background_thread_failure_finishes_job_and_releases_registry(tmp_path, monkeypatch, failure):
    from gbox import server
    cfg, app, store = _launch_fixture(tmp_path)
    route = next(r for r in app.routes if r.path == '/api/sessions/{sid}/swap')
    submit_swap = dict(zip(route.endpoint.__code__.co_freevars,
                          (c.cell_contents for c in route.endpoint.__closure__)))['swap_job']
    live = dict(zip(submit_swap.__code__.co_freevars,
                   (c.cell_contents for c in submit_swap.__closure__)))['_server_job_threads']

    class BrokenThread:
        def __init__(self, **kwargs):
            if failure == 'constructor':
                raise RuntimeError('synthetic constructor failure')
        def start(self):
            raise RuntimeError('synthetic start failure')

    with TestClient(app, headers={'Authorization': f'Bearer {cfg.token()}'}, raise_server_exceptions=False) as client:
        client.get('/api/jobs?limit=1')
        with monkeypatch.context() as m:
            m.setattr(server.threading, 'Thread', BrokenThread)
            response = client.post('/api/sessions/w1-s1/swap', json={'mod': '', 'keep_state': False})
        assert response.status_code == 503
        job = next(j for j in store.all('job') if j['tool'] == 'session_swap')
        assert job['state'] == 'failed' and job['finished']
        assert job['id'] not in live and job['error'].startswith('Replacement background task could not start')
        assert client.post('/api/jobs/' + job['id'] + '/cancel').json()['state'] == 'failed'
    assert store.get('session', 'w1-s1')['state'] == 'ended'
    assert not [j for j in store.all('job') if j['tool'] != 'session_swap']


def test_deferred_launch_with_unknown_outcome_never_starts_recovery(tmp_path):
    cfg, app, store = _launch_fixture(tmp_path, running=True)
    route = next(r for r in app.routes if r.path == '/api/sessions/{sid}/swap')
    cells = lambda fn: dict(zip(fn.__code__.co_freevars, fn.__closure__))
    submit_swap = cells(route.endpoint)['swap_job'].cell_contents
    swap = cells(submit_swap)['session_swap'].cell_contents
    run_cell = cells(swap)['_run_job']
    original = run_cell.cell_contents
    submit_cell = cells(original)['submit']
    original_submit = submit_cell.cell_contents

    def claimed_launch(req, actor):
        child = original_submit(req, actor)
        with store.lock:
            store.put('job', child.id, store.get('job', child.id) |
                      {'state': 'running', 'worker_id': 'w1', 'started': time.time()})
        return child

    def short_wait(tool, inp, actor, **kwargs):
        assert tool == 'launch_game'  # no capture/recovery/game stop on an unknown launch result
        return original(tool, inp, actor, **(kwargs | {'wait': .01}))

    try:
        submit_cell.cell_contents = claimed_launch
        run_cell.cell_contents = short_wait
        # The first safe pre-launch check is false; cancel arrives after its claim.
        checks = iter([False, True, True, True])
        with pytest.raises(Exception) as caught:
            swap('w1-s1', '', '', 'test', keep_state=False, should_stop=lambda: next(checks, True))
        assert getattr(caught.value, 'status_code', None) == 409
        assert str(caught.value.detail).startswith('Cancellation remains deferred:')
    finally:
        submit_cell.cell_contents = original_submit
        run_cell.cell_contents = original
    child = store.all('job')[0]
    assert child['state'] == 'running' and not child.get('cancel')
    assert len(store.all('job')) == 1
    assert store.get('session', 'w1-s1')['state'] == 'running'
