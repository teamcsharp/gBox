"""On the local route the queue dispatches only small, well-scoped work, one run at a time, with a tighter prompt;
big tasks stay queued for paid routes; local runs publish labelled draft PRs with a test summary."""
import json

from gbox import hermes_local, hermes_work_queue as q
from gbox.config import HermesLocalConfig

S = HermesLocalConfig(proxy_url='http://127.0.0.1:8765/api/llm/local/v1')
P = 'c' * 16


def test_dispatch_size_policy():
    size = lambda item, request=None: hermes_local.dispatch_size(item, request)['size']  # noqa: E731
    assert size({'lane': 'favorite', 'stages': {}}) == 'small'                         # inventory
    assert size({'lane': 'favorite', 'stages': {'inventory': {'status': 'verified'}}}) == 'large'   # analysis
    assert size({'lane': 'inbox', 'repair': True}, {'title': 'Fix typo'}) == 'large'
    assert size({'lane': 'inbox', 'session_observer': True}, {'title': 'Fix typo'}) == 'large'
    assert size({'lane': 'inbox', 'launch_failure': True}, {'title': 'Fix typo'}) == 'large'
    assert size({'lane': 'inbox'}, {'title': 'Fix the typo in the Tasks tooltip'}) == 'small'
    assert size({'lane': 'inbox'}, {'title': 'Run the flaky test_cache test and fix it'}) == 'small'
    assert size({'lane': 'inbox'}, {'title': 'Write the GTA3 model writer'}) == 'large'
    assert size({'lane': 'inbox'}, {'title': 'Fix black screen in Dolphin'}) == 'large'
    assert size({'lane': 'inbox'}, {'title': 'Tidy', 'body': 'edit a.py, b.py and c.js'}) == 'large'
    assert size({'lane': 'inbox'}, {'title': 'Adjust x', 'body': 'in gbox/inbox.py'}) == 'small'
    assert size({'lane': 'inbox'}, {'title': 'Something vague'}) == 'large'
    assert size({'lane': 'inbox', 'attempts': 3}, {'title': 'Fix typo'}) == 'large'
    assert size({'lane': 'inbox'}, {'title': 'Fix typo', 'body': 'x' * 3000}) == 'large'
    assert size({'lane': 'inbox'}, {'title': 'Write the reader', 'context': {'hermes_size': 'small'}}) == 'small'


def test_local_prompt_tightens_the_budget():
    base = 'Assigned queue task. Use a 45-tool-call work budget with the final 10 calls reserved for tests.'
    out = hermes_local.local_prompt(base, S)
    assert out.startswith('LOCAL MODEL RUN (spark-local · gpt-oss:20b')
    assert 'Use a 20-tool-call work budget with the final 6 calls' in out and '45-tool-call' not in out
    assert 'at most one source file' in out


def test_local_pr_note_has_the_test_summary():
    head, summary = hermes_local.pr_note(['===== 12 passed, 1 skipped in 3.2s =====', '3 passed in 1s'], S)
    assert 'local model' in head and summary == 'Test summary: 15 passed, 1 skipped'
    assert hermes_local.pr_note([], S)[1] == 'Test summary: no Python tests ran'


def _env(monkeypatch, tmp_path, reqs, favorites, gate=None):
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    monkeypatch.setenv('GBOX_CONFIG', str(tmp_path / 'missing.toml'))
    q._save({'version': 1, 'items': {}, 'parent_request_id': P, 'last_lane': 'inbox'})
    jobs = [{'id': 'controller', 'name': q.mode.NAME, 'enabled': True, 'no_agent': True}]
    monkeypatch.setattr(q.mode, '_job', lambda: jobs[0])
    monkeypatch.setattr(q.mode, '_jobs', lambda: jobs)
    monkeypatch.setattr(q.mode, '_config', lambda: {'cron': {'model_provider': 'spark-local', 'model': 'gpt-oss:20b',
                                                             'max_parallel_jobs': 4}})
    monkeypatch.setattr(q, '_executions', lambda: ({}, set()))
    monkeypatch.setattr(q, '_native_jobs', lambda: [])
    from gbox import hermes_recovery
    monkeypatch.setattr(hermes_recovery, '_active_requests', lambda: set())
    monkeypatch.setattr(q.mode, '_handoff', lambda: ' Use a 45-tool-call work budget with the final 10 calls reserved.')

    def api(path, body=None):
        if path == '/api/llm/local/status':
            return {'enabled': True, 'gated': gate}
        if path == '/api/chat':
            return []
        if path == '/api/favorites':
            return {'count': len(favorites), 'items': favorites}
        if path == '/api/requests' and body is None:
            return reqs
        raise AssertionError(path)
    monkeypatch.setattr(q, '_api', api)
    calls = []

    def run(*args):
        calls.append(args)
        if args[0] == 'create':
            jobs.append({'id': 'j' + str(len(jobs)), 'name': args[args.index('--name') + 1], 'enabled': True,
                         'schedule': {'kind': 'once'}})
    monkeypatch.setattr(q.mode, '_run', run)
    return calls


