import json
import sqlite3

import pytest

from gbox import hermes_feedback, hermes_recovery as recovery

RID = 'abcdef0123456789'


@pytest.fixture
def lane(monkeypatch, tmp_path):
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    job = {'id': 'job', 'name': 'gBox emulation investigation #7', 'enabled': False,
           'schedule': {'kind': 'once'}, 'last_status': 'error'}
    session = {'id': 'session', 'model': 'limited', 'billing_provider': 'zai'}
    recovery.checkpoint({'id': 'failure'}, job, session, [RID], now=1000)
    monkeypatch.setattr(recovery.hermes_task_mode, '_jobs', lambda: [job])
    monkeypatch.setattr(recovery.hermes_task_mode, '_active', lambda _: False)
    monkeypatch.setattr(recovery.hermes_task_mode, '_config', lambda: {
        'cron': {'model_provider': 'deepseek', 'model': 'available'}})
    monkeypatch.setattr(recovery, '_active_requests', lambda: set())
    monkeypatch.setattr(recovery, '_latest_run', lambda _: 'failure')
    monkeypatch.setattr(recovery, '_request_state', lambda _: 'in_progress')
    calls = []
    monkeypatch.setattr(recovery.hermes_task_mode, '_run', lambda *a: calls.append(a))
    return job, session, calls, tmp_path


def test_failed_occurrence_resumes_same_job_with_continuity_exactly_once(lane):
    job, _, calls, _ = lane
    first = recovery.recover({}, now=1100)
    assert first == {'status': 'resumed_checkpoint', 'job_id': 'job', 'request_ids': [RID]}
    assert calls == [('edit', 'job', '--continuity'), ('resume', 'job', '--run-now')]
    recovery.recover({}, now=1101)
    assert len(calls) == 2 and recovery.status()[0]['resume_count'] == 1


def test_pinned_job_is_never_unpinned_for_another_provider(lane):
    job, _, calls, _ = lane
    job.update(provider='zai', model='limited')
    assert recovery.recover({}, now=1100)['status'] == 'waiting_pinned_provider'
    assert not calls


def test_no_available_route_defers_without_launch_then_recovers(lane):
    _, _, calls, _ = lane
    assert recovery.recover({'cooldowns': {'deepseek/available': 2000}}, now=1100)['status'] == 'waiting_provider'
    assert not calls
    assert recovery.recover({}, now=2001)['status'] == 'resumed_checkpoint'


@pytest.mark.parametrize('status', ['done', 'cancelled', None])
def test_closed_or_unknown_ticket_is_not_reopened(lane, monkeypatch, status):
    _, _, calls, _ = lane
    monkeypatch.setattr(recovery, '_request_state', lambda _: status)
    recovery.recover({}, now=1100)
    assert not calls


def test_ticket_owned_elsewhere_and_live_disabled_one_shot_cannot_duplicate(lane, monkeypatch):
    _, _, calls, _ = lane
    monkeypatch.setattr(recovery, '_active_requests', lambda: {RID})
    recovery.recover({}, now=1100)
    assert recovery.status()[0]['status'] == 'request_owned_by_active_run' and not calls
    monkeypatch.setattr(recovery, '_active_requests', lambda: set())
    monkeypatch.setattr(recovery.hermes_task_mode, '_active', lambda _: True)
    recovery.recover({}, now=1101)
    monkeypatch.setattr(recovery.hermes_task_mode, '_active', lambda _: False)
    recovery.recover({}, now=1102)
    assert not calls and recovery.status()[0]['status'] == 'resumed'


def test_resume_timeout_is_uncertain_and_never_reissued(lane, monkeypatch):
    _, _, calls, path = lane
    def fail(*args):
        calls.append(args)
        raise RuntimeError('private-key-in-subprocess-message')
    monkeypatch.setattr(recovery.hermes_task_mode, '_run', fail)
    assert recovery.recover({}, now=1100)['status'] == 'dispatch_uncertain'
    recovery.recover({}, now=1101)
    assert len(calls) == 1
    assert 'private-key' not in (path / 'provider-recovery.json').read_text()


def test_three_resumes_per_day_bound_repeated_quota_failures(lane, monkeypatch):
    job, session, calls, _ = lane
    for index in range(3):
        recovery.checkpoint({'id': str(index)}, job, session, [RID], now=1100 + index)
        # Each observation is the latest real failed occurrence of the same job.
        monkeypatch.setattr(recovery, '_latest_run', lambda _, value=str(index): value)
        assert recovery.recover({}, now=1100 + index)['status'] == 'resumed_checkpoint'
    recovery.checkpoint({'id': 'fourth'}, job, session, [RID], now=1200)
    monkeypatch.setattr(recovery, '_latest_run', lambda _: 'fourth')
    assert recovery.recover({}, now=1200)['status'] == 'recovery_budget_exhausted'
    assert len(calls) == 6
    assert recovery.recover({}, now=1200 + 86400)['status'] == 'resumed_checkpoint'


