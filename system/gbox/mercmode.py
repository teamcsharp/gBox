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
DEFAULT = {'enabled': False, 'titles': ['re4', 're5', 're6'], 'rounds_per_title': 1,
           'presentation_priority': False, 'queue': []}
QUEUE_MAX = 20
TITLES = {
    're4': {'name': 'Resident Evil 4', 'map_id': 'G4BE08', 'platform': 'gamecube',
            'game_ids': ('78ab9efa2e310db4', 'e42c9b780c07c437'), 'playable': True,
            'characters': 5, 'stages': 4, 'modes': ['mercenaries']},
    're5': {'name': 'Resident Evil 5', 'map_id': 'BLUS30491', 'platform': 'ps3',
            'game_ids': ('e7ca89bbeb67360d',), 'playable': True,
            'characters': 18, 'stages': 8, 'modes': ['mercenaries', 'reunion']},
    're6': {'name': 'Resident Evil 6', 'map_id': 'BLUS30855', 'platform': 'ps3',
            'game_ids': ('6fc93ff62e4eb868',), 'playable': True, 'witnessed_launch_required': True,
            'characters': 7, 'stages': 3, 'modes': ['mercenaries']},
}
# re6: the PS3/RPCS3 backend (BLUS30855) replaces the unavailable Xbox 360 placeholder
# (0871eee3b68cdea3 / BH6). No native Mercenaries driver, menu cursor or terminal-round
# reader is measured for this revision yet, so playable is gated per host: only a host
# that has actually launched BLUS30855 (inventory rom_access source
# 'actual_prior_host_launch') rotates into RE6; a reachable ROM path alone never does.


def normalize(patch, current=None):
    if not isinstance(patch, dict) or set(patch)-DEFAULT.keys():
        raise ValueError('Unknown MercMode setting')
    out = {**DEFAULT, **(current or {}), **patch}
    if type(out['enabled']) is not bool or type(out['presentation_priority']) is not bool or type(out['rounds_per_title']) is not int \
            or not 1 <= out['rounds_per_title'] <= 20:
        raise ValueError('MercMode needs enabled true/false and 1..20 rounds per title')
    if not isinstance(out['titles'], list) or not out['titles'] or len(out['titles']) > 3 \
            or any(t not in TITLES for t in out['titles']) or len(set(out['titles'])) != len(out['titles']):
        raise ValueError('Choose distinct titles from re4, re5 and re6')
    out['queue'] = [queue_entry(e) for e in (out.get('queue') or [])]
    if len(out['queue']) > QUEUE_MAX:
        raise ValueError(f'The MercMode queue holds at most {QUEUE_MAX} rounds')
    return out


def catalog():
    """What the DJ queue can ask for, per verified title: modes -> characters (native roster order), stages."""
    from . import re4_menus
    from .mercs.titles import re5_ps3, re6_ps3
    return {'re4': {'modes': {'mercenaries': list(re4_menus.PLAYERS)}, 'stages': list(re4_menus.STAGES)},
            're5': {'modes': {m: list(r) for m, r in re5_ps3.MODE_ROSTERS.items()}, 'stages': list(re5_ps3.STAGE_NAMES)},
            're6': {'modes': {m: list(r) for m, r in re6_ps3.MODE_ROSTERS.items()}, 'stages': list(re6_ps3.STAGE_NAMES)}}


def queue_entry(entry):
    """One queued round (operator 2026-10-24: "be the DJ ... what mode is being played next, who's being played next
    ... and see the queue ahead"): {title, mode, character, stage}; mode / character / stage None = random."""
    if not isinstance(entry, dict) or set(entry) - {'title', 'mode', 'character', 'stage'} or entry.get('title') not in TITLES:
        raise ValueError('A queued round needs a known title and only mode, character and stage')
    title = entry['title']
    out = {'title': title, 'mode': entry.get('mode'), 'character': entry.get('character'), 'stage': entry.get('stage')}
    known = catalog().get(title)
    if known is None:
        if out['mode'] or out['character'] or out['stage'] is not None:
            raise ValueError(f"{TITLES[title]['name']} has no verified roster or stage list yet")
        return out
    if out['mode'] is not None and out['mode'] not in known['modes']:
        raise ValueError('Unknown mode for ' + TITLES[title]['name'])
    if out['character'] is not None:
        rosters = [known['modes'][out['mode']]] if out['mode'] else list(known['modes'].values())
        if not any(out['character'] in r for r in rosters):
            raise ValueError(f"{out['character']} is not in that roster")
    if out['stage'] is not None and (type(out['stage']) is not int or not 0 <= out['stage'] < len(known['stages'])):
        raise ValueError('Unknown stage for ' + TITLES[title]['name'])
    return out


