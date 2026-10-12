"""Capture an emulator incident before attempting checkpoint-preserving recovery."""
from __future__ import annotations

import base64
import concurrent.futures
import datetime as dt
import io
import json
import re
import threading
import time
from typing import Literal

from fastapi import Depends, HTTPException
from PIL import Image, ImageChops, ImageStat
from pydantic import BaseModel, Field

from .models import Job, JobState

WINDOW_SURFACE = 'window-surface'   # adapters.WINDOW_SURFACE: the emulator window rendered itself


# Versioned recipes keep the menu and the backend execution plan in sync. Add new
# repairs here after reproducing and testing them, rather than accepting shell text.
RECIPES = [
    {'id': 'auto', 'label': 'Report and recover automatically',
     'detail': 'Capture evidence, resume, then restore a checkpoint if a restart is needed.'},
    {'id': 'diagnose', 'label': 'Capture diagnostics and investigate',
     'detail': 'Save screenshots, state, logs, ROM paths and drivers; dispatch Hermes.'},
    {'id': 'resume', 'label': 'Resume and reconnect the display',
     'detail': 'Preserve the moment, reconnect the game view and check for visible motion.'},
    {'id': 'restart', 'label': 'Restart from a captured checkpoint',
     'detail': 'Relaunch the same ROM and mod, then load the preserved state.'},
    {'id': 'best_graphics', 'label': 'Apply this PC’s GPU preset',
     'detail': 'Record current settings, save the GPU preset, restart and load the checkpoint.'},
]


# Probe frames are resized to 96x72; the top ~20% is where HUD timers, score and
# status text are drawn by the CPU even while every 3D/textured layer stays black
# (angrylion RDP + HLE RSP on MK4). A changing timer must not count as gameplay
# motion, so the recovery motion check ignores this band.
HUD_BAND_ROWS = 14


class IncidentIn(BaseModel):
    image_b64: str | None = None
    attachments: list[dict] = Field(default_factory=list)
    context: dict = Field(default_factory=dict)
    note: str = "The game froze, stopped displaying, or stopped responding."
    action: Literal['auto', 'diagnose', 'resume', 'restart', 'best_graphics'] = 'auto'


