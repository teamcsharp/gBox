"""Persistent discovery -> verified live control publication -> session-pinned jobs."""
import threading
import time
from fastapi import Depends, HTTPException
from . import live_controls as L


def instructions(game):
    gid = game['game_id']
    return (f'Discover and implement live controls for {game.get("title") or gid} using the owned executable in Ghidra. '
        'Inventory the item database, native give/spawn/upgrade paths, level completion, boss health, NPC spawning, '
        'and every hidden character, costume, level, mode, item and extra. Cover each relevant play mode; distinguish '
        'not relevant from unknown. Preserve operator games and personal saves; use isolated offline test sessions. '
        'Implement native insertion/spawning through the game\'s routines, not guessed item IDs or arbitrary pointers. '
        'Record exact executable SHA256, immutable loaded revision fingerprints, mode/scene guards, parameter ranges '
        'and item choices, Ghidra artifacts and actual runtime evidence. Add the reusable adapter if required. '
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
            if not r:
                r = create_request({'title': f'Live inventory, world controls and hidden content: {g.get("title") or gid}'[:140],
                    'body': instructions(g), 'source': 'api', 'automated': True,
                    'context': {'game_id': gid, 'game_live_controls': gid, 'requires_ghidra': True}})
            if r.get('status') == 'done':
                r['status'] = 'open'
                store.put('request', r['id'], r)
                t['dispatched'] = False
            t.update(request_id=r['id'], number=r['number'])
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
        if inp.op == 'apply':
            a = next((a for a in p['actions'] if a['id'] == inp.action), None)
            try:
                if not a: raise ValueError('Unknown control')
                L.values_for(a, inp.values)
            except ValueError as e:
                raise HTTPException(422, str(e)) from e
        j = submit(JobRequest(tool='game_live_controls', input=inp.model_dump(),
                              require_worker=inp.session_id.split('-')[0]), actor)
        return j