def resolve_selection(entry, rng):
    """A queued round's random parts drawn now, so the game receives an exact mode, character and stage."""
    known = catalog().get(entry['title'])
    if known is None:
        return dict(entry)
    mode = entry.get('mode') or next((m for m, r in known['modes'].items() if entry.get('character') in r), None) \
        or rng.choice(sorted(known['modes']))
    character = entry.get('character') or rng.choice(known['modes'][mode])
    stage = entry['stage'] if entry.get('stage') is not None else rng.randrange(len(known['stages']))
    return {'title': entry['title'], 'mode': mode, 'character': character, 'stage': stage,
            'stage_name': known['stages'][stage]}


def pop_queue(store, host):
    cfg = settings(store, host)
    if cfg['queue']:
        store.put(SETTING, host, cfg | {'queue': cfg['queue'][1:]})


def selection_job(title, sid, selection):
    """(tool, input) that queues `selection` at the running game's next native menu visit, or None."""
    if title == 're5':
        return 're5_mods', {'session_id': sid, 'op': 'mercs_select', 'mode': selection['mode'],
                            'character': selection['character'], 'stage': selection['stage']}
    if title == 're4':
        return 're_mods', {'session_id': sid, 'op': 'mercs_select', 'character': selection['character'],
                           'target': str(selection['stage'])}
    return None


def settings(store, host):
    return normalize(store.get(SETTING, host) or {})


def presentation_launch(store, worker, job):
    """Only an explicitly selected host's exact scheduler launch has priority.

    Client-supplied launch hints and unrelated automation grant no exception.
    Human-session/watch checks, fresh telemetry and memory limits still apply.
    """
    if job.get('tool')!='launch_game':return False
    from .screensaver import STATE,ACTOR
    cfg=settings(store,worker['name']);run=store.get(STATE,worker['name']) or {}
    title=(run.get('mercmode') or {}).get('title');spec=TITLES.get(title) or {}
    game=(job.get('input') or {}).get('game') or {}
    return bool(cfg['enabled'] and cfg['presentation_priority'] and title in cfg['titles']
        and spec.get('playable') and job.get('tool')=='launch_game' and job.get('actor')==ACTOR
        and job.get('id')==run.get('job') and run.get('phase')=='launching'
        and run.get('worker_id')==worker.get('id')==job.get('require_worker')
        and game.get('game_id')==run.get('game_id') and run.get('game_id') in spec.get('game_ids',())
        and {k:v for k,v in ((game.get('launch') or {}).get('mercmode') or {}).items() if k!='selection'}
            =={'random_characters':True,'random_stages':True})


