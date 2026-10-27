"""Host-scoped Mercenaries screensaver selection and native round receipts.

This scheduler does not change gameplay modifiers or fabricate backend readiness.
RPCS3 keeps its existing disk caches; it has no safe instant-state shortcut here.
"""
from __future__ import annotations

import math
import json
import re
import time
import uuid

SETTING = 'mercmode'
HISTORY = 'mercmode_history'
PREPARATION = 'mercmode_preparation'
OBSERVED = 'mercmode_observed'
COMMAND = 'mercmode_command'
ADOPTION = 'mercmode_adoption'
DEFAULT = {'enabled': False, 'titles': ['re4', 're5', 're6'], 'rounds_per_title': 1,
           'presentation_priority': False, 'queue': [], 'keep_warm': 1, 'preferred_editions': {},
           # the bots' stalemate rule (gbox.mercs.stalemate; operator 2026-10-26): no enemies for 15 s with time on the
           # clock -> the clock is cut to stalemate_cut_s once per round. Rides in the launch payload (game.launch.mercmode)
           'stalemate_cut': True, 'stalemate_cut_s': 5}
STALEMATE_KEYS = ('stalemate_cut', 'stalemate_cut_s')
STALEMATE_FEATURE = 'mercmode_stalemate_cut'     # worker feature: its mercmode tool accepts the stalemate settings
# Warm pool (operator 2026-10-24: "now that there is more ram on the spark, get the swapping of mercenary modes more
# seamless by having emulators ready to swap in for merc mode fully prepared"). keep_warm = how many titles besides the
# one playing may wait in memory, paused and off-screen (0 = off: every switch is a cold launch, as before).
WARM = 'mercmode_warm'          # host -> {title: {session_id, game_id, job, worker_id, state: prelaunch|parked|ready, at,
                                #          prepare_job, prepare_at, prepared: {character, stage, ...} | prepare_failed}}
                                # prelaunch: booting / paused at its boot menu; parked: paused where its last round left
                                # it (a results screen); ready: paused on the first frame of its next round (prepared)
NEXT = 'mercmode_next'          # host -> the pick made ahead of the round's end (prelaunch), honoured at the switch
PRELAUNCH_S = 3600.0            # (status text) the next title starts loading in the background as soon as the playing one
                                # is up - it loads and prepares its round while this one plays (operator 2026-10-24:
                                # "precaching of the next rom during the playing of the current rom"; 2026-10-26: after a
                                # service restart the pool boots at once, not only when the first title's round ends)
EXTRA_ROUNDS_MAX = 3            # failed attempts to get the next title ready (a failed / skipped preload or prepare) before
                                # MercMode stays in the playing title; while an attempt is on its way the playing title
                                # adds rounds without limit - never a cold switch with a loading screen while a title plays
WARM_MAX = 2                    # keep_warm upper bound (three titles at most: the playing one plus two waiting)
WARM_FEATURE = 'mercmode_warm_launch'   # worker feature: launch_game keep_sessions/warm and session_op pause warm
PREPARE_FEATURE = 'mercmode_prepare'    # worker feature: autoplay op=prepare drives a warm game's menus to a round start
                                        # and pauses it there (operator 2026-10-26: "continue playing a round ... while the
                                        # next session is loading and preparing in the background so the swap is seamless")
