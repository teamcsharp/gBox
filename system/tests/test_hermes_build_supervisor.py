import json
from types import SimpleNamespace

import pytest

from gbox import hermes_build_supervisor as S, hermes_work_queue as Q, hermes_pool as P


@pytest.fixture
def supervisor(tmp_path, monkeypatch):
    monkeypatch.setenv('GBOX_HERMES_DISPATCH_STATE', str(tmp_path))
    monkeypatch.setattr(S.M, '_job', lambda: {'enabled': True})
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
