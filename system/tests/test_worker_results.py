import base64
import concurrent.futures
import json
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from gbox import tools, worker, worker_results
from gbox.models import WorkerInfo
from gbox.registry import REGISTRY
from gbox.server import create_app
from gbox.worker_results import ResultOutbox, result_digest


def control(cfg, jid='launch', *, tool='launch_game', state='running', cancel=False):
    app = create_app(cfg)
    client = TestClient(app, headers={'Authorization': f'Bearer {cfg.token()}'}, raise_server_exceptions=False)
    app.state.store.put('job', jid, {'id': jid, 'tool': tool, 'input': {}, 'state': state,
        'worker_id': 'old-worker', 'started': time.time(), 'created': time.time(), 'cancel': cancel})
    # Installed Starlette may return httpx2.Response; real worker transport uses
    # httpx.Response. Preserve actual route status/body while exercising the
    # worker client's exception contract, rather than mixing exception types.
    class Wire:
        def post(self, path, **kwargs):
            response = client.post(path, **kwargs)
            return httpx.Response(response.status_code, content=response.content,
                                  headers=response.headers,
                                  request=httpx.Request('POST', 'http://fixture' + path))
    return app, Wire()


def launch_result(jid='launch'):
    return {'job_id': jid, 'ok': True, 'output': {'session_id': 'old-worker-' + jid,
        'adapter': 'retroarch', 'capabilities': {}, 'detail': {'pid': 4321, '_game': {'game_id': None, 'title': 'Owned test'}}},
        'log': ['Native launch completed once'], 'artifacts': [{'name': 'proof.bin',
        'media_type': 'application/octet-stream', 'provenance': {'owned': True},
        'b64': base64.b64encode(b'actual finished bytes').decode()}]}


class LostAcknowledgement:
    def __init__(self, client):
        self.client, self.calls = client, 0

    def post(self, *args, **kwargs):
        self.calls += 1
        response = self.client.post(*args, **kwargs)
        if self.calls == 1:
            raise httpx.ReadTimeout('ACK lost after control-plane commit')
        return response


def test_real_lost_ack_tool_executes_once_and_result_is_durable(cfg, monkeypatch):
    app, plane = control(cfg)
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    client = LostAcknowledgement(plane)
    executed = []
    def execute(name, inp, ctx):
        executed.append(name)
        return launch_result()['output']
    monkeypatch.setattr(worker, 'execute', execute)
    active, agent = {'launch'}, set()
    worker._run_job({'id': 'launch', 'tool': 'launch_game', 'input': {}}, cfg, 'old-worker',
                    'http://fixture', {}, client, active, agent, set(), outbox)
    assert executed == ['launch_game'] and active == {'launch'} and outbox.pending_count() == 1
    saved = outbox.records()[0]
    assert saved['result']['output']['detail']['pid'] == 4321
    sid = saved['result']['output']['session_id']
    started = app.state.store.get('session', sid)['started']
    receipt = app.state.store.get('job', 'launch')['receipt_id']
    assert outbox.send_ready(client, force=True) == ['launch']
    assert executed == ['launch_game'] and client.calls == 2 and outbox.pending_count() == 0
    assert app.state.store.get('session', sid)['started'] == started
    assert app.state.store.get('job', 'launch')['receipt_id'] == receipt
    assert len(app.state.store.all('receipt')) == 1
    assert len([e for e in app.state.store.audit_log() if e['action'] == 'job.succeeded']) == 1


def test_artifact_bytes_fsynced_before_first_transport_and_restart_retry(cfg):
    app, plane = control(cfg)
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    result = launch_result()
    outbox.save('old-worker', result)
    class Observe:
        def post(self, path, **kwargs):
            persisted = json.loads(next(outbox.directory.glob('*.json')).read_text())
            assert persisted['attempts'] == 1
            assert persisted['result']['artifacts'][0]['b64'] == result['artifacts'][0]['b64']
            assert 'token' not in persisted
            raise httpx.ConnectError('offline')
    assert outbox.deliver(Observe(), 'launch') is False
    restarted = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    assert restarted.send_ready(plane, force=True) == ['launch']
    ack = restarted.records(include_acknowledged=True)[0]['acknowledgement']
    assert ack['result_sha256'] == result_digest(result) and ack['worker_id'] == 'old-worker'
    receipt = app.state.store.get('receipt', ack['receipt'])
    assert app.state.store.read_artifact(receipt['artifacts'][0]['sha256']) == b'actual finished bytes'


