"""Explicit, durable pull/start jobs for a curated task model on the dedicated Spark."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from . import hermes_delivery as D, hermes_local as L
from .hermes_model_remote import MODEL

SOURCE = 'https://github.com/NVIDIA/dgx-spark-playbooks/blob/main/nvidia/vllm/README.md#run-agent-ready-qwen36-35b-model-with-vllm'
_ACCESS = {}


class ModelAction(BaseModel):
    action: str
    model: str


def settings():
    return L.settings().nodes.get('sparkDeux', {}).get('management', {})


def ssh_args():
    s = settings()
    host, user = s.get('host', ''), s.get('user', '')
    if not re.fullmatch(r'[a-zA-Z0-9.-]+', host) or not re.fullmatch(r'[a-zA-Z0-9_-]+', user):
        raise ValueError('SSH management is not configured')
    args = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', '-o', 'StrictHostKeyChecking=yes']
    if s.get('identity_file'):
        args += ['-i', str(Path(s['identity_file']).expanduser())]
    return args + [user+'@'+host]


def _path():
    return D.state_dir() / 'model-management.json'


def _read():
    try:
        return json.loads(_path().read_text())
    except (OSError, ValueError):
        return {}


def _save(data):
    p = _path();p.parent.mkdir(parents=True, exist_ok=True)
    temp = p.with_suffix('.tmp');temp.write_text(json.dumps(data, indent=2));temp.replace(p)


def access():
    now = time.time()
    if _ACCESS.get('at', 0) > now - 60:
        return _ACCESS['value']
    try:
        p = subprocess.run(ssh_args()+['docker info --format "{{.ServerVersion}}"'], capture_output=True, timeout=12)
        value = {'ready': p.returncode == 0,
                 'reason': 'SSH and Docker ready' if p.returncode == 0 else 'SSH key or Docker permission unavailable'}
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        value = {'ready': False, 'reason': str(exc) if isinstance(exc, ValueError) else type(exc).__name__}
    _ACCESS.update(at=now, value=value)
    return value


def status():
    if not settings():
        return {'configured': False}
    data = _read()
    return {'configured': True, 'access': access(), 'job': data,
        'recommendation': {'model': MODEL, 'source': SOURCE,
            'title': 'Agent and coding throughput candidate',
            'reason': 'NVIDIA provides a DGX Spark agent recipe for this sparse model. Compare completed tasks and correctness against the current model before keeping it; superiority is not yet measured.',
            'gpu_memory_utilization': .9, 'context_tokens': 65536,
            'downloaded': MODEL in data.get('downloaded', []),
            'current': data.get('state') == 'ready' and data.get('model') == MODEL}}


def submit(action, model):
    if action not in ('pull', 'start') or model != MODEL:
        raise ValueError('Unknown model action')
    if not access()['ready']:
        raise RuntimeError(access()['reason'])
    with D.locked('model-management'):
        data = _read()
        if data.get('state') in ('queued', 'downloading', 'draining', 'starting'):
            pid = data.get('pid')
            if pid:
                try:
                    os.kill(pid, 0)
                    raise RuntimeError('A model action is already running')
                except ProcessLookupError:
                    pass
            else:
                raise RuntimeError('A model action is already queued')
        if action == 'start' and MODEL not in data.get('downloaded', []):
            raise ValueError('Pull the model before starting it')
        job = {'id': uuid.uuid4().hex[:12], 'action': action, 'model': model, 'state': 'queued',
               'created_at': time.time(), 'downloaded': data.get('downloaded', []),
               'container': data.get('container') or settings().get('container')}
        _save(job)
        try:
            p = subprocess.Popen([sys.executable, '-m', 'gbox.hermes_models', '--worker', job['id']],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
            job['pid'] = p.pid;_save(job)
        except OSError:
            job.update(state='failed', error='Could not start management worker');_save(job)
            raise
        return job


def worker(job_id):
    from . import hermes_pool as P
    with D.locked('model-management'):
        job = _read()
        assert job.get('id') == job_id
    plan = {k: job[k] for k in ('id', 'action', 'model', 'container')}
    if job['action'] == 'start':
        P.maintenance('sparkDeux', True)  # New calls hand off to prime; existing streams finish.
    try:
        source = Path(__file__).with_name('hermes_model_remote.py').read_text()
        # Send code and plan on stdin; neither shell interpolation nor secret arguments.
        wire = ('import sys,json; plan=json.loads('+repr(json.dumps(plan))+'); '
                'exec(compile('+repr(source.split("if __name__ == '__main__':")[0])+',"gbox-model-remote","exec")); '
                'main(plan)')
        p = subprocess.Popen(ssh_args()+['python3 -'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True)
        p.stdin.write(wire);p.stdin.close()
        for line in p.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            with D.locked('model-management'):
                job.update(event, updated_at=time.time());_save(job)
        if p.wait() != 0:
            raise RuntimeError('Remote action failed; inspect the retained container on sparkDeux')
        if job.get('state') == 'downloaded':
            job['downloaded'] = [MODEL]
        elif job.get('state') == 'ready':
            with D.locked('local-nodes'):
                data = P._state();data.setdefault('nodes', {}).setdefault('sparkDeux', {})['model'] = MODEL
                dest = D.state_dir()/'local-nodes.json';temp = dest.with_suffix('.tmp')
                temp.write_text(json.dumps(data, indent=2));temp.replace(dest)
            P.register_providers()
        else:
            raise RuntimeError('No successful management acknowledgment')
    except Exception as exc:
        job.update(state='failed', error=str(exc)[:180])
    finally:
        if job['action'] == 'start':
            P.maintenance('sparkDeux', False)  # Preserve any operator toggle made during the switch.
        with D.locked('model-management'):
            job.update(updated_at=time.time());_save(job)


def routes(app, auth):
    @app.post('/api/hermes/local/models/action')
    def action(body: ModelAction, actor=Depends(auth)):
        try:
            return submit(body.action, body.model)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from None


if __name__ == '__main__' and len(sys.argv) == 3 and sys.argv[1] == '--worker':
    worker(sys.argv[2])
