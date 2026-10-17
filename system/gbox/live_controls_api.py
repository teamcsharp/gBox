"""Persistent discovery -> verified live control publication -> session-pinned jobs."""
import threading
import time
import math
import re
import uuid
import hashlib
from pathlib import Path
from fastapi import Depends, HTTPException
from . import live_controls as L


def worker_sources():
    root = Path(__file__).parent
    return {'gbox/' + name: hashlib.sha256((root/name).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
            for name in ('live_controls.py', 'auf_live.py')}


def require_current_worker(store, session, profile):
    if not any(a['binding'].get('tool') == 'auf_live' for a in profile['actions']):
        return
    worker = store.get('worker', session.get('worker_id') or session['session_id'].split('-')[0]) or {}
    if time.time() - worker.get('last_seen', 0) > 60:
        raise HTTPException(409, 'The emulator worker is offline; reconnect it before checking live controls')
    if not {'game_live_controls', 'auf_live'} <= set(worker.get('tools') or []):
        raise HTTPException(409, 'This worker needs a safe idle refresh to load Agent Under Fire live controls')
    try:
        expected = worker_sources()
    except OSError as exc:
        raise HTTPException(409, 'Agent Under Fire live control sources are not installed on the server') from exc
    if any(worker.get('build_sources', {}).get(name) != sha for name, sha in expected.items()):
        raise HTTPException(409, 'This worker needs a safe idle refresh to load the current verified live controls')


def instructions(game):
    gid = game['game_id']
    return (f'Discover and implement live controls for {game.get("title") or gid} using the owned executable in Ghidra. '
        'Inventory the item database, native give/spawn/upgrade paths, level completion, boss health, NPC spawning, '
        'walk-through-walls/obstacles (noclip), warp-to-next-checkpoint, unlimited ammunition and a pistol firing '
        'rockets through the native projectile path, plus every hidden character, costume, level, mode, item and extra. '
        'These are standing discovery targets for each decomposed game. Cover each relevant play mode; distinguish '
        'not relevant from unknown. Preserve operator games and personal saves; use isolated offline test sessions. '
        'Implement native insertion/spawning through the game\'s routines, not guessed item IDs or arbitrary pointers. '
        'Record exact executable SHA256, immutable loaded revision fingerprints, mode/scene guards, parameter ranges '
        'and item choices, Ghidra artifacts and actual runtime evidence. Add the reusable adapter if required. '
        'Give-item controls need real item names in a bounded choice dropdown. Persistent switches need verified '
        'enable/disable behavior and an inspected current boolean state; do not present one-shot writes as toggles. '
        f'Publish tested actions with POST /api/games/{gid}/live-controls/profile (see docs/live-controls.md). '
        'Publication makes the Mods panel available without another UI change. Pending research is not a working action. '
        'Unlock-all is also the standing default acceptance requirement for EVERY custom build; implement it in the '
        'build writer/recipe, preserve base ROM and original saves, and submit exact-build receipts via '
        '/api/custom-build-unlocks. A live switch alone does not fulfill build acceptance.')


def routes(app, store, auth, submit, JobRequest, create_request, investigate):
    lock = threading.RLock()

    def game(gid):
        value = store.catalog_get(gid)
        if not value:
            raise HTTPException(404, 'Game is not in the owned catalog')
        return value

    @app.get('/api/games/{gid}/live-controls')
    def get(gid: str, actor=Depends(auth)):
        g = game(gid)
        p = store.get(L.PROFILE, gid)
        return {'game_id': gid, 'title': g.get('title'), 'profile': p,
                'categories': L.CATEGORIES, 'task': store.get(L.TASK, gid),
                'requested_controls': list(L.REQUESTED_CONTROLS),
                'unlock_policy': store.get('custom_build_unlock_policy', 'default') or {'enabled': False}}

    @app.post('/api/games/{gid}/live-controls/profile')
    def publish(gid: str, body: dict, actor=Depends(auth)):
        game(gid)
        try:
            p = L.validate(body, store)
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            raise HTTPException(422, str(e)) from e
        p['game_id'] = gid
        p['revision'] = L.digest(p)
        p.update(by=actor, ts=time.time())
        with lock:
            store.put(L.PROFILE, gid, p)
            store.audit(actor, 'live_controls.publish', gid, {'revision': p['revision'], 'actions': [a['id'] for a in p['actions']]})
        return p

    @app.post('/api/games/{gid}/live-controls/discover')
    def discover(gid: str, actor=Depends(auth)):
        g = game(gid)
        with lock:
            t = store.get(L.TASK, gid) or {}
            r = store.get('request', t.get('request_id')) if t.get('request_id') else None
            changed = t.get('discovery_schema') != L.DISCOVERY_SCHEMA
            if not r:
                r = create_request({'title': f'Live inventory, world controls and hidden content: {g.get("title") or gid}'[:140],
                    'body': instructions(g), 'source': 'api', 'automated': True,
                    'context': {'game_id': gid, 'game_live_controls': gid, 'requires_ghidra': True,
                                'requested_controls': list(L.REQUESTED_CONTROLS),
                                'discovery_schema': L.DISCOVERY_SCHEMA}})
            elif changed:
                r.setdefault('context', {}).update(requested_controls=list(L.REQUESTED_CONTROLS),
                                                   discovery_schema=L.DISCOVERY_SCHEMA)
                r.setdefault('messages', []).append({'author': 'system', 'ts': time.time(),
                    'text': 'Additional standing live-control discovery requirements:\n' + instructions(g),
                    'attachments': []})
                store.put('request', r['id'], r)
            if r.get('status') == 'done':
                r['status'] = 'open'
                store.put('request', r['id'], r)
                t['dispatched'] = False
            if changed:
                t['dispatched'] = False
            t.update(request_id=r['id'], number=r['number'], discovery_schema=L.DISCOVERY_SCHEMA,
                     requested_controls=list(L.REQUESTED_CONTROLS))
            store.put(L.TASK, gid, t)
            if not t.get('dispatched'):
                try:
                    t['dispatch'] = investigate(r['id'], r['number'], instructions(g), name=f'Live game controls #{r["number"]}')
                    t['dispatched'] = True
                    t.pop('error', None)
                except Exception as e:
                    t['error'] = str(e)
                store.put(L.TASK, gid, t)
            return t

    @app.post('/api/games/{gid}/live-controls/run')
    def run(gid: str, body: dict, actor=Depends(auth)):
        game(gid)
        try:
            inp = L.LiveIn.model_validate(body | {'game_id': gid})
            if inp.op not in ('inspect', 'apply'):
                raise ValueError('Use inspect or apply')
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        s = store.get('session', inp.session_id)
        if not s or s.get('game_id') != gid or s.get('state') != 'running':
            raise HTTPException(409, 'Select a running session of this game')
        p = store.get(L.PROFILE, gid)
        if not p or p['revision'] != inp.revision:
            raise HTTPException(409, 'The research profile changed; refresh')
        require_current_worker(store, s | {'session_id': inp.session_id}, p)
        if inp.op == 'apply':
            a = next((a for a in p['actions'] if a['id'] == inp.action), None)
            try:
                if not a: raise ValueError('Unknown control')
                L.values_for(a, inp.values)
                now = time.time()
                # Old clients get a short deadline at submission, never at worker
                # execution. A client-supplied earlier deadline is not extended.
                if inp.expires:
                    if not math.isfinite(inp.expires) or inp.expires <= now:
                        raise ValueError('This control command expired; refresh and activate it again')
                    inp.expires = min(inp.expires, now + 15)
                else:
                    inp.expires = now + 15
                inp.command_id = inp.command_id or uuid.uuid4().hex
                if not re.fullmatch(r'[A-Za-z0-9_-]{16,64}', inp.command_id):
                    raise ValueError('command_id must be a unique 16-64 character identifier')
            except ValueError as e:
                raise HTTPException(422, str(e)) from e
        with lock:
            if inp.op == 'apply':
                fingerprint = L.digest({'game_id': gid, 'session_id': inp.session_id, 'revision': inp.revision,
                                        'action': inp.action, 'values': inp.values})
                prior = store.get(L.COMMAND, inp.command_id)
                if prior:
                    if prior.get('fingerprint') != fingerprint or not prior.get('job'):
                        raise HTTPException(409, 'This command was already submitted; refresh before another action')
                    return store.get('job', prior['job']['id']) or prior['job']
                # Reserve before submit. An uncertain submission is never repeated.
                receipt = {'fingerprint': fingerprint, 'expires': inp.expires, 'by': actor, 'ts': time.time()}
                store.put(L.COMMAND, inp.command_id, receipt)
            j = submit(JobRequest(tool='game_live_controls', input=inp.model_dump(),
                                  require_worker=inp.session_id.split('-')[0]), actor)
            if inp.op == 'apply':
                # The real server returns a Job model; store.put's default=str
                # would otherwise turn it into a string and break replay lookup.
                job = j.model_dump(mode='json') if hasattr(j, 'model_dump') else j
                store.put(L.COMMAND, inp.command_id, receipt | {'job': job})
        return j
