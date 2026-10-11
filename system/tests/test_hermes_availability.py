import json

import pytest

from gbox import hermes_availability as availability


def quota(*limits):
    return {'success': True, 'data': {'limits': list(limits)}}


def test_live_credit_quota_and_mcp_windows_are_not_confused():
    observed = availability.quota_status(quota(
        {'type': 'CREDIT_LIMIT', 'unit': 3, 'number': 5, 'remaining': 2000, 'percentage': 0},
        {'type': 'CREDIT_LIMIT', 'unit': 6, 'number': 1, 'remaining': 7986, 'percentage': 20},
        {'type': 'TIME_LIMIT', 'remaining': 0, 'percentage': 100}), 1000)
    assert observed['status'] == 'quota_available' and len(observed['windows']) == 2


def test_weekly_and_five_hour_exhaustion_wait_for_both_epoch_resets():
    observed = availability.quota_status(quota(
        {'type': 'CREDIT_LIMIT', 'remaining': 0, 'nextResetTime': 1500000},
        {'type': 'CREDIT_LIMIT', 'percentage': 100, 'nextResetTime': 3000000}), 1000)
    assert observed['status'] == 'quota_wait' and observed['next_check_at'] == 3010


def test_missing_reset_uses_cheap_recheck_instead_of_guessing_five_hours():
    observed = availability.quota_status(quota({'type': 'CREDIT_LIMIT', 'remaining': 0}), 1000)
    assert observed['status'] == 'quota_wait' and observed['next_check_at'] == 1300
    assert availability.quota_status({'success': False}, 1000)['status'] == 'unknown'


@pytest.fixture
def lane(monkeypatch, tmp_path):
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    monkeypatch.setattr(availability.hermes_task_mode, '_home', lambda: tmp_path / 'isolated-hermes-home')
    path = tmp_path / 'zai-availability.json'
    path.write_text(json.dumps({'work_job_id': 'work', 'request_ids': ['report']}))
    job = {'id': 'work', 'enabled': False}
    calls = []
    monkeypatch.setattr(availability.hermes_task_mode, '_jobs', lambda: [job])
    monkeypatch.setattr(availability.hermes_task_mode, '_active', lambda _: False)
    monkeypatch.setattr(availability.hermes_task_mode, '_run', lambda *args: calls.append(args))
    monkeypatch.setattr(availability, '_native_pending', lambda _: False)
    monkeypatch.setattr(availability, '_credential', lambda: 'test-credential')
    return path, job, calls


def test_available_quota_requires_actual_completion_before_single_dispatch(lane, monkeypatch):
    path, job, calls = lane
    probes = []
    def respond(kind, key, body=None):
        probes.append(kind)
        return (200, quota({'type': 'CREDIT_LIMIT', 'remaining': 2000})) if kind == 'quota' else (
            200, {'choices': [{'message': {'content': 'OK'}}], 'usage': {'prompt_tokens': 8}})
    monkeypatch.setattr(availability, '_zai', respond)
    assert availability.tick(1000)['status'] == 'work_dispatched'
    assert calls == [('resume', 'work', '--run-now')] and probes == ['quota', 'probe']
    job['enabled'] = True
    assert availability.tick(1120)['status'] == 'work_queued_or_running'
    assert len(calls) == 1 and len(probes) == 2
    assert json.loads((path.parent / 'feedback.json').read_text())['zai_available_at'] == 1000


def test_exhausted_quota_never_calls_model_or_rearms_job(lane, monkeypatch):
    path, _, calls = lane
    kinds = []
    def respond(kind, key, body=None):
        kinds.append(kind)
        return 200, quota({'type': 'CREDIT_LIMIT', 'remaining': 0, 'nextResetTime': 5000000})
    monkeypatch.setattr(availability, '_zai', respond)
    assert availability.tick(1000)['status'] == 'quota_wait'
    assert availability.tick(1100)['status'] == 'quota_wait'
    assert kinds == ['quota'] and calls == []
    assert json.loads((path.parent / 'feedback.json').read_text())['cooldowns']['zai/glm-5.3'] == 5010


def test_successful_quota_get_does_not_hide_failed_model_probe(lane, monkeypatch):
    _, _, calls = lane
    monkeypatch.setattr(availability, '_zai', lambda kind, *args: (
        (200, quota({'type': 'CREDIT_LIMIT', 'remaining': 2000})) if kind == 'quota'
        else (429, {'error_code': '1308'})))
    result = availability.tick(1000)
    assert result['status'] == 'probe_wait' and result['probe_http'] == 429 and calls == []


def test_pending_native_analysis_does_not_burn_more_inference(lane, monkeypatch):
    monkeypatch.setattr(availability, '_native_pending', lambda _: True)
    monkeypatch.setattr(availability, '_credential', lambda: pytest.fail('No credential/probe needed'))
    assert availability.tick(1000)['status'] == 'waiting_for_native_analysis'


def test_probe_exception_never_exposes_credentials(lane, monkeypatch):
    def fail():
        raise RuntimeError('private-secret-value')
    monkeypatch.setattr(availability, '_credential', fail)
    result = availability.tick(1000)
    assert result['status'] == 'monitor_error' and 'private-secret-value' not in json.dumps(result)


