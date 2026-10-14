"""Standing unlock-all requirement, Ghidra work queue, and exact-build verification.

Discovery is per game; acceptance is per build version. A queued task, installed
decompiler, or working character swap is never evidence that everything unlocked.
"""
import hashlib
import json
import re
import threading
import time

POLICY = 'custom_build_unlock_policy'
TASK = 'custom_build_unlock_task'
PROFILE = 'custom_build_unlock_profile'
RECEIPT = 'custom_build_unlock_receipt'
CATEGORIES = ('characters', 'hidden_characters', 'levels', 'stages', 'costumes', 'modes', 'items', 'extras')


def version(rec):
    return hashlib.sha256(json.dumps([rec['game_id'], rec['name'], rec.get('meta') or {}, rec.get('marker')],
                                     sort_keys=True, default=str).encode()).hexdigest()


def badge(store, rec):
    if not (store.get(POLICY, 'default') or {}).get('enabled'): return None
    gid, name = rec['game_id'], rec['name']
    profile, task = store.get(PROFILE, gid), store.get(TASK, gid) or {}
    receipt = store.get(RECEIPT, f'{gid}/{name}') or {}
    verified = bool(profile and not receipt.get('invalidated') and receipt.get('version') == version(rec)
                    and receipt.get('profile_revision') == profile['revision'])
    return {'status': 'verified' if verified else 'pending', 'required': True,
            'number': task.get('number'), 'request_id': task.get('request_id'),
            'label': 'All unlocks verified' if verified else 'Unlock-all pending',
            'categories': list(CATEGORIES), 'error': task.get('error')}


def artifacts(store, values, label):
    if not isinstance(values, list) or not values:
        raise ValueError(f'{label} requires stored evidence artifacts')
    for sha in values:
        if not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha):
            raise ValueError(f'{label}: use artifact SHA256 identifiers')
        if not store.read_artifact(sha): raise ValueError(f'{label}: artifact {sha} is unavailable')
    return values


def validate_profile(store, body):
    sha = body.get('executable_sha256')
    if not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha):
        raise ValueError('Pin the exact source executable SHA256')
    inventory = body.get('inventory')
    if not isinstance(inventory, dict) or set(inventory) != set(CATEGORIES):
        raise ValueError('Account for every unlock category, including categories absent from this game')
    for category, row in inventory.items():
        if not isinstance(row, dict) or row.get('status') not in ('unlocked', 'not_present') or not str(row.get('evidence') or '').strip():
            raise ValueError(f'{category}: record unlocked/not_present and supporting evidence')
        entries = row.get('entries')
        if not isinstance(entries, list) or any(not isinstance(x, str) or not x.strip() for x in entries):
            raise ValueError(f'{category}: enumerate the unlockable entries')
        if (row['status'] == 'unlocked') != bool(entries):
            raise ValueError(f'{category}: unlocked entries must be enumerated; absent categories must be empty')
    if body.get('inventory_complete') is not True:
        raise ValueError('Incomplete discovery cannot be called unlock-all')
    implementation = str(body.get('implementation') or '').strip()
    if not implementation: raise ValueError('Record the reusable writer/patch implementation and how builds apply it')
    return {'executable_sha256': sha, 'inventory': inventory, 'inventory_complete': True,
            'implementation': implementation,
            'ghidra_artifacts': artifacts(store, body.get('ghidra_artifacts'), 'Ghidra analysis'),
            'runtime_artifacts': artifacts(store, body.get('runtime_artifacts'), 'Unlock verification')}