WARM_MIN_FREE_BYTES = 8 * 1024**3       # memory guard: an extra emulator needs this much free RAM on the host ...
WARM_MAX_MEMORY_PERCENT = 80            # ... and the host under this much used, both measured in the last 30 s
QUEUE_MAX = 20
TITLES = {
    're4': {'name': 'Resident Evil 4', 'map_id': 'G4BE08', 'platform': 'gamecube',
            'game_ids': ('78ab9efa2e310db4', 'e42c9b780c07c437'), 'playable': True,
            'characters': 5, 'stages': 4, 'modes': ['mercenaries']},
    're5': {'name': 'Resident Evil 5', 'map_id': 'BLUS30491', 'platform': 'ps3',
            'game_ids': ('e7ca89bbeb67360d',), 'playable': True,
            'characters': 18, 'stages': 8, 'modes': ['mercenaries', 'reunion']},
    're6': {'name': 'Resident Evil 6', 'map_id': 'BH6', 'platform': 'xbox360',
            'game_ids': ('0871eee3b68cdea3',), 'playable': False,
            'backends': {
                'xbox360': {'game_id': '0871eee3b68cdea3', 'adapter': 'xenia', 'verified': False},
                'ps3': {'game_id': '6fc93ff62e4eb868', 'title_id': 'BLUS30855', 'app_ver': '01.00',
                        'adapter': 'rpcs3', 'verified': True,
                        'eboot_sha256': 'ddd022477e679cb1125dc327b0e43c5aeb4d8fa84352a7c8ae98ec74271d41ed'},
            },
            'reason': 'RE6 PS3 (BLUS30855) has a verified native RPCS3 launch but no verified Mercenaries combat driver, menu cursor, timer or terminal-round reader.'},
    'merc3d': {'name': 'Resident Evil: The Mercenaries 3D', 'map_id': 'CTR-ABRE', 'platform': '3ds',
               'game_ids': ('0ed22ae742e1b56b',), 'playable': False, 'modes': ['mercenaries'],
               'reason': 'The 3DS round RAM map (HP, timer, menu cursor, mission index) has no measured offsets; '
                         'the pinned .code findings are static, not runtime addresses, so there is no verified combat driver yet.'},
    're3': {'name': 'Resident Evil 3: Nemesis', 'map_id': 'SLUS-00923', 'platform': 'psx',
            'game_ids': (), 'playable': False,
            'modes': ['mercenaries'],
            'reason': 'RE3 Operation Mad Jackal has no reviewed PSX RAM map, combat driver, menu cursor, '
                      'timer or terminal-round reader yet (see mercs/titles/re3_psx.py).'},
}


def normalize(patch, current=None):
    if not isinstance(patch, dict) or set(patch)-DEFAULT.keys():
        raise ValueError('Unknown MercMode setting')
    out = {**DEFAULT, **(current or {}), **patch}
    from .re_switch import normalize_preferences
    out['preferred_editions'] = normalize_preferences(out['preferred_editions'])
    if type(out.get('keep_warm')) is bool:            # true/false from an older client: one title kept warm, or none
        out['keep_warm'] = int(out['keep_warm'])
    if type(out.get('keep_warm')) is not int or not 0 <= out['keep_warm'] <= WARM_MAX:
        raise ValueError(f'MercMode keep_warm is how many titles wait ready: 0..{WARM_MAX}')
    if type(out['enabled']) is not bool or type(out['presentation_priority']) is not bool or type(out['rounds_per_title']) is not int \
            or not 1 <= out['rounds_per_title'] <= 20:
        raise ValueError('MercMode needs enabled true/false and 1..20 rounds per title')
    from .mercs.stalemate import CUT_MIN_S, CUT_MAX_S
    if type(out['stalemate_cut']) is not bool or type(out['stalemate_cut_s']) is not int \
            or not CUT_MIN_S <= out['stalemate_cut_s'] <= CUT_MAX_S:
        raise ValueError(f'MercMode stalemate: stalemate_cut true/false and {CUT_MIN_S}..{CUT_MAX_S} seconds on the clock')
    if not isinstance(out['titles'], list) or not out['titles'] or len(out['titles']) > 3 \
            or any(t not in TITLES for t in out['titles']) or len(set(out['titles'])) != len(out['titles']):
        raise ValueError('Choose distinct titles from re4, re5, re6 and re3')
    out['queue'] = [queue_entry(e) for e in (out.get('queue') or [])]
    if len(out['queue']) > QUEUE_MAX:
        raise ValueError(f'The MercMode queue holds at most {QUEUE_MAX} rounds')
    return out


def catalog():
    """What the DJ queue can ask for, per verified title: modes -> characters (native roster order), stages."""
    from . import re4_menus
    from .mercs.titles import re5_ps3
    return {'re4': {'modes': {'mercenaries': list(re4_menus.PLAYERS)}, 'stages': list(re4_menus.STAGES)},
            're5': {'modes': {m: list(r) for m, r in re5_ps3.MODE_ROSTERS.items()}, 'stages': list(re5_ps3.STAGE_NAMES)}}


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


