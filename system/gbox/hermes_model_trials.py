"""Operator-selected, single-Spark model recipes with durable progress and rollback.

The remote half uses only the standard library and the installed recipe runner.
Model names are an allowlist; no arbitrary commands arrive through the API.
Recipes gBox ships (system/hermes/spark2-recipes) are installed into the runner's
recipes folder on lilspark2 before every prepare and start, so the Tasks view
launches each model with the settings that fill one GB10.
"""
from __future__ import annotations

import json
from contextlib import contextmanager, ExitStack
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request
import uuid


def _profile(title, model, recipe, context=None, gpu_memory=.88, seqs=None, batched=None, extra=(),
             shipped=False, weights=None, mount=None, held=None, cluster_only=False):
    """context: --max-model-len gBox asks for (None: the recipe's own default, e.g. "auto");
    seqs/batched: documented sizing (baked into shipped recipes); extra: verbatim vLLM args after '--';
    weights/mount: a ~/models folder on lilspark2 mounted read-only into the container;
    held: why Prepare and Start trial are unavailable (Use if already running stays)."""
    return {'title': title, 'model': model, 'recipe': recipe, 'context': context, 'gpu_memory': gpu_memory,
            'seqs': seqs, 'batched': batched, 'extra': list(extra), 'shipped': shipped, 'weights': weights,
            'mount': mount, 'held': held, 'cluster_only': cluster_only}


PROFILES = {
    'qwen-flash': _profile('Qwen3.8 Flash Next FP4', 'nvidia/Qwen3.8-Flash-Next-FP4-Local', 'qwen3.8-flash-next-nvfp4-solo',
                           context=262144, seqs=8, batched=4096),
    'qwen-coder': _profile('Qwen3-Coder-Next FP8', 'Qwen/Qwen3-Coder-Next-FP8', 'gbox-qwen3-coder-next-fp8',
                           context=262144, seqs=64, batched=8192, shipped=True),
    'glm-flash': _profile('GLM-5.3 Flash NVFP4', 'nvidia/GLM-5.3-Flash-FP4-Local', 'glm-5.3-flash', cluster_only=True,
                          held='This checkpoint requires about 166 GiB; the installed cluster recipe cannot run on this 128 GB Spark'),
    'nemotron-super': _profile('Nemotron 3 Super 120B NVFP4', 'nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4', 'nemotron-3-super-nvfp4',
                               context=262144, seqs=32),
    'nemotron-bolt': _profile('Nemotron 3.5 Bolt 74B-A9B 24GB', 'nvidia/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB', 'nemotron-3.5-bolt-24gb',
                              seqs=32, batched=8192),   # the recipe fits max_model_len "auto" to the KV cache
    'ornith-35b': _profile('Ornith 1.5 35B-A3B NVFP4', 'ornith-ai/Ornith-1.5-35B-A3B-NVFP4', 'gbox-ornith-1.5-35b-a3b-nvfp4',
                           context=262144, seqs=64, batched=8192, shipped=True,
                           weights='models/ornith-1.5-35b-nvfp4', mount='/models/ornith-1.5-35b-nvfp4'),
    'laguna-s': _profile('Laguna S 2.1 NVFP4 (RedHatAI)', 'RedHatAI/Laguna-S-2.1-NVFP4', 'gbox-laguna-s-2.1-nvfp4',
                         context=262144, gpu_memory=.9, seqs=16, batched=4096, shipped=True,
                         weights='models/laguna-s-2.1-nvfp4', mount='/models/laguna-s-2.1-nvfp4'),
    'ornith-122b': _profile('Ornith 1.5 122B GGUF (llama-server)', 'unsloth/Ornith-1.5-122B-GGUF', 'ornith-1.5-122b-gguf',
                            context=262144, seqs=8, weights='models/ornith-122b/UD-Q4_K_XL',
                            held='GGUF checkpoint: vLLM on lilspark2 has no loader for it. Serve it with the llama-server '
                                 'recipe (system/hermes/spark2-recipes/ornith-1.5-122b-gguf.sh), then use it if already running'),
}
BUSY = ('queued', 'preparing', 'draining', 'starting', 'validating', 'rolling_back')
UPSTREAM = 'http://10.89.1.225:8000/v1'