def instructions(game, builds, profile=None):
    gid = game['game_id']
    names = '\n'.join(f'- {r["name"]} (version {version(r)})' for r in builds)
    return (f'Standing operator requirement: every custom build of {game.get("title") or gid} must unlock everything '
        'unlockable in the owned game: characters, hidden characters, levels, hidden levels, stages, costumes, modes, '
        'items and extras. This is part of build acceptance, not an optional enhancement.\n\n'
        'Use re_executable/re_study and Ghidra (ghidra_bridge decompile, xrefs, strings and/or ghidra_script) on the '
        'exact executable. Inventory unlockable content and trace lock predicates, progress flags and menu selection '
        'checks. Record executable hashes, addresses, expected original bytes and analysis artifacts. Do not guess '
        'addresses or use another region/revision blindly. Account for hidden content, not just visible menu entries.\n'
        'Implement a reusable game/revision-specific unlock step in the custom-build writer and its rebuild recipe. '
        'Apply it automatically to every custom build for this game, preserving character/stage mods. Prefer built-in '
        'custom-ROM changes or a build-specific save overlay; preserve the base ROM and original personal saves. '
        'Handle image checksums/container rebuilding. Keep source and analysis reusable so future builds need no '
        'fresh Ghidra analysis or long launch delay. Do not run Ghidra on the Play path.\n'
        'Use an idle test machine and separate test saves; never stop, switch or modify the operator\'s running game. '
        'Verify a fresh boot, actual selection and gameplay for every discovered unlock, including hidden stages. '
        'Do not confuse model replacement with unlocking its selection. If a category has no content, record evidence '
        'for not_present; unavailable content stays explicitly unsupported. Do not claim universal completion from a subset.\n\n'
        f'Profile: POST /api/custom-build-unlocks/{gid}/profile with executable_sha256, inventory_complete:true, '
        'implementation (reusable code/recipe and applicability), ghidra_artifacts and runtime_artifacts (stored artifact '
        f'SHA256 IDs), and inventory covering exactly {", ".join(CATEGORIES)}. Each category has status unlocked or '
        'not_present, entries (all names, empty only for not_present), and evidence.\n'
        f'For EACH resulting build: GET /api/custom-build-unlocks/{gid}/BUILD/manifest and POST '
        f'/api/custom-build-unlocks/{gid}/BUILD/verify with version, profile_revision, files (the exact SHA256 manifest), '
        'runtime_artifacts and notes proving the complete inventory works in THAT build. Do not post verification '
        'until the unlock step is applied and tested. Changed builds lose their prior acceptance. Closing this ticket '
        'without those receipts does not fulfill the requirement.\n\n'
        + (f'Reuse existing profile revision {profile["revision"]}: {profile["implementation"]}\n' if profile else '')
        + f'Current builds (refresh GET /api/custom-build-unlocks for additions):\n{names}')


def stat_signature(folder):
    from .build_quarantine import safe_tree
    from .filemods import STAGED_MARK
    safe_tree(folder.parent, folder)
    return [[p.relative_to(folder).as_posix(), p.stat().st_size, p.stat().st_mtime_ns]
            for p in sorted(folder.rglob('*')) if p.is_file() and p.name != STAGED_MARK and not p.name.endswith('.part')]


