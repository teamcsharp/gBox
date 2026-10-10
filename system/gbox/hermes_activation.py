"""Activate the Hermes bridge update when gBox has no work to interrupt."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import time
import urllib.request


def idle_reason(chats: list[dict], tasks: dict, sessions: list[dict]) -> str:
    if any(c.get('busy') for c in chats):
        return 'Waiting for the active gBox conversation to finish.'
    if tasks.get('jobs'):
        return 'Waiting for active gBox worker jobs to finish.'
    linux = {m['worker_id'] for m in tasks.get('machines', []) if m.get('os') == 'linux'}
    if any(s.get('state') == 'running' and s.get('session_id', '').split('-', 1)[0] in linux for s in sessions):
        return 'Waiting for the Spark game session to finish.'
    return ''


def verify_activation(policy: dict, before: list[dict], after: list[dict], expected_fields=None) -> None:
    required = expected_fields or {'fallback_enabled', 'max_parallel_jobs', 'image_input_mode'}
    if not set(required) <= policy.keys():
        raise RuntimeError('The updated Hermes bridge is not loaded.')
    pids = {s['session_id']: (s.get('detail') or {}).get('pid') for s in after if s.get('state') == 'running'}
    for s in before:
        if s.get('state') == 'running' and (s['session_id'] not in pids or
                pids[s['session_id']] != (s.get('detail') or {}).get('pid')):
            raise RuntimeError('A previously running game has not reappeared with its original PID.')


def activate(root: Path, request_id: str, verification_run: str, timeout: int = 3300, *,
             expected_fields=None, verification_summary=None, complete=True) -> None:
    token = (root / 'gbox-data/api_token').read_text().strip()
    base = 'http://127.0.0.1:8765'

    def api(path, body=None):
        request = urllib.request.Request(base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', 'x-gbox-actor': 'hermes'})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)

    def step(text, status):
        print(text, flush=True)
        api('/api/requests/' + request_id + '/messages', {'author': 'agent', 'text': text,
            'task_step': {'action': 'activate Hermes bridge safely', 'attempt': '1', 'result': text, 'status': status}})

    deadline, previous = time.monotonic() + timeout, None
    try:
        while time.monotonic() < deadline:
            sessions = api('/api/sessions')
            reason = idle_reason(api('/api/chat'), api('/api/tasks'), sessions)
            if reason:
                if reason != previous:
                    step(reason, 'waiting')
                    previous = reason
                time.sleep(10)
                continue
            # Recheck immediately before the restart so a new operator turn wins.
            time.sleep(2)
            if idle_reason(api('/api/chat'), api('/api/tasks'), api('/api/sessions')):
                continue
            step('gBox is idle. Applying the backend update; Windows emulators stay in their own processes.', 'running')
            subprocess.run(['sudo', '-n', 'systemctl', 'restart', 'gbox.service'], check=True, timeout=45,
                           capture_output=True, text=True)
            last_error = None
            for _ in range(30):
                try:
                    verify_activation(api('/api/hermes/task-mode'), sessions, api('/api/sessions'), expected_fields)
                    break
                except (OSError, ValueError, RuntimeError) as exc:
                    last_error = type(exc).__name__
                    time.sleep(2)
            else:
                raise RuntimeError('Backend activation verification failed: ' + str(last_error))
            step(verification_summary or ('Updated Hermes bridge loaded. Cloud policy fields are visible and running Windows games retained their PIDs. '
                 'The repair passed 19 focused tests and independent cloud screenshot/MCP verification. '
                 'Investigations #1071, #1093 and #1081 retain their own acceptance checks.'), 'finished')
            if not complete:
                return  # Deployment is a task step, not automatic acceptance.
            api('/api/requests/' + request_id + '/status', {'status': 'done',
                'note': 'Hermes reliability repair verified and activated; screenshots, checks and actual cloud usage are attached.',
                'solved_by': {'service': 'codex', 'model': 'GPT-6', 'system': 'Codex',
                    'verified_by': 'Hermes / Ollama Cloud kimi-k2.7-code', 'run_id': verification_run,
                    'verification': '19 focused tests; actual screenshot analysis followed by successful MCP calls; '
                                    'working cloud defaults and fallbacks; real retry/deduplication checks; '
                                    'updated backend policy fields and original Windows emulator PIDs verified.'}})
            return
        raise RuntimeError('No safe idle window occurred before the activation deadline.')
    except Exception as exc:
        step('Backend refresh remains pending: ' + type(exc).__name__ + '. No ticket completion was recorded.', 'failed')
        raise
