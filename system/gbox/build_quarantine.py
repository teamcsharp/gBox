"""Temporary, verified evidence for broken builds; small findings outlive the ROMs."""
import hashlib
import json
import shutil
import threading
import time
from pathlib import Path

from . import filemods

KIND = 'build_broken'
EVIDENCE = 'build_evidence'
ROOT = '.broken-builds'


def serialized(guard):
    from functools import wraps
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            with guard: return fn(*args, **kwargs)
        return wrapped
    return decorate


def safe_tree(root, folder):
    from .build_retention import linked
    root, folder = Path(root), Path(folder)
    if any(linked(p) for p in [root, *root.parents] if p.exists()):
        raise ValueError('Linked storage roots cannot be quarantined')
    root = root.resolve()
    if not folder.resolve().is_relative_to(root) or folder.resolve() == root:
        raise ValueError('Evidence path escaped its storage root')
    parts = [folder, *folder.parents]
    for p in parts:
        if p == root: break
        if p.exists() and linked(p): raise ValueError('Linked build paths cannot be quarantined')
    if folder.exists() and any(linked(p) for p in folder.rglob('*')):
        raise ValueError('Linked build contents cannot be quarantined')


def manifest(folder):
    folder = Path(folder)
    safe_tree(folder.parent, folder)
    rows = []
    for p in sorted(folder.rglob('*')):
        if not p.is_file() or p.name == filemods.STAGED_MARK or p.name.endswith('.part'): continue
        before = p.stat()
        digest = filemods._sha(p)
        after = p.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('Build changed while preserving it; retry when idle')
        rows.append({'path': p.relative_to(folder).as_posix(), 'size': after.st_size, 'sha256': digest})
    return sorted(filemods._manifest(rows, folder), key=lambda r: r['path'])


def begin(store, cfg, gid, name, copy, files):
    source = filemods.mod_dir(cfg, gid, name)
    if source.exists(): safe_tree(Path(cfg.cache), source)
    filemods.mod_dir(cfg, gid, copy)  # validate folder components
    rows = sorted(filemods._manifest(files, source), key=lambda r: r['path'])
    qid = hashlib.sha256(json.dumps([gid, name, copy, rows], sort_keys=True).encode()).hexdigest()
    root = Path(cfg.cache) / ROOT
    folder = root / qid / 'files'
    safe_tree(Path(cfg.cache), folder)
    folder.mkdir(parents=True, exist_ok=True)
    record = store.get(EVIDENCE, qid) or {'id': qid, 'game_id': gid, 'name': name, 'copy': copy,
        'files': rows, 'path': str(folder), 'sealed': False, 'created': time.time()}
    if record.get('deleted'): raise ValueError('This evidence was already examined and deleted')
    missing = []
    for row in rows:
        dst = filemods._file_path(folder, row['path'])
        if dst.is_file() and dst.stat().st_size == row['size'] and filemods._sha(dst) == row['sha256']: continue
        src = filemods._file_path(source, row['path'])
        if src.is_file() and src.stat().st_size == row['size'] and filemods._sha(src) == row['sha256']:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)  # never a hard link to a build a writer may modify
        else: missing.append(row['path'])
    store.put(EVIDENCE, qid, record)
    return record | {'missing': missing}


def seal(store, cfg, qid):
    r = store.get(EVIDENCE, qid)
    if not r or r.get('deleted'): raise ValueError('Evidence not available')
    folder = Path(r['path'])
    safe_tree(Path(cfg.cache) / ROOT, folder)
    if manifest(folder) != r['files']: raise ValueError('Evidence checksum verification failed')
    r.update(sealed=True, verified=time.time())
    store.put(EVIDENCE, qid, r)
    return r


