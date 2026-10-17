import datetime as dt
import json
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gbox import hermes_device_work as W

RID = '0123456789abcdef'
NODES = [dict(id='sparkDeux', name='Spark2', provider='gbox-sparkDeux', model='shared-model', endpoints={'http://two/v1'}),
         dict(id='lilspark', name='lilspark', provider='gbox-lilspark', model='shared-model', endpoints={'http://one/v1'})]


def call(provider='gbox-sparkDeux', endpoint='http://two/v1', state='ok', ts=110):
    return dict(provider=provider, model='shared-model', base_url=endpoint, state=state, ts=ts, completed_at=ts+1)


def run(rid='run-a', start=110, finish=150, **extra):
    return dict(id=rid, job_id='job-a', session_id=rid, title='Task', state='completed', started=start,
                finished=finish, current_action='Read source', request_ids=[RID], tokens_in=4, tokens_out=2) | extra


def aggregate(runs, sessions, receipts=(), requests=None, merges=None, calls=(), since=100, now=200):
    return W.aggregate(runs, sessions, NODES, list(receipts), requests or {}, merges or {}, calls, since, now)


def test_device_identity_uses_endpoint_not_same_model_or_current_route(monkeypatch):
    assert W._device(call(), NODES) == ('sparkDeux', 'logged_endpoint')
    assert W._device(call(provider='custom', endpoint='http://one/v1'), NODES) == ('lilspark', 'logged_endpoint')
    assert W._device(call(provider='custom', endpoint=''), NODES)[0] == 'unknown'
    monkeypatch.setattr(W.P, 'is_local', lambda *args: True)
    assert W._device(call(endpoint='http://changed/v1'), NODES)[0] == 'unknown'
    assert W.observed_routes({'calls': [call(state='open'), call(state='failed')]}, NODES) == []


def test_concurrency_window_clipping_and_calls_are_not_completed_tasks():
    runs = [run('a', 80, 130), run('b', 120, 160), run('c', 140, None, state='running')]
    sessions = {r['id']: {'calls': [call()]} for r in runs}
    calls = [dict(host_name='sparkDeux', ts=140, status='ok', duration_s=3, prompt_tokens=10, completion_tokens=5),
             dict(host_name='sparkDeux', ts=141, status='error'), dict(host_name='sparkDeux', ts=90, status='ok')]
    devices, rows = aggregate(runs, sessions, calls=calls)
    metrics = next(d for d in devices if d['id'] == 'sparkDeux')['metrics']
    assert metrics['peak_concurrency'] == 2 and metrics['wall_s'] == 130
    assert metrics['active_runs'] == 1 and metrics['ended_runs'] == 2
    assert metrics['calls_ok'] == 1 and metrics['calls_failed'] == 1 and metrics['call_success_rate'] == .5
    assert metrics['prs_opened'] == metrics['prs_merged'] == metrics['requests_resolved'] == 0
    assert metrics['tokens_in'] == 10 and metrics['tokens_out'] == 5
    assert all(r['outcomes'] == [] for r in rows)
    assert next(d for d in devices if d['id'] == 'lilspark')['metrics']['calls_ok'] is None


def test_mixed_provider_run_is_not_credited_solely_to_last_model():
    devices, rows = aggregate([run()], {'run-a': {'calls': [call(), call('gbox-lilspark', 'http://one/v1')]}})
    assert rows[0]['device_id'] == 'mixed'
    assert len(rows[0]['attribution']['routes']) == 2
    assert next(d for d in devices if d['id'] == 'sparkDeux')['metrics']['ended_runs'] == 0


def receipt(**extra):
    return dict(request_id=RID, commit='a'*40, pr_number=123, url='https://github.com/teamcsharp/gBox/pull/123',
                published_at=145, checks=['4 passed'], provenance={'runs': [{'run_id': 'run-a'}]}) | extra


def test_exact_publication_merge_identity_and_reopened_ticket():
    request = {RID: dict(id=RID, number=12, title='Fix reader', status='open')}
    merge = dict(state='MERGED', headRefOid='a'*40, baseRefName='main', mergedAt='1970-01-01T00:02:40+00:00')
    devices, rows = aggregate([run()], {'run-a': {'calls': [call()]}}, [receipt()], request, {'observations': {'123': merge}})
    assert rows[0]['title'] == '#12: Fix reader'
    assert {o['kind'] for o in rows[0]['outcomes']} == {'pr_published', 'pr_merged'}
    m = next(d for d in devices if d['id'] == 'sparkDeux')['metrics']
    assert m['prs_opened'] == m['prs_merged'] == 1 and m['requests_resolved'] == 0
    _, rows = aggregate([run()], {'run-a': {'calls': [call()]}}, [receipt()], request,
                        {'observations': {'123': merge | {'headRefOid': 'b'*40}}})
    assert [o['kind'] for o in rows[0]['outcomes']] == ['pr_published', 'pr_reviewed_merge']
    assert rows[0]['outcomes'][1]['verified'] is False


