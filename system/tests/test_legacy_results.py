"""Migration from real old receipt shape; raw result bytes must remain provable."""
import base64
import copy
import concurrent.futures
import sqlite3

import pytest

from gbox.registry import REGISTRY
from gbox import legacy_results
from gbox.worker_results import result_digest
from test_worker_results import control, launch_result


def legacy(cfg, *, previous_checkpoint=False):
    app, plane = control(cfg)
    result = launch_result()
    if previous_checkpoint:
        store = app.state.store
        artifact = store.put_artifact(b'owned previous saved state', 'previous.state', 'application/octet-stream', {})
        store.put('session', 'old-worker-prior', {'session_id': 'old-worker-prior', 'state': 'running'})
        result['output']['detail']['previous_checkpoints'] = [{'session_id': 'old-worker-prior',
            'artifact': artifact.sha256, 'bytes': artifact.size}]
    accepted = plane.post('/api/workers/old-worker/result', json=result)
    assert accepted.status_code == 200
    store = app.state.store
    job = store.get('job', 'launch')
    # Old servers stored these independent hashes, artifacts and the success
    # audit, but none of the durable-delivery identity/completion fields.
    for key in ('result_sha256', 'result_acceptance', 'result_state'):
        job.pop(key, None)
    store.put('job', 'launch', job)
    session = store.get('session', 'old-worker-launch') | {'state': 'ended', 'ended': 123, 'exit': 'owned fixture ended'}
    store.put('session', 'old-worker-launch', session)
    return app, plane, result, copy.deepcopy(job), copy.deepcopy(session)


def settled_late(response, store):
    """Unverifiable legacy evidence is never bound to the job and never replays a callback.

    The worker still gets a verifiable "late" acknowledgement and the bytes are kept as
    audited evidence, because a refusal would hold that worker offline at every start.
    """
    body = response.json()
    assert response.status_code == 200 and body['accepted'] is True and body['late'] is True
    assert not store.get('job', 'launch').get('result_sha256')
    assert not [row for row in store.audit_log() if row['action'] == 'job.result_reconciled']
    assert len(store.all('late_result')) == 1 and not store.db.in_transaction
    return body


def test_legacy_success_reconciles_exact_result_once_without_resurrecting_game(cfg):
    app, plane, result, before, session = legacy(cfg)
    store = app.state.store
    receipt = copy.deepcopy(store.get('receipt', before['receipt_id']))
    response = plane.post('/api/workers/old-worker/result', json=result)
    assert response.status_code == 200 and response.json()['accepted'] is True
    assert response.json()['result_sha256'] == result_digest(result)
    after = store.get('job', 'launch')
    assert {key: after[key] for key in before} == before
    assert store.get('session', 'old-worker-launch') == session
    assert store.get('receipt', before['receipt_id']) == receipt
    assert plane.post('/api/workers/old-worker/result', json=result).json() == response.json()
    assert len([row for row in store.audit_log() if row['action'] == 'job.result_reconciled']) == 1
    assert len([row for row in store.audit_log() if row['action'] == 'job.succeeded']) == 1
    assert store.verify_audit()[0]


@pytest.mark.parametrize('change', ['output', 'log', 'artifact', 'provenance', 'name', 'type',
    'error', 'ok', 'input', 'receipt_id', 'validation', 'receipt_worker', 'receipt_version',
    'finished', 'receipt_audit', 'job_state', 'cancel', 'session_pid', 'session_absent', 'blob_absent'])
def test_legacy_ambiguous_or_changed_evidence_stays_unbound(cfg, change):
    app, plane, result, before, session = legacy(cfg)
    store = app.state.store
    job = copy.deepcopy(before)
    receipt = store.get('receipt', job['receipt_id'])
    if change == 'output': result['output']['detail']['pid'] = 55
    elif change == 'log': result['log'].append('another log')
    elif change == 'artifact': result['artifacts'][0]['b64'] = base64.b64encode(b'other').decode()
    elif change == 'provenance': result['artifacts'][0]['provenance']['worker'] = 'foreign'
    elif change == 'name': result['artifacts'][0]['name'] = 'different.bin'
    elif change == 'type': result['artifacts'][0]['media_type'] = 'image/png'
    elif change == 'error': result['error'] = 'different error'
    elif change == 'ok': result['ok'] = False
    elif change == 'input': job['input'] = {'different': True}
    elif change == 'receipt_id': job['receipt_id'] = 'missing'
    elif change == 'validation': receipt['validation_ok'] = False
    elif change == 'receipt_worker': receipt['worker_id'] = 'foreign'
    elif change == 'receipt_version': receipt.pop('tool_version')
    elif change == 'finished': receipt['finished'] += 1
    elif change == 'receipt_audit': receipt['audit_seq'] += 1
    elif change == 'job_state': job['state'] = 'failed'
    elif change == 'cancel': job['cancel'] = True
    elif change == 'session_pid': store.put('session', session['session_id'], session | {'detail': {'pid': 999}})
    elif change == 'session_absent': store.delete('session', session['session_id'])
    elif change == 'blob_absent': store.artifact_path(receipt['artifacts'][0]['sha256']).unlink()
    store.put('job', job['id'], job)
    store.put('receipt', receipt['id'], receipt)
    settled_late(plane.post('/api/workers/old-worker/result', json=result), store)


