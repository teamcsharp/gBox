import io
import json
import os
from pathlib import Path

import pytest

from gbox import hermes_model_trials as T, hermes_delivery as D, hermes_models as M


def test_solo_commands_never_start_a_cluster():
    for key, profile in T.PROFILES.items():
        if profile[3]:
            with pytest.raises(ValueError):
                T.recipe_args(Path('/recipes'), key, 'trial')
            continue
        args = T.recipe_args(Path('/recipes'), key, 'trial')
        assert '--solo' in args and args[args.index('--tp') + 1] == '1'
        assert '--setup' not in args and '--download-only' not in args
        assert profile[2] in args


def test_remote_payload_is_complete_python_without_package_imports():
    source = Path(T.__file__).read_text().rsplit("if __name__ == '__main__':", 1)[0]
    scope = {}
    exec(compile(source, 'remote-model-trials', 'exec'), scope)
    assert callable(scope['remote'])
    assert scope['PROFILES'] == T.PROFILES


def test_adopt_requires_native_tool_and_followup(monkeypatch):
    replies = [
        {'data': [{'id': 'model', 'max_model_len': 32768}]},
        {'choices': [{'message': {'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': 'call1', 'type': 'function', 'function': {'name': 'report_status', 'arguments': '{"status":"ready"}'}}]}}]},
        {'choices': [{'message': {'content': 'READY'}}]},
    ]
    sent = []
    def urlopen(req, **kwargs):
        if not isinstance(req, str):
            sent.append(json.loads(req.data))
        return io.BytesIO(json.dumps(replies.pop(0)).encode())
    monkeypatch.setattr(T.urllib.request, 'urlopen', urlopen)
    receipt = T.probe('http://server/v1', 'model')
    assert receipt['context_tokens'] == 32768
    assert sent[1]['messages'][-2]['tool_call_id'] == 'call1'
    assert sent[1]['tool_choice'] == 'none'


def test_wrong_served_model_cannot_change_routing(monkeypatch):
    monkeypatch.setattr(T.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(b'{"data":[{"id":"other"}]}'))
    with pytest.raises(RuntimeError, match='not served'):
        T.probe('http://server/v1', 'model')


def test_incomplete_preparation_and_concurrent_actions_are_held(tmp_path, monkeypatch):
    monkeypatch.setattr(D, 'state_dir', lambda: tmp_path)
    monkeypatch.setattr(M, '_read', lambda: {})
    T.save({'enabled': True})
    with pytest.raises(ValueError, match='Prepare'):
        T.submit('trial_start', 'qwen-coder')
    with pytest.raises(ValueError, match='cluster'):
        T.submit('trial_start', 'glm-flash')
    T.save({'enabled': True, 'job': {'state': 'starting'}})
    with pytest.raises(RuntimeError, match='already pending'):
        T.submit('trial_adopt', 'qwen-flash')


def test_reject_unknown_profile_and_action():
    with pytest.raises(ValueError):
        T.submit('trial_adopt', 'arbitrary/model')
    with pytest.raises(ValueError):
        T.submit('execute', 'qwen-flash')


@pytest.mark.skipif(os.name == 'nt', reason='Remote worker uses the Spark flock API')
@pytest.mark.parametrize('restores', [True, False])
def test_failed_launch_restarts_retained_container_and_script(tmp_path, monkeypatch, capsys, restores):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    (tmp_path / 'spark-vllm-docker').mkdir()
    monkeypatch.setattr(T.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(
        b'vllm:num_requests_running 0\nvllm:num_requests_waiting 0\n'))
    commands = []
    def run(args, **kwargs):
        commands.append(args)
        if '--daemon' in args:
            raise T.subprocess.CalledProcessError(1, args)
    monkeypatch.setattr(T.subprocess, 'run', run)
    def restored(model, timeout):
        assert model == 'original-model' and timeout == 300
        if not restores:
            raise RuntimeError('not served')
        return {'model': model}
    monkeypatch.setattr(T, 'wait_ready', restored)
    with pytest.raises(T.subprocess.CalledProcessError):
        T.remote({'id': '123456abcdef', 'action': 'trial_start', 'profile': 'qwen-coder',
                  'container': 'old_model', 'previous_model': 'original-model'})
    assert ['docker', 'start', 'old_model'] in commands
    assert any(c[:4] == ['docker', 'exec', '-d', 'old_model'] and '/workspace/exec-script.sh' in c[-1] for c in commands)
    assert not any(c[:2] == ['docker', 'rm'] for c in commands)
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[-1]['state'] == ('rolled_back' if restores else 'rollback_failed')
    assert not any(e['state'] == 'ready' for e in events)