def warm_pool(store, host, running=None):
    """This host's kept-warm MercMode games (operator 2026-10-24: "the emulators should be kept in memory if they are going
    to keep being used ... I feel like this shader dialog wouldn't even have to show"). With `running`, entries whose
    session ended are dropped (a prelaunch whose launch is still pending stays). Ownership is checked by the scheduler
    (gbox.screensaver.Screensaver._warm) before any of these sessions is paused, resumed or stopped."""
    pool = dict(store.get(WARM, host) or {})
    if running is None:
        return pool
    alive = {s.get('session_id') for s in running}
    kept = {t: row for t, row in pool.items()
            if row.get('session_id') in alive or (row.get('state') == 'prelaunch' and not row.get('session_id'))}
    if kept != pool:
        store.put(WARM, host, kept)
    return kept


def warm_sessions(store, host):
    """Session ids waiting in this host's pool, never one the operator took over (label owner "you")."""
    return {sid for row in (store.get(WARM, host) or {}).values() if (sid := row.get('session_id'))
            and (store.get('slabel', sid) or {}).get('owner') != 'you'}


def keep_warm(store, host, title, row):
    store.put(WARM, host, warm_pool(store, host) | {title: row})


def take_warm(store, host, title):
    pool = warm_pool(store, host)
    row = pool.pop(title, None)
    store.put(WARM, host, pool)
    return row


def memory_reason(worker, now=None):
    """Why this host may not hold one more emulator in memory now (None = it may): fresh measured free RAM only."""
    now = time.time() if now is None else now
    res = (worker or {}).get('resources') or {}
    stamp, free, used = res.get('sampled_at'), res.get('memory_available_bytes'), res.get('memory_percent')
    if type(stamp) not in (int, float) or not 0 <= now - stamp <= 30:
        return 'no current memory measurement from this host'
    if type(free) not in (int, float) or type(used) not in (int, float):
        return 'no measured memory headroom on this host'
    if free < WARM_MIN_FREE_BYTES or used >= WARM_MAX_MEMORY_PERCENT:
        return (f'only {free / 1024**3:.1f} GiB free ({used:g}% used); a warm emulator needs '
                f'{WARM_MIN_FREE_BYTES / 1024**3:g} GiB free and under {WARM_MAX_MEMORY_PERCENT}% used')
    return None


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
    ahead=run.get('mercmode_prelaunch') or {}
    if job.get('id') and job.get('id')==ahead.get('job'):
        # the next title's warm preload during this run's last seconds: the same foreground priority as its launch
        nxt=TITLES.get(ahead.get('title')) or {}
        return bool(cfg['enabled'] and cfg['presentation_priority'] and ahead.get('title') in cfg['titles']
            and nxt.get('playable') and job.get('actor')==ACTOR and (job.get('input') or {}).get('warm') is True
            and run.get('phase') in ('starting','playing') and run.get('worker_id')==worker.get('id')==job.get('require_worker')
            and game.get('game_id') in nxt.get('game_ids',()))
    return bool(cfg['enabled'] and cfg['presentation_priority'] and title in cfg['titles']
        and spec.get('playable') and job.get('tool')=='launch_game' and job.get('actor')==ACTOR
        and job.get('id')==run.get('job') and run.get('phase')=='launching'
        and run.get('worker_id')==worker.get('id')==job.get('require_worker')
        and game.get('game_id')==run.get('game_id') and run.get('game_id') in spec.get('game_ids',())
        and {k:v for k,v in ((game.get('launch') or {}).get('mercmode') or {}).items()
             if k!='selection' and k not in STALEMATE_KEYS}
            =={'random_characters':True,'random_stages':True})


def launch_block(cfg, selection=None) -> dict:
    """The launch payload's mercmode block (game.launch.mercmode): random character and stage every round, the DJ's
    exact selection when there is one, and the bots' stalemate rule settings (gbox.mercs.stalemate.configure reads
    them on the worker)."""
    return {'random_characters': True, 'random_stages': True,
            **({'selection': selection} if selection else {}),
            **{k: cfg[k] for k in STALEMATE_KEYS if k in cfg}}