@pytest.mark.parametrize('status', [400, 404, 409, 422])
def test_rejected_result_stays_pending_and_never_blindly_retries(cfg, status):
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    outbox.save('old-worker', launch_result())
    calls = []
    class Reject:
        def post(self, path, **_):
            calls.append(path)
            return httpx.Response(status, request=httpx.Request('POST', 'http://fixture' + path))
    assert not outbox.deliver(Reject(), 'launch')
    assert outbox.pending_count() == 1 and outbox.records()[0]['status'] == 'rejected'
    assert outbox.send_ready(Reject(), force=True) == [] and len(calls) == 1


@pytest.mark.parametrize('status', [408, 429, 500, 503])
def test_transient_http_failure_retries_identical_saved_payload(cfg, status):
    app, plane = control(cfg)
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    outbox.save('old-worker', launch_result())
    class Transient:
        def post(self, path, **_):
            return httpx.Response(status, request=httpx.Request('POST', 'http://fixture' + path))
    assert not outbox.deliver(Transient(), 'launch')
    assert outbox.records()[0]['status'] == 'pending'
    assert outbox.send_ready(plane, force=True) == ['launch']


@pytest.mark.parametrize('ack', [{'state': 'succeeded', 'receipt': 'legacy'},
    {'accepted': True, 'job_id': 'another', 'worker_id': 'old-worker', 'state': 'succeeded', 'receipt': 'r', 'result_sha256': 'wrong'}])
def test_incomplete_or_wrong_ack_is_not_completion(cfg, ack):
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    outbox.save('old-worker', launch_result())
    class Wrong:
        def post(self, path, **_):
            return httpx.Response(200, json=ack, request=httpx.Request('POST', 'http://fixture' + path))
    assert not outbox.deliver(Wrong(), 'launch')
    assert outbox.pending_count() == 1


@pytest.mark.parametrize('change', ['output', 'artifact', 'log', 'error'])
def test_finished_result_mismatches_and_foreign_worker_rejected(cfg, change):
    app, plane = control(cfg)
    original = launch_result()
    accepted = plane.post('/api/workers/old-worker/result', json=original).json()
    changed = json.loads(json.dumps(original))
    if change == 'output': changed['output']['detail']['pid'] = 9999
    elif change == 'artifact': changed['artifacts'][0]['b64'] = base64.b64encode(b'different').decode()
    elif change == 'log': changed['log'].append('other log')
    else: changed['error'] = 'different result'
    assert plane.post('/api/workers/old-worker/result', json=changed).status_code == 409
    assert plane.post('/api/workers/foreign-worker/result', json=original).status_code == 409
    assert app.state.store.get('job', 'launch')['receipt_id'] == accepted['receipt']
    assert len(app.state.store.all('receipt')) == 1


@pytest.mark.parametrize('state,cancel', [('running', True), ('failed', True), ('failed', False)])
def test_late_cancelled_or_unverified_terminal_result_rejected(cfg, state, cancel):
    app, plane = control(cfg, state=state, cancel=cancel)
    assert plane.post('/api/workers/old-worker/result', json=launch_result()).status_code == 409
    assert app.state.store.all('session') == [] and app.state.store.all('receipt') == []


def test_concurrent_identical_results_have_one_acceptance(cfg, monkeypatch):
    app, plane = control(cfg)
    callback = REGISTRY['launch_game'].on_accept
    accepts = []
    def accept(*args):
        accepts.append(1)
        time.sleep(0.02)
        return callback(*args)
    monkeypatch.setattr(REGISTRY['launch_game'], 'on_accept', accept)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(lambda _: plane.post('/api/workers/old-worker/result', json=launch_result()), range(4)))
    assert all(r.status_code == 200 for r in replies)
    assert len({r.json()['receipt'] for r in replies}) == 1 and len(accepts) == 1