def test_quota_get_rechecks_reset_card_without_calling_exhausted_model(lane, monkeypatch):
    _, _, calls = lane
    kinds = []
    def respond(kind, *args):
        kinds.append(kind)
        return 200, quota({'type': 'CREDIT_LIMIT', 'remaining': 0, 'nextResetTime': 5000000})
    monkeypatch.setattr(availability, '_zai', respond)
    assert availability.tick(1000)['status'] == 'quota_wait'
    assert availability.tick(1300)['status'] == 'quota_wait'
    assert kinds == ['quota', 'quota'] and not calls


def test_running_work_refreshes_account_quota_without_a_probe_or_duplicate(lane, monkeypatch):
    path, job, calls = lane
    job['enabled'] = True
    kinds = []
    def respond(kind, *args):
        kinds.append(kind)
        return 200, quota({'type': 'CREDIT_LIMIT', 'remaining': 12})
    monkeypatch.setattr(availability, '_zai', respond)
    result = availability.tick(1000)
    assert result['status'] == 'work_queued_or_running' and result['quota_status'] == 'quota_available'
    assert kinds == ['quota'] and not calls
    assert availability.tick(1100)['status'] == 'work_queued_or_running'
    assert kinds == ['quota'] and json.loads(path.read_text())['checked_at'] == 1000


def test_failed_quota_get_cannot_mark_previous_account_balance_fresh(lane, monkeypatch):
    path, _, _ = lane
    state = json.loads(path.read_text())
    state.update(checked_at=1, windows=[{'type': 'CREDIT_LIMIT', 'remaining': 2000}])
    path.write_text(json.dumps(state))
    monkeypatch.setattr(availability, '_zai', lambda *a: (503, {}))
    availability.tick(1000)
    state = json.loads(path.read_text())
    assert state['windows'] == [] and not state['quota_balance_known']


def test_old_probe_success_is_not_reported_as_part_of_a_new_exhausted_quota_check(lane, monkeypatch):
    path, _, calls = lane
    state = json.loads(path.read_text())
    state.update(probe_http=200, probe_usage={'prompt_tokens': 15}, dispatched_at=100)
    path.write_text(json.dumps(state))
    monkeypatch.setattr(availability, '_zai', lambda *args: (
        200, quota({'type': 'CREDIT_LIMIT', 'remaining': 0})))
    result = availability.tick(1000)
    assert result['status'] == 'quota_wait' and result['probe_http'] is None
    assert result['probe_usage'] == {} and not calls
    assert json.loads(path.read_text())['last_probe']['checked_at'] == 100