def read():
    from . import hermes_delivery as D
    try:
        return json.loads((D.state_dir() / 'model-trials.json').read_text())
    except FileNotFoundError:
        return {}


def save(data):
    from . import hermes_delivery as D
    p = D.state_dir() / 'model-trials.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.tmp'); tmp.write_text(json.dumps(data, indent=2)); tmp.replace(p)


@contextmanager
def management_lock():
    # D.locked is nonblocking. Brief parent/worker state updates must retry
    # contention instead of abandoning a durable action at startup.
    from . import hermes_delivery as D
    with ExitStack() as stack:
        for _ in range(100):
            try:
                stack.enter_context(D.locked('model-management'))
                break
            except BlockingIOError:
                time.sleep(.05)
        else:
            raise RuntimeError('Model management is busy; retry after its state update')
        yield


def status():
    from . import hermes_pool as P
    data = read()
    if not data.get('enabled'):
        return None
    current = P.node_settings().get('sparkDeux')
    return {'job': data.get('job'), 'profiles': [
        {'id': key, 'title': p['title'], 'model': p['model'], 'recipe': p['recipe'],
         'cluster_only': p['cluster_only'], 'held': p['held'], 'context': p['context'],
         'gpu_memory': p['gpu_memory'], 'max_num_seqs': p['seqs'],
         'prepared': key in data.get('prepared', []),
         'current': bool(current and current.model == p['model'])}
        for key, p in PROFILES.items()]}


def shipped_recipes():
    """The recipe files the repo ships for lilspark2 (LF; the deployed share is CRLF), by file name."""
    folder = Path(__file__).resolve().parent.parent / 'hermes' / 'spark2-recipes'
    return {p['recipe'] + '.yaml': (folder / (p['recipe'] + '.yaml')).read_text(encoding='utf-8').replace('\r\n', '\n')
            for p in PROFILES.values() if p['shipped']}