def adopt_current(store, worker, session, telemetry, *, now=None):
    """Explicit operator adoption of this exact already-running solo bot.

    No controller input, stop or launch. A human session, stale telemetry or a
    foreign job cannot become a scheduler-owned run through this operation.
    """
    from .screensaver import STATE
    now=time.time() if now is None else now
    sid=session.get('session_id','');wid=worker.get('id');cfg=settings(store,worker.get('name'))
    if not cfg['enabled'] or not worker.get('online') or worker.get('federation') \
            or session.get('state')!='running' or not wid or not sid.startswith(wid+'-'):
        raise ValueError('An enabled native host and its exact running session are required')
    stats=telemetry.get('stats') or {};age=telemetry.get('age_s')
    if telemetry.get('running') is not True or type(age) not in (int,float) or not 0<=age<=8 \
            or stats.get('source_session_id')!=sid or stats.get('team_role')!='solo_p1' \
            or stats.get('screen')!='playing':
        raise ValueError('Fresh exact-session solo autobot gameplay is required')
    jid=stats.get('source_autoplay_job_id');job=store.get('job',jid) or {}
    if job.get('tool')!='autoplay' or job.get('state') not in ('running','assigned','succeeded') \
            or job.get('worker_id')!=wid or job.get('require_worker')!=wid \
            or (job.get('input') or {}).get('session_id')!=sid or (job.get('input') or {}).get('op')!='start':
        raise ValueError('The active bot does not match its accepted native worker job')
    title=next((t for t,r in TITLES.items() if session.get('game_id') in r['game_ids'] and r['playable']),None)
    if title not in cfg['titles']:
        raise ValueError('This verified title is not selected for MercMode')
    old=store.get(STATE,worker['name'])
    if old:
        if old.get('session_id')==sid and old.get('mercmode'):return old
        raise ValueError('The host already has a different scheduler-owned run')
    run={'worker':worker['name'],'worker_id':wid,'session_id':sid,'game_id':session['game_id'],
         'title':session.get('title') or TITLES[title]['name'],'phase':'playing','started':now,
         'playing_since':now,'autoplay_job':jid,'adopted_existing_solo':True,
         'mercmode':{'title':title,'map_id':TITLES[title]['map_id'],'rounds_per_title':cfg['rounds_per_title']}}
    store.put(STATE,worker['name'],run)
    return run


def _same_host_worker(store, source, worker):
    if not isinstance(source,str) or not source or not worker.get('id') or not worker.get('name'):return False
    seen=set()
    for _ in range(8):
        if source==worker.get('id'):return True
        if not source or source in seen:return False
        seen.add(source);alias=store.get('worker_alias',source) or {}
        if alias.get('name')!=worker.get('name'):return False
        source=alias.get('to')
    return False


def rotation_predecessor(store, worker, now):
    from .screensaver import LOG
    rows=[r for r in store.all(LOG) if _same_host_worker(store,r.get('worker_id'),worker)
          and r.get('why')=='verified native round boundary: next MercMode title'
          and r.get('mercmode_rotate_requested') is True and 0<=now-r.get('ended',0)<=900
          and isinstance(r.get('mercmode_last_round'),dict)]
    if not rows:return None
    row=max(rows,key=lambda r:r['ended']);receipt=row['mercmode_last_round']
    if not re.fullmatch('[a-f0-9]{32}',str(receipt.get('round_id',''))):return None
    return {'session_id':row['session_id'],'game_id':row['game_id'],'round_id':receipt['round_id'],
            'ended':row['ended'],'worker_id':worker['id'],'source_worker_id':row['worker_id']}


def link_rotation(store, run, successor, now):
    """Only the scheduler's accepted launch may extend a watched MercMode chain."""
    prior=run.get('mercmode_predecessor')
    if not isinstance(prior,dict) or not run.get('mercmode') or run.get('worker_id')!=prior.get('worker_id') \
            or not 0<=now-prior.get('ended',0)<=900:
        return False
    from .screensaver import _launch_session
    job=store.get('job',run.get('job')) or {}
    if job.get('tool')!='launch_game' or job.get('state')!='succeeded' \
            or job.get('worker_id')!=run.get('worker_id') or job.get('require_worker')!=run.get('worker_id') \
            or ((job.get('input') or {}).get('game') or {}).get('game_id')!=run.get('game_id'):
        return False
    if _launch_session(store,run.get('job'),[successor],worker_id=run.get('worker_id'),game_id=run.get('game_id')) is None:
        return False
    sid=successor.get('session_id','');old=store.get('session',prior.get('session_id')) or {}
    source_worker=prior.get('source_worker_id',prior['worker_id'])
    if not _same_host_worker(store,source_worker,{'id':run['worker_id'],'name':run['worker']}) \
            or not str(prior.get('session_id','')).startswith(source_worker+'-'):
        return False
    if old.get('state')!='ended' or old.get('game_id')!=prior.get('game_id') or old.get('replaced_by') \
            or successor.get('state')!='running' or successor.get('game_id')!=run.get('game_id') \
            or not sid.startswith(run['worker_id']+'-'):
        return False
    # The caller has already resolved the exact launch job with _launch_session.
    receipt={'v':1,'source':'native_terminal_reader','round_id':prior['round_id'],
             'worker_id':run['worker_id'],'source_worker_id':source_worker,
             'from_game':old['game_id'],'to_game':successor['game_id'],
             'successor_session_id':sid,'at':now}
    store.put('session',prior['session_id'],old|{'replaced_by':sid,'mercmode_rotation':receipt})
    return True


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


