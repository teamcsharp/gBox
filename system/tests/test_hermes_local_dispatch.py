"""On the local route the queue dispatches only small, well-scoped work, one run at a time, with a tighter prompt;
big tasks stay queued for paid routes; local runs publish labelled draft PRs with a test summary."""
import json
import pytest

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


def test_reused_local_job_replaces_stale_reasoning_effort(monkeypatch, tmp_path):
    rid = 'd' * 16
    reqs = [{'id': rid, 'number': 6, 'title': 'Fix typo', 'status': 'open'}]
    calls = _env(monkeypatch, tmp_path, reqs, [])
    q.mode._jobs().append({'id': 'old-job', 'name': 'gBox queue inbox ' + rid,
                          'enabled': False, 'reasoning_effort': 'max'})
    assert q.tick(now=1000)['status'] == 'dispatched'
    edit = next(c for c in calls if c[0] == 'edit')
    assert edit[edit.index('--reasoning-effort') + 1] == 'medium'
    assert calls[-1] == ('resume', 'old-job', '--run-now')


def test_dedicated_local_route_dispatches_large_inbox_work_and_respects_checkbox(monkeypatch, tmp_path):
    reqs = [{'id': P, 'number': 1, 'title': 'parent', 'status': 'open'},
            {'id': 'b' * 16, 'number': 5, 'title': 'Write the verified unlock writer', 'status': 'open'},
            {'id': 'd' * 16, 'number': 6, 'title': 'Fix the emulator launch', 'status': 'open'}]
    calls = _env(monkeypatch, tmp_path, reqs, [])
    dedicated = S.model_copy(update={'host_name': 'sparkDeux', 'max_parallel_jobs': 2,
                                     'allow_large_tasks': True, 'shared_with_games': False})
    monkeypatch.setattr(hermes_local, 'settings', lambda: dedicated)
    out = q.tick(now=1000)
    assert len(out['dispatched']) == 2 and out['capacity'] == 2 and out['deferred_for_paid_route'] == 0
    assert all('one concrete, reviewable milestone' in c[2] for c in calls)
    monkeypatch.setattr(q.mode, '_job', lambda: {'enabled': False, 'no_agent': True})
    assert q.tick(now=1100)['status'] == 'disabled_or_legacy_controller' and len(calls) == 2


@pytest.mark.parametrize('global_limit', [4, 5])
def test_pool_pins_each_host_and_keeps_durable_handoff(monkeypatch, tmp_path, global_limit):
    from gbox import hermes_pool as pool
    reqs = [{'id': P, 'number': 1, 'title': 'parent', 'status': 'open'}] + [
        {'id': str(n)*16, 'number': n, 'title': 'Fix typo' if n == 1 else 'Implement verified game reader', 'status': 'open'}
        for n in range(1, 7)]
    calls = _env(monkeypatch, tmp_path, reqs, [])
    config = q.mode._config()
    config['cron']['max_parallel_jobs'] = global_limit
    monkeypatch.setattr(q.mode, '_config', lambda: config)
    s = S.model_copy(update={'nodes': {'lilspark': {'provider': 'prime', 'max_parallel_jobs': 1},
        'sparkDeux': {'provider': 'second', 'model': 'large', 'max_parallel_jobs': 4,
                      'shared_with_games': False, 'allow_large_tasks': True}}})
    monkeypatch.setattr(hermes_local, 'settings', lambda: s)
    original = q._api
    monkeypatch.setattr(q, '_api', lambda path, body=None: {'capacity': 5, 'nodes': [
        {'name': name, 'primary': v.shared_with_games, 'enabled': True, 'capable': True, 'capacity': v.max_parallel_jobs}
        for name, v in pool.node_settings().items()]} if path == '/api/hermes/local/nodes' else original(path, body))
    out = q.tick(now=1000)
    assert [d['inference_node'] for d in out['dispatched']] == ['lilspark'] + ['sparkDeux']*(global_limit-1)
    assert [c[c.index('--provider')+1] for c in calls] == ['prime'] + ['second']*(global_limit-1)
    assert all('Read the latest request checkpoints' in c[2] for c in calls)
    assert sum(i.get('inference_node') == 'sparkDeux' for i in q._read()['items'].values()) == global_limit-1
    assert q.tick(now=1010)['dispatched'] == []


def test_local_policy_and_the_stream_stability_gate_both_apply(monkeypatch, tmp_path):
    reqs = [{'id': P, 'number': 1, 'title': 'parent', 'status': 'open'},
            {'id': 'd' * 16, 'number': 6, 'title': 'Fix the typo in the inbox tooltip', 'status': 'open', 'created': 2}]
    calls = _env(monkeypatch, tmp_path, reqs, [])
    monkeypatch.setattr(q, '_operator_playing', lambda: [{'title': 'Soulcalibur', 'session_id': 's'}])
    monkeypatch.setattr(q, 'throttle_sandboxes', lambda playing: {'reniced': 2})
    out = q.tick(now=1000)
    assert out['capacity'] == 1 and out['operator_playing']['games'] == ['Soulcalibur']
    prompt = calls[0][2]
    assert prompt.startswith('LOCAL MODEL RUN') and 'Do not start an emulator' in prompt


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


def test_an_inbox_lane_run_gets_the_larger_inbox_budget():
    """#2399: a 45-call local run on an operator ticket read for 23 turns and published nothing. tool_budget_inbox
    raises the inbox lane's budget (prompt and proxy alike); favorites keep tool_budget."""
    s = S.model_copy(update={'tool_budget': 20, 'tool_budget_inbox': 60})
    assert hermes_local.lane_budget(s, 'inbox') == 60 and hermes_local.lane_budget(s, 'favorite') == 20
    assert hermes_local.lane_budget(S.model_copy(update={'tool_budget': 20}), 'inbox') == 20, 'unset: the plain budget'
    assert hermes_local.lane_budget(S.model_copy(update={'tool_budget': 70, 'tool_budget_inbox': 60}), 'inbox') == 70
    base = 'Assigned queue task. Use a 45-tool-call work budget with the final 10 calls reserved for tests.'
    out = hermes_local.local_prompt(base, s, lane='inbox')
    assert 'Use a 60-tool-call work budget with the final 6 calls' in out and 'at most 60 tool calls' in out
    assert 'at most 20 tool calls' in hermes_local.local_prompt(base, s, lane='favorite')