@pytest.mark.parametrize('after_write', [False, True])
def test_interrupted_launch_acceptance_recovers_missing_or_partial_session(cfg, monkeypatch, after_write):
    app, plane = control(cfg)
    store = app.state.store
    original_put = store.put
    failures = []
    def put(kind, key, body):
        if kind == 'session' and not failures:
            failures.append(True)
            if after_write: original_put(kind, key, body)
            raise OSError('interrupted callback')
        return original_put(kind, key, body)
    monkeypatch.setattr(store, 'put', put)
    first = plane.post('/api/workers/old-worker/result', json=launch_result())
    assert first.status_code == 500
    job = store.get('job', 'launch')
    assert job['result_acceptance'] == 'pending' and job['state'] == 'running' and job['result_state'] == 'succeeded'
    prior = store.get('session', 'old-worker-launch')
    second = plane.post('/api/workers/old-worker/result', json=launch_result())
    assert second.status_code == 200 and second.json()['accepted'] is True
    assert store.get('job', 'launch')['result_acceptance'] == 'complete'
    assert len(store.all('receipt')) == 1 and len(store.all('session')) == 1
    if prior: assert store.get('session', 'old-worker-launch') == prior


def test_interrupted_unknown_callback_is_not_blindly_replayed(cfg, monkeypatch):
    app, plane = control(cfg)
    called = []
    def unknown(*_):
        called.append(1)
        raise RuntimeError('unknown partial effects')
    monkeypatch.setattr(REGISTRY['launch_game'], 'on_accept', unknown)
    assert plane.post('/api/workers/old-worker/result', json=launch_result()).status_code == 500
    assert plane.post('/api/workers/old-worker/result', json=launch_result()).status_code == 409
    assert called == [1] and app.state.store.get('job', 'launch')['result_acceptance'] == 'pending'


def test_launch_callback_never_resurrects_ended_or_overwrites_changed_session(cfg):
    app, _ = control(cfg)
    store = app.state.store
    output = tools.LaunchOut.model_validate(launch_result()['output'])
    tools._launch_accept(store, output, 'fixture')
    existing = store.get('session', output.session_id) | {'state': 'ended', 'ended': 123, 'custom': 'preserve'}
    store.put('session', output.session_id, existing)
    tools._launch_accept(store, output, 'fixture')
    assert store.get('session', output.session_id) == existing
    changed = existing | {'detail': existing['detail'] | {'pid': 999}}
    store.put('session', output.session_id, changed)
    with pytest.raises(RuntimeError, match='conflicts'):
        tools._launch_accept(store, output, 'fixture')
    assert store.get('session', output.session_id) == changed


def test_disk_failure_before_transport_keeps_busy_and_never_posts(cfg, monkeypatch):
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    active, agent = {'launch'}, {'launch'}
    monkeypatch.setattr(outbox, 'save', lambda *_: (_ for _ in ()).throw(OSError('disk full')))
    class NoPost:
        def post(self, *_, **__): pytest.fail('result was not persisted')
    worker._deliver_finished(outbox, NoPost(), 'old-worker', launch_result(), active, agent)
    assert active == agent == {'launch'}


def test_corrupt_saved_result_refuses_replay_and_reexecution(cfg):
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    outbox.save('old-worker', launch_result())
    path = next(outbox.directory.glob('*.json'))
    record = json.loads(path.read_text()); record['result']['output']['detail']['pid'] = 1
    path.write_text(json.dumps(record))
    with pytest.raises(RuntimeError, match='Invalid durable'):
        outbox.records()


def test_outbox_payload_collision_refused(cfg):
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    outbox.save('old-worker', launch_result())
    changed = launch_result(); changed['ok'] = False
    with pytest.raises(RuntimeError, match='different finished'):
        outbox.save('old-worker', changed)


def test_native_ownership_guard_protects_legacy_and_recovered_launches(cfg):
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    path = cfg.runtime / 'gbox-running.json'
    path.write_text(json.dumps({'legacy-no-outbox-job': {'pid': 4321}, 'dead': {'pid': 4}}))
    assert outbox.protected_sessions(path, is_alive=lambda pid: pid == 4321) == ['legacy-no-outbox-job']
    path.write_text(json.dumps({'invalid': {'pid': None}}))
    with pytest.raises(RuntimeError, match='Invalid owned emulator PID'):
        outbox.protected_sessions(path)