def redacted(value):
    if isinstance(value, dict):
        return {k: "[redacted]" if re.search(r"(?i)(?:api.?key|password|authorization|secret|access.?token|refresh.?token)", k)
                else redacted(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redacted(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)([?&]token=)[^&\s]+", r"\1[redacted]", value)
        value = re.sub(r"(?i)(Bearer\s+)\S+", r"\1[redacted]", value)
        value = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}", "[redacted]", value)
        return re.sub(r"(?im)\b(api[_-]?key|password|access[_-]?token|refresh[_-]?token)(\s*[:=]\s*)[^\s,]+",
                      r"\1\2[redacted]", value)
    return value


def markdown(data):
    return "# Emulation incident\n\n" + "\n\n".join(
        f"## {title}\n\n```json\n{json.dumps(redacted(value), indent=2, default=str, ensure_ascii=False)}\n```"
        for title, value in data.items()) + "\n"


class Incident:
    def __init__(self, store, report, session, game, worker, run_job, dispatch, job, sleep=time.sleep):
        self.store, self.rid, self.session, self.game = store, report['id'], session, game
        self.worker, self.run_job, self.dispatch, self.job, self.sleep = worker, run_job, dispatch, job, sleep
        self.sid = session['session_id']
        self.action = report.get('context', {}).get('troubleshooting_action', 'auto')
        self.calls = {}
        self.data = {'Captured at': dt.datetime.now(dt.timezone.utc).isoformat(), 'Operator report': report['body'],
                     'Session and emulator': session, 'ROM, paths and core': game, 'Worker and drivers': worker,
                     'Application': report.get('context', {}),
                     'Tasks at capture': sorted(store.all('job'), key=lambda j: -j.get('created', 0))[:80]}
        self.data['Troubleshooting recipe'] = {'version': 1, 'action': self.action}

    def step(self, action, result, status='finished', attachment=None, **context):
        result = redacted(str(result))[:6000]
        with self.store.lock:
            report = self.store.get('request', self.rid)
            report.setdefault('context', {}).update(context)
            report['messages'].append({'author': 'agent', 'text': result, 'ts': time.time(),
                'attachments': [attachment] if attachment else [],
                'task_step': {'action': action, 'attempt': '1', 'result': result, 'status': status}})
            self.store.put('request', self.rid, report)
            current = self.store.get('job', self.job.id)
            current['progress'] = {'msg': action, 'ts': time.time()}
            current['progress_log'] = (current.get('progress_log') or []) + [action + ': ' + result[:500]]
            self.store.put('job', self.job.id, current)

    def artifact(self, name, content, media_type):
        ref = self.store.put_artifact(content, name, media_type, {'request': self.rid, 'job': self.job.id})
        return {'sha256': ref.sha256, 'name': name, 'type': media_type, 'size': ref.size}

    def call(self, tool, data, wait=35):
        with self.store.lock:
            if (self.store.get('job', self.job.id) or {}).get('cancel'):
                raise RuntimeError('Recovery cancelled by the operator; captured evidence retained')
            self.calls[tool] = self.calls.get(tool, 0) + 1
        return self.run_job(tool, data, self.worker['id'], wait)

    def op(self, op, **args):
        return self.call('session_op', {'session_id': self.sid, 'op': op, 'args': args})

    def frame(self, label):
        out = self.call('get_frame', {'session_id': self.sid})
        ref = self.store.get('artifact', out.get('sha256'))
        if not ref:
            raise RuntimeError('The frame job did not upload its screenshot')
        raw = self.store.artifact_path(out['sha256']).read_bytes()
        image = Image.open(io.BytesIO(raw)).convert('RGB').resize((96, 72))
        luma = ImageStat.Stat(image.convert('L')).mean[0]
        covered = out.get('covered', 0)
        self.frame_source = out.get('capture_source')
        surface = covered and self.frame_source == WINDOW_SURFACE
        self.step(label, f'Game screenshot captured; mean RGB luminance {luma:.2f}'
                         + (f'; {covered}/9 capture points covered by another window'
                            + (", pixels rendered from the emulator's own window." if surface else '.')
                            if covered else '.'),
                  attachment={'sha256': ref['sha256'], 'name': label.replace(' ', '-') + '.png',
                              'type': 'image/png', 'size': ref['size']})
        return image, luma, covered

    def observe(self):
        previous, visible, covered_error = None, False, None
        previous_source = None
        errors = []
        for delay in (0, 2, 4, 8):
            self.sleep(delay)
            try:
                image, luma, covered = self.frame('verify recovery frame')
                # PrintWindow renders the emulator's own surface, so its pixels are the game even when
                # another window covers it. Compare only frames captured the same way (#1057).
                source = WINDOW_SURFACE if covered and getattr(self, 'frame_source', None) == WINDOW_SURFACE else 'screen'
                if source != previous_source:
                    previous = None
                previous_source = source
                if covered and source != WINDOW_SURFACE:
                    covered_error = f'frame capture had {covered}/9 points covered by another window (pixels are the window surface)'
                    # A newly exposed static game is not motion relative to an
                    # obscuring window. Start a fresh clear-frame comparison.
                    previous = None
                    continue
                visible |= luma > 3
                if previous is not None and luma > 3:
                    diff = ImageChops.difference(previous, image)
                    if diff.height > HUD_BAND_ROWS:
                        # HUD timers keep ticking on a dead scene; motion must
                        # come from the playfield below the HUD band.
                        diff = diff.crop((0, HUD_BAND_ROWS, diff.width, diff.height))
                    if ImageStat.Stat(diff).mean[0] > .6:
                        return {'visible': True, 'motion': True}
                previous = image
            except Exception as exc:
                errors.append(str(exc)[:500])
        if covered_error and not visible:
            errors.append(covered_error)
        return {'visible': visible, 'motion': False, 'errors': errors}

    def capture(self):
        running = self.session.get('state') == 'running'
        if running:
            try:
                self.frame('capture reported moment')
            except Exception as exc:
                self.step('capture reported moment', f'Session screenshot unavailable: {exc}', 'failed')
        checkpoint = None
        if running:
            slot = 80 + sum(1 for r in self.store.all('request') if (r.get('context') or {}).get('emulation_issue')
                            and (r.get('context') or {}).get('session_id') == self.sid)
            try:
                if self.session.get('adapter') in ('retroarch', 'dolphin'):
                    saved = self.call('state_transfer', {'session_id': self.sid, 'op': 'export', 'slot': slot}, wait=55)['result']
                    checkpoint = saved['artifact']
                    ref = self.store.get('artifact', checkpoint)
                    if not ref:
                        raise RuntimeError('Checkpoint bytes were not uploaded')
                    self.data['Saved program state'] = saved
                    filename = saved.get('file', '')
                    if self.session.get('adapter') == 'retroarch' and '.state' in filename:
                        suffix = filename.rsplit('.state', 1)[-1]
                        slot = int(suffix) if suffix.isdigit() else 0
                    elif self.session.get('adapter') == 'dolphin':
                        slot = 1
                    self.step('preserve program state', f"Portable checkpoint retained: {saved['file']} ({saved['bytes']} bytes).",
                              attachment={'sha256': checkpoint, 'name': saved['file'], 'type': ref['media_type'], 'size': ref['size']},
                              state_artifact=checkpoint, state_slot=slot)
                else:
                    saved = self.op('save_state', slot=slot)
                    self.data['Saved program state'] = saved
                    self.step('preserve program state', 'Local save state created; portable export is unavailable for this emulator.',
                              state_slot=slot, local_checkpoint=True)
            except Exception as exc:
                self.data['Saved program state'] = {'unavailable': str(exc)}
                self.step('preserve program state', f'Save-state capture failed: {exc}', 'failed')
        # Each read may fail when the emulator is hung; retain those failures as diagnostic evidence.
        checks = [('Runtime status', lambda: self.op('query_runtime')),
                  ('Emulator log', lambda: self.op('log_tail', n=100000)),
                  ('Machine tasks and resources', lambda: self.call('tasks', {'op': 'list'})),
                  ('Graphics preferences and GPU', lambda: self.call('graphics', {
                      'game_id': self.game['game_id'], 'session_id': self.sid if running else '', 'op': 'get'}))]
        if not running:
            checks = checks[2:]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(fn): name for name, fn in checks}
            for future in concurrent.futures.as_completed(futures):
                name = futures[future]
                try:
                    self.data[name] = future.result()
                    self.step('capture ' + name.lower(), 'Captured ' + name + '.')
                except Exception as exc:
                    self.data[name] = {'unavailable': str(exc)}
                    self.step('capture ' + name.lower(), str(exc), 'failed')
        self.step('attach diagnostic markdown', 'Session, ROM paths, core, GPU/drivers, logs, tasks, and checkpoint results attached.',
                  attachment=self.artifact('emulation-diagnostics-complete.md', markdown(self.data).encode(), 'text/markdown'))
        return checkpoint

    def recover(self, checkpoint):
        running = self.session.get('state') == 'running'
        if self.action == 'diagnose':
            return {'session_id': self.sid, 'method': 'diagnostics', 'diagnostics_only': True,
                    'motion': False, 'moment_restored': False}
        if running and self.action in ('auto', 'resume'):
            try:
                self.op('resume')
                self.step('resume emulator', 'Resume requested; checking real game frames.')
            except Exception as exc:
                self.step('resume emulator', str(exc), 'failed')
            result = self.observe()
            if result['motion']:
                return result | {'session_id': self.sid, 'method': 'resume and reconnect display', 'moment_restored': True}
            if self.action == 'resume':
                return result | {'session_id': self.sid, 'method': 'resume', 'moment_restored': False}
        if self.action == 'resume' and not running:
            raise RuntimeError('The session has ended. Use restart or automatic recovery to relaunch it.')
        if running and not checkpoint:
            self.step('retain current session', 'Automatic relaunch deferred because no portable checkpoint could be preserved.', 'failed')
            return {'visible': False, 'motion': False, 'session_id': self.sid,
                    'method': 'diagnosis required', 'moment_restored': False}
        other = [s for s in self.store.all('session') if s.get('state') == 'running'
                 and s['session_id'] != self.sid and s['session_id'].split('-')[0] == self.worker['id']]
        if other:
            raise RuntimeError('Another game is now running on this PC. Recovery will not interrupt it; evidence is retained.')
        if self.action == 'best_graphics':
            settings = self.call('graphics', {'game_id': self.game['game_id'],
                                 'session_id': self.sid if running else '', 'op': 'best'})
            self.data['Applied GPU preset'] = settings
            self.step('apply GPU preset', json.dumps(settings))
        # Restart only after preserving the running session, or if it has already ended.
        out = self.call('launch_game', {'game': self.game,
                        'mod': self.session.get('mod') or (self.session.get('detail') or {}).get('mod') or ''}, wait=150)
        old_sid, self.sid = self.sid, out['session_id']
        with self.store.lock:
            original = self.store.get('session', old_sid) or self.session
            self.store.put('session', old_sid, original | {'replaced_by': self.sid, 'state': 'ended'})
        self.step('relaunch same ROM and mod', 'New emulator session: ' + self.sid, recovery_session_id=self.sid)
        restored = False
        if checkpoint:
            self.sleep(6)
            try:
                self.call('state_transfer', {'session_id': self.sid, 'op': 'import', 'artifact': checkpoint}, wait=55)
                restored = True
                self.step('restore preserved checkpoint', 'Checkpoint load requested; verifying visible game progress.')
            except Exception as exc:
                self.step('restore preserved checkpoint', f'Restore failed; checkpoint remains attached: {exc}', 'failed')
        result = self.observe()
        return result | {'session_id': self.sid, 'method': 'relaunch', 'checkpoint_load_requested': restored,
                         'moment_restored': False}  # moving pixels alone cannot prove exact saved-moment identity

    def run(self):
        result, error = None, None
        try:
            checkpoint = self.capture()
            result = self.recover(checkpoint)
            self.step('recovery result', json.dumps(result),
                      'finished' if result['motion'] or result.get('diagnostics_only') else 'failed', recovery=result)
        except Exception as exc:
            error = redacted(str(exc))[:1500]
            self.step('recovery result', error, 'failed')
        finally:
            self.data['Recovery result'] = result or {'error': error}
            self.step('attach recovery markdown', 'Recovery attempts and outcomes attached.',
                      attachment=self.artifact('emulation-recovery.md', markdown(self.data).encode(), 'text/markdown'))
            try:
                report = self.store.get('request', self.rid)
                jid = self.dispatch(self.rid, report['number'])
                self.step('dispatch root-cause investigation', f'Hermes cloud investigation queued: {jid}.', 'running', hermes_job_id=jid)
            except Exception as exc:
                self.step('dispatch root-cause investigation', f'Cloud dispatch unavailable: {exc}', 'failed')
            with self.store.lock:
                report = self.store.get('request', self.rid)
                report['metrics'].update({'tokens_detail': {'token_count_unavailable': 1}, 'tools': self.calls,
                                          'duration_s': time.time() - self.job.started, 'turns': 1})
                self.store.put('request', self.rid, report)
                current = self.store.get('job', self.job.id)
                succeeded = result and (result['motion'] or result.get('diagnostics_only'))
                self.store.put('job', self.job.id, current | {'state': JobState.SUCCEEDED if succeeded else JobState.FAILED,
                    'finished': time.time(), 'output': result, 'error': error or (None if succeeded else
                    'Visible game progress was not verified; diagnostic evidence is retained for investigation.')})