def messages(result=None):
    return [dict(role='assistant', tool_calls=json.dumps([{'id': 'call-1', 'function': {
        'name': 'mcp__gbox__set_request_status', 'arguments': json.dumps({'request_id': RID, 'status': 'done'})}}])),
        dict(role='tool', tool_name='mcp__gbox__set_request_status', tool_call_id='call-1', timestamp=140,
             content=json.dumps(result or {'request_id': RID, 'status': 'done', 'status_transition': {
                 'changed': True, 'previous': 'in_progress', 'status': 'done', 'audit_seq': 17, 'at': 140}}))]


def test_resolution_requires_paired_response_and_current_done_state():
    accepted = W.response_outcomes(messages())
    assert len(accepted) == 1
    assert W.response_outcomes(messages({'error': 'denied'})) == []
    assert W.response_outcomes(messages()[:1]) == []
    req = {RID: dict(id=RID, number=12, status='done', completed=140)}
    devices, rows = aggregate([run(recorded_outcomes=accepted)], {'run-a': {'calls': [call()]}}, requests=req)
    assert next(d for d in devices if d['id'] == 'sparkDeux')['metrics']['requests_resolved'] == 1
    devices, rows = aggregate([run(recorded_outcomes=accepted)], {'run-a': {'calls': [call()]}},
                             requests={RID: req[RID] | {'status': 'open'}})
    assert rows[0]['outcomes'] == []
    devices, _ = aggregate([run(recorded_outcomes=accepted)], {'run-a': {'calls': [call()]}},
                          requests={RID: req[RID] | {'completed': 190}})
    assert next(d for d in devices if d['id'] == 'sparkDeux')['metrics']['requests_resolved'] == 0
    _, rows = aggregate([run()], {'run-a': {'calls': [call()]}}, requests=req)
    assert rows[0]['outcomes'][0]['verified'] is False
    for result in ({'request_id': RID, 'status': 'done'}, {'request_id': RID, 'status': 'done',
            'status_transition': {'changed': False, 'previous': 'done', 'status': 'done', 'audit_seq': 18}}):
        outcomes = W.response_outcomes(messages(result))
        assert outcomes[0]['verified'] is False and outcomes[0]['kind'] == 'request_status'
        devices, _ = aggregate([run(recorded_outcomes=outcomes)], {'run-a': {'calls': [call()]}}, requests=req)
        assert next(d for d in devices if d['id'] == 'sparkDeux')['metrics']['requests_resolved'] == 0


def test_publication_attribution_does_not_use_global_configuration(monkeypatch):
    monkeypatch.setattr(W, 'load_runs', lambda *a: ([run()], []))
    monkeypatch.setattr(W, '_scan', lambda now: {'run-a': {'calls': [call()]}})
    monkeypatch.setattr(W, '_nodes', lambda: NODES)
    provenance = W.publication_provenance(RID, now=200)
    note = W.pr_note(provenance)
    assert 'Spark2' in note and 'gbox-sparkDeux' in note and 'shared-model' in note and 'run-a' in note
    assert 'not sole authorship' in note and 'Validation execution host' in note
    assert W.publication_provenance('0'*16, now=200)['status'] == 'unknown'


def test_all_active_runs_survive_history_limit(tmp_path, monkeypatch):
    home = tmp_path / 'hermes'; (home / 'cron').mkdir(parents=True)
    monkeypatch.setenv('GBOX_HERMES_HOME', str(home))
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path / 'dispatch'))
    monkeypatch.setattr(W, 'LIMIT', 2)
    db = sqlite3.connect(home / 'cron/executions.db')
    db.execute('CREATE TABLE executions(id TEXT, job_id TEXT, status TEXT, started_at TEXT, finished_at TEXT, error TEXT)')
    iso = lambda seconds: dt.datetime.fromtimestamp(seconds, dt.timezone.utc).isoformat()
    for i in range(15):
        db.execute('INSERT INTO executions VALUES(?,?,?,?,?,?)', (str(i), str(i), 'running', iso(90), None, None))
    for i in range(5):
        db.execute('INSERT INTO executions VALUES(?,?,?,?,?,?)', ('old'+str(i), str(i), 'completed', iso(110), iso(120), None))
    db.commit(); db.close()
    rows, notes = W.load_runs(100, 200)
    assert len([r for r in rows if r['state'] == 'running']) == 15
    assert len(rows) == 17 and any('limited' in n for n in notes)


def test_readonly_endpoint_validates_window_caches_and_does_not_dispatch(monkeypatch):
    app, seen = FastAPI(), []
    monkeypatch.setattr(W, 'summary', lambda store, window, now: seen.append(window) or {'generated_at': now, 'runs': []})
    W.install(app, object(), lambda: 'test')
    client = TestClient(app)
    assert client.get('/api/tasks/device-work').status_code == 200
    assert client.get('/api/tasks/device-work').status_code == 200
    assert seen == ['today']
    assert client.get('/api/tasks/device-work?window=anything').status_code == 422
    assert client.get('/api/tasks/device-work?window=7d').status_code == 200
    assert seen == ['today', '7d']