def test_restart_replays_old_result_before_new_identity_and_refuses_live_native_game(cfg, monkeypatch):
    app, plane = control(cfg)
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    outbox.save('old-worker', launch_result())
    (cfg.runtime / 'gbox-running.json').write_text(json.dumps({'old-worker-launch': {'pid': 4321}}))
    class Client:
        def __init__(self, **_): pass
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def post(self, path, **kwargs): return plane.post(path, **kwargs)
    monkeypatch.setattr(worker.httpx, 'Client', Client)
    monkeypatch.setattr(ResultOutbox, 'protected_sessions', lambda *_: ['old-worker-launch'])
    monkeypatch.setattr(worker, 'describe', lambda *_: pytest.fail('new worker registered before owned-game reconciliation'))
    monkeypatch.setattr(tools, 'reap_orphans', lambda *_: pytest.fail('live game must not be killed'))
    with pytest.raises(RuntimeError, match='owned PID record'):
        worker.run('http://fixture', 'secret', cfg, 'owned-worker', stop=threading.Event())
    assert app.state.store.get('job', 'launch')['result_acceptance'] == 'complete'
    assert app.state.store.get('session', 'old-worker-launch')['detail']['pid'] == 4321
    assert ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker').pending_count() == 0


def test_fsync_failure_never_transports_uncommitted_result(cfg, monkeypatch):
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    monkeypatch.setattr(worker_results.os, 'fsync', lambda *_: (_ for _ in ()).throw(OSError('sync failed')))
    with pytest.raises(OSError): outbox.save('old-worker', launch_result())
    assert not list(outbox.directory.glob('*.json'))
    assert not list(outbox.directory.glob('*.tmp'))


def test_blocked_delivery_does_not_block_heartbeat_inventory_or_new_persistence(cfg):
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    outbox.save('old-worker', launch_result())
    entered, release, inspected = threading.Event(), threading.Event(), threading.Event()
    class Blocking:
        def post(self, *_args, **_kwargs):
            entered.set()
            release.wait(5)
            raise httpx.ReadTimeout('bounded fixture')
    delivery = threading.Thread(target=outbox.deliver, args=(Blocking(), 'launch'))
    delivery.start()
    assert entered.wait(2)
    observed = []
    def inspect():
        observed.append(outbox.pending_count())
        outbox.save('old-worker', launch_result('another'))
        observed.append(outbox.pending_count())
        inspected.set()
    reader = threading.Thread(target=inspect)
    reader.start()
    try:
        assert inspected.wait(1), 'heartbeat inventory waited for transport'
        assert observed == [1, 2] and not release.is_set()
    finally:
        release.set()
        delivery.join(2)
        reader.join(2)
    assert not delivery.is_alive()


def test_admission_transaction_never_leaves_result_identity_without_receipt(cfg):
    app, plane = control(cfg)
    store = app.state.store
    store.db.execute("CREATE TRIGGER reject_receipt BEFORE INSERT ON docs WHEN NEW.kind='receipt' "
                     "BEGIN SELECT RAISE(ABORT,'fixture disk failure'); END")
    store.db.commit()
    assert plane.post('/api/workers/old-worker/result', json=launch_result()).status_code == 500
    assert 'result_sha256' not in store.get('job', 'launch')
    assert store.all('receipt') == [] and store.all('session') == []
    store.db.execute('DROP TRIGGER reject_receipt'); store.db.commit()
    assert plane.post('/api/workers/old-worker/result', json=launch_result()).json()['accepted'] is True


