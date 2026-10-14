"""Per-PC local build retention. Central collection and saves are never targets."""
import json
import shutil
import stat
import threading
from collections import defaultdict
from pathlib import Path

DEFAULT = 3
KIND = 'build_retention'


def policy(value=None):
    value = value or {}
    default, limits = value.get('default', DEFAULT), dict(value.get('games', {}))
    if type(default) is not int or not 1 <= default <= 10:
        raise ValueError('Keep between 1 and 10 builds')
    if any(not isinstance(g, str) or not g or type(n) is not int or not 1 <= n <= 10 for g, n in limits.items()):
        raise ValueError('Each game must keep between 1 and 10 builds')
    return {'default': default, 'games': limits, 'enabled': bool(value.get('enabled', False))}


def plan(rows, settings, busy=()):
    settings = policy(settings)
    groups = defaultdict(lambda: defaultdict(list))
    for row in rows:
        groups[row['game_id']][row.get('staged_of') or row['name'].split('~')[0]].append(row)
    remove, protected = [], []
    for gid, builds in groups.items():
        limit = settings['games'].get(gid, settings['default'])
        ordered = sorted(builds, key=lambda n: (-max(r['built'] for r in builds[n]), n))
        for name in ordered[limit:]:
            copies = builds[name]
            if any((gid, r['name']) in busy or (gid, name) in busy for r in copies):
                protected.extend(copies)
            else: remove.extend(copies)
    return {'remove': remove, 'protected': protected}


def linked(path):
    s = path.lstat()
    return stat.S_ISLNK(s.st_mode) or bool(getattr(s, 'st_file_attributes', 0) & 0x400)


def inventory(cfg):
    root = Path(cfg.cache).resolve() / 'mods'
    rows = []
    if not root.is_dir() or linked(root): return rows
    for game in root.iterdir():
        if not game.is_dir() or linked(game): continue
        for folder in game.iterdir():
            marker = folder / '.gbox-mod.json'
            if not folder.is_dir() or linked(folder) or not marker.is_file() or linked(marker): continue
            try:
                meta = json.loads(marker.read_text(encoding='utf-8'))
                stamp = marker.stat()
                built = meta.get('built') or meta.get('created') or stamp.st_mtime
                if not isinstance(built, (int, float)): built = stamp.st_mtime
                stage = folder / '.gbox-staged-of'
                if stage.exists() and linked(stage): continue
                name = stage.read_text().strip() if stage.is_file() else folder.name.split('~')[0]
                rows.append({'game_id': game.name, 'name': folder.name, 'staged_of': name,
                             'built': built, 'marker_mtime_ns': stamp.st_mtime_ns})
            except (OSError, ValueError): continue
    return rows


def apply(cfg, settings, busy=(), dry_run=False):
    from . import filemods
    root = Path(cfg.cache).resolve() / 'mods'
    result = plan(inventory(cfg), settings, busy)
    result.update(removed=[], errors=[], freed_bytes=0)
    for row in result['remove']:
        folder = root / row['game_id'] / row['name']
        try:
            # Resolve and check each target before deleting; never traverse a
            # symlink/junction to a library, cold tier, saves, or another PC.
            if linked(root) or linked(folder.parent) or linked(folder) or not folder.resolve().is_relative_to(root.resolve()):
                raise ValueError('build path is linked or outside the local build cache')
            marker = folder / '.gbox-mod.json'
            if marker.stat().st_mtime_ns != row['marker_mtime_ns']:
                raise ValueError('build changed during cleanup')
            files = list(folder.rglob('*'))
            if any(linked(p) for p in files): raise ValueError('build contains a linked path')
            own = sum(p.stat().st_size for p in files if p.is_file() and p.stat().st_nlink == 1)
            row['bytes'] = own
            if dry_run: continue
            shutil.rmtree(folder)
            result['removed'].append({'game_id': row['game_id'], 'name': row['name'], 'bytes': own})
            result['freed_bytes'] += own
        except (OSError, ValueError) as e:
            result['errors'].append({'game_id': row['game_id'], 'name': row['name'], 'error': str(e)})
    filemods._LOCAL_CACHE.clear()
    return result


