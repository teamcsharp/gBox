"""Host-scoped Mercenaries screensaver selection and native round receipts.

This scheduler does not change gameplay modifiers or fabricate backend readiness.
RPCS3 keeps its existing disk caches; it has no safe instant-state shortcut here.
"""
from __future__ import annotations

import math
import json
import re
import time

SETTING = 'mercmode'
HISTORY = 'mercmode_history'
PREPARATION = 'mercmode_preparation'
OBSERVED = 'mercmode_observed'
COMMAND = 'mercmode_command'
DEFAULT = {'enabled': False, 'titles': ['re4', 're5', 're6'], 'rounds_per_title': 1}
TITLES = {
    're4': {'name': 'Resident Evil 4', 'map_id': 'G4BE08', 'platform': 'gamecube',
            'game_ids': ('78ab9efa2e310db4', 'e42c9b780c07c437'), 'playable': True,
            'characters': 5, 'stages': 4, 'modes': ['mercenaries']},
    're5': {'name': 'Resident Evil 5', 'map_id': 'BLUS30491', 'platform': 'ps3',
            'game_ids': ('e7ca89bbeb67360d',), 'playable': True,
            'characters': 18, 'stages': 8, 'modes': ['mercenaries', 'reunion']},
    're6': {'name': 'Resident Evil 6', 'map_id': 'BH6', 'platform': 'xbox360',
            'game_ids': ('0871eee3b68cdea3',), 'playable': False,
            'reason': 'RE6 has no verified Mercenaries combat driver, menu cursor, timer or terminal-round reader. '
                      'The requested PS3 share contains no RE6 entry in the 2026-10-23 inventory.'},
}


def normalize(patch, current=None):
    if not isinstance(patch, dict) or set(patch)-DEFAULT.keys():
        raise ValueError('Unknown MercMode setting')
    out = {**DEFAULT, **(current or {}), **patch}
    if type(out['enabled']) is not bool or type(out['rounds_per_title']) is not int \
            or not 1 <= out['rounds_per_title'] <= 20:
        raise ValueError('MercMode needs enabled true/false and 1..20 rounds per title')
    if not isinstance(out['titles'], list) or not out['titles'] or len(out['titles']) > 3 \
            or any(t not in TITLES for t in out['titles']) or len(set(out['titles'])) != len(out['titles']):
        raise ValueError('Choose distinct titles from re4, re5 and re6')
    return out


def settings(store, host):
    return normalize(store.get(SETTING, host) or {})


def configure(store, host, patch):
    if not isinstance(host, str) or not 1 <= len(host) <= 120:
        raise ValueError('An exact worker name is required')
    row = normalize(patch, settings(store, host))
    store.put(SETTING, host, row)
    return row


def observation(store,worker):
    """Last local scheduler observation from this worker's paired authority."""
    row=store.get(OBSERVED,worker['name']) or {}
    authority=(worker.get('federation') or {}).get('authority')
    if authority and row.get('authority')==authority and row.get('worker_id')==worker.get('id'):
        return row
    return {}


def valid_preparation(receipt):
    """Finite, fresh local file probes; these flags cannot authorize game writes."""
    if not isinstance(receipt,dict):return False
    try:
        if len(json.dumps(receipt,allow_nan=False).encode())>8000:
            return False
    except (ValueError,TypeError,RecursionError):
        return False
    now=time.time();checked=receipt.get('checked_at')
    games=receipt.get('games')
    known={gid for title in TITLES.values() for gid in title['game_ids']}
    if (receipt.get('emulator_launched') is not False or receipt.get('configuration_changed') is not False
            or type(checked) not in (int,float) or not 0<=now-checked<=1800
            or not isinstance(games,dict) or set(games)-known):
        return False
    for probe in games.values():
        stamp=probe.get('checked_at') if isinstance(probe,dict) else None
        if (not isinstance(probe,dict) or type(probe.get('reachable')) is not bool
                or type(stamp) not in (int,float) or not 0<=now-stamp<=1800
                or not isinstance(probe.get('reason',''),str) or len(probe.get('reason',''))>500
                or not isinstance(probe.get('path',''),str) or len(probe.get('path',''))>2048
                or probe['reachable'] and not probe.get('path')):
            return False
    return True


