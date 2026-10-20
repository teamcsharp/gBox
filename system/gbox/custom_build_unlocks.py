"""Standing unlock-all requirement, Ghidra work queue, and exact-build verification.

Discovery is per game; acceptance is per build version. A queued task, installed
decompiler, or working character swap is never evidence that everything unlocked.
"""
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import time

POLICY = 'custom_build_unlock_policy'
TASK = 'custom_build_unlock_task'
PROFILE = 'custom_build_unlock_profile'
RECEIPT = 'custom_build_unlock_receipt'
CATEGORIES = ('characters', 'hidden_characters', 'levels', 'stages', 'costumes', 'modes', 'items', 'extras')
BASE = '@original'
FAVORITE_DEFAULTS = {'favorites_enabled': True, 'default_boot': True, 'idle_resolution': True,
                     'excluded_games': [], 'quiet_seconds': 300, 'dispatch_per_hour': 2}


def policy_value(store):
    return {'enabled': False, **FAVORITE_DEFAULTS, **(store.get(POLICY, 'default') or {})}


def favorite_games(store):
    """The authoritative unfiltered favorite table, including missing titles."""
    rows = store.favorites() if callable(getattr(store, 'favorites', None)) else []
    if not isinstance(rows, list) or any(not isinstance(r, dict) or not r.get('game_id') for r in rows):
        raise ValueError('A complete favorite inventory is required')
    return {r['game_id']: r for r in rows}


def base_record(game):
    # Catalog identity is cheap; executable and native revision guards are
    # separately pinned by the accepted profile. Never hash/copy a ROM on Play.
    identity = {k: game.get(k) for k in ('game_id', 'platform', 'serial', 'library', 'rel_path',
                                        'source_paths', 'size', 'hashes', 'format')}
    return {'game_id': game['game_id'], 'name': BASE, 'base': True, 'meta': identity}


def required(store, rec):
    policy = policy_value(store)
    if policy['enabled'] and not rec.get('base'):
        return True
    if rec.get('favorite_required') is True:
        return bool(policy['favorites_enabled'] and rec['game_id'] not in policy['excluded_games'])
    favorite = (policy['favorites_enabled'] and rec['game_id'] not in policy['excluded_games']
                and rec['game_id'] in favorite_games(store))
    return bool(favorite or policy['enabled'] and not rec.get('base'))


def idle_reason(store, workers, policy, *, now=None, parent_request_id='', owned_hermes_ids=(), require_guard=False):
    """Fresh measured admission before dispatching one bounded research request."""
    from . import background_testing as B
    from .hermes_activation import read_cron_snapshot
    now = time.time() if now is None else now
    if not policy['idle_resolution']:
        return 'Idle unlock research is paused'
    if require_guard:
        from .hermes_unlock_guard import readiness_reason
        if reason := readiness_reason():
            return reason
    sessions = store.running_sessions()
    if sessions:
        return 'Waiting for games to stop; unlock research never interrupts gameplay'
    chats = store.all('chat')
    if any(type(c.get('busy')) is not bool for c in chats):
        return 'Waiting for a complete conversation inventory'
    if any(c['busy'] for c in chats):
        return 'Waiting for the active conversation to finish'
    if any(type(c.get('updated')) in (int, float) and 0 <= now - c['updated'] < policy['quiet_seconds'] for c in chats):
        return 'Waiting for quiet time after the latest conversation'
    jobs = store.jobs(states=('running',), limit=1001)
    if len(jobs) > 1000:
        return 'Waiting for a complete bounded running-job inventory'
    own_jobs = [j for j in jobs if parent_request_id and j.get('parent_request_id') == parent_request_id]
    if any(j not in own_jobs for j in jobs):
        return 'Waiting for running worker jobs to finish'
    if not isinstance(workers, list) or not workers:
        return 'Waiting for a registered research worker'
    for worker in workers:
        if worker.get('online') is True:
            if any(type(worker.get(k)) is not int or worker[k] < 0 for k in ('active_jobs', 'pending_results')):
                return 'Waiting for a complete worker inventory'
            own_count = sum(j.get('worker_id') == worker['id'] for j in own_jobs)
            if worker['active_jobs'] > own_count or worker['pending_results']:
                return 'Waiting for worker execution and result delivery'
            if worker.get('os') == 'windows':
                idle = worker.get('idle_seconds')
                if type(idle) not in (int, float) or not math.isfinite(idle) or idle < policy['quiet_seconds']:
                    return 'Waiting for operator input to be idle on every online PC'
    eligible = [w for w in workers if w.get('online') is True and w.get('os') == 'linux'
                and isinstance(w.get('id'), str) and isinstance(w.get('name'), str)]
    if not any(B.guarded_reason(store, w, now=now) is None for w in eligible):
        return 'Waiting for fresh idle CPU/GPU/memory admission on Spark'
    try:
        cron = read_cron_snapshot(Path(__import__('os').environ.get('GBOX_HERMES_HOME') or Path.home() / '.hermes'))
    except (OSError, ValueError, TypeError, RuntimeError):
        return 'Waiting for a complete canonical research execution inventory'
    if cron['hermes']:
        from . import hermes_task_mode
        controller = hermes_task_mode._job() or {}
        # The bounded no-agent dispatcher is the caller of the admission API.
        # It is not an LLM investigation and cannot block its own admission.
        active = [run for run in cron['hermes'] if not (controller.get('no_agent') is True
                  and run.get('job_id') == controller.get('id')) and run.get('job_id') not in owned_hermes_ids]
        if active:
            return 'Waiting for active Hermes work to finish'
    return ''