def routes(app, store, cfg, auth, create_request, investigate, workers=lambda: []):
    from fastapi import Depends, HTTPException
    from . import filemods, build_quarantine as Q
    guard, wake, stop = threading.RLock(), threading.Event(), threading.Event()

    def records():
        index = getattr(app.state, 'built_mods', None)
        rows = index.records() if index else []
        seen = {(r['game_id'], r['name']) for r in rows}
        for worker in workers():
            if worker.get('os') != 'windows': continue
            for b in worker.get('local_builds') or []:
                gid, name = b.get('game_id'), b.get('staged_of') or str(b.get('name') or '').split('~')[0]
                if not gid or not name or (gid, name) in seen: continue
                rows.append({'game_id': gid, 'name': name, 'meta': {'built': b.get('built'), 'local_only': True}})
                seen.add((gid, name))
        return rows

    def current(gid, name):
        filemods.mod_dir(cfg, gid, name)
        rec = next((r for r in records() if r['game_id'] == gid and r['name'] == name), None)
        if not rec: raise ValueError('Build is not in the current collection index')
        return rec

    def invalidate():
        inv = getattr(app.state, 'built_mods_invalidate', None)
        if inv: inv()

    def pending(gid):
        if not (store.get(POLICY, 'default') or {}).get('enabled'): return []
        names = []
        for rec in records():
            if rec['game_id'] != gid: continue
            key = f'{gid}/{rec["name"]}'
            broken = store.get(Q.KIND, key)
            if broken and broken.get('state') != 'deleted': continue
            accepted = badge(store, rec)['status'] == 'verified'
            if accepted:
                receipt = store.get(RECEIPT, key)
                try: accepted = stat_signature(filemods.mod_dir(cfg, gid, rec['name'])) == receipt.get('signature')
                except (OSError, ValueError): accepted = False
            if not accepted: names.append(rec['name'])
        return names
    app.state.custom_build_unlocks_pending = pending

    def reconcile():
        with guard:
            if not (store.get(POLICY, 'default') or {}).get('enabled'): return
            for receipt in store.all(RECEIPT):
                if receipt.get('invalidated'): continue
                try:
                    gid, name = receipt['key'].split('/', 1)
                    valid = stat_signature(filemods.mod_dir(cfg, gid, name)) == receipt.get('signature')
                except (OSError, ValueError): valid = False
                if not valid:
                    store.put(RECEIPT, receipt['key'], receipt | {'invalidated': time.time()})
            groups = {}
            for rec in records():
                broken = store.get(Q.KIND, f'{rec["game_id"]}/{rec["name"]}')
                if broken and broken.get('state') != 'deleted': continue
                groups.setdefault(rec['game_id'], []).append(rec)
            for gid, builds in groups.items():
                if all(badge(store, r)['status'] == 'verified' for r in builds): continue
                game = store.catalog_get(gid) or {'game_id': gid, 'title': gid}
                profile = store.get(PROFILE, gid)
                task = store.get(TASK, gid) or {'game_id': gid}
                request = store.get('request', task.get('request_id')) or next((r for r in store.all('request')
                    if r.get('context', {}).get('custom_build_unlocks') == gid), None)
                versions = {r['name']: version(r) for r in builds}
                changed = task.get('versions') != versions or task.get('profile_revision') != (profile or {}).get('revision')
                text = instructions(game, builds, profile)
                new_request = not request
                if not request:
                    request = create_request({'title': f'Unlock everything in custom builds: {game.get("title") or gid}'[:140],
                        'body': text, 'source': 'api', 'automated': True,
                        'context': {'custom_build_unlocks': gid, 'game_id': gid, 'requires_ghidra': True}})
                reopened = request.get('status') == 'done'
                if changed or reopened:
                    request['status'] = 'open' if reopened else request.get('status', 'open')
                    request.setdefault('context', {})['unlock_build_versions'] = versions
                    if not new_request:
                        summary = 'Unlock-all acceptance pending for current builds: ' + ', '.join(r['name'] for r in builds
                            if badge(store, r)['status'] != 'verified')
                        request.setdefault('messages', []).append({'author': 'system', 'ts': time.time(), 'text': summary,
                            'attachments': []})
                    store.put('request', request['id'], request)
                dispatch = changed or reopened or not task.get('dispatched')
                if changed or reopened or not task.get('attempt'):
                    task['attempt'] = task.get('attempt', 0) + 1
                task.update(request_id=request['id'], number=request['number'], versions=versions,
                            profile_revision=(profile or {}).get('revision'), updated=time.time())
                store.put(TASK, gid, task)  # link survives dispatch errors; never create duplicate tickets
                if dispatch:
                    try:
                        task['dispatch'] = investigate(request['id'], request['number'], text,
                            name=f'Custom build unlocks #{request["number"]}', attempt=task['attempt'])
                        task['dispatched'] = True
                        task.pop('error', None)
                    except Exception as exc:
                        task.update(dispatched=False, error=str(exc))
                    store.put(TASK, gid, task)
            invalidate()

    @app.get('/api/custom-build-unlocks')
    def status(actor=Depends(auth)):
        policy = store.get(POLICY, 'default') or {'enabled': False}
        rows = [{'game_id': r['game_id'], 'name': r['name'], 'version': version(r), 'unlocks': badge(store, r)} for r in records()]
        return {'policy': policy, 'builds': rows, 'tasks': store.all(TASK),
                'verified': sum((r['unlocks'] or {}).get('status') == 'verified' for r in rows), 'total': len(rows)}

    @app.post('/api/custom-build-unlocks/policy')
    def policy(body: dict, actor=Depends(auth)):
        if type(body.get('enabled')) is not bool: raise HTTPException(422, 'enabled must be a boolean')
        value = {'enabled': body['enabled'], 'categories': list(CATEGORIES), 'requires_ghidra': True,
                 'scope': 'every_custom_build', 'by': actor, 'ts': time.time()}
        store.put(POLICY, 'default', value)
        store.audit(actor, 'custom_build_unlocks.policy', 'default', value)
        invalidate(); wake.set()
        return value

    @app.post('/api/custom-build-unlocks/{gid}/profile')
    def profile(gid: str, body: dict, actor=Depends(auth)):
        try: value = validate_profile(store, body)
        except (ValueError, FileNotFoundError) as exc: raise HTTPException(422, str(exc)) from exc
        with guard:
            value['revision'] = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
            value.update(game_id=gid, by=actor, ts=time.time())
            store.put(PROFILE, gid, value)
            store.audit(actor, 'custom_build_unlocks.profile', gid, {'revision': value['revision']})
        wake.set(); invalidate()
        return value

    @app.get('/api/custom-build-unlocks/{gid}/profile')
    def read_profile(gid: str, actor=Depends(auth)):
        from .game_unlocks import profile_for
        return {'profile': store.get(PROFILE, gid), 'existing_unlock_support': profile_for(
            store.catalog_get(gid) or {'game_id': gid})}

    @app.get('/api/custom-build-unlocks/{gid}/{name}/manifest')
    def manifest(gid: str, name: str, actor=Depends(auth)):
        try:
            rec = current(gid, name)
            return {'version': version(rec), 'profile_revision': (store.get(PROFILE, gid) or {}).get('revision'),
                    'files': Q.manifest(filemods.mod_dir(cfg, gid, name))}
        except ValueError as exc: raise HTTPException(409, str(exc)) from exc

    @app.post('/api/custom-build-unlocks/{gid}/{name}/verify')
    def verify(gid: str, name: str, body: dict, actor=Depends(auth)):
        with guard:
            try:
                rec = current(gid, name); p = store.get(PROFILE, gid)
                if not p or body.get('profile_revision') != p['revision']: raise ValueError('Use the current verified profile')
                if body.get('version') != version(rec): raise ValueError('Build changed; verify the current version')
                if not str(body.get('notes') or '').strip(): raise ValueError('Describe the application and complete runtime verification')
                evidence = artifacts(store, body.get('runtime_artifacts'), 'This build runtime verification')
                folder = filemods.mod_dir(cfg, gid, name)
                before = stat_signature(folder)
                files = Q.manifest(folder)
                signature = stat_signature(folder)
                if before != signature: raise ValueError('Build changed during verification')
                if body.get('files') != files: raise ValueError('Build bytes changed; verification manifest does not match')
                key = f'{gid}/{name}'
                receipt = {'key': key, 'version': version(rec), 'profile_revision': p['revision'], 'files': files,
                           'signature': signature, 'runtime_artifacts': evidence, 'notes': str(body['notes'])[:12000], 'by': actor, 'ts': time.time()}
                store.put(RECEIPT, key, receipt)
                store.audit(actor, 'custom_build_unlocks.verified', key, {'version': receipt['version']})
            except (ValueError, FileNotFoundError) as exc: raise HTTPException(409, str(exc)) from exc
        invalidate(); wake.set()
        return receipt

    def loop():
        while not stop.is_set():
            wake.wait(30); wake.clear()
            if stop.is_set(): break
            try: reconcile()
            except Exception as exc: print(f'Custom build unlock scan deferred: {exc}', flush=True)
    app.on_event('startup')(lambda: threading.Thread(target=loop, daemon=True, name='custom-build-unlocks').start())
    app.on_event('shutdown')(lambda: (stop.set(), wake.set()))
    return reconcile