def adopt_current(store, worker, session, telemetry, *, now=None):
    """Explicit operator adoption of this exact already-running solo bot.

    No controller input, stop or launch. A human session, stale telemetry or a
    foreign job cannot become a scheduler-owned run through this operation.
    """
    from .screensaver import STATE, _launch_session
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
    launch_id=sid.split('-',1)[1]
    launch=store.get('job',launch_id) or {}
    pid=(session.get('detail') or {}).get('pid'); started=session.get('started')
    if launch.get('tool')!='launch_game' or launch.get('state')!='succeeded' \
            or launch.get('worker_id')!=wid or launch.get('require_worker')!=wid \
            or ((launch.get('input') or {}).get('game') or {}).get('game_id')!=session['game_id'] \
            or _launch_session(store,launch_id,[session],worker_id=wid,game_id=session['game_id']) is None \
            or type(pid) is not int or pid<=0 or type(started) not in (int,float) or not math.isfinite(started) \
            or session.get('adapter') not in ('rpcs3','dolphin'):
        raise ValueError('The adopted emulator needs its exact accepted launch and process identity')
    old=store.get(STATE,worker['name'])
    if old:
        if old.get('session_id')==sid and old.get('mercmode'):return old
        raise ValueError('The host already has a different scheduler-owned run')
    proof={'version':1,'id':uuid.uuid4().hex,'worker':worker['name'],'worker_id':wid,
           'session_id':sid,'game_id':session['game_id'],'job':launch_id,'pid':pid,'started':started,
           'adapter':session['adapter'],
           'autoplay_job':jid,'at':now}
    store.put(ADOPTION,sid,proof)
    label=store.get('slabel',sid) or {}
    store.put('slabel',sid,label|{'session_id':sid,'owner':'agent','ts':now,
                                 'task':'MercMode: explicitly adopted solo autoplay'})
    run={'worker':worker['name'],'worker_id':wid,'session_id':sid,'game_id':session['game_id'],
         'title':session.get('title') or TITLES[title]['name'],'phase':'playing','started':now,
         'playing_since':now,'autoplay_job':jid,'adopted_existing_solo':True,
         'job':launch_id,'warm_adoption':proof['id'],
         'mercmode':{'title':title,'map_id':TITLES[title]['map_id'],'rounds_per_title':cfg['rounds_per_title']}}
    store.put(STATE,worker['name'],run)
    return run


def warm_adoption_owned(store, worker, row, session):
    """Only the exact explicitly adopted process may bypass scheduler launch provenance.

    The durable receipt survives removal of the active run when it is parked.
    It never authorizes a different process or a newer unrelated control owner.
    """
    from . import autoplay_resume
    from .screensaver import ACTOR
    sid=session.get('session_id')
    proof=store.get(ADOPTION,sid) or {}
    if not row.get('warm_adoption') or proof.get('version')!=1 or proof.get('id')!=row['warm_adoption'] \
            or proof.get('worker')!=worker.get('name') or proof.get('worker_id')!=worker.get('id') \
            or any(proof.get(k)!=row.get(k) for k in ('session_id','game_id','job','worker_id')) \
            or session.get('state')!='running' or session.get('game_id')!=proof.get('game_id') \
            or session.get('started')!=proof.get('started') \
            or session.get('adapter')!=proof.get('adapter') \
            or (session.get('detail') or {}).get('pid')!=proof.get('pid') \
            or session.get('replaced_by') or (store.get('slabel',sid) or {}).get('owner')=='you':
        return False
    original=store.get('job',proof.get('autoplay_job')) or {}
    if original.get('tool')!='autoplay' or original.get('state') not in ('assigned','running','succeeded') \
            or original.get('worker_id')!=worker['id'] or original.get('require_worker')!=worker['id'] \
            or (original.get('input') or {}).get('session_id')!=sid or (original.get('input') or {}).get('op')!='start' \
            or autoplay_resume.revoked(store,sid,original.get('id')):
        return False
    current=autoplay_resume.latest_control(store,sid) or {}
    if current.get('id')!=row.get('autoplay_job') or current.get('require_worker')!=worker['id'] \
            or current.get('worker_id') not in (None,worker['id']) or current.get('state')=='cancelled' \
            or autoplay_resume.revoked(store,sid,current.get('id')):
        return False
    with store.reading() as db:
        changed=db.execute("SELECT 1 FROM docs INDEXED BY docs_job_session WHERE kind='job' "
            "AND json_extract(body,'$.tool')='session_op' "
            "AND json_extract(body,'$.input.session_id')=? "
            "AND json_extract(body,'$.input.op') IN ('pause','resume','reset','load_state','send_input','stop_game') "
            "AND json_extract(body,'$.created')>=? AND COALESCE(json_extract(body,'$.actor'),'')!=? LIMIT 1",
            (sid,proof['at'],ACTOR)).fetchone()
    if changed:
        return False
    return (current.get('id')==original.get('id') or current.get('actor')==ACTOR
            and current.get('tool')=='autoplay' and (current.get('input') or {}).get('op') in ('start','stop')
            and (current.get('input') or {}).get('session_id')==sid)


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