def test_completion_transaction_and_audit_resume_after_callback_without_duplicate_session(cfg):
    app, plane = control(cfg)
    store = app.state.store
    store.db.execute("CREATE TRIGGER reject_completion BEFORE UPDATE ON docs WHEN NEW.kind='job' "
                     "AND json_extract(NEW.body,'$.result_acceptance')='complete' "
                     "BEGIN SELECT RAISE(ABORT,'fixture commit failure'); END")
    store.db.commit()
    assert plane.post('/api/workers/old-worker/result', json=launch_result()).status_code == 500
    session = store.get('session', 'old-worker-launch')
    assert session and store.get('job', 'launch')['result_acceptance'] == 'pending'
    assert not [e for e in store.audit_log() if e['action'] == 'job.succeeded']
    store.db.execute('DROP TRIGGER reject_completion'); store.db.commit()
    assert plane.post('/api/workers/old-worker/result', json=launch_result()).json()['accepted'] is True
    assert store.get('session', 'old-worker-launch') == session
    assert len([e for e in store.audit_log() if e['action'] == 'job.succeeded']) == 1
    assert store.verify_audit()[0]


def test_ack_persistence_failure_replays_exact_result_without_second_acceptance(cfg, monkeypatch):
    app, plane = control(cfg)
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    outbox.save('old-worker', launch_result())
    original_write = worker_results._write
    def fail_ack(path, value):
        if value['status'] == 'acknowledged':
            raise OSError('disk failed after response')
        return original_write(path, value)
    monkeypatch.setattr(worker_results, '_write', fail_ack)
    with pytest.raises(OSError): outbox.deliver(plane, 'launch')
    receipt = app.state.store.get('job', 'launch')['receipt_id']
    assert outbox.pending_count() == 1
    monkeypatch.setattr(worker_results, '_write', original_write)
    assert outbox.send_ready(plane, force=True) == ['launch']
    assert app.state.store.get('job', 'launch')['receipt_id'] == receipt
    assert len(app.state.store.all('receipt')) == 1


def test_failed_callback_rolls_back_open_transaction_before_safe_retry(cfg, monkeypatch):
    app, plane = control(cfg)
    store = app.state.store
    result = launch_result(); result['output']['detail']['_game']['game_id'] = 'fixture'
    update = store.catalog_update
    def fail_update(*_args, **_kwargs):
        store.db.execute('INSERT INTO docs(kind,id,body) VALUES(?,?,?)', ('fixture', 'uncommitted', '{}'))
        raise OSError('callback database failure')
    monkeypatch.setattr(store, 'catalog_update', fail_update)
    assert plane.post('/api/workers/old-worker/result', json=result).status_code == 500
    assert store.get('fixture', 'uncommitted') is None
    assert not store.db.in_transaction and store.get('job', 'launch')['result_acceptance'] == 'pending'
    session = store.get('session', 'old-worker-launch')
    monkeypatch.setattr(store, 'catalog_update', update)
    assert plane.post('/api/workers/old-worker/result', json=result).json()['accepted'] is True
    assert store.get('session', 'old-worker-launch') == session


@pytest.mark.parametrize("already_ended", [False, True])
def test_interrupted_stop_acceptance_preserves_ended_session_metadata(cfg, monkeypatch, already_ended):
    from types import SimpleNamespace
    app, plane = control(cfg, jid="stop", tool="session_op")
    store = app.state.store
    sid = "old-worker-preserved-session"
    initial = {"session_id": sid, "game_id": "fixture", "adapter": "retroarch",
               "state": "ended" if already_ended else "running", "started": 111,
               "custom": {"operator_note": "preserve this", "nested": [1, 2]}}
    if already_ended:
        initial.update(ended=222, exit={"reason": "previous verified stop"})
    store.put("session", sid, initial)
    output = {"session_id": sid, "ended": True, "result": {"native_stopped": True}}
    payload = {"job_id": "stop", "ok": True, "output": output, "log": [], "artifacts": []}
    monkeypatch.setattr(tools, "time", SimpleNamespace(time=lambda: 1001))
    store.db.execute("CREATE TRIGGER reject_stop_completion BEFORE UPDATE ON docs WHEN NEW.kind='job' "
                     "AND json_extract(NEW.body,'$.result_acceptance')='complete' "
                     "BEGIN SELECT RAISE(ABORT,'fixture interrupted stop completion'); END")
    store.db.commit()
    first = plane.post("/api/workers/old-worker/result", json=payload)
    assert first.status_code == 500
    assert store.get("job", "stop")["result_acceptance"] == "pending"
    expected = initial if already_ended else initial | {"state": "ended", "ended": 1001, "exit": output["result"]}
    assert store.get("session", sid) == expected
    assert not [e for e in store.audit_log() if e["action"] == "job.succeeded"]
    # The callback's first write committed before the terminal transaction failed.
    # Recovery at a different time must preserve that existing native-stop record.
    monkeypatch.setattr(tools, "time", SimpleNamespace(time=lambda: 2002))
    store.db.execute("DROP TRIGGER reject_stop_completion"); store.db.commit()
    second = plane.post("/api/workers/old-worker/result", json=payload)
    assert second.status_code == 200 and second.json()["accepted"] is True
    assert store.get("session", sid) == expected
    third = plane.post("/api/workers/old-worker/result", json=payload)
    assert third.status_code == 200 and third.json()["receipt"] == second.json()["receipt"]
    assert store.get("session", sid) == expected
    assert len(store.all("receipt")) == 1
    assert len([e for e in store.audit_log() if e["action"] == "job.succeeded"]) == 1
    assert store.verify_audit()[0]