def version(rec):
    return hashlib.sha256(json.dumps([rec['game_id'], rec['name'], rec.get('meta') or {}, rec.get('marker')],
                                     sort_keys=True, default=str).encode()).hexdigest()


def badge(store, rec):
    if not required(store, rec): return None
    gid, name = rec['game_id'], rec['name']
    profile, task = store.get(PROFILE, gid), store.get(TASK, gid) or {}
    receipt = store.get(RECEIPT, f'{gid}/{name}') or {}
    verified = bool(profile and not receipt.get('invalidated') and receipt.get('version') == version(rec)
                    and receipt.get('profile_revision') == profile['revision'])
    if rec.get('base') and not (profile or {}).get('boot_apply'):
        verified = False
    held = None
    if not verified:
        # A verified unlock-on-load code profile (profiles/gamedata/<game_id>-codes.json, gbox.game_unlocks) holds its
        # unlocks in every session of the game from launch, stock or custom build alike (2026-10-19).
        from .game_unlocks import code_profile
        game = (store.catalog_get(gid) if hasattr(store, 'catalog_get') else None) or {}
        held = code_profile({'game_id': gid, 'platform': game.get('platform') or rec.get('platform')})
        verified = bool(held)
    label = ('Unlocks held on load: ' + ', '.join(held.get('scope') or [])[:120]) if held else \
        ('All unlocks verified' if verified else 'Unlock-all pending')
    return {'status': 'verified' if verified else 'pending', 'required': True,
            'number': task.get('number'), 'request_id': task.get('request_id'),
            'label': label, 'categories': list(CATEGORIES), 'error': task.get('error'),
            **({'code_profile': held.get('profile')} if held else {})}


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
    out = {'executable_sha256': sha, 'inventory': inventory, 'inventory_complete': True,
            'implementation': implementation,
            'ghidra_artifacts': artifacts(store, body.get('ghidra_artifacts'), 'Ghidra analysis'),
            'runtime_artifacts': artifacts(store, body.get('runtime_artifacts'), 'Unlock verification')}
    if 'boot_apply' in body:
        from . import live_controls as L
        recipe = body['boot_apply']
        if (not isinstance(recipe, dict) or set(recipe) != {'kind', 'revision', 'action', 'values', 'coverage', 'runtime_artifacts'}
                or recipe.get('kind') != 'live_control' or recipe.get('coverage') != inventory):
            raise ValueError('Boot application needs a published live control and the complete exact inventory coverage')
        live = store.get(L.PROFILE, body.get('game_id'))
        if not live or live.get('revision') != recipe.get('revision') or live.get('executable_sha256') != sha:
            raise ValueError('Boot action must reference the current exact-executable live-control profile')
        action = next((a for a in live.get('actions', []) if a.get('id') == recipe.get('action')), None)
        if not action or action.get('category') != 'unlocks' or action.get('binding', {}).get('kind') != 'native':
            raise ValueError('Boot action must be an already published native unlock control')
        binding = action['binding']
        if binding.get('input', {}).get('op') != 'unlock_all' or binding.get('tool') not in L.NATIVE:
            raise ValueError('Partial native actions cannot fulfill unlock-all at boot')
        L.values_for(action, recipe['values'])
        resolved = {k: recipe['values'][v[1:]] if isinstance(v, str) and v.startswith('$') else v
                    for k, v in binding.get('input', {}).items()}
        if any(resolved.get(key) is False for key in ('on', 'enable', 'enabled')):
            raise ValueError('A disabled/revert action cannot be an unlock boot default')
        out['boot_apply'] = recipe | {'runtime_artifacts': artifacts(store, recipe['runtime_artifacts'], 'Complete boot application')}
    return out


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
        'Publish reusable tested live inventory, item upgrades/spawning, level completion, next-checkpoint warps, '
        'walk-through-walls/obstacles, unlimited ammunition, native pistol-to-rocket projectile overrides, boss health and NPC '
        'controls discovered during this research with POST /api/games/' + gid + '/live-controls/profile '
        '(docs/live-controls.md). Include mode guards, bounded inputs, native routines, executable fingerprints '
        'and stored Ghidra/runtime evidence. Use named item dropdowns and native enable/disable switches with inspected '
        'boolean state, and test restoring each switch. Account for unknown and inapplicable controls explicitly. '
        'This exposes findings in Mods automatically; do not substitute live '
        'switches for the required default unlock step in every rebuilt ROM.\n'
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