def preserve(store, cfg, gid, name, copy=None):
    copy = copy or name
    src = filemods.mod_dir(cfg, gid, copy)
    rows = manifest(src)
    r = begin(store, cfg, gid, name, copy, rows)
    for rel in r['missing']:
        dst = filemods._file_path(Path(r['path']), rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(filemods._file_path(src, rel), dst)
    return seal(store, cfg, r['id'])


def worker(ctx, gid, name, in_use):
    import httpx
    from urllib.parse import quote
    names = filemods.copies_of(ctx.config, gid, name)
    if set(names) & set(in_use): raise ValueError('The broken build is still running; leave it intact until stopped')
    saved, snapshots = [], {}
    with httpx.Client(headers=ctx.headers, timeout=900) as client:
        for copy in names:
            folder = filemods.mod_dir(ctx.config, gid, copy)
            files = snapshots[copy] = manifest(folder)
            ctx.progress(10, f'Preserving broken build {copy} on Spark before removal')
            response = client.post(ctx.server + '/api/build-quarantine/archive', json={
                'game_id': gid, 'name': name, 'copy': copy, 'files': files})
            response.raise_for_status(); record = response.json()
            for rel in record['missing']:
                with filemods._file_path(folder, rel).open('rb') as stream:
                    response = client.put(ctx.server + f"/api/build-quarantine/{record['id']}/file/{quote(rel, safe='/')}", content=stream)
                    response.raise_for_status()
            response = client.post(ctx.server + f"/api/build-quarantine/{record['id']}/seal", json={})
            response.raise_for_status(); sealed = response.json()
            if not sealed.get('sealed') or sealed.get('files') != files:
                raise ValueError('Spark did not verify the exact broken build; local files kept')
            saved.append(sealed['id'])
        if filemods.copies_of(ctx.config, gid, name) != names:
            raise ValueError('Local builds changed during preservation; local files kept')
        for copy in names:
            if manifest(filemods.mod_dir(ctx.config, gid, copy)) != snapshots[copy]:
                raise ValueError('Local build changed after preservation; local files kept')
        # Worker serializes this operation with builds/launches. Re-check live sessions as well.
        response = client.get(ctx.server + '/api/sessions?include_ended=false'); response.raise_for_status()
        busy = [s.get('mod') or (s.get('detail') or {}).get('mod') for s in response.json()
                if s.get('game_id') == gid and s.get('state') == 'running']
        result = filemods.delete_build(ctx.config, gid, name, busy)
        if result['errors']: raise ValueError('; '.join(result['errors']))
    return result | {'archives': saved}


def purge(store, cfg, record):
    """Completion alone is insufficient: explicit findings and resolution must be recorded."""
    request = store.get('request', record.get('request_id')) or {}
    analysis = record.get('analysis') or {}
    if request.get('status') != 'done' or not analysis.get('findings') or not analysis.get('resolution'):
        return False
    if record.get('state') != 'preserved': return False
    archives = [store.get(EVIDENCE, q) for q in record.get('archives', [])]
    if not archives or any(not a or not a.get('sealed') for a in archives): return False
    # Keep a subsequently repaired/rebuilt collection copy whose bytes differ.
    for copy in {record['name'], *(a['copy'] for a in archives)}:
        folder = filemods.mod_dir(cfg, record['game_id'], copy)
        if folder.exists() and any(manifest(folder) == a['files'] for a in archives):
            safe_tree(Path(cfg.cache) / 'mods', folder)
            shutil.rmtree(folder)
    # Failed/resumed uploads may leave unsealed variants; once all preservation
    # completed, these temporary payloads are no longer needed either.
    leftovers = [a for a in store.all(EVIDENCE) if a.get('game_id') == record['game_id']
                 and a.get('name') == record['name'] and not a.get('deleted')]
    for a in leftovers:
        folder = Path(a['path']).parent
        safe_tree(Path(cfg.cache) / ROOT, folder)
        if folder.exists(): shutil.rmtree(folder)
        store.put(EVIDENCE, a['id'], a | {'deleted': time.time()})
    record.update(state='deleted', deleted=time.time())
    store.put(KIND, record['key'], record)
    request.setdefault('messages', []).append({'author': 'system', 'ts': time.time(), 'attachments': [],
        'text': 'Broken ROM payloads and temporary evidence deleted after recorded analysis and resolution. Findings and repair history retained.'})
    store.put('request', record['request_id'], request)
    return True


def routes(app, store, cfg, auth, submit, workers, changed):
    from fastapi import Depends, HTTPException, Request
    guard = threading.RLock()

    @app.post('/api/build-quarantine/archive')
    def archive(body: dict, actor=Depends(auth)):
        if not store.get(KIND, f"{body.get('game_id')}/{body.get('name')}"):
            raise HTTPException(409, 'Mark the build broken before preserving it')
        with guard:
            try: return begin(store, cfg, body['game_id'], body['name'], body['copy'], body['files'])
            except (KeyError, ValueError) as e: raise HTTPException(422, str(e)) from e

    @app.put('/api/build-quarantine/{qid}/file/{rel:path}')
    async def upload(qid: str, rel: str, request: Request, actor=Depends(auth)):
        r = store.get(EVIDENCE, qid)
        row = next((f for f in (r or {}).get('files', []) if f['path'] == rel), None)
        if not row or r.get('sealed') or r.get('deleted'): raise HTTPException(409, 'Evidence file is not writable')
        folder = Path(r['path']); safe_tree(Path(cfg.cache) / ROOT, folder)
        dst = filemods._file_path(folder, rel); dst.parent.mkdir(parents=True, exist_ok=True)
        import tempfile
        fd, tmp = tempfile.mkstemp(dir=dst.parent, prefix='.upload-')
        import os
        count, digest = 0, hashlib.sha256()
        try:
            with os.fdopen(fd, 'wb') as stream:
                async for data in request.stream():
                    count += len(data)
                    if count > row['size']: raise HTTPException(422, 'Evidence exceeds its manifest size')
                    stream.write(data); digest.update(data)
            if count != row['size'] or digest.hexdigest() != row['sha256']: raise HTTPException(422, 'Evidence checksum mismatch')
            with guard:
                if (store.get(EVIDENCE, qid) or {}).get('sealed'): raise HTTPException(409, 'Evidence already sealed')
                os.replace(tmp, dst)
            return {'ok': True}
        finally:
            Path(tmp).unlink(missing_ok=True)

    @app.post('/api/build-quarantine/{qid}/seal')
    def finish(qid: str, actor=Depends(auth)):
        with guard:
            try: return seal(store, cfg, qid)
            except ValueError as e: raise HTTPException(409, str(e)) from e

    @app.post('/api/builds/{gid}/{name}/broken/analysis')
    @serialized(guard)
    def analysis(gid: str, name: str, body: dict, actor=Depends(auth)):
        key = f'{gid}/{name}'; r = store.get(KIND, key)
        if not r: raise HTTPException(404, 'No broken build report')
        values = {k: str(body.get(k) or '').strip()[:12000] for k in ('findings', 'resolution')}
        if not all(values.values()): raise HTTPException(422, 'Record both findings and resolution before deleting evidence')
        with store.lock:
            r['analysis'] = values | {'by': actor, 'ts': time.time()}; store.put(KIND, key, r)
        store.audit(actor, 'build.broken.analysis', key, values)
        return r

    def tick():
        ws = {w['name']: w for w in workers()}
        sessions = store.all('session')
        for r in store.all(KIND):
            if r.get('state') == 'deleted': continue
            gid, name = r['game_id'], r['name']; w = ws.get(r.get('node'))
            r['archives'] = list(dict.fromkeys(r.get('archives', []) + [a['id'] for a in store.all(EVIDENCE)
                if a.get('game_id') == gid and a.get('name') == name and a.get('sealed') and not a.get('deleted')]))
            # Do not delete any running copy, on any machine.
            if any(s.get('state') == 'running' and s.get('game_id') == gid and
                   str(s.get('mod') or (s.get('detail') or {}).get('mod') or '').split('~')[0] == name for s in sessions): continue
            job = store.get('job', r.get('cleanup_job')) if r.get('cleanup_job') else None
            if job and job.get('state') == 'succeeded':
                r['archives'] = list(dict.fromkeys(r.get('archives', []) + (job.get('output') or {}).get('result', {}).get('archives', [])))
                r['state'] = 'preserved'
            elif job and job.get('state') in ('failed', 'rejected', 'cancelled'):
                r.update(state='blocked', error=job.get('error') or 'Local preservation did not complete')
            elif not job and w and w.get('online') and 'local_builds' in w and not w.get('active_jobs'):
                local = [b for b in w.get('local_builds', []) if b.get('game_id') == gid and
                         (b.get('staged_of') or b['name'].split('~')[0]) == name]
                if not local and r.get('archives'): r['state'] = 'preserved'
                elif local:
                    try:
                        j = submit({'tool': 'file_mod', 'input': {'op': 'quarantine_build', 'game_id': gid, 'name': name},
                                    'require_worker': w['id'], 'low_priority': True}, r.get('by') or 'operator')
                        r.update(cleanup_job=j.id if hasattr(j, 'id') else j['id'], state='preserving')
                    except Exception as exc:
                        r.update(state='blocked', error=str(exc))
            store.put(KIND, r['key'], r)
            try:
                if purge(store, cfg, r):
                    index = getattr(app.state, 'built_mods', None)
                    if index and not filemods.mod_dir(cfg, gid, name).exists(): index.forget(gid, name)
            except Exception as exc:
                r['error'] = f'Evidence cleanup will retry: {exc}'
                store.put(KIND, r['key'], r)
            changed()

    stop = threading.Event()
    def loop():
        while not stop.wait(30):
            try:
                with guard: tick()
            except Exception as e: print(f'Broken-build cleanup deferred: {e}', flush=True)
    app.on_event('startup')(lambda: threading.Thread(target=loop, daemon=True, name='broken-build-cleanup').start())
    app.on_event('shutdown')(stop.set)
    tick.guard = guard
    return tick
