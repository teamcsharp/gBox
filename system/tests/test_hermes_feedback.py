import json
import sqlite3

from gbox import hermes_feedback


def test_only_actual_tool_errors_change_dispatch_feedback():
    assert not hermes_feedback.tool_error(json.dumps({'output': 'source says timed out; quota', 'error': None}))
    assert not hermes_feedback.tool_error(json.dumps({'messages': [{'text': 'last worker timed out'}]}))
    wrapped = '<untrusted_tool_result>Warning text\n\n' + json.dumps({'error': 'MCP call timed out after 300s'}) + '\n</untrusted_tool_result>'
    assert hermes_feedback.classify(hermes_feedback.tool_error(wrapped)) == 'worker_timeout'
    failure = {'error': json.dumps({'error': "FileNotFoundError: '/worktree/gbox-data/hermes-dispatch/ticket.json'"})}
    assert hermes_feedback.classify(hermes_feedback.tool_error(json.dumps(failure))) == 'workspace_state'


def test_mcp_repair_prevents_worktree_shadowing_without_changing_operator_choice(monkeypatch, tmp_path):
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    original = {'command': '/venv/bin/python', 'args': ['-m', 'gbox', 'mcp'],
                'env': {'PYTHONPATH': '/worktree', 'GBOX_OPERATOR_WORKER': 'i9-NUC'}, 'tools': {'include': ['get_request']}}
    fixed = hermes_feedback.canonical_mcp({'mcp_servers': {'gbox': original}})
    assert fixed['args'][0] == '-P'
    assert fixed['env']['GBOX_HERMES_DISPATCH_STATE'] == str(tmp_path)
    assert fixed['env']['GBOX_OPERATOR_WORKER'] == 'i9-NUC' and fixed['tools'] == original['tools']
    assert hermes_feedback.canonical_mcp({'mcp_servers': {'gbox': fixed}}) is None


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
    assert first['cooldowns']['zai/glm'] == 1300
    assert first['cooldowns']['openrouter/google/flash'] == 1060
    assert first['cooldown_details']['zai/glm']['source'] == 'scheduler_backoff'
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
    finalized = []
    def finalize():
        finalized.append(True)
        return {'checked_runs': 1, 'tokens_in_added': 42, 'tokens_out_added': 3}
    monkeypatch.setattr(hermes_feedback, 'finalize_usage', finalize)
    monkeypatch.setattr(hermes_feedback, 'finalize_merges', lambda: {'posted': []})
    monkeypatch.setattr(hermes_feedback, 'finalize_summaries', lambda: {'posted': []})
    monkeypatch.setattr(hermes_feedback.hermes_task_mode, '_config', lambda: config)
    monkeypatch.setattr(hermes_feedback.hermes_task_mode, '_jobs', lambda: [{'id': 'live'}])
    monkeypatch.setattr(hermes_feedback.hermes_task_mode, '_active', lambda _: busy[0])
    monkeypatch.setattr(hermes_feedback.subprocess, 'run', run)
    held = hermes_feedback.adjust_routes()
    assert held['route'] == routes[0]
    assert finalized == [True] and held['completed_usage']['tokens_in_added'] == 42
    assert json.loads(path.read_text())['completed_usage'] == held['completed_usage']
    assert json.loads(path.read_text())['rotation_pending']
    assert config['fallback_providers'] == routes[1:]
    busy[0] = False
    assert hermes_feedback.adjust_routes()['route'] == routes[1]
    assert routes[2] not in config['fallback_providers']
    data.update(cooldowns={}, rotation_pending=False)
    hermes_feedback.adjust_routes()
    assert routes[2] in config['fallback_providers']


def test_accounting_transport_failure_does_not_interrupt_dispatch_monitor(monkeypatch):
    from gbox import hermes_accounting
    def fail(**_kwargs):
        raise OSError('private transport information must remain private')
    monkeypatch.setattr(hermes_accounting, 'reconcile_completed', fail)
    assert hermes_feedback.finalize_usage() == {'status': 'deferred', 'error_type': 'OSError'}


def test_run_summary_failure_does_not_interrupt_dispatch_monitor(monkeypatch):
    from gbox import hermes_summaries
    def fail(*_args, **_kwargs):
        raise OSError('inbox unreachable')
    monkeypatch.setattr(hermes_summaries, 'reconcile', fail)
    assert hermes_feedback.finalize_summaries() == {'status': 'deferred', 'error_type': 'OSError'}


def test_native_capture_and_checkpoint_failures_have_distinct_recovery_lessons():
    failures = {
        'RuntimeError: the game window is covered by another app; bring gBox forward': 'capture_occlusion',
        "RuntimeError: the game window isn't open": 'capture_occlusion',
        'NotReadableError: Could not start video source': 'capture_occlusion',
        'Saved checkpoint container could not be validated: truncated RZIP frame': 'checkpoint_container',
        'saved checkpoint container exceeds inspection budget': 'checkpoint_container',
        'saved checkpoint contains no core state': 'checkpoint_container',
        'saved checkpoint is empty': 'checkpoint_container',
    }
    for error, category in failures.items():
        assert hermes_feedback.classify(error) == category
        assert category in hermes_feedback.ADVICE
    assert not hermes_feedback.tool_error(json.dumps({'output': list(failures), 'error': None}))
    assert hermes_feedback.classify('NotReadableError: microphone is busy') == 'other'
    # Provider errors keep their existing measured cooldown policy.
    assert hermes_feedback.classify('HTTP 429 rate limit: game window is covered by another app') == 'rate_limit'


def test_native_failure_lessons_do_not_cool_down_the_inference_provider(monkeypatch, tmp_path):
    home = tmp_path / 'home'
    (home / 'cron').mkdir(parents=True)
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path / 'feedback'))
    (home / 'cron/jobs.json').write_text(json.dumps({'jobs': [
        {'id': 'capture', 'provider': 'nous', 'model': 'opus'},
        {'id': 'checkpoint', 'provider': 'zai', 'model': 'glm'}]}))
    with sqlite3.connect(home / 'cron/executions.db') as db:
        db.execute('CREATE TABLE executions (id TEXT,job_id TEXT,status TEXT,started_at TEXT,finished_at TEXT,error TEXT)')
        db.executemany('INSERT INTO executions VALUES (?,?,?,?,?,?)', [
            ('capture-run', 'capture', 'failed', None, None,
             'RuntimeError: the game window is covered by another app'),
            ('checkpoint-run', 'checkpoint', 'failed', None, None,
             'Saved checkpoint container could not be validated: truncated RZIP frame')])
    first = hermes_feedback.scan(home=home, now=1000)
    assert first['cooldowns'] == {}
    assert {lesson['category'] for lesson in first['lessons']} == {'capture_occlusion', 'checkpoint_container'}
    assert all('operator PC' in lesson['advice'] or 'original' in lesson['advice'] for lesson in first['lessons'])
    second = hermes_feedback.scan(home=home, now=1100)
    assert second['new_lessons'] == 0 and len(second['lessons']) == 2
