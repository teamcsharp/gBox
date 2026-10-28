"""Live rebuild evidence crosses the existing mapping; no worker or rebuild is executed."""
from types import SimpleNamespace

import httpx
import pytest

from gbox.desktop_bridge import DesktopBridge, Submissions
from gbox.store import Store
from test_federation import AUTH, KEY, WID, LOCAL, plane, queued, snapshot


@pytest.fixture
def relay(cfg, tmp_path):
    app, client = plane(cfg)
    body = snapshot(sessions=False)
    body['worker']['tools'].append('rebuild_node')
    response = client.post('/api/federation/' + AUTH + '/snapshot', json=body)
    assert response.status_code == 200, response.text
    jid = queued(app, tool='rebuild_node')
    command = client.post('/api/federation/' + AUTH + '/commands', json={'maximum': 1}).json()['commands'][0]
    local = Store(tmp_path / 'local')

    def submit(command, worker, origin):
        job = {'id': LOCAL, 'tool': command['tool'], 'input': command['input'], 'origin': origin,
               'worker_id': WID, 'state': 'running'}
        local.put('job', LOCAL, job)
        return job

    submissions = Submissions(local, submit, AUTH, 'http://central.example:8765')
    submissions.accept(command, body['worker'])
    bridge = DesktopBridge.__new__(DesktopBridge)
    bridge.store, bridge.state, bridge.submissions = local, {}, submissions
    bridge.authority, bridge.remote, bridge.active_worker_id = AUTH, submissions.remote, WID
    bridge.token, bridge.secret, bridge.input_secret = 'central-fixture-secret', KEY, 'input-fixture-secret'
    bridge.cfg = SimpleNamespace(token=lambda: 'local-fixture-secret')

    def central(_client, method, path, **kwargs):
        response = client.request(method, '/api/federation/' + AUTH + path, **kwargs)
        response.raise_for_status()
        return response.json()

    bridge._central = central
    yield SimpleNamespace(app=app, client=client, store=app.state.store, local=local, bridge=bridge,
                          jid=jid, central=central, path='/api/federation/' + AUTH + '/jobs/' + jid)
    local.db.close()
    client.close()


def advance(r, lines, seq, pct=20):
    row = r.local.get('job', LOCAL)
    r.local.put('job', LOCAL, row | {'console': lines, 'console_seq': seq,
        'progress': {'pct': pct, 'msg': lines[-1] if lines else '', 'ts': 100. + seq}})


def console(r, after=0):
    return r.client.get(f'/api/jobs/{r.jid}/console?after={after}').json()


def test_running_rebuild_relays_console_and_progress_before_result(relay):
    r = relay
    advance(r, ['== 1/5 Code ==', '[ok] update'], 2, 14)
    r.bridge._report_jobs(None)
    evidence = console(r)
    assert evidence['state'] == 'running' and evidence['pct'] == 14
    assert evidence['seq'] == 2 and evidence['lines'] == ['== 1/5 Code ==', '[ok] update']
    assert r.store.get('job', r.jid)['progress_log'] == evidence['lines']
    assert r.local.get('job', LOCAL)['state'] == 'running'


def test_lost_ack_replay_reordered_updates_and_trimmed_tail_are_idempotent(relay):
    r = relay
    advance(r, ['line 1', 'line 2'], 2)
    attempts = []
    def lost(*args, **kwargs):
        answer = r.central(*args, **kwargs)
        attempts.append(kwargs['json'])
        if len(attempts) == 1:
            raise httpx.ReadError('lost response')
        return answer
    r.bridge._central = lost
    r.bridge._report_jobs(None)
    assert r.bridge.state['delivery_holds']
    r.bridge._report_jobs(None)
    assert console(r)['lines'] == ['line 1', 'line 2'] and console(r)['seq'] == 2
    assert console(r, 2)['lines'] == []
    advance(r, [f'line {n}' for n in range(151, 351)], 350, 75)
    r.bridge._report_jobs(None)
    newer = console(r, 2)
    assert newer['seq'] == 350 and len(newer['lines']) == 200
    assert newer['lines'][0] == 'line 151' and newer['pct'] == 75
    # An older report may arrive after a reconnect; it cannot rewind evidence.
    assert r.client.post(r.path, json=attempts[0]).status_code == 200
    assert console(r) == console(r, 0) and console(r)['seq'] == 350
    assert console(r)['pct'] == 75
    assert console(r, 348)['lines'] == ['line 349', 'line 350']
    advance(r, ['new detail at a lower reported percent'], 351, 12)
    r.bridge._report_jobs(None)
    assert console(r)['seq'] == 351 and console(r)['pct'] == 75
    assert console(r, 350)['lines'] == ['new detail at a lower reported percent']


def test_progress_is_redacted_and_bounded_on_both_sides(relay):
    r = relay
    secrets = ['central-fixture-secret', 'local-fixture-secret', 'input-fixture-secret', KEY]
    text = ' '.join(secrets) + ' token="quoted-secret" Authorization: Bearer abcdefgh12345 https://user:pass@example.test/'
    advance(r, ['x' * 5000] * 240 + [text], 241, 40)
    sent = []
    def record(*args, **kwargs):
        sent.append(kwargs['json'])
        return r.central(*args, **kwargs)
    r.bridge._central = record
    r.bridge._report_jobs(None)
    assert sent
    value = str(sent[0]['rebuild_progress'])
    assert not any(secret in value for secret in secrets + ['quoted-secret', 'abcdefgh12345', 'user:pass@'])
    tail = console(r)
    assert tail['seq'] == 241 and len(tail['lines']) <= 200
    assert sum(map(len, tail['lines'])) <= 32768 and max(map(len, tail['lines'])) <= 1024
    # The receiver redacts too, even if a paired older sender did not.
    payload = {'local_job_id': LOCAL, 'state': 'running', 'rebuild_progress': {
        'seq': 242, 'lines': ['password=private ' + KEY],
        'progress': {'pct': 41, 'msg': 'secret="private-two"', 'ts': 342.}}}
    assert r.client.post(r.path, json=payload).status_code == 200
    assert 'private' not in str(console(r)) and KEY not in str(console(r))