def test_completed_usage_tracks_actual_owner_cache_and_records_once(tmp_path, monkeypatch):
    import copy
    import sqlite3
    from gbox import hermes_tasks
    home = tmp_path / 'home'
    (home / 'cron').mkdir(parents=True)
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path / 'dispatch'))
    monkeypatch.setattr(availability.hermes_task_mode, '_home', lambda: home)
    started = '2026-10-10T21:50:00+00:00'
    stamp = hermes_tasks._stamp(started)
    rid, run_id, session_id = 'abcdef0123456789', 'a'*32, 'cron_work_today'
    with sqlite3.connect(home / 'cron/executions.db') as db:
        db.execute('CREATE TABLE executions (id TEXT,job_id TEXT,status TEXT,started_at TEXT,finished_at TEXT)')
        db.execute('INSERT INTO executions VALUES (?,?,?,?,?)',
                   (run_id, 'work', 'completed', started, '2026-10-10T21:50:30+00:00'))
    with sqlite3.connect(home / 'state.db') as db:
        db.execute('CREATE TABLE sessions (id TEXT,source TEXT,started_at REAL,ended_at REAL,model TEXT,'
                   'billing_provider TEXT,input_tokens INT,cache_read_tokens INT,cache_write_tokens INT,'
                   'output_tokens INT,reasoning_tokens INT,api_call_count INT)')
        db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                   (session_id, 'cron', stamp, stamp + 30, 'glm-5.3', 'zai', 100, 300, 20, 7, 0, 5))
        db.execute('CREATE TABLE session_model_usage (session_id TEXT,billing_provider TEXT,model TEXT,task TEXT,'
                   'input_tokens INT,cache_read_tokens INT,cache_write_tokens INT,output_tokens INT,'
                   'reasoning_tokens INT,api_call_count INT,estimated_cost_usd REAL)')
        db.executemany('INSERT INTO session_model_usage VALUES (?,?,?,?,?,?,?,?,?,?,?)', [
            (session_id, 'zai', 'glm-5.3', 'primary', 100, 300, 20, 7, 0, 5, 0.1),
            (session_id, 'nous', 'fixture-vision', 'vision', 17, 3, 0, 4, 0, 1, 0.2),
        ])
        db.execute('CREATE TABLE messages (id INTEGER PRIMARY KEY,session_id TEXT,role TEXT,content TEXT,'
                   'tool_name TEXT,tool_calls TEXT,tool_call_id TEXT)')
        args = {'request_id': rid, 'status': 'in_progress'}
        calls = json.dumps([{'id': 'confirmed-owner', 'function': {
            'name': 'tool_call', 'arguments': json.dumps({'calls': [
                {'name': 'mcp__gbox__set_request_status', 'arguments': args}]})}}])
        db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?,?)',
                   (1, session_id, 'assistant', '', None, calls, None))
        db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?,?)',
                   (2, session_id, 'tool', json.dumps({'result': json.dumps({'id': rid, 'status': 'in_progress'})}),
                    'mcp__gbox__set_request_status', None, 'confirmed-owner'))
    database_bytes = {p.name: p.read_bytes() for p in (home/'state.db', home/'cron/executions.db')}
    recorded, request = [], {'id': rid, 'status': 'in_progress', 'solved_by': {'service': 'earlier-reviewer'},
        'messages': [{'author': 'user', 'text': 'Original report'}],
        'metrics': {'tokens_in': 0, 'tokens_out': 0, 'tokens_detail': {'original_detail': 'preserve'},
                    'tools': {'terminal': 8}, 'turns': 6, 'agent_seconds': 42, 'duration_s': 19,
                    'files_changed': ['earlier.py']}}
    original = copy.deepcopy(request)
    def api(path, body=None):
        assert path in ('/api/requests/'+rid, '/api/requests/'+rid+'/metrics')
        if body is not None:
            assert path.endswith('/metrics')
            assert body['tools'] == {} and body['turns'] == 0 and 'duration_s' not in body
            recorded.append(copy.deepcopy(body))
            mt = request['metrics']
            mt['tokens_in'] += body['tokens_in']
            mt['tokens_out'] += body['tokens_out']
            for key, value in body['tokens_detail'].items():
                mt['tokens_detail'][key] = mt['tokens_detail'].get(key, 0)+value if isinstance(value, int) else value
        return copy.deepcopy(request)
    monkeypatch.setattr(availability, '_api', api)
    state = {'work_job_id': 'work', 'usage_request_id': '0000000000000000', 'status': 'quota_wait'}
    first = availability._completed_usage(state)
    assert first[0]['status'] == 'reconciled' and first[0]['tokens_in_added'] == 440
    second = availability._completed_usage(state)
    assert second[0]['status'] == 'already_recorded' and second[0]['tokens_in_added'] == 0
    assert len(recorded) == 3  # Two model records and one aggregate marker, never duplicate credits.
    assert request['metrics']['tokens_in'] == 440 and request['metrics']['tokens_out'] == 11
    rows = {value['task']: value for value in request['metrics']['tokens_detail'].values()
            if isinstance(value, dict) and value.get('task') in ('primary', 'vision')}
    assert rows['primary']['tokens_in_including_caches'] == 420 and rows['primary']['tokens_out'] == 7
    assert rows['primary']['input_cache_read'] == 300 and rows['primary']['input_cache_write'] == 20
    assert rows['primary']['api_call_count'] == 5
    assert rows['vision']['tokens_in_including_caches'] == 20 and rows['vision']['tokens_out'] == 4
    assert rows['vision']['api_call_count'] == 1 and rows['vision']['provider'] == 'nous'
    assert rows['vision']['actual_cost_usd'] is None
    for key in ('tools', 'turns', 'agent_seconds', 'duration_s', 'files_changed'):
        assert request['metrics'][key] == original['metrics'][key]
    for key in ('status', 'solved_by', 'messages'):
        assert request[key] == original[key]
    assert request['metrics']['tokens_detail']['original_detail'] == 'preserve'
    assert state['last_usage_request'] == rid and state['last_usage_session'] == session_id
    assert state['request_ids'] == [rid] and state['usage_request_id'] == '0000000000000000'
    assert state['status'] == 'quota_wait' and state['usage_reconciliation'] == second
    assert database_bytes == {p.name: p.read_bytes() for p in (home/'state.db', home/'cron/executions.db')}


def test_completed_usage_does_not_assign_deferred_or_unacknowledged_owners(tmp_path, monkeypatch):
    from gbox import hermes_accounting
    home = tmp_path/'home'
    monkeypatch.setattr(availability.hermes_task_mode, '_home', lambda: home)
    state = {'request_ids': ['0123456789abcdef'], 'last_usage_request': '0123456789abcdef',
             'last_usage_session': 'confirmed-earlier', 'usage_request_id': '0000000000000000'}
    calls = []
    def reconcile(**kwargs):
        calls.append(kwargs)
        return [{'status': 'deferred', 'request_id': 'fedcba9876543210', 'session_id': 'unconfirmed',
                 'tokens_in_added': 0, 'tokens_out_added': 0}] * 12
    monkeypatch.setattr(hermes_accounting, 'reconcile_completed', reconcile)
    result = availability._completed_usage(state)
    assert calls == [{'api': availability._api, 'home': home, 'limit': 10}]
    assert len(result) == 10 and len(state['usage_reconciliation']) == 10
    assert state['request_ids'] == ['0123456789abcdef']
    assert state['last_usage_request'] == '0123456789abcdef' and state['last_usage_session'] == 'confirmed-earlier'