def test_api_failure_preserves_checkpoint_without_consuming_retry_budget(lane, monkeypatch):
    _, _, calls, _ = lane
    def fail(_):
        raise OSError('unreachable')
    monkeypatch.setattr(recovery, '_request_state', fail)
    recovery.recover({}, now=1100)
    assert not calls and recovery.status()[0]['resume_count'] == 0
    assert recovery.status()[0]['status'] == 'request_verification_deferred'


def test_no_agent_or_discovery_only_run_does_not_claim_recovery(lane):
    job, session, _, _ = lane
    recovery.checkpoint({'id': 'other'}, job | {'id': 'script', 'no_agent': True}, session, [RID], now=1200)
    recovery.checkpoint({'id': 'other'}, job | {'id': 'reader'}, session, [], now=1200)
    assert len(recovery.status()) == 1


def test_completed_later_occurrence_supersedes_an_old_quota_checkpoint(lane, monkeypatch):
    _, _, calls, _ = lane
    monkeypatch.setattr(recovery, '_latest_run', lambda _: 'later-completed-run')
    recovery.recover({}, now=1100)
    assert not calls and recovery.status()[0]['status'] == 'superseded'


def test_actual_failed_quota_session_saves_owner_and_provider_retry_once(monkeypatch, tmp_path):
    home = tmp_path / 'home'
    (home / 'cron').mkdir(parents=True)
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path / 'dispatch'))
    job = {'id': 'job', 'name': 'gBox emulation investigation #7', 'schedule': {'kind': 'once'}}
    (home / 'cron/jobs.json').write_text(json.dumps({'jobs': [job]}))
    started = '1970-01-01T00:16:40+00:00'
    finished = '1970-01-01T00:17:00+00:00'
    with sqlite3.connect(home / 'cron/executions.db') as db:
        db.execute('CREATE TABLE executions (id TEXT,job_id TEXT,status TEXT,started_at TEXT,finished_at TEXT,error TEXT)')
        db.execute('INSERT INTO executions VALUES (?,?,?,?,?,?)', ('failure', 'job', 'failed', started, finished,
            json.dumps({'error': {'code': '1308'}, 'headers': {'Retry-After': '90'}})))
    with sqlite3.connect(home / 'state.db') as db:
        db.execute('CREATE TABLE sessions (id TEXT,source TEXT,started_at REAL,model TEXT,billing_provider TEXT,output_tokens INT,api_call_count INT)')
        db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?)', ('cron_job_today', 'cron', 1000, 'glm', 'zai', 9, 3))
        db.execute('CREATE TABLE messages (id INTEGER,session_id TEXT,role TEXT,content TEXT,tool_name TEXT,tool_calls TEXT)')
        calls = [{'function': {'name': 'mcp_gbox_set_request_status',
                              'arguments': json.dumps({'request_id': RID, 'status': 'in_progress'})}}]
        db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)', (1, 'cron_job_today', 'assistant', '', None, json.dumps(calls)))
    first = hermes_feedback.scan(home=home, now=1030)
    assert first['cooldowns']['zai/glm'] == 1111
    assert first['cooldown_details']['zai/glm']['source'] == 'provider_retry_metadata'
    assert recovery.status()[0]['request_ids'] == [RID]
    assert hermes_feedback.scan(home=home, now=1040)['new_lessons'] == 0
    assert len(recovery.status()) == 1


def test_tool_quota_is_a_lesson_without_cooling_inference_provider(monkeypatch, tmp_path):
    home = tmp_path / 'home'
    (home / 'cron').mkdir(parents=True)
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path / 'dispatch'))
    with sqlite3.connect(home / 'cron/executions.db') as db:
        db.execute('CREATE TABLE executions (id TEXT,job_id TEXT,status TEXT,started_at TEXT,finished_at TEXT,error TEXT)')
        db.execute('INSERT INTO executions VALUES (?,?,?,?,?,?)', ('completed', 'job', 'completed',
                   '1970-01-01T00:16:40+00:00', None, None))
    with sqlite3.connect(home / 'state.db') as db:
        db.execute('CREATE TABLE sessions (id TEXT,source TEXT,started_at REAL,model TEXT,billing_provider TEXT,output_tokens INT,api_call_count INT)')
        db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?)', ('cron_job_today', 'cron', 1000, 'glm', 'zai', 9, 3))
        db.execute('CREATE TABLE messages (session_id TEXT,role TEXT,content TEXT,tool_name TEXT)')
        db.execute('INSERT INTO messages VALUES (?,?,?,?)', ('cron_job_today', 'tool',
                   json.dumps({'error': 'Remote screenshot service usage limit reached'}), 'screenshot'))
    result = hermes_feedback.scan(home=home, now=1030)
    assert result['lessons'][0]['category'] == 'quota' and not result['cooldowns']