def routes(app, store, auth, create_request, run_job, dispatch):
    @app.get('/api/sessions/{sid}/troubleshooting')
    def troubleshooting_options(sid: str, actor=Depends(auth)):
        if not store.get('session', sid):
            raise HTTPException(404, 'Session not found')
        return {'version': 1, 'recipes': RECIPES}

    @app.post('/api/sessions/{sid}/emulation-issue')
    def report_and_recover(sid: str, body: IncidentIn, actor=Depends(auth)):
        with store.lock:
            session = store.get('session', sid)
            if not session:
                raise HTTPException(404, 'Session not found')
            game = store.catalog_get(session.get('game_id') or '')
            if not game:
                raise HTTPException(409, 'This session has no ROM catalog entry to diagnose or relaunch')
            for job in store.all('job'):
                if job.get('tool') == 'emulation_recovery' and job.get('input', {}).get('session_id') == sid and job['state'] in ('queued', 'running'):
                    return {'request': store.get('request', job['parent_request_id']), 'job': job}
            worker_id = sid.split('-')[0]
            worker = store.get('worker', worker_id) or {'id': worker_id, 'name': (session.get('detail') or {}).get('worker_name')}
            captured = {'Captured at': dt.datetime.now(dt.timezone.utc).isoformat(), 'Session and emulator': session,
                        'ROM, paths and core': game, 'Worker and drivers': worker, 'Application': body.context,
                        'Tasks at capture': sorted(store.all('job'), key=lambda j: -j.get('created', 0))[:80]}
            attachments = []
            for item in body.attachments[:18]:
                item = dict(item)
                if item.get('type', '').startswith('text/') or item.get('type') == 'application/json':
                    try:
                        text = base64.b64decode(item['b64']).decode('utf-8', 'replace')
                        item['b64'] = base64.b64encode(redacted(text).encode()).decode()
                    except (ValueError, KeyError):
                        continue
                attachments.append(item)
            attachments.append({'name': 'emulation-diagnostics.md', 'type': 'text/markdown',
                                'b64': base64.b64encode(markdown(captured).encode()).decode()})
            report = create_request({'title': ('Emulation issue: ' + (session.get('title') or game['title']))[:140],
                'body': body.note + '\n\nSelected troubleshooting: ' + body.action +
                        '. Capture diagnostics, preserve the program state, investigate the cause, and restore gameplay.',
                'source': 'app', 'kind': 'screenshot' if body.image_b64 else 'text', 'image_b64': body.image_b64,
                'attachments': attachments, 'context': redacted(body.context) | {'session_id': sid, 'game_id': game['game_id'],
                    'emulation_issue': True, 'auto_report': True, 'save_state_requested': True,
                    'troubleshooting_action': body.action, 'troubleshooting_recipe_version': 1,
                    'recovery_requested': body.action != 'diagnose'}}, actor)
            report.update(status='in_progress', started=time.time())
            job = Job(tool='emulation_recovery', input={'session_id': sid, 'game_id': game['game_id'], 'action': body.action},
                      parent_request_id=report['id'], state=JobState.RUNNING, started=time.time(), worker_id=worker_id)
            report['context']['recovery_job_id'] = job.id
            store.put('request', report['id'], report)
            store.put('job', job.id, job.model_dump())
            store.audit(actor, 'session.emulation_issue', sid, {'request': report['id'], 'recovery_job': job.id})
        incident = Incident(store, report, session, game, worker,
                            lambda tool, data, wid, wait: run_job(tool, data, wid, wait, report['id'], actor), dispatch, job)
        threading.Thread(target=incident.run, daemon=True, name='emulation-recovery-' + job.id).start()
        return {'request': report, 'job': job.model_dump()}