def favorite_instructions(game, builds, profile=None):
    """Original-title boot work never inherits custom-ROM rebuilding guidance."""
    gid = game['game_id']
    names = '\n'.join(f'- {r["name"]} (version {version(r)})' for r in builds)
    return (f'Standing favorite default: {game.get("title") or gid} must boot with every unlockable character, '
        'hidden character, level (including hidden levels), stage, costume, mode, item and extra available. '
        '@original is the unmodified catalog title; the listed custom builds keep their exact existing payloads.\n\n'
        'Research only while idle. Reuse existing REA/Ghidra findings, captured RAM/executable artifacts, exact '
        'source hashes and tested native controls. Do not copy/promote/rebuild a ROM for discovery, run '
        're_executable/re_study with source auto/disc, launch an emulator, edit personal saves, or alter any current '
        'game. Analysis does not belong on Play. If needed evidence is unavailable, retain the precise pending '
        'gap; never guess addresses or use another revision.\n\n'
        f'Use the favorite_unlocks MCP convenience with this assigned request_id and game_id {gid} for '
        'status, native_profile, unlock_profile, manifest and verify metadata; no shell is needed to publish evidence. '
        'Trace native lock predicates/progress flags and inventory every unlockable entry. Publish a reusable '
        'exact-executable native unlock_all control with revision/mode guards through '
        f'POST /api/games/{gid}/live-controls/profile. Partial native actions are insufficient. The boot recipe '
        'must preserve original ROMs/saves and cover all eight categories, including evidence for absent content. '
        'Existing baked-in mod unlocks can reuse their exact accepted build receipts.\n\n'
        f'POST /api/custom-build-unlocks/{gid}/profile with executable_sha256, inventory_complete:true, '
        'implementation, stored ghidra_artifacts/runtime_artifacts, and inventory covering exactly '
        f'{", ".join(CATEGORIES)}. Each category needs status unlocked/not_present, all named entries (empty only '
        'for absent content) and evidence. For @original include boot_apply: kind live_control, current published '
        'revision/action, exact declared values, coverage equal to that entire inventory, and stored runtime_artifacts '
        'proving full boot application. No generic verified flag or one field can prove everything unlocked.\n\n'
        f'For each listed target GET /api/custom-build-unlocks/{gid}/NAME/manifest and POST '
        f'/api/custom-build-unlocks/{gid}/NAME/verify with matching version/profile_revision/files, stored '
        'runtime_artifacts and complete verification notes. @original uses a cheap catalog/executable identity; '
        'custom payload receipts retain exact existing files. Runtime acceptance needs preserved evidence of a '
        'fresh boot and actual selection/gameplay for the complete inventory; do not launch a game automatically '
        'to obtain it. Missing evidence remains pending, and closing a ticket is not acceptance.\n\n'
        + (f'Reuse profile revision {profile["revision"]}: {profile["implementation"]}\n' if profile else '')
        + f'Current exact targets:\n{names}')


def stat_signature(folder):
    from .build_quarantine import safe_tree
    from .filemods import STAGED_MARK
    safe_tree(folder.parent, folder)
    return [[p.relative_to(folder).as_posix(), p.stat().st_size, p.stat().st_mtime_ns]
            for p in sorted(folder.rglob('*')) if p.is_file() and p.name != STAGED_MARK and not p.name.endswith('.part')]


