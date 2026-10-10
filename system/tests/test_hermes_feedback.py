import json
import sqlite3

from gbox import hermes_feedback


def test_only_actual_tool_errors_change_dispatch_feedback():
    assert not hermes_feedback.tool_error(json.dumps({'output': 'source says timed out; quota', 'error': None}))
    assert not hermes_feedback.tool_error(json.dumps({'messages': [{'text': 'last worker timed out'}]}))
    wrapped = '<untrusted_tool_result>Warning text\n\n' + json.dumps({'error': 'MCP call timed out after 300s'}) + '\n</untrusted_tool_result>'
    assert hermes_feedback.classify(hermes_feedback.tool_error(wrapped)) == 'worker_timeout'


def test_failure_lessons_are_durable_idempotent_and_model_specific(monkeypatch, tmp_path):
    home = tmp_path / 'home'; (home / 'cron').mkdir(parents=True)
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path / 'feedback'))
    (home / 'cron/jobs.json').write_text(json.dumps({'jobs': [
        {'id': 'quota', 'provider': 'zai', 'model': 'glm'},
        {'id': 'limited', 'provider': 'openrouter', 'model': 'google/flash'}]}))
    with sqlite3.connect(home / 'cron/executions.db') as db:
        db.execute('CREATE TABLE executions (id TEXT,job_id TEXT,status TEXT,started_at TEXT,finished_at TEXT,error TEXT)')
        db.executemany('INSERT INTO executions VALUES (?,?,?,?,?,?)', [
            ('quota-run', 'quota', 'failed', None, None, 'Usage limit reached for 5 hour'),
            ('rpm-run', 'limited', 'failed', None, None, 'HTTP 429 rate limit'),
            ('claim-run', 'missing', 'failed', None, None, 'Fire claim ownership lost')])
    first = hermes_feedback.scan(home=home, now=1000)
    assert first['new_lessons'] == 3
    assert first['cooldowns']['zai/glm'] == 19000
    assert first['cooldowns']['openrouter/google/flash'] == 1900
    assert 'openrouter/anthropic/opus' not in first['cooldowns']
    assert {l['category'] for l in first['lessons']} == {'quota', 'rate_limit', 'scheduler_claim'}
    second = hermes_feedback.scan(home=home, now=1100)
    assert second['new_lessons'] == 0 and len(second['lessons']) == 3


def test_completed_verification_without_source_edits_is_not_a_missing_publication(monkeypatch, tmp_path):
    home = tmp_path / 'home'; (home / 'cron').mkdir(parents=True)
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path / 'feedback'))
    with sqlite3.connect(home / 'cron/executions.db') as db:
        db.execute('CREATE TABLE executions (id TEXT,job_id TEXT,status TEXT,started_at TEXT,finished_at TEXT,error TEXT)')
        db.execute('INSERT INTO executions VALUES (?,?,?,?,?,?)', ('verified', 'verify', 'completed', '2026-10-10T10:00:00+00:00', None, None))
    started = hermes_feedback._stamp('2026-10-10T10:00:00+00:00')
    with sqlite3.connect(home / 'state.db') as db:
        db.execute('CREATE TABLE sessions (id TEXT,source TEXT,started_at REAL,model TEXT,billing_provider TEXT,output_tokens INT,api_call_count INT)')
        db.execute('CREATE TABLE messages (session_id TEXT,role TEXT,content TEXT,tool_name TEXT)')
        db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?)', ('cron_verify_today', 'cron', started, 'kimi', 'ollama-cloud', 100, 5))
        db.execute('INSERT INTO messages VALUES (?,?,?,?)', ('cron_verify_today', 'tool', '1 passed', 'terminal'))
    assert hermes_feedback.scan(home=home)['lessons'] == []


def test_route_rotation_waits_for_running_agent_and_restores_expired_routes(monkeypatch, tmp_path):
    from types import SimpleNamespace
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    routes = [{'provider': 'a', 'model': 'first'}, {'provider': 'b', 'model': 'second'}, {'provider': 'c', 'model': 'limited'}]
    data = {'routes': routes, 'cooldowns': {'c/limited': 2000}, 'new_lessons': 1, 'rotation_pending': True}
    config = {'cron': {'model_provider': 'a', 'model': 'first'}, 'fallback_providers': routes[1:]}
    busy = [True]
    path = tmp_path / 'feedback.json'
    def scan():
        path.write_text(json.dumps(data))
        return data
    def run(args, **_):
        key, value = args[-2:]
        if key == 'fallback_providers': config[key] = json.loads(value)
        else: config['cron'][key.split('.')[1]] = value
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(hermes_feedback, 'scan', scan)
    monkeypatch.setattr(hermes_feedback.hermes_task_mode, '_config', lambda: config)
    monkeypatch.setattr(hermes_feedback.hermes_task_mode, '_jobs', lambda: [{'id': 'live'}])
    monkeypatch.setattr(hermes_feedback.hermes_task_mode, '_active', lambda _: busy[0])
    monkeypatch.setattr(hermes_feedback.subprocess, 'run', run)
    assert hermes_feedback.adjust_routes()['route'] == routes[0]
    assert json.loads(path.read_text())['rotation_pending']
    assert config['fallback_providers'] == [routes[1]]
    busy[0] = False
    assert hermes_feedback.adjust_routes()['route'] == routes[1]
    data.update(cooldowns={}, rotation_pending=False)
    hermes_feedback.adjust_routes()
    assert routes[2] in config['fallback_providers']
