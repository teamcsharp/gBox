import io
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import yaml

from gbox import hermes_model_trials as T, hermes_delivery as D, hermes_models as M

RECIPES = Path(T.__file__).resolve().parent.parent / 'hermes' / 'spark2-recipes'


def test_solo_commands_never_start_a_cluster():
    for key, profile in T.PROFILES.items():
        if profile['cluster_only'] or profile['held']:
            with pytest.raises(ValueError):
                T.recipe_args(Path('/recipes'), key, 'trial')
            continue
        args = T.recipe_args(Path('/recipes'), key, 'trial')
        assert '--solo' in args and args[args.index('--tp') + 1] == '1'
        assert '--setup' not in args and '--download-only' not in args
        assert profile['recipe'] in args
        assert args[args.index('--gpu-memory-utilization') + 1] == str(profile['gpu_memory'])


def test_every_launch_asks_for_the_profile_context_and_memory():
    args = T.recipe_args(Path('/root/spark-vllm-docker'), 'qwen-coder', 'trial', '--daemon', '--earlyoom')
    assert args[args.index('--max-model-len') + 1] == '262144'
    assert args[args.index('--gpu-memory-utilization') + 1] == '0.88'
    assert '65536' not in args and '--' not in args
    # Operator-placed weights are mounted read-only; the recipe serves the mount.
    args = T.recipe_args(Path('/root/spark-vllm-docker'), 'laguna-s', 'trial', '--dry-run')
    assert args[args.index('-v') + 1] == '/root/models/laguna-s-2.1-nvfp4:/models/laguna-s-2.1-nvfp4:ro'
    assert args[-1] == '--dry-run'
    # Bolt keeps its recipe's "auto" context: vLLM fits it to the KV cache.
    assert '--max-model-len' not in T.recipe_args(Path('/root/spark-vllm-docker'), 'nemotron-bolt', 'trial')


def test_runner_flags_precede_extra_vllm_args(monkeypatch):
    monkeypatch.setitem(T.PROFILES, 'extra-demo', T._profile('Demo', 'org/demo', 'demo', context=4096, extra=['--max-num-seqs', '8']))
    args = T.recipe_args(Path('/root/spark-vllm-docker'), 'extra-demo', 'trial', '--setup', '--build-only')
    assert args[-4:] == ['--build-only', '--', '--max-num-seqs', '8']


def test_shipped_recipes_match_their_profiles_and_render_solo():
    shipped = T.shipped_recipes()
    assert set(shipped) == {'gbox-qwen3-coder-next-fp8.yaml', 'gbox-ornith-1.5-35b-a3b-nvfp4.yaml', 'gbox-laguna-s-2.1-nvfp4.yaml'}
    for key, profile in T.PROFILES.items():
        if not profile['shipped']:
            continue
        text = shipped[profile['recipe'] + '.yaml']
        assert '\r' not in text
        recipe = yaml.safe_load(text)
        assert recipe['recipe_version'] == '1' and recipe['container'] == 'vllm-node' and recipe['solo_only']
        defaults = recipe['defaults']
        assert defaults['gpu_memory_utilization'] == profile['gpu_memory']
        assert defaults['max_model_len'] == profile['context']
        assert defaults['max_num_seqs'] == profile['seqs'] and defaults['max_num_batched_tokens'] == profile['batched']
        # The same substitution run-recipe.py performs, with gBox's overrides.
        command = recipe['command'].format(**(defaults | {'tensor_parallel': 1}))
        assert '--distributed-executor-backend' not in command and '-tp 2' not in command
        assert f"--served-model-name {profile['model']}" in command or f"vllm serve {profile['model']} " in command
        assert '--kv-cache-dtype fp8' in command and '--enable-prefix-caching' in command
        assert '--enable-auto-tool-choice' in command and '--tool-call-parser' in command
        if profile['weights']:
            assert recipe.get('model') is None and f"vllm serve {profile['mount']} " in command
        else:
            assert recipe['model'] == profile['model']


def test_gguf_plan_is_held_but_adoptable(tmp_path, monkeypatch):
    plan = (RECIPES / 'ornith-1.5-122b-gguf.sh').read_text()
    assert 'llama-server' in plan and '--alias unsloth/Ornith-1.5-122B-GGUF' in plan and '--port "${PORT:-8000}"' in plan
    profile = T.PROFILES['ornith-122b']
    assert profile['held'] and not profile['cluster_only'] and not profile['shipped']
    monkeypatch.setattr(D, 'state_dir', lambda: tmp_path)
    monkeypatch.setattr(M, '_read', lambda: {})
    T.save({'enabled': True})
    for action in ('trial_prepare', 'trial_start'):
        with pytest.raises(ValueError, match='llama-server'):
            T.submit(action, 'ornith-122b')
    monkeypatch.setattr(T.subprocess, 'Popen', lambda *a, **k: SimpleNamespace(pid=7))
    assert T.submit('trial_adopt', 'ornith-122b')['action'] == 'trial_adopt'