def test_local_route_dispatches_one_small_task_and_leaves_big_work_queued(monkeypatch, tmp_path):
    reqs = [{'id': P, 'number': 1, 'title': 'parent', 'status': 'open'},
            {'id': 'b' * 16, 'number': 5, 'title': 'Write the Def Jam model writer', 'status': 'open', 'created': 1},
            {'id': 'd' * 16, 'number': 6, 'title': 'Fix the typo in the inbox tooltip', 'status': 'open', 'created': 2}]
    calls = _env(monkeypatch, tmp_path, reqs, [])
    out = q.tick(now=1000)
    assert out['status'] == 'dispatched' and out['capacity'] == 1 and out['local_route']
    assert [d['request_id'] for d in out['dispatched']] == ['d' * 16] and out['deferred_for_paid_route'] == 1
    create = calls[0]
    prompt = create[2]
    assert prompt.startswith('LOCAL MODEL RUN') and 'request #6' in prompt
    assert 'Use a 20-tool-call work budget with the final 6 calls' in prompt
    assert create[create.index('--reasoning-effort') + 1] == 'medium'
    item = q._read()['items']['inbox:' + 'd' * 16]
    assert item['local'] is True and item['route'] == {'provider': 'spark-local', 'model': 'gpt-oss:20b'}
    assert hermes_local.run_was_local('d' * 16)


def test_local_route_waits_while_the_operator_plays(monkeypatch, tmp_path):
    reqs = [{'id': P, 'number': 1, 'title': 'parent', 'status': 'open'},
            {'id': 'd' * 16, 'number': 6, 'title': 'Fix the typo in the tooltip', 'status': 'open'}]
    calls = _env(monkeypatch, tmp_path, reqs, [], gate='the operator is playing Soulcalibur on the Spark')
    out = q.tick(now=1000)
    assert out['status'] == 'waiting_for_operator' and 'Soulcalibur' in out['reason'] and calls == []


def test_triage_priority_ranks_after_the_operator_list(monkeypatch, tmp_path):
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    q._save({'version': 1, 'items': {}, 'priority': ['g1']})
    q.add_triage_priority(['r2', 'r1'])
    data = q._read()
    assert q.priority_rank({'game_id': 'g1'}, data) == 0
    assert q.priority_rank({'request_id': 'r2'}, data) == 1 and q.priority_rank({'request_id': 'r1'}, data) == 2
    assert q.priority_rank({'request_id': 'zz'}, data) == 3
    assert json.loads((tmp_path / 'work-queue.json').read_text())['priority'] == ['g1']   # operator list untouched


def test_publish_marks_a_local_run_pr(monkeypatch, tmp_path):
    from gbox import hermes_delivery
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    monkeypatch.setenv('GBOX_CONFIG', str(tmp_path / 'missing.toml'))
    seen = []

    class Done:
        returncode = 0
    monkeypatch.setattr(hermes_delivery.subprocess, 'run', lambda args, **kw: seen.append(args) or Done())
    out = hermes_delivery._mark_local(tmp_path, 42, existed=True)
    assert out == {'label': 'local model', 'labelled': True, 'draft': True}
    assert seen[0][:3] == ['gh', 'api', 'repos/teamcsharp/gBox/issues/42/labels'] and 'labels[]=local model' in seen[0]
    assert seen[1] == ['gh', 'pr', 'ready', '42', '--repo', 'teamcsharp/gBox', '--undo']


def test_emulation_investigations_wait_for_a_paid_route(monkeypatch, tmp_path):
    import pytest
    from gbox import hermes_task_mode
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    monkeypatch.setenv('GBOX_CONFIG', str(tmp_path / 'missing.toml'))
    (tmp_path / 'feedback.json').write_text(json.dumps({'current_route': {'provider': 'spark-local', 'model': 'gpt-oss:20b'}}))

    def no_job(*args):
        raise AssertionError('no job may be created')
    monkeypatch.setattr(hermes_task_mode, '_run', no_job)
    with pytest.raises(RuntimeError, match='queued for a paid route'):
        hermes_task_mode.dispatch_request('a' * 16, 7)