def host_preparation(store, worker):
    """Consume only this host's exact requested, accepted read-only preparation."""
    observed=observation(store,worker).get('preparation') or {}
    saved=(observed if valid_preparation(observed) else {}) | (store.get(PREPARATION,worker['name']) or {})
    jid=saved.get('job');job=store.get('job',jid) if jid else None
    if not job or job.get('state')!='succeeded' or job.get('tool')!='mercmode' \
            or (job.get('input') or {}).get('op')!='prepare' \
            or job.get('worker_id')!=worker.get('id') or job.get('require_worker')!=worker.get('id'):
        return saved
    result=(job.get('output') or {}).get('result') or {}
    receipt=result.get('preparation')
    if result.get('saved') is not True or result.get('host')!=worker['name'] or not valid_preparation(receipt):
        return saved
    return saved | receipt | {'state':'checked','source':'accepted_worker_prepare_job','job':jid}


def inventory(store, worker, cfg=None):
    cfg = cfg or settings(store, worker['name'])
    rows = []
    for key in TITLES:
        spec = TITLES[key]
        games = [g for gid in spec['game_ids'] if (g := store.catalog_get(gid))
                 and g.get('platform') == spec['platform']]
        tools = worker.get('tools')
        reason = spec.get('reason', '')
        if not reason and not games:
            reason = 'The verified game revision is absent from the catalog'
        if not reason and worker.get('os') not in ('windows', 'linux'):
            reason = 'This host OS has no verified Mercenaries input/RAM backend'
        if not reason and isinstance(tools, list) and not {'launch_game', 'autoplay'} <= set(tools):
            reason = 'The host does not advertise launch_game and autoplay tools'
        backend_ready=bool(spec['playable'] and not reason)
        access={'verified':False,'reason':'ROM access has not been verified on this PC'}
        selected_game=games[0] if games else None
        if backend_ready:
            prepared=host_preparation(store,worker)
            for game in games:
                gid=game['game_id']
                prior=next((s for s in store.all('session') if s.get('game_id')==gid
                    and s.get('session_id','').startswith(worker.get('id','')+'-')
                    and s.get('state') in ('running','ended')),None)
                candidate={'verified':False,'reason':'ROM access has not been verified on this PC'}
                probe=(prepared.get('games') or {}).get(gid) or {}
                if prior:
                    candidate={'verified':True,'source':'actual_prior_host_launch','session_id':prior['session_id']}
                if probe and 0<=time.time()-probe.get('checked_at',0)<=1800:
                    candidate={'verified':probe.get('reachable') is True,'source':'worker_local_path_probe',
                               'checked_at':probe.get('checked_at'),'reason':probe.get('reason','')}
                if game is games[0] or candidate['verified']:
                    access=candidate;selected_game=game
                if candidate['verified']:break       # preferred accessible exact disc, never another disc's evidence
            if not access['verified']:reason=access.get('reason') or 'ROM is unavailable on this PC'
        rows.append({'title': key, 'name': spec['name'], 'map_id': spec['map_id'],
                     'playable': bool(backend_ready and access['verified']), 'backend_playable':backend_ready,
                     'rom_access':access, 'reason': reason,
                     'game_id': selected_game['game_id'] if selected_game else None,
                     'modes': spec.get('modes', []), 'characters': spec.get('characters'),
                     'stages': spec.get('stages'), 'preparation': preparation(spec['platform'])})
    return rows


def preparation(platform):
    return ({'strategy': 'persistent_install_and_shader_cache', 'instant_state_supported': False,
             'reason': 'RPCS3 uses its installed data and retained caches, then verified native menus. '
                       'No save-state capture/reload or second emulator is started for prewarming.'}
            if platform == 'ps3' else
            {'strategy': 'existing_dolphin_menu_jump_if_available', 'instant_state_supported': True,
             'reason': 'An existing matching Dolphin menu jump may be reused; otherwise native menus boot normally.'})


def choose(store, worker, rng, cfg=None):
    cfg = cfg or settings(store, worker['name'])
    pool = [r for r in inventory(store, worker, cfg) if r['playable'] and r['title'] in cfg['titles']]
    history = store.get(HISTORY, worker['name']) or {}
    fresh = [r for r in pool if r['game_id'] != history.get('last_game_id')]
    return rng.choice(fresh or pool) if pool else None