def test_remote_payload_is_complete_python_without_package_imports():
    source = Path(T.__file__).read_text().rsplit("if __name__ == '__main__':", 1)[0]
    scope = {}
    exec(compile(source, 'remote-model-trials', 'exec'), scope)
    assert callable(scope['remote']) and callable(scope['install_recipes'])
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


@pytest.mark.parametrize('advertised, fallback, expected', [(262144, 65536, 262144), (None, 262144, 262144), (None, None, 65536)])
def test_served_context_is_recorded_without_a_cap(monkeypatch, advertised, fallback, expected):
    model = {'id': 'model'} | ({'max_model_len': advertised} if advertised else {})
    replies = [{'data': [model]},
               {'choices': [{'message': {'role': 'assistant', 'content': None, 'tool_calls': [
                   {'id': 'c', 'type': 'function', 'function': {'name': 'report_status', 'arguments': '{"status":"ready"}'}}]}}]},
               {'choices': [{'message': {'content': 'READY'}}]}]
    monkeypatch.setattr(T.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(json.dumps(replies.pop(0)).encode()))
    assert T.probe('http://server/v1', 'model', fallback)['context_tokens'] == expected


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
    with pytest.raises(ValueError, match='cluster'):
        T.submit('trial_adopt', 'glm-flash')
    T.save({'enabled': True, 'job': {'state': 'starting'}})
    with pytest.raises(RuntimeError, match='already pending'):
        T.submit('trial_adopt', 'qwen-flash')


def test_reject_unknown_profile_and_action():
    with pytest.raises(ValueError):
        T.submit('trial_adopt', 'arbitrary/model')
    with pytest.raises(ValueError):
        T.submit('execute', 'qwen-flash')


def test_status_lists_every_profile_with_its_sizing(tmp_path, monkeypatch):
    from gbox import hermes_pool as P
    monkeypatch.setattr(D, 'state_dir', lambda: tmp_path)
    monkeypatch.setattr(P, 'node_settings', lambda: {'sparkDeux': SimpleNamespace(model='ornith-ai/Ornith-1.5-35B-A3B-NVFP4')})
    T.save({'enabled': True, 'prepared': ['laguna-s']})
    rows = {row['id']: row for row in T.status()['profiles']}
    assert set(rows) == set(T.PROFILES)
    assert rows['ornith-35b']['current'] and rows['ornith-35b']['context'] == 262144 and rows['ornith-35b']['max_num_seqs'] == 64
    assert rows['laguna-s']['prepared'] and rows['laguna-s']['gpu_memory'] == .9
    assert 'llama-server' in rows['ornith-122b']['held'] and rows['glm-flash']['cluster_only']


def _fake_fcntl(monkeypatch):
    if os.name == 'nt':
        monkeypatch.setitem(sys.modules, 'fcntl', SimpleNamespace(flock=lambda *a: None, LOCK_EX=2, LOCK_NB=4))


def test_prepare_installs_shipped_recipes_and_checks_local_weights(tmp_path, monkeypatch, capsys):
    _fake_fcntl(monkeypatch)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    recipes = tmp_path / 'spark-vllm-docker' / 'recipes'; recipes.mkdir(parents=True)
    (recipes / 'gbox-laguna-s-2.1-nvfp4.yaml').write_text('name: stale\n')
    weights = tmp_path / 'models' / 'laguna-s-2.1-nvfp4'; weights.mkdir(parents=True)
    (weights / 'config.json').write_text('{}')
    (weights / 'model.safetensors.index.json').write_text(json.dumps({'weight_map': {'a': 'model-00001-of-00002.safetensors', 'b': 'model-00002-of-00002.safetensors'}}))
    (weights / 'model-00001-of-00002.safetensors').write_bytes(b'x' * 10)
    (weights / 'model-00002-of-00002.safetensors').write_bytes(b'y' * 20)
    commands = []
    monkeypatch.setattr(T.subprocess, 'run', lambda args, **kwargs: commands.append(args))
    monkeypatch.setattr(T.urllib.request, 'urlopen', lambda *a, **k: (_ for _ in ()).throw(OSError('offline')))
    shipped = T.shipped_recipes()
    T.remote({'id': '123456abcdef', 'action': 'trial_prepare', 'profile': 'laguna-s', 'container': 'old', 'previous_model': 'm', 'recipes': shipped})
    assert (recipes / 'gbox-laguna-s-2.1-nvfp4.yaml').read_text() == shipped['gbox-laguna-s-2.1-nvfp4.yaml']
    assert (recipes / 'gbox-qwen3-coder-next-fp8.yaml').read_text() == shipped['gbox-qwen3-coder-next-fp8.yaml']
    kept = list((tmp_path / '.local/state/gbox-model-trials/recipe-backups').iterdir())
    assert len(kept) == 1 and kept[0].read_text() == 'name: stale\n'
    assert [c for c in commands if '--download-only' in c] == []
    assert any('--build-only' in c and c[c.index('-v') + 1].endswith(':/models/laguna-s-2.1-nvfp4:ro') for c in commands)
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[1]['weights'] == {'shards': 2, 'bytes': 30, 'verified': 'local'} and events[-1]['state'] == 'prepared'