def inventory(store, worker, cfg=None, sessions=None):
    """sessions: store.all('session') when the caller already read it (one read for every host, not one per game)."""
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
            known=sessions if sessions is not None else store.all('session')
            for game in games:
                gid=game['game_id']
                # a restart gives the same PC a new worker id: the registered aliases keep its launch history
                prior=next((s for s in known if s.get('game_id')==gid
                    and s.get('state') in ('running','ended')
                    and _same_host_worker(store,s.get('session_id','').split('-')[0],worker)),None)
                candidate={'verified':False,'reason':'ROM access has not been verified on this PC'}
                probe=(prepared.get('games') or {}).get(gid) or {}
                if prior:
                    candidate={'verified':True,'source':'actual_prior_host_launch','session_id':prior['session_id']}
                if probe and 0<=time.time()-probe.get('checked_at',0)<=1800 and not spec.get('witnessed_launch_required'):
                    candidate={'verified':probe.get('reachable') is True,'source':'worker_local_path_probe',
                               'checked_at':probe.get('checked_at'),'reason':probe.get('reason','')}
                elif probe and spec.get('witnessed_launch_required') and not prior:
                    # a reachable ROM path alone never makes a witnessed-launch title playable
                    candidate={'verified':False,'source':'worker_local_path_probe',
                               'reason':'RE6 (BLUS30855) has no verified native round on this PC; '
                                        'this host must actually launch it before it joins the rotation'}
                if game is games[0] or candidate['verified']:
                    access=candidate;selected_game=game
                if candidate['verified']:break       # preferred accessible exact disc, never another disc's evidence
            if not access['verified']:reason=access.get('reason') or 'ROM is unavailable on this PC'
            if not access['verified'] and spec.get('witnessed_launch_required'):
                reason=('RE6 (BLUS30855) has no verified native round on this PC; '
                        'it joins the rotation only after this host actually launches it')
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
    rows = inventory(store, worker, cfg)
    head = (cfg.get('queue') or [None])[0]
    queued = next((r for r in rows if head and r['playable'] and r['title'] == head['title']), None)
    if queued:                                   # the DJ's next round comes first, even for an unchecked title
        return queued | {'selection': resolve_selection(head, rng)}
    pool = [r for r in rows if r['playable'] and r['title'] in cfg['titles']]
    history = store.get(HISTORY, worker['name']) or {}
    fresh = [r for r in pool if r['game_id'] != history.get('last_game_id')]
    return rng.choice(fresh or pool) if pool else None


def successor_autoplay(run, job, original):
    """The scheduler's own autoplay start, or a strictly later start of the autobot in this same owned session.

    The operator's PiP menu (F3 / "Take control") and the bot's own hang relaunch restart autoplay inside the
    MercMode session under a new job; the game, worker and session are unchanged, so its native round
    boundaries still belong to this run (live lilspark 2026-10-24: every boundary after such a restart was
    refused with 422 and the rotation stalled). A start for another session or worker, or one not created
    after the run's accepted job, never qualifies.
    """
    if job.get('id') == run.get('autoplay_job'):
        return True
    created, before = job.get('created'), (original or {}).get('created')
    return bool(job.get('id') and (job.get('input') or {}).get('session_id') == run.get('session_id')
                and job.get('worker_id') in (None, run.get('worker_id'))
                and job.get('require_worker') == run.get('worker_id')
                and isinstance(created, (int, float)) and isinstance(before, (int, float)) and created > before)


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
            or not successor_autoplay(run, parent_job, store.get('job', run.get('autoplay_job'))):
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