def accept_boundary(store, run, body, *, parent_job, now=None):
    """Check an active worker autoplay job and native terminal witness, not a flag.

    The worker callback is emitted only by the read-only terminal reader. This
    control-plane check also fences stale/replayed/other-session messages.
    """
    now = time.time() if now is None else now
    if not isinstance(body, dict) or not isinstance(parent_job, dict):
        raise ValueError('A running worker autoplay job is required')
    if parent_job.get('tool') != 'autoplay' or parent_job.get('state') not in ('running', 'assigned','succeeded') \
            or (parent_job.get('input') or {}).get('session_id') != run.get('session_id') \
            or (parent_job.get('input') or {}).get('op') != 'start' \
            or parent_job.get('require_worker') != run.get('worker_id') \
            or parent_job.get('id') != run.get('autoplay_job'):
        raise ValueError('The boundary does not belong to this active MercMode autoplay job')
    if body.get('session_id') != run.get('session_id') or not run.get('mercmode'):
        raise ValueError('The boundary does not belong to an owned MercMode session')
    rid, at = body.get('round_id'), body.get('at')
    if not isinstance(rid, str) or not re.fullmatch('[a-f0-9]{32}', rid) \
            or not isinstance(at, (float, int)) or not math.isfinite(at) \
            or not run.get('playing_since', now) <= at <= now+5 or now-at > 120:
        raise ValueError('The native round identity or timestamp is stale')
    spec = TITLES[run['mercmode']['title']]
    witness = body.get('witness')
    if body.get('map_id') != spec['map_id'] or body.get('role') != 'solo_p1' \
            or body.get('source') != 'native_terminal_reader' or not isinstance(witness, dict) \
            or witness.get('playing_observed') is not True or witness.get('player_verified') is not True:
        raise ValueError('A solo native terminal-round witness is required')
    terminal = witness.get('screen')
    if spec['map_id']=='G4BE08' and (witness.get('game_routine') not in (3,4)
            or type(witness.get('room')) is not int or witness['room']>>8!=4):
        raise ValueError('RE4 must be in its native Mercenaries room routine')
    if terminal == 'results':
        if witness.get('tally_ready') is not True or not (witness.get('timer') == 0
                or isinstance(witness.get('kills'), (int, float)) and witness['kills'] >= 150):
            raise ValueError('The native result tally is not complete')
    elif terminal == 'dead':
        if not isinstance(witness.get('hp'), (int, float)) or not math.isfinite(witness['hp']) or witness['hp'] > 0:
            raise ValueError('Death needs the actual player health, not a missing player')
    else:
        raise ValueError('Menus, interrupted rounds and role changes cannot rotate MercMode')
    if rid in run.get('mercmode_round_ids', []):
        return None
    return {k: body.get(k) for k in ('round_id', 'at', 'map_id', 'mode', 'stage', 'character', 'witness')}


def publish_boundary(sink, body, stats):
    """Runs between rounds with released inputs; ordinary telemetry cannot rotate."""
    if sink is None or not hasattr(sink, 'client') or not getattr(sink, 'sid', None):
        return False
    try:
        response = sink.client.post('/api/autoplay-screensaver/round-boundary',
                                    json={**body, 'session_id': sink.sid})
        response.raise_for_status()
        if response.json().get('saved'):
            stats['mercmode_boundaries_delivered'] = stats.get('mercmode_boundaries_delivered', 0)+1
            if response.json().get('rotate_requested'):
                stats['mercmode_rotate_requested'] = True
            return True
    except Exception as exc:
        stats['mercmode_boundary_error'] = str(exc)[:180]
    return False


def inspect_preparation(runtime):
    """Bounded filesystem inspection only; never launches an emulator to warm it."""
    from pathlib import Path
    root=Path(runtime)/'rpcs3-linux'
    if not root.exists():
        root=Path(runtime)/'rpcs3'
    candidates=(root/'config/rpcs3',root/'config',root)
    config=next((p for p in candidates if (p/'config.yml').is_file()),None)
    cache=root/'cache/rpcs3' if (root/'cache/rpcs3').is_dir() else root/'cache'
    return {'checked_at':time.time(),'emulator_launched':False,'configuration_changed':False,
        'rpcs3':{'config_present':config is not None,
            'firmware_present':bool(config and (config/'dev_flash').is_dir()),
            're5_installed_data_present':bool(config and (config/'dev_hdd0/game/BLUS30491').is_dir()),
            'cache_present':cache.is_dir(),'instant_state_supported':False,
            'strategy':preparation('ps3')['strategy']},
        'reason':'Existing installed assets/caches inspected. Normal sequential launches retain and warm them; '
                 'this operation does not assert playable readiness or capture an RPCS3 save state.'}


def inspect_rom_access(config,game):
    """Resolve the existing launch path using this host's configured library roots."""
    from .models import CatalogEntry
    from .tools import rom_path
    try:
        path=rom_path(CatalogEntry.model_validate(game),config)
        reachable=path.exists()
        return {'reachable':reachable,'checked_at':time.time(),'reason':'' if reachable else
                'The configured ROM path is not reachable on this PC','path':str(path)}
    except Exception as exc:
        return {'reachable':False,'checked_at':time.time(),'reason':str(exc)[:240]}