@pytest.mark.parametrize('status', [401, 403])
def test_auth_failure_is_not_a_verdict_on_the_result(cfg, status):
    # A wrong token says nothing about the result: keep it pending so it can still be delivered (#1296).
    app, plane = control(cfg)
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    outbox.save('old-worker', launch_result())
    class Denied:
        def post(self, path, **_):
            return httpx.Response(status, request=httpx.Request('POST', 'http://fixture' + path))
    assert not outbox.deliver(Denied(), 'launch')
    assert outbox.records()[0]['status'] == 'pending'
    assert outbox.send_ready(plane, force=True) == ['launch']


class _PlaneClient:
    plane = None
    def __init__(self, **_): pass
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def post(self, path, **kwargs): return self.plane.post(path, **kwargs)


class _Registered(Exception):
    pass


def test_refused_result_without_ack_still_holds_worker_activation(cfg, monkeypatch):
    # A server refusal is not delivery acceptance, even after reconnect.
    app, plane = control(cfg, state='succeeded')
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    outbox.save('old-worker', launch_result())
    class Refuse:
        def post(self, path, **_):
            return httpx.Response(409, request=httpx.Request('POST', 'http://fixture' + path))
    assert not outbox.deliver(Refuse(), 'launch')
    saved = next(outbox.directory.glob('*.json')).read_bytes()
    monkeypatch.setattr(_PlaneClient, 'plane', plane)
    monkeypatch.setattr(worker.httpx, 'Client', _PlaneClient)
    monkeypatch.setattr(ResultOutbox, 'protected_sessions', lambda *_: [])
    def describe(*_):
        raise _Registered()
    monkeypatch.setattr(worker, 'describe', describe)
    with pytest.raises(RuntimeError, match='activation held.*job launch rejected'):
        worker.run('http://fixture', 'secret', cfg, 'owned-worker', stop=threading.Event(), reconcile_results=True)
    fresh = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    assert fresh.pending_count() == 1 and fresh.held()[0]['status'] == 'rejected'
    kept = list((fresh.directory / 'refused-evidence').glob('*.json'))
    assert len(kept) == 1 and kept[0].read_bytes() == saved
    assert not (fresh.directory / 'rejected').exists()


def test_uncertain_result_still_holds_activation_and_names_the_job(cfg, monkeypatch):
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    outbox.save('old-worker', launch_result())
    class Down:
        def __init__(self, **_): pass
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def post(self, path, **_): raise httpx.ConnectError('spark unreachable')
    monkeypatch.setattr(worker.httpx, 'Client', Down)
    monkeypatch.setattr(worker, 'describe', lambda *_: pytest.fail('registered while a result was uncertain'))
    with pytest.raises(RuntimeError, match=r'activation held.*job launch pending after 1 attempt\(s\) \(ConnectError\)'):
        worker.run('http://fixture', 'secret', cfg, 'owned-worker', stop=threading.Event())
    assert outbox.pending_count() == 1


def refuse(outbox):
    class Refuse:
        def post(self, path, **_):
            return httpx.Response(409, request=httpx.Request('POST', 'http://fixture' + path))
    assert not outbox.deliver(Refuse(), 'launch')
    return next(outbox.directory.glob('*.json')).read_bytes()


