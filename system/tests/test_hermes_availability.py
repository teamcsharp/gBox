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


def test_completed_usage_tracks_actual_owner_cache_and_records_once(tmp_path, monkeypatch):
    import sqlite3
    from gbox import hermes_tasks
    home = tmp_path / 'home'
    (home / 'cron').mkdir(parents=True)
    monkeypatch.setattr(availability.hermes_task_mode, '_home', lambda: home)
    started = '2026-10-10T21:50:00+00:00'
    stamp = hermes_tasks._stamp(started)
    rid = 'abcdef0123456789'
    with sqlite3.connect(home / 'cron/executions.db') as db:
        db.execute('CREATE TABLE executions (job_id TEXT,status TEXT,started_at TEXT)')
        db.execute('INSERT INTO executions VALUES (?,?,?)', ('work', 'completed', started))
    with sqlite3.connect(home / 'state.db') as db:
        db.execute('CREATE TABLE sessions (id TEXT,source TEXT,started_at REAL,ended_at REAL,model TEXT,'
                   'billing_provider TEXT,input_tokens INT,cache_read_tokens INT,cache_write_tokens INT,'
                   'output_tokens INT,api_call_count INT)')
        db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                   ('cron_work_today', 'cron', stamp, stamp + 30, 'glm-5.3', 'zai', 100, 300, 20, 7, 5))
        db.execute('CREATE TABLE messages (id INTEGER PRIMARY KEY,session_id TEXT,role TEXT,content TEXT,'
                   'tool_name TEXT,tool_calls TEXT)')
        args = {'request_id': rid, 'status': 'in_progress'}
        calls = json.dumps([{'function': {'name': 'mcp_gbox_set_request_status', 'arguments': json.dumps(args)}}])
        db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)',
                   (1, 'cron_work_today', 'assistant', '', None, calls))
        db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)',
                   (2, 'cron_work_today', 'tool', '{}', 'mcp_gbox_set_request_status', None))
    recorded, request = [], {'metrics': {'tokens_detail': {}}}
    def api(path, body=None):
        assert rid in path
        if body is not None:
            recorded.append(body)
            request['metrics']['tokens_detail'].update(body['tokens_detail'])
        return request
    monkeypatch.setattr(availability, '_api', api)
    state = {'work_job_id': 'work', 'usage_request_id': '0000000000000000'}
    availability._completed_usage(state)
    availability._completed_usage(state)
    assert len(recorded) == 1
    measured = recorded[0]
    assert measured['tokens_in'] == 420 and measured['tokens_out'] == 7
    assert measured['duration_s'] == 30 and measured['turns'] == 5
    assert measured['provider'] == 'zai' and measured['tools'] == {'mcp_gbox_set_request_status': 1}
    assert state['last_usage_request'] == rid and rid in state['request_ids']
