"""Bounded native run archive and separate idle-PC playback requests."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import tas, background_testing as background


class Play(BaseModel):
    segment: str = ''
    loop: bool = False
    sprite: str = ''
    worker: str = ''


class Idle(BaseModel):
    enabled: bool
    sprite: str = ''


class Result(BaseModel):
    job_id: str
    status: dict


def public(row):
    result = {k: v for k, v in row.items() if k not in ('path', 'checkpoints', 'core_options')}
    result['full_verified_sprites'] = sorted({r.get('sprite', '') for r in row.get('replay_receipts', [])
                                             if r.get('verified') and not r.get('segment')})
    return result


def install(app, store, config, auth, submit, workers):
    from .server import JobRequest
    root = config.data_dir/'tas-runs'
    root.mkdir(parents=True, exist_ok=True)
    upload_lock = threading.Lock()

    def core_path(digest):
        if not re.fullmatch('[a-f0-9]{64}', digest):
            raise HTTPException(422, 'Invalid replay core identity')
        folder = config.data_dir/'tas-cores'; folder.mkdir(parents=True, exist_ok=True)
        return folder/(digest+'.dll')

    @app.post('/api/tas/cores/{digest}')
    async def upload_core(digest: str, request: Request, actor=Depends(auth)):
        target = core_path(digest)
        if target.is_file():
            return {'sha256': digest, 'retained': True}
        if sum(p.stat().st_size for p in target.parent.glob('*.dll')) >= 4*2**30 or shutil.disk_usage(target.parent).free < 4*2**30:
            raise HTTPException(507, 'Replay engine archive is full; worker keeps the original')
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix='core-')
        try:
            size = 0
            with os.fdopen(fd, 'wb') as out:
                async for block in request.stream():
                    size += len(block)
                    if size > 64*2**20:
                        raise HTTPException(413, 'Replay engine exceeds 64 MiB')
                    from starlette.concurrency import run_in_threadpool
                    await run_in_threadpool(out.write, block)
            with open(tmp, 'rb') as f:
                if f.read(2) != b'MZ' or tas.fingerprint(tmp) != digest:
                    raise HTTPException(422, 'Replay engine digest differs')
            os.replace(tmp, target)
            return {'sha256': digest, 'retained': True}
        finally:
            Path(tmp).unlink(missing_ok=True)

    @app.get('/api/tas/cores/{digest}')
    def download_core(digest: str, actor=Depends(auth)):
        path = core_path(digest)
        if not path.is_file():
            raise HTTPException(404, 'Recorded replay engine is not archived')
        return FileResponse(path, media_type='application/octet-stream', filename='mesen_libretro.dll')

    def runtime_folder(source):
        if source != tas.fingerprint(Path(tas.__file__).parent/'native/tas_core.c'):
            raise HTTPException(409, 'Native runtime must match the installed source revision')
        return config.data_dir/'tas-runtime/windows'/source

    @app.post('/api/tas/runtime/windows/{source}')
    async def upload_runtime(source: str, request: Request, actor=Depends(auth)):
        folder = runtime_folder(source); folder.mkdir(parents=True, exist_ok=True)
        expected = request.headers.get('x-gbox-sha256', '')
        if not re.fullmatch('[a-f0-9]{64}', expected):
            raise HTTPException(422, 'Native runtime digest is required')
        fd, tmp = tempfile.mkstemp(dir=folder, prefix='binary-')
        try:
            size = 0
            with os.fdopen(fd, 'wb') as out:
                async for block in request.stream():
                    size += len(block)
                    if size > 4*2**20:
                        raise HTTPException(413, 'Native binary exceeds limit')
                    from starlette.concurrency import run_in_threadpool
                    await run_in_threadpool(out.write, block)
            with open(tmp, 'rb') as stream:
                if stream.read(2) != b'MZ' or tas.fingerprint(tmp) != expected:
                    raise HTTPException(422, 'Native Windows binary identity check failed')
            os.replace(tmp, folder/'gbox_tas_libretro.dll')
            manifest = {'source_sha256': source, 'sha256': expected, 'bytes': size, 'uploaded': time.time()}
            (folder/'manifest.json').write_text(json.dumps(manifest))
            return manifest
        finally:
            Path(tmp).unlink(missing_ok=True)

    @app.get('/api/tas/runtime/windows/{source}/manifest')
    def runtime_manifest(source: str, actor=Depends(auth)):
        path = runtime_folder(source)/'manifest.json'
        if not path.is_file():
            raise HTTPException(404, 'Native runtime has not been built on Windows yet')
        return json.loads(path.read_text())

    @app.get('/api/tas/runtime/windows/{source}/file')
    def runtime_binary(source: str, actor=Depends(auth)):
        path = runtime_folder(source)/'gbox_tas_libretro.dll'
        if not path.is_file():
            raise HTTPException(404, 'Native runtime has not been built on Windows yet')
        return FileResponse(path, media_type='application/octet-stream', filename=path.name)

    def get(rid):
        row = store.get('tas_run', rid)
        if not row:
            raise HTTPException(404, 'Native run not found')
        return row

    def launch(row, body, actor):
        candidates = [w for w in workers() if w.get('online') and w.get('os') == 'windows' and 'tas_play' in (w.get('tools') or [])
                      and not w.get('active_jobs') and (not body.worker or body.worker in (w['id'], w['name']))]
        candidates = [w for w in candidates if not any(s['session_id'].split('-')[0] == w['id']
                      for s in store.running_sessions())]
        reasons = [background.guarded_reason(store, w, require_gpu=False) for w in candidates]
        chosen = next((w for w, why in zip(candidates, reasons) if not why), None)
        if not chosen:
            raise HTTPException(409, next((why for why in reasons if why),
                                          'Waiting for an available idle PC with native replay support; current games stay running'))
        if body.segment and body.segment not in {s['id'] for s in row['segments']}:
            raise HTTPException(422, 'Level segment not found')
        game = store.catalog_get(row['game_id'])
        if not game:
            raise HTTPException(404, 'The owned game is no longer in the library')
        return submit(JobRequest(tool='tas_play', input={'run_id': row['id'], 'game': game,
                      'segment': body.segment, 'loop': body.loop, 'sprite': body.sprite},
                      agent_use=True, low_priority=True, require_worker=chosen['id']), actor=actor,
                      origin={'via': 'native TAS playback', 'run_id': row['id']})

    @app.post('/api/tas/captures/{sid}/{rid}')
    async def upload(sid: str, rid: str, request: Request, actor=Depends(auth)):
        from starlette.concurrency import run_in_threadpool
        if not re.fullmatch('[a-f0-9]{32}', rid):
            raise HTTPException(422, 'Invalid native run ID')
        session = store.get('session', sid)
        if not session:
            raise HTTPException(404, 'Recorded session not found')
        if background.agent_owned(store.get('slabel', sid), store.get('job', sid.split('-', 1)[-1])):
            raise HTTPException(409, 'Automated playback is not a new human recording')
        try:
            raw = request.headers.get('x-gbox-tas-meta', '')
            if len(raw) > 70000:
                raise ValueError('Native metadata too large')
            meta = json.loads(raw)
            for key in ('core_sha256', 'proxy_sha256', 'rom_sha256', 'prg_sha256', 'header_sha256', 'chr_sha256'):
                if not re.fullmatch('[a-f0-9]{64}', meta[key]):
                    raise ValueError('Missing capture identity: '+key)
            if meta.get('game_id') != session['game_id'] or meta.get('session_id') != sid:
                raise ValueError('Capture belongs to another session')
            options = meta.get('core_options', '')
            if not isinstance(options, str) or len(options) > 65536:
                raise ValueError('Invalid captured core options')
        except (ValueError, TypeError, KeyError) as error:
            raise HTTPException(422, str(error)) from error
        if not upload_lock.acquire(blocking=False):
            raise HTTPException(429, 'Another native run is archiving; recording stays on the worker')
        tmp = None
        try:
            if shutil.disk_usage(root).free < 4*2**30 or sum(p.stat().st_size for p in root.glob('*.gbt')) >= 64*2**30:
                raise HTTPException(507, 'Native archive budget reached; recording stays on the worker')
            fd, tmp = tempfile.mkstemp(dir=root, prefix='upload-')
            size, digest = 0, hashlib.sha256()
            with os.fdopen(fd, 'wb') as stream:
                async for block in request.stream():
                    size += len(block)
                    if size > tas.MAX_TAPE + tas.MAX_RECORD:
                        raise HTTPException(413, 'Native run exceeds its capture budget')
                    await run_in_threadpool(stream.write, block); digest.update(block)
            try:
                info = await run_in_threadpool(tas.index, tmp)
            except (ValueError, OSError) as error:
                raise HTTPException(422, str(error)) from error
            sha = digest.hexdigest()
            old = store.get('tas_run', rid)
            if old and (old['sha256'] != sha or old['session_id'] != sid):
                raise HTTPException(409, 'Run ID already belongs to different native data')
            if old and any(old.get(k) != meta.get(k, '') for k in
                           ('core_sha256', 'proxy_sha256', 'rom_sha256', 'core_options')):
                raise HTTPException(409, 'Native recording identity is immutable')
            dest = root/(sha+'.gbt')
            os.replace(tmp, dest)
            row = {k: meta[k] for k in ('core_sha256', 'proxy_sha256', 'rom_sha256', 'prg_sha256',
                   'header_sha256', 'chr_sha256')}
            row.update(info, id=rid, path=str(dest), core_options=options, session_id=sid,
                       game_id=session['game_id'], title=session.get('title'), mod=session.get('mod') or '',
                       started=meta.get('started') if isinstance(meta.get('started'), (int, float)) and math.isfinite(meta['started']) else time.time(),
                       archived=time.time(), idle=(old or {}).get('idle', {}),
                       replay_receipts=(old or {}).get('replay_receipts', []))
            store.put('tas_run', rid, row)
            capture = getattr(app.state, 'capture_gameplay', None)
            if capture:
                capture(sid, 'checkpoint', {'native_tas': rid, 'frames': info['frames'], 'sha256': sha}, 'tas-'+rid)
            return public(row)
        finally:
            if tmp:
                Path(tmp).unlink(missing_ok=True)
            upload_lock.release()

    @app.get('/api/tas/runs')
    def listing(game_id: str = '', session_id: str = '', actor=Depends(auth)):
        rows = sorted((r for r in store.all('tas_run') if not game_id or r['game_id'] == game_id),
                      key=lambda r: r.get('started', 0), reverse=True)[:100]
        session = store.get('session', session_id) if session_id else None
        capture = None
        if session and session.get('state') == 'running':
            native = (session.get('detail') or {}).get('tas_capture') or {'state': 'unavailable',
                       'reason': 'This session started before native capture was available. It needs a new launch after the worker updates.'}
            capture = {k: native[k] for k in ('id', 'state', 'frame', 'reason') if k in native}
        return {'runs': [public(r) for r in rows], 'capture': capture, 'scope': 'separate test sessions on available idle PCs',
                'legacy_reason': 'Earlier ghost tracks have no full native input/state tape. Exact TAS playback cannot be reconstructed from them.'}

    @app.get('/api/tas/runs/{rid}')
    def detail(rid: str, actor=Depends(auth)):
        row = get(rid)
        return public(row) | {'core_options': row.get('core_options', '')}

    @app.get('/api/tas/runs/{rid}/file')
    def download(rid: str, actor=Depends(auth)):
        row = get(rid)
        path = root/(row['sha256']+'.gbt')
        if not path.is_file():
            raise HTTPException(404, 'Native tape is missing; worker copy is retained')
        return FileResponse(path, media_type='application/octet-stream', filename=rid+'.gbt')

    @app.post('/api/tas/runs/{rid}/play')
    def play(rid: str, body: Play, actor=Depends(auth)):
        return launch(get(rid), body, actor)

    @app.post('/api/tas/runs/{rid}/idle')
    def idle(rid: str, body: Idle, actor=Depends(auth)):
        with store.lock:
            row = get(rid)
            store.put('tas_run', rid, row | {'idle': body.model_dump()})
        return {'saved': True, 'state': 'armed' if body.enabled else 'off',
                'reason': 'Idle loops wait for a successful full replay with the selected sprite'}

    @app.post('/api/tas/runs/{rid}/result')
    def result(rid: str, body: Result, actor=Depends(auth)):
        row, job = get(rid), store.get('job', body.job_id)
        if not job or job.get('tool') != 'tas_play' or job.get('input', {}).get('run_id') != rid:
            raise HTTPException(409, 'Replay result does not belong to this run')
        status = {k: v for k, v in body.status.items() if k in ('state', 'reason', 'frame', 'loops', 'mismatches')}
        if any(type(status.get(k)) is not int or status[k] < 0 for k in ('frame', 'loops', 'mismatches')):
            raise HTTPException(422, 'Replay result needs native frame, loop and mismatch counters')
        end = row['frames']
        segment_id = job['input'].get('segment')
        if segment_id:
            segment = next((s for s in row['segments'] if s['id'] == segment_id), None)
            if not segment:
                raise HTTPException(422, 'Replay result names an unknown segment')
            end = segment['end_frame']-segment['checkpoint_frame']
        receipt = {'job_id': body.job_id, 'at': time.time(), 'sprite': job['input'].get('sprite', ''),
                   'segment': job['input'].get('segment', ''), 'status': status,
                   'verified': status.get('state') in ('finished', 'playing') and status.get('mismatches') == 0
                   and (status['loops'] > 0 or status.get('state') == 'finished' and status['frame'] == end)}
        with store.lock:
            current = get(rid)
            receipts = [r for r in current.get('replay_receipts', []) if r['job_id'] != body.job_id] + [receipt]
            store.put('tas_run', rid, current | {'replay_receipts': receipts[-40:]})
        return receipt

    def idle_tick():
        for row in store.all('tas_run'):
            pref = row.get('idle') or {}
            if not pref.get('enabled'):
                continue
            verified = any(r.get('verified') and not r.get('segment') and r.get('sprite', '') == pref.get('sprite', '')
                           for r in row.get('replay_receipts', []))
            if not verified or time.time() - row.get('idle_last', 0) < 300:
                continue
            if any(j.get('tool') == 'tas_play' and j.get('state') in ('queued', 'running') for j in store.all('job')):
                continue
            try:
                launch(row, Play(loop=True, sprite=pref.get('sprite', '')), 'tas-screensaver')
                with store.lock:
                    store.put('tas_run', row['id'], get(row['id']) | {'idle_last': time.time()})
                break
            except HTTPException:
                pass
    app.state.tas_idle_tick = idle_tick
    stopped = threading.Event()
    def idle_loop():
        while not stopped.wait(30):
            try:
                idle_tick()
            except Exception:
                pass  # next heartbeat retries; never disrupt the control plane
    app.on_event('startup')(lambda: threading.Thread(target=idle_loop, daemon=True, name='tas-idle-dispatch').start())
    app.on_event('shutdown')(stopped.set)
