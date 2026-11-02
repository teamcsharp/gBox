"""Bounded, read-only game evidence runs. Crystals retain provenance, not input authority.

This module never sends game input, captures a GPU frame, writes native memory,
launches an emulator, or follows a replacement session. Model text is a hypothesis.
"""
import hashlib
import json
import math
import threading
import time
import uuid

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

SCHEMA = 'gbox.analysis.crystal.v1'
TERMINAL = {'completed', 'cancelled', 'interrupted', 'failed'}
FEATURES = ('mapping', 'autoplay', 'mission', 'inventory', 'mods', 'extraction', 'replacement')
MODEL_FINAL = {'succeeded', 'failed', 'rejected', 'invalid', 'cancelled'}


def finite_json(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None  # unavailable, never a fabricated zero counter
    if isinstance(value, dict):
        return {str(k): finite_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite_json(v) for v in value]
    return value


def packed(value):
    return json.dumps(finite_json(value), sort_keys=True, separators=(',', ':'), default=str, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(packed(value)).hexdigest()


def bounded(value, size=16384):
    value = finite_json(value)
    raw = packed(value)
    if len(raw) <= size:
        return value
    return {'truncated': True, 'original_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'preview': raw[:size].decode('utf-8', 'replace')}


def identity(session):
    detail = session.get('detail') or {}
    return {k: session.get(k) for k in ('session_id', 'game_id', 'started', 'worker_id', 'adapter', 'mod')} | {
        'process': {k: detail[k] for k in ('pid', 'process_created', 'process_started', 'native_pid') if k in detail}}


class Start(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_id: str = Field('', max_length=160)
    game_id: str = Field('', max_length=160)
    build: str = Field('', max_length=200)
    duration_s: int = Field(300, ge=15, le=600)
    interval_s: int = Field(3, ge=2, le=10)
    local_model: StrictBool | None = None  # None follows this title's stored preference

    @model_validator(mode='after')
    def target(self):
        if not self.session_id and not self.game_id:
            raise ValueError('Choose a title or an exact live session')
        return self


class ModelRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    worker_id: str = Field(min_length=1, max_length=160)
    allow_during_gameplay: StrictBool = False


class Preferences(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requested: dict[str, StrictBool] = {}
    local_model: StrictBool = True

    @model_validator(mode='after')
    def keys(self):
        if set(self.requested) - set(FEATURES):
            raise ValueError('Unknown analysis feature')
        return self


def exact_jobs(store, run):
    """Use the existing session index, never a title-name or newest-session guess."""
    target = run['target']
    sid = target.get('session_id')
    with store.reading() as db:
        if sid:
            rows = db.execute("SELECT id FROM docs WHERE kind='job' AND json_extract(body,'$.input.session_id')=? "
                              "ORDER BY rowid DESC LIMIT 30", (sid,)).fetchall()
        else:
            rows = db.execute("SELECT id FROM (SELECT id,body FROM docs WHERE kind='job' ORDER BY rowid DESC LIMIT 200) "
                              "WHERE json_extract(body,'$.input.game_id')=? "
                              "AND COALESCE(json_extract(body,'$.input.mod'),'')=? "
                              "AND COALESCE(json_extract(body,'$.input.session_id'),'')='' LIMIT 30",
                              (target['game_id'], target.get('mod') or '')).fetchall()
    # Sort only identifiers. A multi-megabyte tool result must not be copied into
    # SQLite's sorting temporary files for every three-second evidence poll.
    jobs = [j for row in rows if (j := store.get('job', row[0]))]
    jid = run.get('model_job_id')
    if jid and (j := store.get('job', jid)) and all(x['id'] != jid for x in jobs):
        jobs.insert(0, j)
    return jobs


def capability_rows(worker, observer, requested):
    tools = set((worker or {}).get('tools') or [])
    candidates = {
        'mapping': ('read_memory', 'memory_search', 'analyze_binary'),
        'autoplay': ('autoplay',), 'mission': ('read_memory',),
        'inventory': ('pso_mods', 're_inventory'), 'mods': ('mod', 'file_mod'),
        'extraction': ('characters', 'pick', 'extract_pso_area', 'extract_pso_model'),
        'replacement': ('pick_replace', 'characters'),
    }
    return [{'feature': name, 'requested': bool(requested.get(name)), 'execution_enabled': False,
             'state': 'adapter_verification_required' if tools.intersection(candidates[name]) else 'unavailable',
             'installed_hooks': sorted(tools.intersection(candidates[name])),
             'reason': 'Analysis observes existing evidence. An installed tool is not proof that this title/build supports the operation.'}
            for name in FEATURES]


def is_model_job(job):
    return job.get('tool') == 'ollama_assist' and bool((job.get('input') or {}).get('analysis_run_id'))


def model_reason(store, worker, job, *, continuing=False, now=None):
    """Explicit gameplay coexistence keeps load/memory/ownership gates and bounded lifetime.

    No generic agent job can opt out of idle admission by supplying a run ID:
    the server-created run must link back to this exact job and worker.
    """
    now = time.time() if now is None else now
    inp = job.get('input') or {}
    run = store.get('game_analysis', inp.get('analysis_run_id') or '') or {}
    if (run.get('state') != 'running' or run.get('model_job_id') != job.get('id')
            or run.get('model_worker_id') != worker.get('id') or now >= run.get('deadline', 0)):
        return 'Analysis permission expired or does not belong to this exact job.'
    if run.get('target', {}).get('session_id'):
        session = store.get('session', run['target']['session_id']) or {}
        if session.get('state') != 'running' or identity(session) != run['identity']:
            return 'The analyzed session ended or its identity changed.'
    if not run.get('allow_during_gameplay'):
        from .background_testing import guarded_reason
        return guarded_reason(store, worker, now=now, require_gpu=not continuing)
    from .background_testing import admission_reason, excluded, policy
    # Explicit user work may coexist with play, but cannot override an excluded
    # PC, stale/unknown measurements, pressure, or the configured load budget.
    why = admission_reason(worker, excluded(store), policy(store, worker['name'])['budget_percent'],
                           now=now, allow_active=True, require_gpu=not continuing)
    if why:
        return why
    if now - worker.get('last_seen', 0) > 30:
        return 'The selected worker is offline.'
    # Do not allow a session-scoped permission to cover another human's game.
    from .operator_guard import operator_sessions
    owned = operator_sessions(store.running_sessions(), lambda sid: store.get('slabel', sid),
                              lambda jid: store.get('job', jid), [worker['id']])
    sid = run['target'].get('session_id')
    if any(s['session_id'] != sid for s in owned):
        return 'Another human session is active on this PC; choose a different analysis worker.'
    return None


class Analysis:
    def __init__(self, store, *, clock=time.time, telemetry=None, submit=None, launch=True):
        self.store, self.clock, self.submit, self.launch = store, clock, submit, launch
        if telemetry is None:
            from .screensaver import telemetry_get
            telemetry = telemetry_get
        self.telemetry = telemetry
        self.lock = threading.RLock()
        self.active = {}
        # A server restart never silently resumes analysis or inference permission.
        for run in store.recent('game_analysis', 100):
            if run.get('state') == 'running':
                self.finish(run, 'interrupted', 'Control plane restarted; explicitly start a new analysis run.')

    def start(self, inp, actor):
        sid = inp.session_id
        session = self.store.get('session', sid) if sid else None
        if sid and (not session or session.get('state') != 'running'):
            raise ValueError('Choose a running session; analysis never launches or follows a replacement')
        gid = (session or {}).get('game_id') or inp.game_id
        if sid and inp.game_id and inp.game_id != gid:
            raise ValueError('Session and title do not match')
        game = self.store.catalog_get(gid)
        if not game:
            raise ValueError('Unknown catalog title')
        target = {'game_id': gid, 'title': game.get('title'), 'platform': game.get('platform'),
                  'hashes': game.get('hashes') or {}, 'session_id': sid or None,
                  'mod': (session or {}).get('mod') or inp.build,
                  'build_hash': None, 'build_verification': 'Catalog disc hashes and selected build name only; derived build hash unavailable',
                  'worker_id': (session or {}).get('worker_id') or (sid.split('-')[0] if sid else None)}
        now = self.clock()
        with self.lock:
            for rid in self.active:
                old = self.store.get('game_analysis', rid) or {}
                if old.get('target') == target and old.get('actor') == actor and old.get('state') == 'running':
                    return old
            if len(self.active) >= 4:
                raise ValueError('Four analysis runs are already active; stop one first')
            run = dict(id=uuid.uuid4().hex, schema=SCHEMA, target=target, identity=identity(session) if sid else None,
                       actor=actor, state='running', started=now, deadline=now + inp.duration_s,
                       interval_s=inp.interval_s, updated=now, samples=[], console=[], seen_lines=[],
                       evidence={}, observations={}, artifacts={}, jobs=[], capabilities=[],
                       model_job_id=None, allow_during_gameplay=False, mutation_enabled=False)
            self.store.put('game_analysis', run['id'], run)
            self.active[run['id']] = threading.Event()
            self.store.audit(actor, 'analysis.start', run['id'], target)
            self.sample(run['id'])
            prefs = self.store.get('analysis_preferences', gid) or {}
            auto = inp.local_model if inp.local_model is not None else prefs.get('local_model', True)
            if auto and sid:
                self.automatic_model(run['id'], actor)
            if self.launch:
                threading.Thread(target=self.loop, args=(run['id'],), name='game-analysis', daemon=True).start()
            return self.store.get('game_analysis', run['id'])

    def automatic_model(self, rid, actor):
        """Opening Analysis is the explicit request; never select a different PC or cloud route."""
        run = self.store.get('game_analysis', rid)
        worker = self.store.get('worker', run['target'].get('worker_id') or '') or {}
        status = {'state': 'unavailable', 'worker_id': worker.get('id')}
        try:
            if 'ollama_assist' not in (worker.get('tools') or []):
                raise ValueError('This exact session worker does not advertise local Ollama analysis.')
            from .ollama_assist import selected, reason
            p = selected(self.store, worker)
            if not p['enabled']:
                raise ValueError('Local Ollama assistance is not enabled on this session worker.')
            inv = worker.get('ollama') or {}
            if not inv.get('available') or not 0 <= self.clock() - inv.get('sampled_at', 0) <= 360:
                raise ValueError('Waiting for a current local model inventory from this session worker.')
            if not any(m.get('name') == p['model'] for m in inv.get('models') or []):
                raise ValueError('The configured model is not installed on this worker. No model download was requested.')
            job = self.model(rid, ModelRequest(worker_id=worker['id'], allow_during_gameplay=True), actor)
            status.update(state=job['state'], job_id=job['id'], model=p['model'],
                          reason=job.get('error') or reason(self.store, worker, job) or 'Bounded local evidence review queued on this session worker.')
        except (ValueError, KeyError) as exc:
            status['reason'] = str(exc)
        run = self.store.get('game_analysis', rid)
        run['automatic_model'] = status
        self.store.put('game_analysis', rid, run)

    def loop(self, rid):
        event = self.active.get(rid)
        try:
            while event and not event.wait((self.store.get('game_analysis', rid) or {}).get('interval_s', 3)):
                run = self.sample(rid)
                if run['state'] != 'running':
                    return
        except Exception as exc:
            with self.lock:
                run = self.store.get('game_analysis', rid)
                if run and run['state'] == 'running':
                    self.finish(run, 'failed', str(exc)[:500])

    def finish(self, run, state, reason):
        run.update(state=state, reason=reason, finished=self.clock(), updated=self.clock())
        if event := self.active.pop(run['id'], None):
            event.set()
        # Cancels only the local hypothesis job created by this exact run.
        if jid := run.get('model_job_id'):
            with self.store.lock:
                job = self.store.get('job', jid)
                if job and is_model_job(job) and (job.get('input') or {}).get('analysis_run_id') == run['id'] and job.get('state') not in MODEL_FINAL:
                    change = {'cancel': True}
                    if job.get('state') == 'queued':
                        change.update(state='failed', finished=self.clock(), error='Analysis ended before local inference was admitted')
                    self.store.put('job', jid, job | change)
        self.save_crystal(run)
        self.store.put('game_analysis', run['id'], run)
        return run

    def sample(self, rid):
        with self.lock:
            run = self.store.get('game_analysis', rid)
            if not run or run['state'] != 'running':
                return run
            now, target = self.clock(), run['target']
            sid = target.get('session_id')
            if sid:
                session = self.store.get('session', sid) or {}
                if session.get('state') != 'running' or identity(session) != run['identity']:
                    return self.finish(run, 'interrupted', 'Exact session ended or changed; replacement was not adopted.')
            if now >= run['deadline']:
                return self.finish(run, 'completed', 'Bounded evidence window completed.')
            observer = (self.store.get('session_observer', sid) or {}) if sid else {}
            worker = self.store.get('worker', target.get('worker_id') or '') or {}
            raw_tel = self.telemetry(sid) or {} if sid else {}
            tel = bounded(raw_tel, 32768)
            latest = observer.get('latest') or {}
            # An observer snapshot belongs to this exact session; label model text as hypothesis.
            if latest.get('session_id') == sid and latest.get('game_id') == target['game_id']:
                run['observations'][digest(latest)] = bounded(latest)
                run['observations'] = dict(list(run['observations'].items())[-40:])
            else:
                observer = observer | {'latest': None}
            jobs = exact_jobs(self.store, run)
            run['jobs'] = []
            for job in jobs:
                jid = job['id']
                run['jobs'].append({k: job.get(k) for k in ('id', 'tool', 'state', 'started', 'finished', 'error', 'admission_wait')})
                lines = list(job.get('console') or job.get('progress_log') or [])[-50:]
                seq = int(job.get('console_seq') or len(job.get('console') or job.get('progress_log') or []))
                for i, line in enumerate(lines, max(0, seq - len(lines))):
                    key = f'{jid}:{i}:{digest(line)}'
                    if key not in run['seen_lines']:
                        run['seen_lines'].append(key)
                        run['console'].append({'at': now, 'job_id': jid, 'tool': job['tool'], 'line': str(line)[:1500]})
                receipt = self.store.get('receipt', job.get('receipt_id') or '') or {}
                for art in receipt.get('artifacts') or []:
                    sha = art.get('sha256')
                    if sha and self.store.get('artifact', sha):
                        run['artifacts'][sha] = {k: art.get(k) for k in ('sha256', 'name', 'size', 'media_type')} | {'job_id': jid}
                if jid == run.get('model_job_id') and job.get('state') == 'succeeded':
                    run['model_hypothesis'] = bounded((job.get('output') or {}).get('result') or {}, 65536)
            run['console'] = run['console'][-200:]
            run['seen_lines'] = run['seen_lines'][-2000:]
            run['artifacts'] = dict(list(run['artifacts'].items())[-150:])
            prefs = self.store.get('analysis_preferences', target['game_id']) or {}
            run['local_model_preference'] = prefs.get('local_model', True)
            run['capabilities'] = capability_rows(worker, observer, prefs.get('requested') or {})
            run['evidence'] = {
                'autoplay': tel, 'observer': bounded({k: observer.get(k) for k in ('state', 'gameplay_state', 'updated', 'samples', 'last_checked', 'error', 'models', 'latest')}),
                'worker': {'id': worker.get('id'), 'name': worker.get('name'), 'last_seen': worker.get('last_seen'), 'resources': bounded(worker.get('resources') or {})},
                'native_telemetry': 'reported_by_exact_session' if tel else 'unavailable',
                'job_scope': 'Newest 30 exact-session jobs' if sid else 'Up to 30 exact-title/build jobs among the latest 200 jobs; archived jobs may be omitted',
                'catalog': {k: (self.store.catalog_get(target['game_id']) or {}).get(k) for k in ('analysis', 'asset_mapping', 'autoplay', 'modding')},
            }
            if not target.get('hashes'):
                run['evidence']['build_verification'] = 'unverified: catalog disc hashes are unavailable'
            else:
                run['evidence']['build_verification'] = target['build_verification']
            # Optional native reviewer integration: preserve its exact run/sequence
            # and export endpoint, without deriving routes or room-clear claims.
            review = ((raw_tel.get('stats') or {}).get('pso_review') or raw_tel.get('pso_review')) if isinstance(raw_tel, dict) else None
            if (isinstance(review, dict) and review.get('schema') == 'gbox.pso.run-frame/1'
                    and review.get('session_id') == sid and review.get('game_id') == target['game_id']
                    and isinstance(review.get('run_id'), str) and len(review['run_id']) == 32
                    and all(c in '0123456789abcdef' for c in review['run_id'])):
                run['evidence']['pso_review'] = {'run_id': review['run_id'], 'seq': review.get('seq'),
                    'observed_at': review.get('observed_at'), 'freshness': 'Source timestamps retained; endpoint may contain later observations',
                    'crystal_url': '/api/pso/reviewer/crystal/' + review['run_id'],
                    'navigation_authority': False, 'room_clear_inference': False}
            counts = {'polls': len(run['samples']) + 1, 'observations': len(run['observations']),
                      'jobs': len(jobs), 'artifacts': len(run['artifacts']), 'console_lines': len(run['seen_lines'])}
            run['samples'].append({'at': now, **counts})
            run['samples'] = run['samples'][-300:]
            run.update(updated=now, counts=counts)
            # One immutable checkpoint at start, then every 30 seconds and at completion.
            if not run.get('crystal') or now - run.get('crystal_at', 0) >= 30:
                self.save_crystal(run)
            self.store.put('game_analysis', rid, run)
            return run

    def save_crystal(self, run):
        payload = {k: run.get(k) for k in ('schema', 'id', 'target', 'identity', 'state', 'started', 'updated',
                    'finished', 'reason', 'counts', 'samples', 'evidence', 'observations', 'artifacts',
                    'jobs', 'console', 'capabilities', 'model_hypothesis')}
        payload['semantics'] = {'native': 'Cached worker reports; freshness is retained. No independent native validation by this collector.',
                                'model': 'Hypotheses only. No model text authorizes controls, memory writes, extraction, or replacement.',
                                'progress': 'Measured evidence counts and timestamps; not percentage of reverse engineering completed.',
                                'reuse': 'Match title hashes/build and source provenance. Session-specific addresses are not portable.'}
        ref = self.store.put_artifact(packed(payload), f'analysis-{run["id"]}.crystal.json', 'application/json',
                                     {'analysis_run_id': run['id'], 'game_id': run['target']['game_id'],
                                      'session_id': run['target'].get('session_id'), 'schema': SCHEMA})
        run['crystal'], run['crystal_at'] = ref.model_dump(), self.clock()

    def model(self, rid, inp, actor):
        if actor in ('agent', 'mcp', 'hermes', 'gbox-agent'):
            raise ValueError('Local compute must be explicitly requested by the operator in Analysis')
        with self.lock:
            run = self.sample(rid)
            if not run or run['state'] != 'running':
                raise ValueError('Analysis run is not active')
            if run.get('model_job_id'):
                old = self.store.get('job', run['model_job_id']) or {}
                if old.get('state') not in MODEL_FINAL:
                    return old
            worker = self.store.get('worker', inp.worker_id) or {}
            if 'ollama_assist' not in (worker.get('tools') or []):
                raise ValueError('The selected worker does not advertise local Ollama analysis')
            from .ollama_assist import selected
            p = selected(self.store, worker)
            if not p['enabled']:
                raise ValueError('Enable a locally installed model for this worker in Ollama assistance first')
            # Explicit bounded evidence subset. Never feed console instructions to a tool executor.
            prompt = packed({'task': 'Identify uncertainties and concrete read-only verification steps. Do not assert gameplay was tested.',
                             'target': run['target'], 'counts': run.get('counts'),
                             'evidence': bounded(run.get('evidence'), 1600)}).decode()
            if len(prompt.encode()) > p['context_tokens'] - p['max_output_tokens'] - 512:
                raise ValueError('Selected model context is too small for this evidence')
            if self.submit is None:
                raise ValueError('Analysis job submission is unavailable')
            # Use normal schema/permission/routing admission, with the Store lock
            # held until the exact backlink exists. No worker can claim in between.
            with self.store.lock:
                job = self.submit({'tool': 'ollama_assist', 'input': {'op': 'analyze', 'prompt': prompt,
                                   'purpose': 'Game Analysis evidence review', 'analysis_run_id': rid},
                                   'require_worker': inp.worker_id, 'agent_use': True, 'low_priority': True}, actor)
                if hasattr(job, 'model_dump'):
                    job = job.model_dump(mode='json')
                jid = job['id']
                run.update(model_job_id=jid, model_worker_id=inp.worker_id,
                           allow_during_gameplay=inp.allow_during_gameplay)
                self.store.put('game_analysis', rid, run)
            self.store.audit(actor, 'analysis.local_model', rid, {'job_id': jid, 'worker_id': inp.worker_id,
                             'allow_during_gameplay': inp.allow_during_gameplay})
            return job


def install(app, store, auth, *, submit):
    from fastapi import Depends, HTTPException
    manager = Analysis(store, submit=submit)
    app.state.game_analysis = manager

    def found(rid):
        run = store.get('game_analysis', rid)
        if not run:
            raise HTTPException(404, 'Analysis run not found')
        return run

    @app.post('/api/analysis')
    def start(inp: Start, actor=Depends(auth)):
        try:
            return manager.start(inp, actor)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get('/api/analysis/{rid}')
    def get(rid: str, actor=Depends(auth)):
        run = found(rid)
        return {k: v for k, v in run.items() if k != 'seen_lines'}

    @app.post('/api/analysis/{rid}/stop')
    def stop(rid: str, actor=Depends(auth)):
        with manager.lock:
            run = found(rid)
            if run['state'] == 'running':
                manager.finish(run, 'cancelled', 'Operator stopped this analysis; gameplay was not changed.')
            return run

    @app.post('/api/analysis/{rid}/model')
    def model(rid: str, inp: ModelRequest, actor=Depends(auth)):
        found(rid)
        try:
            return manager.model(rid, inp, actor)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.put('/api/analysis-preferences/{gid}')
    def preferences(gid: str, inp: Preferences, actor=Depends(auth)):
        if not store.catalog_get(gid):
            raise HTTPException(404, 'Unknown title')
        row = {'requested': inp.requested, 'local_model': inp.local_model, 'execution_enabled': False, 'updated': time.time()}
        store.put('analysis_preferences', gid, row)
        store.audit(actor, 'analysis.preferences', gid, row)
        return row

    @app.get('/api/analysis-crystals/{gid}')
    def crystals(gid: str, actor=Depends(auth)):
        return [{'id': r['id'], 'target': r['target'], 'state': r['state'], 'updated': r['updated'], 'crystal': r.get('crystal')}
                for r in store.recent('game_analysis', 100) if r.get('target', {}).get('game_id') == gid and r.get('crystal')]