def routes(app, store, auth, submit, workers):
    from fastapi import Depends, HTTPException
    def target(node):
        w = next((w for w in workers() if w.get('name') == node), None)
        if not w or w.get('os') != 'windows':
            raise HTTPException(422, 'Choose a Windows PC; this limit does not delete Spark collection builds')
        return w

    def queue(node, actor):
        w = target(node)
        if not w.get('online'): return {'queued': False, 'reason': 'PC offline; cleanup resumes when it reconnects'}
        settings = policy(store.get(KIND, node))
        rows = w.get('local_builds', [])
        # Collection creation dates win over when a PC downloaded a copy.
        current = getattr(app.state, 'built_mods_current', None)
        built = {(r['game_id'], r['name']): r.get('built') for r in (current() if current else {}).get('items', [])}
        rows = [r | {'built': built.get((r['game_id'], r.get('staged_of') or r['name'].split('~')[0])) or r['built']} for r in rows]
        busy = {(s.get('game_id'), str(s.get(k) or '')) for s in store.all('session') if s.get('state') == 'running'
                for k in ('mod', 'collection_mod', 'launch_mod')}
        candidates = plan(rows, settings, busy)
        jobs = store.all('job')
        pending = {(j.get('input', {}).get('game_id'), j.get('input', {}).get('name')) for j in jobs
                   if j.get('tool') == 'file_mod' and j.get('input', {}).get('op') == 'delete_build'
                   and j.get('require_worker') in (w['id'], node) and j.get('state') in ('queued', 'running')}
        queued = []
        for r in candidates['remove']:
            name = r.get('staged_of') or r['name'].split('~')[0]
            key = (r['game_id'], name)
            broken = store.get('build_broken', f'{r["game_id"]}/{name}')
            if broken and broken.get('state') != 'deleted': continue
            if key in pending: continue
            j = submit({'tool': 'file_mod', 'input': {'game_id': r['game_id'], 'op': 'delete_build', 'name': name,
                       'retention_node': node}, 'require_worker': w['id'], 'low_priority': True}, actor)
            queued.append(j.id if hasattr(j, 'id') else j['id'])
            pending.add(key)
        return {'queued': True, 'jobs': queued, 'protected': len(candidates['protected'])}

    @app.get('/api/build-retention')
    def get(node: str, actor=Depends(auth)):
        target(node)
        return policy(store.get(KIND, node)) | {'node': node}

    @app.post('/api/build-retention')
    def save(body: dict, actor=Depends(auth)):
        node = str(body.get('node') or '')
        target(node)
        with store.lock:
            p = policy(store.get(KIND, node))
            gid = body.get('game_id') or ''
            if not isinstance(gid, str): raise HTTPException(422, 'game_id must be a string')
            if gid: p['games'][gid] = body.get('limit', DEFAULT)
            else: p['default'] = body.get('limit', DEFAULT)
            p['enabled'] = True
            try: p = policy(p)
            except (TypeError, ValueError) as e: raise HTTPException(422, str(e))
            store.put(KIND, node, p | {'node': node})
            # A slider increase must cancel older queued cleanup decisions.
            for j in store.all('job'):
                if j.get('state') == 'queued' and j.get('input', {}).get('retention_node') == node:
                    store.put('job', j['id'], j | {'state': 'failed', 'error': 'Build limit changed before cleanup'})
            store.audit(actor, 'build_retention.set', node, p)
            return p | queue(node, actor)

    stop = threading.Event()
    def loop():
        while not stop.wait(60):
            for p in store.all(KIND):
                if p.get('enabled') and p.get('node'):
                    try:
                        w = target(p['node'])
                        if w.get('online') and not w.get('active_jobs') and plan(w.get('local_builds', []), p)['remove']:
                            with store.lock: queue(p['node'], 'operator')
                    except Exception: pass  # unavailable worker cannot affect the control plane
    app.on_event('startup')(lambda: threading.Thread(target=loop, daemon=True, name='build-retention').start())
    app.on_event('shutdown')(stop.set)
