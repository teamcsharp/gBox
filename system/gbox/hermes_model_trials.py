"""Operator-selected, single-Spark model recipes with durable progress and rollback.

The remote half uses only the standard library and the installed recipe runner.
Model names are an allowlist; no arbitrary commands arrive through the API.
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

PROFILES = {
    'qwen-flash': ('Qwen3.8 Flash Next FP4', 'nvidia/Qwen3.8-Flash-Next-FP4-Local', 'qwen3.8-flash-next-nvfp4-solo', False),
    'qwen-coder': ('Qwen3-Coder-Next FP8', 'Qwen/Qwen3-Coder-Next-FP8', 'qwen3-coder-next-fp8', False),
    'glm-flash': ('GLM-5.3 Flash NVFP4', 'nvidia/GLM-5.3-Flash-FP4-Local', 'glm-5.3-flash', True),
    'nemotron-super': ('Nemotron 3 Super 120B NVFP4', 'nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4', 'nemotron-3-super-nvfp4', False),
    'nemotron-bolt': ('Nemotron 3.5 Bolt 74B-A9B 24GB', 'nvidia/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB', 'nemotron-3.5-bolt-24gb', False),
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
        {'id': key, 'title': p[0], 'model': p[1], 'recipe': p[2],
         'cluster_only': p[3], 'prepared': key in data.get('prepared', []),
         'current': bool(current and current.model == p[1])}
        for key, p in PROFILES.items()]}


def probe(upstream, expected):
    """Require native tools and a follow-up response, not just /models health."""
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
    return {'model': expected, 'context_tokens': min(65536, int(model.get('max_model_len') or 65536)),
            'elapsed_s': round(time.time() - start, 3), 'calls': [first.get('usage'), second.get('usage')],
            'checked_at': time.time()}


def submit(action, profile):
    from . import hermes_delivery as D, hermes_models as M
    if action not in ('trial_prepare', 'trial_start', 'trial_adopt') or profile not in PROFILES:
        raise ValueError('Unknown model trial action')
    if PROFILES[profile][3]:
        raise ValueError('This checkpoint requires about 166 GiB; the installed cluster recipe cannot run on this 128 GB Spark')
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
                job.update(event, updated_at=time.time()); data['job'] = job; save(data)
        changed = False
        try:
            if action == 'trial_start':
                P.maintenance('sparkDeux', True); changed = True
            if action != 'trial_adopt':
                plan = {'id': job_id, 'action': action, 'profile': profile,
                        'container': data.get('container', 'vllm_node')}
                source = Path(__file__).read_text().split("if __name__ == '__main__':")[0]
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
                    raise RuntimeError('Remote action failed; inspect the retained trial log on lilspark2')
                if action == 'trial_prepare':
                    data['prepared'] = sorted(set(data.get('prepared', [])) | {profile})
                    update(state='prepared'); return
                data['container'] = job['container']
            update(state='validating')
            receipt = probe(UPSTREAM, PROFILES[profile][1])
            with D.locked('local-nodes'):
                state = P._state()
                state.setdefault('nodes', {}).setdefault('sparkDeux', {}).update(
                    model=receipt['model'], upstream=UPSTREAM, context_tokens=receipt['context_tokens'], changed_at=time.time())
                path = D.state_dir() / 'local-nodes.json'
                temp = path.with_suffix('.tmp'); temp.write_text(json.dumps(state, indent=2)); temp.replace(path)
            P.register_providers()
            # Trials begin at four task slots; increase only after observing results.
            P.set_capacity('sparkDeux', 4)
            data.setdefault('history', []).append({'job': job_id, 'profile': profile, **receipt})
            update(state='ready', receipt=receipt)
        except Exception as exc:
            # No raw SSH/HTTP bodies or environment values are persisted.
            update(state='failed', error=str(exc)[:180] if isinstance(exc, RuntimeError) else type(exc).__name__)
        finally:
            if changed:
                P.maintenance('sparkDeux', False)


def recipe_args(root, profile, name):
    if profile not in PROFILES or PROFILES[profile][3]:
        raise ValueError('No single-Spark recipe for this profile')
    return [sys.executable, str(root / 'run-recipe.py'), PROFILES[profile][2], '--solo',
            '--tp', '1', '--port', '8000', '--max-model-len', '65536', '--name', name, '-j', '2']


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
    args = recipe_args(root, plan['profile'], name)
    def emit(state, **details):
        print(json.dumps({'state': state, **details}), flush=True)
    with (directory / 'worker.lock').open('w') as lock, (directory / (plan['id'] + '.log')).open('w') as log:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        def run(argv, timeout=120):
            subprocess.run(argv, cwd=root, stdout=log, stderr=log, check=True, timeout=timeout)
        if plan['action'] == 'trial_prepare':
            emit('preparing')
            run(args + ['--setup', '--build-only'], 7200)
            run(args + ['--setup', '--download-only'], 14400)
            emit('prepared'); return
        # Dry-run validation and rollback script presence precede interruption.
        run(args + ['--dry-run'])
        old = plan['container']
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
            stopped = True
            run(['docker', 'stop', '-t', '30', old], 60)
            emit('starting')
            run(args + ['--daemon', '--earlyoom'], 300)
            deadline = time.monotonic() + 1800
            while time.monotonic() < deadline:
                try:
                    receipt = probe('http://127.0.0.1:8000/v1', PROFILES[plan['profile']][1])
                    emit('ready', container=name, rollback_container=old, receipt=receipt); return
                except Exception:
                    time.sleep(5)
            raise RuntimeError('New model did not pass tool validation')
        except BaseException:
            if stopped:
                emit('rolling_back')
                subprocess.run(['docker', 'stop', '-t', '10', name], stdout=log, stderr=log, timeout=30)
                run(['docker', 'start', old])
                run(['docker', 'exec', '-d', old, 'bash', '-c', '/workspace/exec-script.sh >> /proc/1/fd/1 2>&1'])
                emit('failed', error='Model launch failed; original container restarted', rollback_container=old)
            raise


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--worker':
        worker(sys.argv[2])