def _host_matcher(store, worker):
    """_same_host_worker for one worker, each source worker id walked once (2026-10-26: /api/mercmode took 20-40 s on the
    loaded Spark - inventory() walked the alias chain, up to 8 store reads, for every session of every MercMode title)."""
    seen={}
    def match(source):
        if source not in seen:
            seen[source]=_same_host_worker(store,source,worker)
        return seen[source]
    return match


def rotation_predecessor(store, worker, now):
    from .screensaver import LOG
    same=_host_matcher(store,worker)
    rows=[r for r in store.all(LOG) if same(r.get('worker_id'))
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


def display_successors(store, workers, running):
    """Read-only viewer links from parked games to this host's current MercMode turn.

    Warm games keep their real session identity. Persisting replacement links
    would create A -> B -> A cycles when the same emulator takes another turn.
    These links are projected only into the sessions response, after accepted
    park/resume and autoplay controls; they grant no server control ownership.
    """
    from . import autoplay_resume
    from .screensaver import STATE, ACTOR, _launch_session

    def owned(worker, row):
        sid=row.get('session_id','')
        session=next((s for s in running if s.get('session_id')==sid),None)
        if not session or session.get('state')!='running' or session.get('replaced_by') \
                or row.get('worker_id')!=worker['id'] or not sid.startswith(worker['id']+'-') \
                or (store.get('slabel',sid) or {}).get('owner')=='you':
            return None
        job=store.get('job',row.get('job')) or {}
        if job.get('state')!='succeeded' or job.get('tool')!='launch_game' \
                or job.get('require_worker')!=worker['id'] or job.get('worker_id')!=worker['id'] \
                or _launch_session(store,row.get('job'),[session],worker_id=worker['id'],game_id=row.get('game_id')) is None:
            return None
        if row.get('warm_adoption'):
            return session if warm_adoption_owned(store,worker,row,session) else None
        return session if job.get('actor')==ACTOR and job.get('agent_use') else None

    def control(worker, row, op, since):
        sid=row['session_id'];job=autoplay_resume.latest_control(store,sid) or {}
        if job.get('id')!=row.get('autoplay_job') or job.get('state')!='succeeded' \
                or job.get('require_worker')!=worker['id'] or job.get('worker_id')!=worker['id'] \
                or (job.get('input') or {}).get('op')!=op \
                or autoplay_resume.revoked(store,sid,job.get('id')):
            return False
        if job.get('actor')!=ACTOR and not row.get('warm_adoption'):
            return False
        # A manual pause/reset/input wins even before its worker acknowledges it. By docs_job_session (gbox/store.py):
        # this was a 214 MB scan of every job under the Store lock per /api/sessions poll on the Spark (2026-10-26).
        with store.reading() as db:
            changed=db.execute("SELECT 1 FROM docs INDEXED BY docs_job_session WHERE kind='job' "
                "AND json_extract(body,'$.tool')='session_op' "
                "AND json_extract(body,'$.input.session_id')=? "
                "AND json_extract(body,'$.input.op') IN ('pause','resume','reset','load_state','send_input','stop_game') "
                "AND json_extract(body,'$.created')>=? AND COALESCE(json_extract(body,'$.actor'),'')!=? LIMIT 1",
                (sid,since,ACTOR)).fetchone()
        return not changed

    out={}
    with store.lock:
        for worker in workers:
            host=worker.get('name')
            if not host or not worker.get('online') or worker.get('federation') or not settings(store,host)['enabled']:
                continue
            run=store.get(STATE,host) or {};pool=warm_pool(store,host)
            target=owned(worker,run) if run.get('mercmode') and run.get('phase')=='playing' else None
            if not target or run.get('handover') or run.get('yield') or run.get('mercmode_rotate_requested') \
                    or not control(worker,run,'start',run.get('started',0)) \
                    or any(r.get('session_id')==target['session_id'] for r in pool.values()):
                continue
            if run.get('warm_resume_job') and (store.get('job',run['warm_resume_job']) or {}).get('state')!='succeeded':
                continue
            for row in pool.values():
                proof=row.get('display_park') or {};source=owned(worker,row) if row.get('state')=='parked' else None
                if not source or source['session_id']==target['session_id'] \
                        or not re.fullmatch('[a-f0-9]{32}',str(proof.get('round_id',''))) \
                        or proof.get('started')!=source.get('started') \
                        or type(proof.get('pid')) is not int or proof['pid']<=0 \
                        or proof['pid']!=(source.get('detail') or {}).get('pid') \
                        or not control(worker,row,'stop',row.get('at',0)):
                    continue
                pause=store.get('job',row.get('pause_job')) or {};inp=pause.get('input') or {}
                if pause.get('state')=='succeeded' and pause.get('actor')==ACTOR \
                        and pause.get('worker_id')==worker['id']==pause.get('require_worker') \
                        and pause.get('tool')=='session_op' and inp.get('session_id')==source['session_id'] \
                        and inp.get('op')=='pause' and (inp.get('args') or {}).get('warm') is True:
                    out[source['session_id']]=target['session_id']
    return out


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
    from .re_switch import preferred_spec
    rows = []
    for key in TITLES:
        spec = preferred_spec(key, TITLES[key], cfg)
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
            same=_host_matcher(store,worker)
            for game in games:
                gid=game['game_id']
                # a restart gives the same PC a new worker id: the registered aliases keep its launch history
                prior=next((s for s in known if s.get('game_id')==gid
                    and s.get('state') in ('running','ended')
                    and same(s.get('session_id','').split('-')[0])),None)
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
                     'platform': spec['platform'], 'preferred_mode': spec.get('preferred_mode'),
                     'playable': bool(backend_ready and access['verified']), 'backend_playable':backend_ready,
                     'rom_access':access, 'reason': reason,
                     'game_id': selected_game['game_id'] if selected_game else None,
                     'modes': spec.get('modes', []), 'characters': spec.get('characters'),
                     'stages': spec.get('stages'), 'preparation': preparation(spec['platform'])})
    return rows