def probe(upstream, expected, context=65536):
    """Require native tools and a follow-up response, not just /models health.
    The context recorded for Hermes is what the server advertises (max_model_len), else `context`."""
    with urllib.request.urlopen(upstream + '/models', timeout=10) as r:
        models = json.load(r)['data']
    model = next((m for m in models if m['id'] == expected), None)
    if not model:
        raise RuntimeError('Selected model is not served')
    body = {'model': expected, 'messages': [{'role': 'user', 'content': 'Call report_status with status ready.'}],
            'tools': [{'type': 'function', 'function': {'name': 'report_status', 'parameters': {
                'type': 'object', 'properties': {'status': {'type': 'string'}}, 'required': ['status']}}}],
            'tool_choice': 'auto', 'max_tokens': 256, 'chat_template_kwargs': {'enable_thinking': False}}
    def chat(payload):
        req = urllib.request.Request(upstream + '/chat/completions', data=json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    start = time.time()
    first = chat(body)
    msg = first['choices'][0]['message']
    calls = msg.get('tool_calls', [])
    if len(calls) != 1 or calls[0]['function']['name'] != 'report_status' or json.loads(
            calls[0]['function']['arguments']).get('status') != 'ready':
        raise RuntimeError('Native tool-call validation failed')
    body['messages'] += [msg, {'role': 'tool', 'tool_call_id': calls[0]['id'], 'content': 'Status ready confirmed.'},
                         {'role': 'user', 'content': 'Reply with READY only.'}]
    body['tool_choice'] = 'none'
    second = chat(body)
    if (second['choices'][0]['message'].get('content') or '').strip().upper().rstrip('.') != 'READY':
        raise RuntimeError('Tool-result continuation validation failed')
    return {'model': expected, 'context_tokens': int(model.get('max_model_len') or context or 65536),
            'elapsed_s': round(time.time() - start, 3), 'calls': [first.get('usage'), second.get('usage')],
            'checked_at': time.time()}


def submit(action, profile):
    from . import hermes_delivery as D, hermes_models as M
    if action not in ('trial_prepare', 'trial_start', 'trial_adopt') or profile not in PROFILES:
        raise ValueError('Unknown model trial action')
    p = PROFILES[profile]
    if p['cluster_only'] or (p['held'] and action != 'trial_adopt'):
        raise ValueError(p['held'])
    with management_lock():
        data = read()
        if not data.get('enabled'):
            raise ValueError('Model trials are not configured')
        if (data.get('job') or {}).get('state') in BUSY or M._read().get('state') in BUSY:
            raise RuntimeError('A model action is already pending; inspect its retained progress before retrying')
        if action == 'trial_start' and profile not in data.get('prepared', []):
            raise ValueError('Prepare the image and model before starting it')
        job = {'id': uuid.uuid4().hex[:12], 'action': action, 'profile': profile,
               'state': 'queued', 'created_at': time.time()}
        data['job'] = job; save(data)
    # The child also needs this lock; release it before spawning. Re-read state
    # when recording its PID so a fast worker's progress is never overwritten.
    try:
        process = subprocess.Popen([sys.executable, '-m', 'gbox.hermes_model_trials', '--worker', job['id']],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        with management_lock():
            data = read()
            if data['job']['id'] == job['id']:
                data['job']['pid'] = process.pid; save(data)
                job = data['job']
    except OSError:
        with management_lock():
            data = read()
            if data['job']['id'] == job['id']:
                data['job'].update(state='failed', error='Could not launch model worker'); save(data)
        raise
    return job


def worker(job_id):
    from . import hermes_delivery as D, hermes_models as M, hermes_pool as P
    with D.locked('model-trial-worker'):
        with management_lock():
            data = read(); job = data['job']
            if job['id'] != job_id:
                raise RuntimeError('Model job identity changed')
        action, profile = job['action'], job['profile']
        def update(**event):
            with management_lock():
                fresh = read()
                if fresh['job']['id'] != job_id:
                    raise RuntimeError('Model job identity changed')
                merged = fresh['job'] | job | event | {'updated_at': time.time()}
                job.clear(); job.update(merged)
                for field in ('prepared', 'container', 'history'):
                    if field in data:
                        fresh[field] = data[field]
                fresh['job'] = job
                data.clear(); data.update(fresh); save(data)
        changed = False
        try:
            if action == 'trial_start':
                P.maintenance('sparkDeux', True); changed = True
            if action != 'trial_adopt':
                plan = {'id': job_id, 'action': action, 'profile': profile,
                        'container': data.get('container', 'vllm_node'),
                        'previous_model': P.node_settings()['sparkDeux'].model,
                        'recipes': shipped_recipes()}
                source = Path(__file__).read_text().rsplit("if __name__ == '__main__':", 1)[0]
                wire = 'exec(compile(' + repr(source) + ',"model-trial-remote","exec")); remote(' + repr(plan) + ')'
                p = subprocess.Popen(M.ssh_args() + ['python3 -'], stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                p.stdin.write(wire); p.stdin.close()
                for line in p.stdout:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    update(**event)
                if p.wait() != 0 or job['state'] not in ('prepared', 'ready'):
                    raise RuntimeError(job.get('error') if job.get('state') == 'failed' and job.get('error')
                                       else 'Remote action failed; inspect the retained trial log on lilspark2')
                if action == 'trial_prepare':
                    data['prepared'] = sorted(set(data.get('prepared', [])) | {profile})
                    update(state='prepared'); return
                data['container'] = job['container']
            update(state='validating')
            receipt = probe(UPSTREAM, PROFILES[profile]['model'], PROFILES[profile]['context'])
            with D.locked('local-nodes'):
                state = P._state()
                state.setdefault('nodes', {}).setdefault('sparkDeux', {}).update(
                    model=receipt['model'], upstream=UPSTREAM, context_tokens=receipt['context_tokens'], changed_at=time.time())
                path = D.state_dir() / 'local-nodes.json'
                temp = path.with_suffix('.tmp'); temp.write_text(json.dumps(state, indent=2)); temp.replace(path)
            P.register_providers()
            # Model selection preserves the operator's node and scheduler capacity.
            data.setdefault('history', []).append({'job': job_id, 'profile': profile, **receipt})
            update(state='ready', receipt=receipt)
            if action == 'trial_adopt':
                P.maintenance('sparkDeux', False)
        except Exception as exc:
            # No raw SSH/HTTP bodies or environment values are persisted.
            update(state='rollback_failed' if job.get('state') == 'rollback_failed' else 'failed',
                   error=str(exc)[:180] if isinstance(exc, RuntimeError) else type(exc).__name__)
        finally:
            if changed and job.get('state') != 'rollback_failed':
                P.maintenance('sparkDeux', False)


def recipe_args(root, profile, name, *flags):
    """The run-recipe.py command for a profile on lilspark2. `flags` (--setup, --dry-run, --daemon ...) are
    runner options; a profile's extra vLLM args follow '--' and must stay last, so they go after the flags."""
    p = PROFILES.get(profile)
    if not p or p['cluster_only'] or p['held']:
        raise ValueError('No single-Spark recipe for this profile')
    args = [sys.executable, str(root / 'run-recipe.py'), p['recipe'], '--solo', '--tp', '1', '--port', '8000',
            '--gpu-memory-utilization', str(p['gpu_memory']), '--name', name, '-j', '2']
    if p['context']:
        args += ['--max-model-len', str(p['context'])]
    if p['weights']:
        args += ['-v', f"{(root.parent / p['weights']).as_posix()}:{p['mount']}:ro"]
    args += list(flags)
    return args + (['--', *p['extra']] if p['extra'] else [])


def wait_ready(model, timeout, context=65536):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return probe('http://127.0.0.1:8000/v1', model, context)
        except Exception:
            time.sleep(5)
    raise RuntimeError('Model did not pass tool validation before the deadline')


def install_recipes(root, directory, recipes, log):
    """Write gBox's recipes into the runner's recipes folder as new gbox-* files. A file that already exists
    with other content is copied into the trial state folder first, then replaced; identical files are left."""
    for fname, text in recipes.items():
        assert re.fullmatch(r'gbox-[a-z0-9.-]+\.yaml', fname), fname
        path = root / 'recipes' / fname
        current = path.read_text() if path.exists() else None
        if current == text:
            continue
        if current is not None:
            keep = directory / 'recipe-backups'
            keep.mkdir(exist_ok=True)
            (keep / (fname + '.' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()))).write_text(current)
        tmp = path.with_name(fname + '.tmp'); tmp.write_text(text); tmp.replace(path)
        print(f'installed recipe {path}', file=log, flush=True)


def weights_report(folder, model):
    """Every shard named by the checkpoint's index is present; sizes are compared with the Hub when reachable."""
    index = json.loads((folder / 'model.safetensors.index.json').read_text())
    shards = sorted(set(index['weight_map'].values()))
    missing = [s for s in shards if not (folder / s).is_file() or (folder / s).stat().st_size == 0]
    if missing or not (folder / 'config.json').is_file():
        raise RuntimeError(f'Weights incomplete in {folder.name}: {len(missing)} of {len(shards)} shards missing')
    report = {'shards': len(shards), 'bytes': sum((folder / s).stat().st_size for s in shards), 'verified': 'local'}
    try:
        with urllib.request.urlopen(f'https://huggingface.co/api/models/{model}/tree/main', timeout=15) as r:
            sizes = {e['path']: e.get('size') for e in json.load(r)}
    except Exception:
        return report
    wrong = [s for s in shards if sizes.get(s) not in (None, (folder / s).stat().st_size)]
    if wrong:
        raise RuntimeError(f'Weights differ from the Hub in {folder.name}: {", ".join(wrong[:3])}')
    report['verified'] = 'hub'
    return report


def container_running(name):
    p = subprocess.run(['docker', 'inspect', '-f', '{{.State.Running}}', name], capture_output=True, text=True)
    return p.returncode == 0 and p.stdout.strip() == 'true'


def remote(plan):
    """Executed on lilspark2. Never launches a cluster or deletes old containers."""
    import fcntl
    root = Path.home() / 'spark-vllm-docker'
    directory = Path.home() / '.local/state/gbox-model-trials'
    directory.mkdir(parents=True, exist_ok=True)
    assert re.fullmatch('[0-9a-f]{12}', plan['id'])
    assert re.fullmatch('[a-zA-Z0-9_.-]+', plan['container'])
    assert plan['action'] in ('trial_prepare', 'trial_start')
    name = 'gbox-trial-' + plan['id']
    profile = PROFILES[plan['profile']]
    def emit(state, **details):
        print(json.dumps({'state': state, **details}), flush=True)
    with (directory / 'worker.lock').open('w') as lock, (directory / (plan['id'] + '.log')).open('w') as log:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        def run(argv, timeout=120):
            subprocess.run(argv, cwd=root, stdout=log, stderr=log, check=True, timeout=timeout)
        install_recipes(root, directory, plan.get('recipes') or {}, log)
        if plan['action'] == 'trial_prepare':
            emit('preparing')
            run(recipe_args(root, plan['profile'], name, '--setup', '--build-only'), 7200)
            if profile['weights']:
                # Weights the operator placed under ~/models: present and the Hub's sizes, no download.
                try:
                    emit('preparing', weights=weights_report(root.parent / profile['weights'], profile['model']))
                except RuntimeError as exc:
                    emit('failed', error=str(exc)[:180]); raise
            else:
                run(recipe_args(root, plan['profile'], name, '--setup', '--download-only'), 14400)
            emit('prepared'); return
        # Dry-run validation and rollback script presence precede interruption.
        run(recipe_args(root, plan['profile'], name, '--dry-run'))
        old = plan['container']
        # A retained container the operator stopped by hand (for example to serve a
        # GGUF with llama-server) has nothing to drain and is not a rollback target.
        old_running = container_running(old)
        if old_running:
            run(['docker', 'exec', old, 'test', '-x', '/workspace/exec-script.sh'])
            emit('draining')
            deadline = time.monotonic() + 900
            while time.monotonic() < deadline:
                with urllib.request.urlopen('http://127.0.0.1:8000/metrics', timeout=10) as r:
                    metrics = r.read().decode()
                values = re.findall(r'^vllm:num_requests_(?:running|waiting)(?:\{[^\n]*\})?\s+([0-9.eE+-]+)', metrics, re.M)
                if values and sum(float(v) for v in values) == 0:
                    break
                time.sleep(3)
            else:
                raise RuntimeError('Inference did not drain; original server retained')
        stopped = False
        try:
            if old_running:
                stopped = True
                run(['docker', 'stop', '-t', '30', old], 60)
            emit('starting')
            run(recipe_args(root, plan['profile'], name, '--daemon', '--earlyoom'), 300)
            receipt = wait_ready(profile['model'], 1800, profile['context'])
            emit('ready', container=name, rollback_container=old, receipt=receipt); return
        except BaseException:
            if stopped:
                emit('rolling_back')
                subprocess.run(['docker', 'stop', '-t', '10', name], stdout=log, stderr=log, timeout=30)
                try:
                    run(['docker', 'start', old])
                    run(['docker', 'exec', '-d', old, 'bash', '-c', '/workspace/exec-script.sh >> /proc/1/fd/1 2>&1'])
                    receipt = wait_ready(plan['previous_model'], 300)
                    emit('rolled_back', error='Trial failed; original model passed tool validation',
                         rollback_container=old, rollback_receipt=receipt)
                except Exception:
                    emit('rollback_failed', error='Original model could not be validated; maintenance remains active',
                         rollback_container=old)
            raise


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--worker':
        worker(sys.argv[2])