def test_explicit_reconciliation_requires_exact_real_ack_and_preserves_refusal(cfg):
    app, plane = control(cfg)
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    result = launch_result()
    outbox.save('old-worker', result)
    original = refuse(outbox)
    assert outbox.send_ready(plane, force=True) == []
    assert app.state.store.all('receipt') == []
    assert outbox.reconcile_ready(plane) == ['launch']
    archived = outbox.records(include_acknowledged=True)[0]
    assert archived['result'] == worker_results.normalized_result(result)
    assert archived['acknowledgement']['result_sha256'] == result_digest(result)
    assert outbox.pending_count() == 0
    assert (outbox.directory / archived['refused_evidence'][0]).read_bytes() == original
    assert len(app.state.store.all('receipt')) == len(app.state.store.all('session')) == 1
    assert outbox.reconcile_ready(plane) == []


@pytest.mark.parametrize('ack', [
    {}, {'accepted': False}, {'accepted': True, 'job_id': 'foreign'},
    {'accepted': True, 'worker_id': 'foreign'}, {'accepted': True, 'result_sha256': '0'*64},
    {'accepted': True, 'receipt': 1}, {'accepted': True, 'state': []},
    {'accepted': True, 'state': 'running'},
])
def test_explicit_reconciliation_never_releases_missing_foreign_or_malformed_ack(cfg, ack):
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    outbox.save('old-worker', launch_result())
    original = refuse(outbox)
    expected = {'accepted': True, 'job_id': 'launch', 'worker_id': 'old-worker',
                'result_sha256': result_digest(launch_result()), 'state': 'succeeded', 'receipt': 'actual'}
    # {} and False model wholly missing/refused acknowledgements; other rows
    # corrupt one field of an otherwise exact identity.
    body = ack if not ack or ack.get('accepted') is False else expected | ack
    class Reply:
        def post(self, path, **_):
            return httpx.Response(200, json=body, request=httpx.Request('POST', 'http://fixture' + path))
    assert outbox.reconcile_ready(Reply()) == []
    assert outbox.pending_count() == 1 and outbox.records()[0]['status'] == 'rejected'
    assert len(list((outbox.directory / 'refused-evidence').glob('*.json'))) == 1
    assert next((outbox.directory / 'refused-evidence').glob('*.json')).read_bytes() == original
    assert not list(outbox.archive.glob('*.json'))


@pytest.mark.parametrize('problem', ['missing_job', 'foreign_worker', 'cancelled'])
def test_real_control_plane_refusal_keeps_exact_result_held(cfg, problem):
    app, plane = control(cfg)
    if problem == 'missing_job':
        app.state.store.delete('job', 'launch')
    else:
        job = app.state.store.get('job', 'launch')
        job['worker_id' if problem == 'foreign_worker' else 'cancel'] = 'another-worker' if problem == 'foreign_worker' else True
        app.state.store.put('job', 'launch', job)
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    outbox.save('old-worker', launch_result())
    refuse(outbox)
    assert outbox.reconcile_ready(plane) == []
    assert outbox.pending_count() == 1 and outbox.records()[0]['status'] == 'rejected'
    assert app.state.store.all('session') == app.state.store.all('receipt') == []


def test_lost_reconciliation_ack_keeps_refused_result_and_accepts_once(cfg):
    app, plane = control(cfg)
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    outbox.save('old-worker', launch_result())
    refuse(outbox)
    client = LostAcknowledgement(plane)
    assert outbox.reconcile_ready(client) == []
    assert outbox.pending_count() == 1
    receipt = app.state.store.get('job', 'launch')['receipt_id']
    assert outbox.send_ready(client, force=True) == []
    assert client.calls == 1
    assert outbox.reconcile_ready(client) == ['launch']
    assert client.calls == 2 and outbox.pending_count() == 0
    assert app.state.store.get('job', 'launch')['receipt_id'] == receipt
    assert len(app.state.store.all('receipt')) == len(app.state.store.all('session')) == 1


