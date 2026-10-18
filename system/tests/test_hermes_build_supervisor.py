import json
from types import SimpleNamespace

import pytest

from gbox import hermes_build_supervisor as S, hermes_work_queue as Q, hermes_pool as P


@pytest.fixture
def supervisor(tmp_path, monkeypatch):
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    monkeypatch.setattr(S.M, '_job', lambda: {'enabled': True})
    monkeypatch.setattr(S.M, '_config', lambda: {})
    monkeypatch.setattr(S.D, 'repository', lambda: tmp_path)
    monkeypatch.setattr(S, 'snapshot', lambda rid: {'repair_requests': [{'id': 'a'*16}]})
    monkeypatch.setattr(P, '_sync_cron_capacity', lambda capacity: None)
    S._save({'enabled': True, 'request_id': 'b'*16})
    messages, paid, priority = [], [], []
    def api(path, body=None):
        if body is None:
            return {'messages': messages}
        messages.append(body)
        return body
    def run(args, **kwargs):
        paid.append(args)
        assert args[args.index('--max-turns')+1] == '24'
        assert args[args.index('--run-budget')+1] == '480'
        assert args[args.index('--provider')+1] == 'nous'
        assert kwargs['timeout'] == 540
        return SimpleNamespace(returncode=0, stdout='Tested repair PR #8.\nNEXT_REQUESTS: ["'+'a'*16+'", "unknown"]')
    monkeypatch.setattr(S, '_api', api)
    monkeypatch.setattr(S.subprocess, 'run', run)
    monkeypatch.setattr(Q, 'add_triage_priority', priority.extend)
    return messages, paid, priority


def test_bounded_paid_run_reports_and_prioritizes_only_known_repairs(supervisor):
    messages, paid, priority = supervisor
    assert S.tick()['state'] == 'completed'
    assert len(paid) == 1 and priority == ['a'*16]
    assert 'Tested repair PR' in messages[0]['text']
    assert S.tick()['state'] == 'waiting' and len(paid) == 1


def test_tasks_checkbox_and_opt_in_gate_paid_calls(supervisor, monkeypatch):
    monkeypatch.setattr(S.M, '_job', lambda: {'enabled': False})
    assert S.tick()['state'] == 'paused' and not supervisor[1]
    monkeypatch.setattr(S.M, '_job', lambda: {'enabled': True})
    S._save({'enabled': False})
    assert S.tick()['state'] == 'paused' and not supervisor[1]


def test_lost_report_ack_does_not_duplicate_report_or_paid_run(supervisor, monkeypatch):
    messages, paid, _ = supervisor
    original = S._api
    def lost(path, body=None):
        result = original(path, body)
        if body: raise TimeoutError('ack lost')
        return result
    monkeypatch.setattr(S, '_api', lost)
    S.tick()
    assert S.status()['pending_report'] and len(messages) == 1
    assert S.tick()['state'] == 'waiting'
    assert len(messages) == len(paid) == 1 and 'pending_report' not in S.status()


def test_live_supervisor_excludes_overlapping_paid_run(supervisor):
    with S.D.locked('build-supervisor-run'):
        assert S.tick()['state'] == 'already_running'
    assert not supervisor[1]


def test_slider_keeps_one_nous_scheduler_slot(tmp_path, monkeypatch):
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    S._save({'enabled': True})
    monkeypatch.setattr(S.M, '_config', lambda: {'cron': {'max_parallel_jobs': 26}})
    def unexpected(*args, **kwargs):
        raise AssertionError('Existing reserved slot must not be rewritten')
    monkeypatch.setattr(S.subprocess, 'run', unexpected)
    P._sync_cron_capacity(25)


def test_malformed_priority_output_is_ignored():
    assert S.priorities('NEXT_REQUESTS: [not json]', {'a'}) == []
    assert S.priorities('NEXT_REQUESTS: [1, "a", "a", "b"]', {'a'}) == ['a']


def test_zai_scope_blocks_before_reading_private_snapshot(supervisor, monkeypatch):
    from gbox import hermes_provider_scope as scope
    scope.restrict(['zai'], ['api.z.ai'], apply=True)
    S._save({'enabled': True, 'request_id': 'b'*16, 'supervision_provider': 'zai'})
    monkeypatch.setattr(S, 'snapshot', lambda _: pytest.fail('Private snapshot must not be read'))
    assert S.tick()['state'] == 'waiting_provider_scope'
    assert not supervisor[1]


@pytest.mark.parametrize('age,remaining,http', [(601, 10, 200), (0, 0, 200), (0, 10, 429)])
def test_zai_requires_fresh_available_quota_and_probe(supervisor, age, remaining, http):
    S._save({'enabled': True, 'request_id': 'b'*16, 'supervision_provider': 'zai'})
    (S.D.state_dir()/'zai-availability.json').write_text(json.dumps({
        'checked_at': S.time.time()-age, 'probe_http': http,
        'windows': [{'type': 'CREDIT_LIMIT', 'remaining': remaining}]}))
    assert S.tick()['state'] == 'waiting_provider_quota'
    assert not supervisor[1]


def test_zai_pin_guidance_and_report_attribution(supervisor, monkeypatch):
    S._save({'enabled': True, 'request_id': 'b'*16, 'supervision_provider': 'zai'})
    (S.D.state_dir()/'zai-availability.json').write_text(json.dumps({
        'checked_at': S.time.time(), 'probe_http': 200,
        'windows': [{'type': 'CREDIT_LIMIT', 'remaining': 10}]}))
    def run(args, **kwargs):
        assert args[args.index('--provider')+1] == 'zai'
        assert args[args.index('--model')+1] == 'glm-5.3'
        prompt = S.Path(args[args.index('--query-file')+1]).read_text()
        assert 'Do not take over active implementation tasks' in prompt
        return SimpleNamespace(returncode=0, stdout='Guidance posted. NEXT_REQUESTS: []')
    monkeypatch.setattr(S.subprocess, 'run', run)
    assert S.tick()['state'] == 'completed'
    assert S.status()['provider'] == 'zai'
    assert supervisor[0][0]['text'].startswith('zai build supervision ')


def test_policy_rechecked_after_snapshot(supervisor, monkeypatch):
    from gbox import hermes_provider_scope as scope
    def snapshot(_):
        scope.restrict(['nous'], [], apply=True)
        return {'repair_requests': []}
    monkeypatch.setattr(S, 'snapshot', snapshot)
    assert S.tick()['state'] == 'waiting_provider_scope'
    assert not supervisor[1]


def test_zai_does_not_borrow_other_provider_fallbacks(supervisor, monkeypatch):
    S._save({'enabled': True, 'request_id': 'b'*16, 'supervision_provider': 'zai'})
    monkeypatch.setattr(S.M, '_config', lambda: {
        'fallback_model': {'provider': 'nous', 'model': S.MODEL}})
    assert S.tick()['state'] == 'waiting_provider_config'
    assert not supervisor[1]