def test_failed_adoption_leaves_route_unchanged_and_does_not_restart(tmp_path, monkeypatch):
    from gbox import hermes_pool as P
    monkeypatch.setattr(D, 'state_dir', lambda: tmp_path)
    T.save({'enabled': True, 'job': {'id': 'test', 'state': 'queued', 'action': 'trial_adopt', 'profile': 'qwen-coder'}})
    monkeypatch.setattr(T, 'probe', lambda *a: (_ for _ in ()).throw(RuntimeError('Selected model is not served')))
    monkeypatch.setattr(P, 'maintenance', lambda *a: pytest.fail('Adoption must not interrupt inference'))
    monkeypatch.setattr(P, '_state', lambda: pytest.fail('Failed validation must not change routing'))
    T.worker('test')
    assert T.read()['job']['state'] == 'failed'


def test_fast_worker_can_claim_lock_without_losing_progress(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(D, 'state_dir', lambda: tmp_path)
    monkeypatch.setattr(M, '_read', lambda: {})
    T.save({'enabled': True})
    def spawn(*args, **kwargs):
        with D.locked('model-management'):
            data = T.read()
            data['job']['state'] = 'preparing'
            T.save(data)
        return SimpleNamespace(pid=42)
    monkeypatch.setattr(T.subprocess, 'Popen', spawn)
    job = T.submit('trial_prepare', 'nemotron-bolt')
    assert job['state'] == T.read()['job']['state'] == 'preparing'
    assert T.read()['job']['pid'] == 42


@pytest.mark.parametrize('remote_state', ['ready', 'rolled_back', 'rollback_failed'])
def test_worker_maintenance_and_receipts_follow_actual_recovery(tmp_path, monkeypatch, remote_state):
    from types import SimpleNamespace
    from gbox import hermes_pool as P
    monkeypatch.setattr(D, 'state_dir', lambda: tmp_path)
    T.save({'enabled': True, 'job': {'id': 'test', 'action': 'trial_start', 'profile': 'qwen-coder', 'state': 'queued'}})
    maintenance = []
    monkeypatch.setattr(P, 'maintenance', lambda name, active: maintenance.append(active))
    monkeypatch.setattr(P, 'node_settings', lambda: {'sparkDeux': SimpleNamespace(model='original')})
    monkeypatch.setattr(P, '_state', lambda: {'nodes': {'sparkDeux': {'max_parallel_jobs': 32}}, 'pool_max_parallel_jobs': 33})
    monkeypatch.setattr(P, 'register_providers', lambda: None)
    capacity_changes = []
    monkeypatch.setattr(P, 'set_capacity', lambda *a: capacity_changes.append(a))
    monkeypatch.setattr(M, 'ssh_args', lambda: ['ssh', 'fixture'])
    monkeypatch.setattr(T, 'probe', lambda *a: {'model': T.PROFILES['qwen-coder'][1], 'context_tokens': 65536})
    def spawn(*a, **k):
        # Simulate the parent's PID receipt arriving after the child read state.
        data = T.read(); data['job']['pid'] = 42; T.save(data)
        event = {'state': remote_state, 'container': 'new', 'rollback_receipt': {'model': 'original'}}
        return SimpleNamespace(stdin=io.StringIO(), stdout=[json.dumps(event)], wait=lambda: 0 if remote_state == 'ready' else 1)
    monkeypatch.setattr(T.subprocess, 'Popen', spawn)
    T.worker('test')
    job = T.read()['job']
    assert job['pid'] == 42 and job['rollback_receipt']['model'] == 'original'
    assert maintenance == ([True] if remote_state == 'rollback_failed' else [True, False])
    assert job['state'] == {'ready': 'ready', 'rolled_back': 'failed', 'rollback_failed': 'rollback_failed'}[remote_state]
    assert (tmp_path / 'local-nodes.json').exists() == (remote_state == 'ready')
    assert capacity_changes == []
    if remote_state == 'ready':
        nodes = json.loads((tmp_path / 'local-nodes.json').read_text())
        assert nodes['nodes']['sparkDeux']['max_parallel_jobs'] == 32
        assert nodes['pool_max_parallel_jobs'] == 33