def test_explicit_startup_ack_does_not_reap_a_live_native_game(cfg, monkeypatch):
    app, plane = control(cfg)
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    outbox.save('old-worker', launch_result())
    refuse(outbox)
    monkeypatch.setattr(_PlaneClient, 'plane', plane)
    monkeypatch.setattr(worker.httpx, 'Client', _PlaneClient)
    monkeypatch.setattr(ResultOutbox, 'protected_sessions', lambda *_: ['old-worker-launch'])
    monkeypatch.setattr(worker, 'describe', lambda *_: pytest.fail('Live native game admitted a fresh worker'))
    monkeypatch.setattr(tools, 'reap_orphans', lambda *_: pytest.fail('Reconciliation must not kill natives'))
    monkeypatch.setattr(worker, 'execute', lambda *_: pytest.fail('A result was replayed as a tool'))
    with pytest.raises(RuntimeError, match='owned PID record'):
        worker.run('http://fixture', 'secret', cfg, 'owned-worker', reconcile_results=True)
    assert ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker').pending_count() == 0
    assert app.state.store.get('session', 'old-worker-launch')['detail']['pid'] == 4321


def test_acknowledged_frozen_record_requires_a_string_receipt(cfg):
    app, plane = control(cfg)
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    outbox.save('old-worker', launch_result())
    assert outbox.deliver(plane, 'launch')
    path = next(outbox.archive.glob('*.json'))
    record = json.loads(path.read_text())
    record['acknowledgement']['receipt'] = 1
    path.write_text(json.dumps(record))
    with pytest.raises(RuntimeError, match='Invalid durable acknowledgement'):
        outbox.records(include_acknowledged=True)


def test_legacy_quarantined_refusal_cannot_disappear_from_admission(cfg):
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    outbox.save('old-worker', launch_result())
    refuse(outbox)
    quarantined = outbox.directory / 'rejected'
    quarantined.mkdir()
    source = next(outbox.directory.glob('*.json'))
    frozen = source.read_bytes()
    source.rename(quarantined / source.name)
    with pytest.raises(RuntimeError, match='outside the delivery queue'):
        outbox.pending_count()
    assert next(quarantined.glob('*.json')).read_bytes() == frozen


def test_explicit_reconciliation_attempts_at_most_four_retained_results(cfg):
    app, plane = control(cfg)
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    for k in range(5):
        result = launch_result('extra-' + str(k))
        job = app.state.store.get('job', 'launch') | {'id': result['job_id']}
        app.state.store.put('job', result['job_id'], job)
        outbox.save('old-worker', result)
    assert len(outbox.reconcile_ready(plane)) == 4
    assert outbox.pending_count() == 1 and len(app.state.store.all('receipt')) == 4
    assert len(outbox.reconcile_ready(plane)) == 1
    assert outbox.pending_count() == 0 and len(app.state.store.all('receipt')) == 5


@pytest.mark.parametrize('maximum', [True, 0, -1, 5])
def test_invalid_reconciliation_bound_cannot_expand_transport(cfg, maximum):
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    class NoPost:
        def post(self, *_args, **_kwargs): pytest.fail('Invalid bound reached transport')
    with pytest.raises(ValueError, match='bounded'):
        outbox.reconcile_ready(NoPost(), maximum=maximum)


@pytest.mark.parametrize('mutate', ['boolean_version', 'missing_worker', 'numeric_worker', 'missing_job', 'numeric_ok'])
def test_malformed_durable_identity_is_refused_before_transport(cfg, mutate):
    outbox = ResultOutbox(cfg.runtime, 'http://fixture', 'owned-worker')
    outbox.save('old-worker', launch_result())
    path = next(outbox.directory.glob('*.json'))
    value = json.loads(path.read_text())
    if mutate == 'boolean_version': value['version'] = True
    if mutate == 'missing_worker': value['worker_id'] = ''
    if mutate == 'numeric_worker': value['worker_id'] = 1
    if mutate == 'missing_job': value['result']['job_id'] = None
    if mutate == 'numeric_ok': value['result']['ok'] = 1
    path.write_text(json.dumps(value))
    class NoPost:
        def post(self, *_args, **_kwargs): pytest.fail('Invalid durable identity reached transport')
    with pytest.raises((RuntimeError, ValueError), match='Invalid'):
        outbox.reconcile_ready(NoPost())
    assert path.exists() and not list(outbox.archive.glob('*.json'))