def routes(app, store, cfg, auth, create_request, investigate, workers=lambda: [], admission=None):
    from fastapi import Depends, HTTPException
    from . import filemods, build_quarantine as Q
    guard, wake, stop = threading.RLock(), threading.Event(), threading.Event()
    from functools import wraps

    def serialized(fn):
        @wraps(fn)
        def invoke(*args, **kwargs):
            with guard:
                return fn(*args, **kwargs)
        return invoke
    # The standing favorite default is durable and independently switchable
    # from the older custom-build opt-in. Existing policy values always win.
    original = store.get(POLICY, 'default') or {}
    if any(key not in original for key in FAVORITE_DEFAULTS):
        store.put(POLICY, 'default', policy_value(store))

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

    def targets():
        rows = records()
        policy = policy_value(store)
        favorites = favorite_games(store) if policy['favorites_enabled'] else {}
        favorites = {gid: row for gid, row in favorites.items() if gid not in policy['excluded_games']}
        result = [r | {'favorite_required': r['game_id'] in favorites}
                  for r in rows if policy['enabled'] or r['game_id'] in favorites]
        for gid, saved in favorites.items():
            game = store.catalog_get(gid)
            if game:
                result.append(base_record(game) | {'favorite_required': True})
            else:
                result.append(base_record(saved) | {'unavailable': True, 'favorite_required': True})
        return result

    def current(gid, name):
        if name == BASE:
            game = store.catalog_get(gid)
            if not game: raise ValueError('Original game is not currently in the catalog')
            return base_record(game)
        filemods.mod_dir(cfg, gid, name)
        rec = next((r for r in records() if r['game_id'] == gid and r['name'] == name), None)
        if not rec: raise ValueError('Build is not in the current collection index')
        return rec

    def invalidate():
        inv = getattr(app.state, 'built_mods_invalidate', None)
        if inv: inv()

    def files_and_signature(rec):
        if rec.get('base'):
            profile = store.get(PROFILE, rec['game_id']) or {}
            return ([{'catalog_version': version(rec), 'executable_sha256': profile.get('executable_sha256')}], None)
        folder = filemods.mod_dir(cfg, rec['game_id'], rec['name'])
        before = stat_signature(folder)
        files = Q.manifest(folder)
        signature = stat_signature(folder)
        if before != signature: raise ValueError('Build changed during verification')
        return files, signature

    def pending(gid):
        names = []
        for rec in targets():
            if rec['game_id'] != gid: continue
            key = f'{gid}/{rec["name"]}'
            broken = store.get(Q.KIND, key)
            if broken and broken.get('state') != 'deleted': continue
            accepted = (badge(store, rec) or {}).get('status') == 'verified'
            if accepted and not rec.get('base'):
                receipt = store.get(RECEIPT, key)
                try: accepted = stat_signature(filemods.mod_dir(cfg, gid, rec['name'])) == receipt.get('signature')
                except (OSError, ValueError): accepted = False
            if not accepted: names.append(rec['name'])
        return names
    app.state.custom_build_unlocks_pending = pending

    def reconcile():
        with guard:
            policy = policy_value(store)
            if not policy['enabled'] and not policy['favorites_enabled']: return
            target_rows = targets()
            for receipt in store.all(RECEIPT):
                if receipt.get('invalidated'): continue
                try:
                    gid, name = receipt['key'].split('/', 1)
                    valid = (receipt.get('version') == version(current(gid, name)) if name == BASE else
                             stat_signature(filemods.mod_dir(cfg, gid, name)) == receipt.get('signature'))
                except (OSError, ValueError): valid = False
                if not valid:
                    store.put(RECEIPT, receipt['key'], receipt | {'invalidated': time.time()})
            groups = {}
            for rec in target_rows:
                broken = store.get(Q.KIND, f'{rec["game_id"]}/{rec["name"]}')
                if broken and broken.get('state') != 'deleted': continue
                groups.setdefault(rec['game_id'], []).append(rec)
            now = time.time()
            runtime = store.get(POLICY, 'idle-state') or {'last_busy': now}
            try:
                reason = ('Idle unlock research is paused' if not policy['idle_resolution'] else
                          admission() if admission else idle_reason(store, workers(), policy, now=now,
                              require_guard=any(r.get('base') for r in target_rows)))
            except Exception as exc:
                reason = 'Idle admission unavailable: ' + type(exc).__name__
            if reason:
                runtime.update(last_busy=now, reason=reason)
            elif now - runtime.get('last_busy', now) < policy['quiet_seconds']:
                reason = 'Waiting for the quiet interval before unlock research'
                runtime['reason'] = reason
            else:
                runtime['reason'] = ''
            store.put(POLICY, 'idle-state', runtime)
            hourly = sum(sum(1 for stamp in task.get('dispatch_times', []) if now - 3600 < stamp <= now)
                         for task in store.all(TASK))
            dispatched_this_pass = 0
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
                favorite_scope = any(r.get('base') for r in builds)
                if favorite_scope:
                    text = favorite_instructions(game, builds, profile)
                new_request = not request
                if not request:
                    title = 'Unlock everything for favorite' if any(r.get('base') for r in builds) else 'Unlock everything in custom builds'
                    request = create_request({'title': f'{title}: {game.get("title") or gid}'[:140],
                        'body': text, 'source': 'api', 'automated': True,
                        'context': {'custom_build_unlocks': gid, 'game_id': gid, 'requires_ghidra': True,
                                    'favorite_default': favorite_scope, 'idle_only': True,
                                    **({'no_automatic_launch': True, 'no_rom_copy': True} if favorite_scope else {})}})
                reopened = request.get('status') == 'done'
                context = request.setdefault('context', {})
                context.update(favorite_default=favorite_scope, idle_only=True)
                if favorite_scope:
                    context.update(no_automatic_launch=True, no_rom_copy=True)
                else:
                    context.pop('no_automatic_launch', None); context.pop('no_rom_copy', None)
                if changed or reopened:
                    request['status'] = 'open' if reopened else request.get('status', 'open')
                    request.setdefault('context', {})['unlock_build_versions'] = versions
                    # Existing per-game tickets must receive the new exact
                    # scope, not only a prefix on the dispatch prompt.
                    if favorite_scope:
                        request['body'] = text
                    if not new_request:
                        summary = 'Unlock-all acceptance pending for current builds: ' + ', '.join(r['name'] for r in builds
                            if badge(store, r)['status'] != 'verified')
                        request.setdefault('messages', []).append({'author': 'system', 'ts': time.time(), 'text': summary,
                            'attachments': []})
                    store.put('request', request['id'], request)
                dispatch = changed or reopened or not task.get('dispatched')
                if changed or reopened:
                    task['dispatched'] = False  # a prior version's release cannot satisfy new pending work
                if changed or reopened or not task.get('attempt'):
                    task['attempt'] = task.get('attempt', 0) + 1
                task.update(request_id=request['id'], number=request['number'], versions=versions,
                            profile_revision=(profile or {}).get('revision'), updated=now,
                            state='pending', reason=reason or ('Hourly research budget reached' if hourly >= policy['dispatch_per_hour']
                                else 'Waiting for the next bounded research pass' if dispatched_this_pass else 'Missing verified unlock coverage'))
                store.put(TASK, gid, task)  # link survives dispatch errors; never create duplicate tickets
                if dispatch and not reason and hourly < policy['dispatch_per_hour'] and not dispatched_this_pass and not any(r.get('unavailable') for r in builds):
                    try:
                        request.setdefault('context', {})['unlock_dispatch'] = {
                            'versions': versions, 'profile_revision': (profile or {}).get('revision')}
                        task['job_last_busy'] = runtime.get('last_busy', now)
                        store.put('request', request['id'], request)
                        task['dispatch'] = investigate(request['id'], request['number'], text,
                            name=f'Custom build unlocks #{request["number"]}', attempt=task['attempt'])
                        task['dispatched'] = True
                        task.update(state='research_queued', reason='Research queued; unlock coverage remains unverified')
                        task.pop('error', None)
                    except Exception as exc:
                        task.update(dispatched=False, error=str(exc))
                    # Failed submissions also consume budget; a broken provider
                    # must not create a 30-second retry storm across favorites.
                    task['dispatch_times'] = [t for t in task.get('dispatch_times', []) if now - 3600 < t <= now] + [now]
                    hourly += 1; dispatched_this_pass += 1
                    store.put(TASK, gid, task)
            invalidate()

    @app.get('/api/custom-build-unlocks')
    def status(actor=Depends(auth)):
        policy = policy_value(store)
        rows = [{'game_id': r['game_id'], 'name': r['name'], 'version': version(r), 'unlocks': badge(store, r)} for r in records()]
        favorites = [{'game_id': r['game_id'], 'name': r['name'], 'version': version(r), 'unlocks': badge(store, r),
                      'available': not r.get('unavailable')} for r in targets() if r.get('base')]
        return {'policy': policy, 'builds': rows, 'favorites': favorites,
                'idle': store.get(POLICY, 'idle-state'), 'tasks': store.all(TASK),
                'verified': sum((r['unlocks'] or {}).get('status') == 'verified' for r in rows), 'total': len(rows)}

    @app.get('/api/custom-build-unlocks/dispatch-admission')
    @serialized
    def dispatch_admission(actor=Depends(auth)):
        policy = policy_value(store)
        try:
            reason = ('Idle unlock research is paused' if not policy['idle_resolution'] else
                      admission() if admission else idle_reason(store, workers(), policy,
                          require_guard=any(r.get('base') for r in targets())))
        except Exception as exc:
            reason = 'Idle admission unavailable: ' + type(exc).__name__
        runtime = store.get(POLICY, 'idle-state') or {}
        if reason:
            # Queue polling can be the only observer of short activity between
            # reconcile ticks. Persist only this guard, never enqueue work here.
            runtime.update(last_busy=time.time(), reason=reason)
            store.put(POLICY, 'idle-state', runtime)
        if not reason and time.time() - runtime.get('last_busy', time.time()) < policy['quiet_seconds']:
            reason = 'Waiting for the quiet interval before unlock research'
        eligible = []
        if not reason and (policy['enabled'] or policy['favorites_enabled']):
            versions = {}
            for rec in targets():
                versions.setdefault(rec['game_id'], {})[rec['name']] = version(rec)
            for task in store.all(TASK):
                request = store.get('request', task.get('request_id')) or {}
                release = (request.get('context') or {}).get('unlock_dispatch')
                if (task.get('dispatched') and release == {'versions': task.get('versions'),
                        'profile_revision': task.get('profile_revision')}
                        and task.get('versions') == versions.get(task['game_id'])
                        and task.get('profile_revision') == (store.get(PROFILE, task['game_id']) or {}).get('revision')
                        and pending(task['game_id'])):
                    eligible.append(task['request_id'])
        return {'allowed': not bool(reason), 'reason': reason, 'request_ids': eligible,
                'dispatch_per_hour': policy['dispatch_per_hour']}

    def job_admission(parent_request_id):
        """Submission gate for one already admitted research owner's work.

        Only canonical executions/worker jobs owned by this exact request can
        be excluded. Other work and new operator activity always win.
        """
        with guard:
            task = next((t for t in store.all(TASK) if t.get('request_id') == parent_request_id), None)
            request = store.get('request', parent_request_id) or {}
            if not task or not task.get('dispatched'):
                return 'Unlock research has no current admitted task'
            if not pending(task['game_id']):
                return 'All current exact targets already have verified coverage'
            release = (request.get('context') or {}).get('unlock_dispatch')
            current_versions = {r['name']: version(r) for r in targets() if r['game_id'] == task['game_id']}
            if (release != {'versions': task.get('versions'), 'profile_revision': task.get('profile_revision')}
                    or current_versions != task.get('versions')
                    or task.get('profile_revision') != (store.get(PROFILE, task['game_id']) or {}).get('revision')):
                return 'Unlock task target/profile changed; a new exact admission is required'
            own_hermes = set()
            if (job := (task.get('dispatch') or {}).get('job_id')):
                own_hermes.add(job)
            try:
                from .hermes_work_queue import claims
                own_hermes.update(job_id for job_id, rid in claims().items() if rid == parent_request_id)
            except (OSError, ValueError, TypeError):
                pass  # uncertain claims remain active and block admission
            policy, now = policy_value(store), time.time()
            try:
                reason = idle_reason(store, workers(), policy, now=now,
                                     parent_request_id=parent_request_id, owned_hermes_ids=own_hermes,
                                     require_guard=bool((request.get('context') or {}).get('no_rom_copy')
                                         or (request.get('context') or {}).get('no_automatic_launch')))
            except Exception as exc:
                reason = 'Fresh unlock-job admission unavailable: ' + type(exc).__name__
            if reason:
                # Ongoing owned research need not repeat five quiet minutes
                # after its own result heartbeat/resource sample catches up.
                # Fresh blocking conditions still defer the call; only actual
                # operator activity restarts this task's quiet interval.
                if reason in ('Waiting for games to stop; unlock research never interrupts gameplay',
                              'Waiting for the active conversation to finish',
                              'Waiting for quiet time after the latest conversation',
                              'Waiting for operator input to be idle on every online PC'):
                    task['job_last_busy'] = now
                    store.put(TASK, task['game_id'], task)
                return reason
            if now - task.get('job_last_busy', now) < policy['quiet_seconds']:
                return 'Waiting for quiet time after operator or unrelated activity'
            return ''
    app.state.custom_build_unlock_job_admission = job_admission

    @app.post('/api/custom-build-unlocks/policy')
    def policy(body: dict, actor=Depends(auth)):
        allowed = {'enabled', *FAVORITE_DEFAULTS}
        if not body or set(body) - allowed: raise HTTPException(422, 'Use supported unlock policy fields')
        for key in ('enabled', 'favorites_enabled', 'default_boot', 'idle_resolution'):
            if key in body and type(body[key]) is not bool: raise HTTPException(422, key + ' must be a boolean')
        if 'quiet_seconds' in body and (type(body['quiet_seconds']) is not int or not 30 <= body['quiet_seconds'] <= 3600):
            raise HTTPException(422, 'quiet_seconds must be 30..3600')
        if 'dispatch_per_hour' in body and (type(body['dispatch_per_hour']) is not int or not 1 <= body['dispatch_per_hour'] <= 4):
            raise HTTPException(422, 'dispatch_per_hour must be 1..4')
        if 'excluded_games' in body and (not isinstance(body['excluded_games'], list) or len(body['excluded_games']) > 2000
                or any(not isinstance(gid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', gid) for gid in body['excluded_games'])):
            raise HTTPException(422, 'excluded_games needs bounded exact game IDs')
        value = policy_value(store) | body | {'categories': list(CATEGORIES), 'requires_ghidra': True,
                 'scope': 'favorites_and_enabled_custom_builds', 'by': actor, 'ts': time.time()}
        store.put(POLICY, 'default', value)
        store.audit(actor, 'custom_build_unlocks.policy', 'default', value)
        invalidate(); wake.set()
        return value

    @app.post('/api/custom-build-unlocks/{gid}/profile')
    def profile(gid: str, body: dict, actor=Depends(auth)):
        try: value = validate_profile(store, body | {'game_id': gid})
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

    @app.get('/api/custom-build-unlocks/{gid}/boot-plan')
    def boot_plan(gid: str, name: str = '', actor=Depends(auth)):
        policy = policy_value(store)
        favorite = gid in favorite_games(store) and gid not in policy['excluded_games']
        if not policy['favorites_enabled'] or not policy['default_boot'] or not favorite:
            return {'required': False, 'status': 'disabled', 'game_id': gid, 'name': name}
        target = name or BASE
        try: rec = current(gid, target)
        except ValueError as exc:
            return {'required': True, 'status': 'pending', 'reason': str(exc), 'game_id': gid, 'name': name}
        state = badge(store, rec) or {}
        profile = store.get(PROFILE, gid) or {}
        receipt = store.get(RECEIPT, f'{gid}/{target}') or {}
        if state.get('status') != 'verified':
            return {'required': True, 'status': 'pending', 'reason': 'Complete exact-build unlock coverage is not verified',
                    'game_id': gid, 'name': name, 'request_id': state.get('request_id')}
        if not rec.get('base'):
            try:
                if stat_signature(filemods.mod_dir(cfg, gid, target)) != receipt.get('signature'):
                    raise ValueError('Build changed after verification')
            except (ValueError, OSError) as exc:
                return {'required': True, 'status': 'pending', 'reason': str(exc), 'game_id': gid, 'name': name}
        recipe = profile.get('boot_apply')
        common = {'required': True, 'game_id': gid, 'name': name, 'version': version(rec),
                  'profile_revision': profile['revision'], 'inventory': profile['inventory']}
        if not recipe:
            # Exact mod receipt already proves its writer's baked-in unlocks.
            return common | {'status': 'verified_build'}
        from . import live_controls as L
        live = store.get(L.PROFILE, gid)
        if not live or live.get('revision') != recipe['revision'] or live.get('executable_sha256') != profile['executable_sha256']:
            return common | {'status': 'pending', 'reason': 'Published boot control changed; new coverage verification required'}
        action = next((a for a in live.get('actions', []) if a.get('id') == recipe['action']), None)
        if not action:
            return common | {'status': 'pending', 'reason': 'Verified native boot action is unavailable'}
        return common | {'status': 'ready', 'recipe': recipe,
                         'live_profile': live | {'actions': [action]}}

    @app.get('/api/custom-build-unlocks/{gid}/{name}/manifest')
    def manifest(gid: str, name: str, actor=Depends(auth)):
        try:
            rec = current(gid, name)
            return {'version': version(rec), 'profile_revision': (store.get(PROFILE, gid) or {}).get('revision'),
                    'files': files_and_signature(rec)[0]}
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
                if rec.get('base') and not p.get('boot_apply'):
                    raise ValueError('The original title needs a reusable verified boot application; never modify the base ROM')
                files, signature = files_and_signature(rec)
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


def on_launch(session_id, ctx, requested_mod=''):
    """Reuse one accepted native recipe; never discover, launch or copy on Play.

    Missing profiles, unavailable scenes and absent mutation permission stay
    pending in the session detail. A successful call never closes research.
    """
    from .tools import SESSIONS
    import httpx
    from urllib.parse import quote
    from types import SimpleNamespace
    import uuid
    pair = SESSIONS.get(session_id)
    if not pair:
        return {'required': False, 'status': 'pending', 'reason': 'Launch target is no longer running'}
    adapter, game = pair
    gid = game.get('game_id')
    pending = {'required': True, 'status': 'pending', 'game_id': gid, 'name': requested_mod}
    if not ctx.server:
        return pending | {'reason': 'Unlock policy is unavailable without the control plane'}
    if game.get('mod', '') != requested_mod:
        return pending | {'reason': 'Staged build identity differs; exact local build coverage must be verified'}
    try:
        response = httpx.get(f'{ctx.server}/api/custom-build-unlocks/{quote(gid, safe="")}/boot-plan',
                             params={'name': requested_mod}, headers=ctx.headers, timeout=3)
        response.raise_for_status()
        plan = response.json()
        if not isinstance(plan, dict) or plan.get('game_id') != gid or plan.get('name') != requested_mod:
            raise ValueError('Boot plan did not preserve the exact game/build target')
        if plan.get('status') != 'ready':
            return {k: plan[k] for k in ('required', 'status', 'reason', 'game_id', 'name', 'request_id', 'profile_revision') if k in plan}
        if 'memory_write' not in ctx.config.granted_permissions:
            return pending | {'reason': 'The worker memory_write permission is not granted'}
        from . import live_controls as L
        recipe, profile = plan['recipe'], plan['live_profile']
        # A client-supplied action never enters this path. These are fetched
        # directly from the authenticated, evidence-backed publication contract.
        if (recipe.get('kind') != 'live_control' or recipe.get('coverage') != plan.get('inventory')
                or set(plan.get('inventory', {})) != set(CATEGORIES)
                or profile.get('revision') != recipe.get('revision')):
            raise ValueError('Incomplete or stale full-inventory boot contract')
        action = next((a for a in profile.get('actions', []) if a.get('id') == recipe['action']), None)
        binding = (action or {}).get('binding', {})
        if (not action or action.get('category') != 'unlocks' or binding.get('kind') != 'native'
                or binding.get('tool') not in L.NATIVE
                or binding.get('input', {}).get('op') not in L.NATIVE[binding['tool']]
                or binding['input']['op'] != 'unlock_all'):
            raise ValueError('Only an already reviewed complete native unlock action may run at boot')
        from .registry import REGISTRY
        native = REGISTRY.get(binding['tool'])
        if native is None or any(permission not in ctx.config.granted_permissions for permission in native.permissions):
            raise ValueError('The published native control needs permissions this worker has not granted')
        if SESSIONS.get(session_id) is not pair:
            raise ValueError('The exact launch session changed before boot application')
        inp = SimpleNamespace(session_id=session_id, game_id=gid, revision=profile['revision'],
                              op='apply', action=recipe['action'], values=recipe['values'],
                              command_id=uuid.uuid4().hex, expires=time.time() + 20)
        result = L.operate(adapter, profile, game, inp, ctx)

        def failed(value):
            if isinstance(value, dict):
                return (bool(value.get('error')) or value.get('verified') is False
                        or value.get('status') in ('failed', 'error', 'pending', 'unsupported')
                        or any(failed(child) for child in value.values()))
            return isinstance(value, list) and any(failed(child) for child in value)

        def verified(value):
            return isinstance(value, dict) and (value.get('verified') is True or value.get('unlocked') is True
                    or any(verified(child) for child in value.values()))

        readback = not failed(result) and verified(result)
        outcome = pending | {'status': 'applied' if readback else 'pending', 'runtime_verified': readback,
                             'profile_revision': plan['profile_revision'], 'version': plan['version'],
                             'reason': 'Accepted native recipe applied with readback' if readback else 'Native action returned no explicit unlock readback',
                             'result': result}
        ctx.artifact('favorite-unlock-boot.json', json.dumps(outcome).encode(), 'application/json',
                     game=gid, session_id=session_id, mod=requested_mod)
        return outcome
    except Exception as exc:
        return pending | {'reason': type(exc).__name__ + ': ' + str(exc)[:350]}