def test_legacy_foreign_worker_refused_and_unknown_callback_never_rerun(cfg, monkeypatch):
    app, plane, result, before, session = legacy(cfg)
    assert plane.post('/api/workers/foreign-worker/result', json=result).status_code == 409
    monkeypatch.setattr(REGISTRY['launch_game'], 'on_accept', lambda *_: pytest.fail('callback rerun'))
    settled_late(plane.post('/api/workers/old-worker/result', json=result), app.state.store)
    assert app.state.store.get('session', session['session_id']) == session


def test_legacy_concurrent_result_reconciliation_is_idempotent(cfg):
    app, plane, result, before, session = legacy(cfg)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: plane.post('/api/workers/old-worker/result', json=result), range(4)))
    assert all(response.status_code == 200 for response in responses)
    assert len({response.json()['receipt'] for response in responses}) == 1
    assert len([row for row in app.state.store.audit_log() if row['action'] == 'job.result_reconciled']) == 1
    assert app.state.store.get('session', session['session_id']) == session


def test_legacy_proof_holds_sqlite_writer_lock(cfg, monkeypatch):
    app, plane, result, before, session = legacy(cfg)
    store = app.state.store
    original = legacy_results.verify_legacy_success
    observations = []
    def proof(*args):
        assert store.db.in_transaction
        with sqlite3.connect(store.dir / 'gbox.sqlite3', timeout=0.05) as other:
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                other.execute("UPDATE docs SET body=body WHERE kind='job' AND id='launch'")
        observations.append('locked')
        return original(*args)
    monkeypatch.setattr(legacy_results, 'verify_legacy_success', proof)
    assert plane.post('/api/workers/old-worker/result', json=result).status_code == 200
    assert observations == ['locked']


def test_legacy_reconciliation_audit_failure_rolls_back_identity(cfg, monkeypatch):
    app, plane, result, before, session = legacy(cfg)
    store = app.state.store
    db = store.db
    class Interrupted:
        def execute(self, query, *args):
            if query.startswith('INSERT INTO audit'):
                raise sqlite3.OperationalError('owned audit write failure')
            return db.execute(query, *args)
        def __getattr__(self, key):
            return getattr(db, key)
    monkeypatch.setattr(store, 'db', Interrupted())
    assert plane.post('/api/workers/old-worker/result', json=result).status_code == 500
    assert store.get('job', 'launch') == before
    assert not db.in_transaction
    assert store.get('session', session['session_id']) == session


@pytest.mark.parametrize('change', [None, 'artifact_missing', 'prior_running', 'missing_identity'])
def test_legacy_previous_checkpoint_requires_persisted_bytes(cfg, change):
    app, plane, result, before, session = legacy(cfg, previous_checkpoint=True)
    store = app.state.store
    checkpoint = result['output']['detail']['previous_checkpoints'][0]
    if change == 'artifact_missing': store.artifact_path(checkpoint['artifact']).unlink()
    elif change == 'prior_running': store.put('session', 'old-worker-prior', {'state': 'running', 'checkpoint': checkpoint['artifact']})
    elif change == 'missing_identity':
        checkpoint.pop('artifact')
        job = store.get('job', 'launch'); job['output'] = result['output']; store.put('job', 'launch', job)
    response = plane.post('/api/workers/old-worker/result', json=result)
    if change is None:
        assert response.status_code == 200 and not response.json().get('late')
    else:
        settled_late(response, store)


@pytest.mark.parametrize('invalid', [1, 0, 'true', 'false'])
def test_result_success_flag_requires_json_boolean(cfg, invalid):
    app, plane, result, before, session = legacy(cfg)
    result['ok'] = invalid
    assert plane.post('/api/workers/old-worker/result', json=result).status_code == 422
    assert app.state.store.get('job', 'launch') == before


def test_legacy_stored_output_is_compared_as_canonical_json(cfg):
    app, plane, result, before, session = legacy(cfg)
    # Python considers integer and float equal; independent evidence does not.
    job = app.state.store.get('job', 'launch')
    job['output']['detail']['pid'] = 4321.0
    app.state.store.put('job', 'launch', job)
    settled_late(plane.post('/api/workers/old-worker/result', json=result), app.state.store)


@pytest.mark.parametrize('key', ['started', 'finished'])
def test_legacy_job_timestamps_require_numbers_not_booleans(cfg, key):
    app, plane, result, before, session = legacy(cfg)
    store = app.state.store
    job = store.get('job', 'launch')
    receipt = store.get('receipt', job['receipt_id'])
    job['started'], job['finished'] = 1, 2
    receipt['started'], receipt['finished'] = 1, 2
    if key == 'finished':
        job['started'] = receipt['started'] = 0.5
        job['finished'] = True
        receipt['finished'] = 1
    else: job['started'] = True
    store.put('job', job['id'], job); store.put('receipt', receipt['id'], receipt)
    settled_late(plane.post('/api/workers/old-worker/result', json=result), store)