@pytest.mark.parametrize('field,value', [('authority', '9' * 64), ('worker_id', '9' * 16),
                                       ('local_job_id', '9' * 32)])
def test_receiver_rejects_progress_outside_exact_mapping(relay, field, value):
    r = relay
    advance(r, ['original'], 1)
    r.bridge._report_jobs(None)
    body = {'local_job_id': LOCAL, 'state': 'running', 'rebuild_progress': {
        'seq': 2, 'lines': ['forged'], 'progress': {'pct': 99, 'msg': 'forged', 'ts': 102.}}}
    if field == 'authority':
        path = r.path.replace(AUTH, value)
    else:
        path = r.path
        if field == 'local_job_id': body[field] = value
        else:
            record = r.store.get('federation_command', r.jid)
            r.store.put('federation_command', r.jid, record | {'worker_id': value})
    assert r.client.post(path, json=body).status_code in (403, 409)
    assert console(r)['lines'] == ['original']


@pytest.mark.parametrize('case', ['authority', 'origin-key', 'worker', 'input'])
def test_sender_never_exports_progress_from_an_unrelated_local_job(relay, case):
    r = relay
    advance(r, ['private unrelated output'], 1)
    row = r.local.get('job', LOCAL)
    if case == 'authority': row['origin']['desktop_federation_authority'] = '9' * 64
    if case == 'origin-key': row['origin']['desktop_federation_key'] = 'unrelated'
    if case == 'worker': row['worker_id'] = '9' * 16
    if case == 'input': row['input'] = {'force': True}
    r.local.put('job', LOCAL, row)
    sent = []
    r.bridge._central = lambda *a, **kw: sent.append(kw) or {}
    r.bridge._report_jobs(None)
    assert not sent and r.bridge.state['delivery_holds']


def test_terminal_failure_keeps_actual_error_and_final_console_then_freezes_progress(relay):
    r = relay
    advance(r, ['self-check failed'], 8, 80)
    row = r.local.get('job', LOCAL)
    r.local.put('job', LOCAL, row | {'state': 'failed', 'error': 'actual self-check failure', 'output': None})
    r.bridge._report_jobs(None)
    result = console(r)
    assert result['state'] == 'failed' and result['error'] == 'actual self-check failure'
    assert result['seq'] == 8 and result['lines'] == ['self-check failed']
    stale = {'local_job_id': LOCAL, 'state': 'running', 'rebuild_progress': {
        'seq': 9, 'lines': ['late'], 'progress': {'pct': 90, 'msg': 'late', 'ts': 109.}}}
    assert r.client.post(r.path, json=stale).status_code == 200
    assert console(r) == result


@pytest.mark.parametrize('side', ['sender', 'receiver'])
def test_malformed_optional_progress_never_strands_actual_terminal_failure(relay, side):
    r = relay
    advance(r, ['prior good console'], 2, 25)
    r.bridge._report_jobs(None)
    row = r.local.get('job', LOCAL)
    row.update(state='failed', error='actual self-check failure', output=None)
    if side == 'sender':
        row['console'] = {'unexpected': 'data'}
    else:
        def malformed(*args, **kwargs):
            kwargs['json']['rebuild_progress'] = {'seq': True, 'lines': [], 'progress': {}}
            return r.central(*args, **kwargs)
        r.bridge._central = malformed
    r.local.put('job', LOCAL, row)
    r.bridge._report_jobs(None)
    result = console(r)
    assert result['state'] == 'failed' and result['error'] == 'actual self-check failure'
    assert result['lines'] == ['prior good console'] and result['seq'] == 2
    mapping = r.local.get('desktop_bridge_job', r.bridge.submissions.key(r.jid))
    assert mapping['central_acked'] and not r.bridge.state['delivery_holds']
    if side == 'sender': assert mapping['progress_delivery_error'] == 'invalid_rebuild_progress'
    else: assert r.store.get('job', r.jid)['federation_progress_error'] == 'invalid_rebuild_progress'


@pytest.mark.parametrize('change', [{'seq': -1}, {'seq': True}, {'seq': 0}, {'lines': ['x'] * 201},
                                   {'lines': ['x' * 1025]}, {'progress': {'pct': 101, 'msg': 'x', 'ts': 1}}])
def test_malformed_progress_is_rejected_without_partial_mapping_or_state_change(relay, change):
    r = relay
    payload = {'seq': 1, 'lines': ['line'], 'progress': {'pct': 10, 'msg': 'line', 'ts': 101.}} | change
    response = r.client.post(r.path, json={'local_job_id': LOCAL, 'state': 'running', 'rebuild_progress': payload})
    assert response.status_code == 422, response.text
    assert 'console_seq' not in r.store.get('job', r.jid)
    assert not r.store.get('federation_command', r.jid).get('local_job_id')