def test_prepare_refuses_incomplete_local_weights(tmp_path, monkeypatch, capsys):
    _fake_fcntl(monkeypatch)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    (tmp_path / 'spark-vllm-docker' / 'recipes').mkdir(parents=True)
    weights = tmp_path / 'models' / 'ornith-1.5-35b-nvfp4'; weights.mkdir(parents=True)
    (weights / 'config.json').write_text('{}')
    (weights / 'model.safetensors.index.json').write_text(json.dumps({'weight_map': {'a': 'model-00001-of-00002.safetensors', 'b': 'model-00002-of-00002.safetensors'}}))
    (weights / 'model-00001-of-00002.safetensors').write_bytes(b'x')
    monkeypatch.setattr(T.subprocess, 'run', lambda *a, **k: None)
    with pytest.raises(RuntimeError, match='1 of 2 shards missing'):
        T.remote({'id': '123456abcdef', 'action': 'trial_prepare', 'profile': 'ornith-35b', 'container': 'old', 'previous_model': 'm', 'recipes': {}})
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[-1]['state'] == 'failed' and 'shards missing' in events[-1]['error']


def test_hub_size_mismatch_is_reported(tmp_path, monkeypatch):
    weights = tmp_path / 'w'; weights.mkdir()
    (weights / 'config.json').write_text('{}')
    (weights / 'model.safetensors.index.json').write_text(json.dumps({'weight_map': {'a': 'model-00001-of-00001.safetensors'}}))
    (weights / 'model-00001-of-00001.safetensors').write_bytes(b'x' * 5)
    listing = json.dumps([{'path': 'model-00001-of-00001.safetensors', 'size': 6}]).encode()
    monkeypatch.setattr(T.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(listing))
    with pytest.raises(RuntimeError, match='differ from the Hub'):
        T.weights_report(weights, 'org/model')
    (weights / 'model-00001-of-00001.safetensors').write_bytes(b'x' * 6)
    monkeypatch.setattr(T.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(listing))
    assert T.weights_report(weights, 'org/model') == {'shards': 1, 'bytes': 6, 'verified': 'hub'}


@pytest.mark.parametrize('restores', [True, False])
def test_failed_launch_restarts_retained_container_and_script(tmp_path, monkeypatch, capsys, restores):
    _fake_fcntl(monkeypatch)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    (tmp_path / 'spark-vllm-docker' / 'recipes').mkdir(parents=True)
    monkeypatch.setattr(T, 'container_running', lambda name: name == 'old_model')
    monkeypatch.setattr(T.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(
        b'vllm:num_requests_running 0\nvllm:num_requests_waiting 0\n'))
    commands = []
    def run(args, **kwargs):
        commands.append(args)
        if '--daemon' in args:
            raise T.subprocess.CalledProcessError(1, args)
    monkeypatch.setattr(T.subprocess, 'run', run)
    def restored(model, timeout, context=65536):
        assert model == 'original-model' and timeout == 300
        if not restores:
            raise RuntimeError('not served')
        return {'model': model}
    monkeypatch.setattr(T, 'wait_ready', restored)
    with pytest.raises(T.subprocess.CalledProcessError):
        T.remote({'id': '123456abcdef', 'action': 'trial_start', 'profile': 'qwen-coder',
                  'container': 'old_model', 'previous_model': 'original-model', 'recipes': T.shipped_recipes()})
    assert commands[0][-1] == '--dry-run' and '--max-model-len' in commands[0]
    assert ['docker', 'start', 'old_model'] in commands
    assert any(c[:4] == ['docker', 'exec', '-d', 'old_model'] and '/workspace/exec-script.sh' in c[-1] for c in commands)
    assert not any(c[:2] == ['docker', 'rm'] for c in commands)
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[-1]['state'] == ('rolled_back' if restores else 'rollback_failed')
    assert not any(e['state'] == 'ready' for e in events)