def preparation(platform):
    if platform == 'switch':
        return {'strategy': 'native_readiness_pending', 'instant_state_supported': False,
                'reason': 'Switch emulator startup, No Mercy selection and native autoplay hooks need live verification.'}
    return ({'strategy': 'persistent_install_and_shader_cache', 'instant_state_supported': False,
             'reason': 'RPCS3 uses its installed data and retained caches, then verified native menus. '
                       'No save-state capture/reload. With keep_warm the next title boots paused in the round\'s last '
                       f'{PRELAUNCH_S:g} s, its menus are driven to a round start in the background (autoplay prepare) '
                       'and the switch resumes it in gameplay (gbox.screensaver warm pool).'}
            if platform == 'ps3' else
            {'strategy': 'existing_dolphin_menu_jump_if_available', 'instant_state_supported': True,
             'reason': 'An existing matching Dolphin menu jump may be reused; otherwise native menus boot normally.'})


def choose(store, worker, rng, cfg=None):
    cfg = cfg or settings(store, worker['name'])
    rows = inventory(store, worker, cfg)
    ahead = store.get(NEXT, worker['name'])
    if ahead:                                    # picked (and preloaded) before the round ended: keep that promise
        store.delete(NEXT, worker['name'])
        row = next((r for r in rows if r['playable'] and r['title'] == ahead.get('title')), None)
        if row:
            return row | ({'selection': ahead['selection']} if ahead.get('selection') else {})
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


ROUND_MIN_S = 75.0              # a death this soon after an attempt began is a retry, not a round played (round_boundary)
QUICK_DEATHS_PER_ROUND = 3      # ...though this many of them count as one, so a title where the bot keeps dying still rotates


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