def test_stopped_retained_container_is_neither_drained_nor_restored(tmp_path, monkeypatch, capsys):
    _fake_fcntl(monkeypatch)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    (tmp_path / 'spark-vllm-docker' / 'recipes').mkdir(parents=True)
    monkeypatch.setattr(T, 'container_running', lambda name: False)
    monkeypatch.setattr(T.urllib.request, 'urlopen', lambda *a, **k: pytest.fail('nothing to drain'))
    commands = []
    def run(args, **kwargs):
        commands.append(args)
        if '--daemon' in args:
            raise T.subprocess.CalledProcessError(1, args)
    monkeypatch.setattr(T.subprocess, 'run', run)
    with pytest.raises(T.subprocess.CalledProcessError):
        T.remote({'id': '123456abcdef', 'action': 'trial_start', 'profile': 'ornith-35b',
                  'container': 'old_model', 'previous_model': 'original-model', 'recipes': {}})
    assert not any(c[:2] == ['docker', 'stop'] or c[:2] == ['docker', 'start'] for c in commands)
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [e['state'] for e in events] == ['starting']


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
    probes = []
    def probe(upstream, expected, context=65536):
        probes.append((expected, context))
        return {'model': T.PROFILES['qwen-coder']['model'], 'context_tokens': 262144}
    monkeypatch.setattr(T, 'probe', probe)
    wires = []
    def spawn(*a, **k):
        # Simulate the parent's PID receipt arriving after the child read state.
        data = T.read(); data['job']['pid'] = 42; T.save(data)
        event = {'state': remote_state, 'container': 'new', 'rollback_receipt': {'model': 'original'}}
        stdin = io.StringIO(); stdin.close = lambda: wires.append(stdin.getvalue())
        return SimpleNamespace(stdin=stdin, stdout=[json.dumps(event)], wait=lambda: 0 if remote_state == 'ready' else 1)
    monkeypatch.setattr(T.subprocess, 'Popen', spawn)
    T.worker('test')
    job = T.read()['job']
    assert job['pid'] == 42 and job['rollback_receipt']['model'] == 'original'
    assert maintenance == ([True] if remote_state == 'rollback_failed' else [True, False])
    assert job['state'] == {'ready': 'ready', 'rolled_back': 'failed', 'rollback_failed': 'rollback_failed'}[remote_state]
    assert (tmp_path / 'local-nodes.json').exists() == (remote_state == 'ready')
    assert capacity_changes == []
    # The shipped recipes travel with the plan, so the Spark runs the repo's files.
    assert 'gbox-qwen3-coder-next-fp8.yaml' in wires[0] and 'max_num_seqs: 64' in wires[0]
    if remote_state == 'ready':
        assert probes == [('Qwen/Qwen3-Coder-Next-FP8', 262144)]
        nodes = json.loads((tmp_path / 'local-nodes.json').read_text())
        assert nodes['nodes']['sparkDeux']['max_parallel_jobs'] == 32 and nodes['nodes']['sparkDeux']['context_tokens'] == 262144
        assert nodes['pool_max_parallel_jobs'] == 33


def test_remote_error_text_reaches_the_operator(tmp_path, monkeypatch):
    from gbox import hermes_pool as P
    monkeypatch.setattr(D, 'state_dir', lambda: tmp_path)
    T.save({'enabled': True, 'job': {'id': 'test', 'action': 'trial_prepare', 'profile': 'laguna-s', 'state': 'queued'}})
    monkeypatch.setattr(P, 'node_settings', lambda: {'sparkDeux': SimpleNamespace(model='original')})
    monkeypatch.setattr(M, 'ssh_args', lambda: ['ssh', 'fixture'])
    event = {'state': 'failed', 'error': 'Weights incomplete in laguna-s-2.1-nvfp4: 3 of 49 shards missing'}
    monkeypatch.setattr(T.subprocess, 'Popen', lambda *a, **k: SimpleNamespace(stdin=io.StringIO(), stdout=[json.dumps(event)], wait=lambda: 1))
    T.worker('test')
    job = T.read()['job']
    assert job['state'] == 'failed' and job['error'] == event['error']
    assert 'laguna-s' not in T.read().get('prepared', [])
