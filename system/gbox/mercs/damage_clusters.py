"""RE Mercenaries damage incidents grouped by cause: one batch request per cause per game.

The operator (2026-10-27 19:12): "A lot of these reports I look at as batch incidents that are able to be handled all
together. And so just singular changes to the logic should be able to improve large swaths of the reports". Until then
every autoplay run filed its own player-damage request (gbox/player_damage.py: 127 in a day, 126 never worked) and
nothing grouped the hits by what caused them.

  * incident: every observed HP loss of an RE game (the player_damage ledger) gets one small record of the fields its
    receipt holds at the hit - his health, the live enemies within 2 / 4 m and their bearing off his facing, a grab,
    a knockdown, his own bomb or mine, the buttons held, the bot's decision, a heal in hand - and a few of the driver's
    running counters (wall aim, line of sight, aim away). Recorded at ingest (record_event); older ledger rows are
    read back from their receipts a bounded number per pass (backfill).
  * classify: fixed rules on those fields give each hit one cause signature (SIGNATURES, first match wins) plus every
    rule it matched (tags). No model is involved; the rules are the code below and tests/test_mercs_damage_clusters.py.
    A death takes the signature of the hit that put him down (to dying), else the killing hit's; RE6's death_log
    entry (held, zombies within 2 m, his bomb) for that death is folded in.
  * cluster: the hits and deaths of one game and signature in the rolling WINDOW_S. MIN_BATCH or more own one batch
    request (deterministic id, updated in place as the window rolls, reopened when the cause comes back after a fix)
    with the counts, the trend per turn (autoplay run), representative examples, the suspected bot decision and the
    code it implicates. Hermes takes it first on sparkDeux (gbox.hermes_work_queue: damage_cluster_verified) with one
    instruction: ONE logic change with tests, as a PR.
  * members: the per-run damage requests whose events all sit in batched clusters are linked (context.batched_into)
    and closed "batched into #N" - never deleted; their ledgers stay where they were.

GET /api/mercs/damage-clusters?game= lists the clusters (top-N "what kills him"), GET /api/mercs/damage-clusters/{id}
one cluster with its members.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import time

INCIDENT = 'mercs_damage_incident'
CLUSTER = 'mercs_damage_cluster'
STATE = 'mercs_damage_cluster_state'
SOURCE = 'mercs_damage_cluster'
SCHEMA = 'gbox.mercs.damage-incident/1'
LEDGER = 'player_damage'              # gbox.player_damage.KIND / RUN_KIND (not imported: this module loads standalone)
LEDGER_RUN = 'player_damage_run'
TARGET = 'sparkDeux'                  # gbox.mercs.round_reports.TARGET: the node that takes RE auto-reports first

WINDOW_S = 24 * 3600                  # the rolling window a batch describes
MIN_BATCH = 5                         # episodes + deaths a cluster needs before it owns a batch request
PRIORITY_TOP = 3                      # batches per game on the Hermes priority list (most deaths, then HP lost)
EXAMPLES = 5                          # representative examples per batch
BACKFILL_PER_PASS = 120               # ledger receipts read back per pass (200-400 KB each)
BACKLOG_PER_RUN = 60                  # an open single older than the window: its newest events classified, not all
REOPEN_GRACE_S = 12 * 3600            # a closed batch reopens only for hits this long after it closed (deploys are manual)
REOPEN_MIN = 5                        # ... and at least this many of them
UPDATE_S = 300                        # a batch request's summary is rewritten at most this often
PASS_S = 60.0
PREV_S = 3.0                          # a counter rising since the previous hit this recent belongs to this hit
SPARK2_FIRST_S = 3600                 # paid (priority-only) Hermes nodes leave a new batch to sparkDeux this long

# Geometry at the hit (cm, the drivers' units). MAX_DY: the drivers' own "on his level" (re5_switch / re6_switch).
MAX_DY, CROWD_R, CROWD_N, NEAR4_R, CONTACT_R, GRAB_R = 300.0, 200.0, 4, 400.0, 250.0, 150.0
BEHIND_DEG, AWAY_DEG = 90.0, 45.0     # behind him / his aim this far off the nearest threat
LOW_HP = 0.3                          # of his maximum, before the hit
FALL_DY, FALL_S = 150.0, 2.0          # he dropped this far in the preceding FALL_S
BOMB_R = 500.0                        # RE6 BOMB_RADIUS_CM (before the driver's BlastBook learned one: bomb_radius_cm)
MINE_R = 450.0                        # RE5 proximity bomb: "took 700 of Chris's 1000 at 3.8 m" (re5_switch_mines)
BOMB_CONTACT_R, BOMB_LOSS = 120.0, 200    # with a Majini at arm's length only a big loss is taken as the blast
DYING_HP = 1                          # RE5 and RE6 keep exactly 1 HP while dying (re5_switch / re6_switch DYING_HP)
EPISODE_S = 1.5                       # hits of one cause this close (same round) are one episode
DOWN_LINK_S = 30.0                    # a death goes to the hit that put him down this recently in the same round

RE5_SWITCH, RE6_SWITCH, RE5_PS3, RE4_GC, RE4_PS2 = '010018100CD46000', '01002A000CD48000', 'BLUS30491', 'G4BE08', 'BH6'
TITLE_NAMES = {RE5_SWITCH: 'RE5 Switch', RE6_SWITCH: 'RE6 Switch', RE5_PS3: 'RE5 PS3', RE4_GC: 'RE4 GC',
               RE4_PS2: 'RE4 PS2'}
# gbox.mercs.round_reports.TITLES (title -> game ids), kept here so the pure rules load without the server
GAMES = {'e7ca89bbeb67360d': RE5_PS3, '78ab9efa2e310db4': RE4_GC, 'e42c9b780c07c437': RE4_GC,
         '0871eee3b68cdea3': RE4_PS2, '52d15709be0fda1a': RE5_SWITCH, '115f9cdbba115432': RE6_SWITCH}
HELD_MOTIONS = frozenset({100, 106, 107, 113, 114})   # re5_switch MOTION_HELD (107 grabbed, 106 held, 113/100/114 strangled)
DYING_MOTIONS = frozenset({40, 47, 51})                # re5_switch P_MOTION: dying at 1 HP (8 is dead)
HELD_STATES = frozenset({8, 9, 25})                    # re6_switch HELD_STATES (P_STATE 3: knocked down)
HEAL_IDS = frozenset({0x304, 0x305, 0x307, 0x309})     # RE5 First Aid Spray, green herb, mixed herbs (both editions)
AIM_KEYS = frozenset({'zl', 'l1'})                     # Switch ZL / the PS3 bot's L1 raise the gun
DOWN_WORDS = ('lying', 'creeping', 'dying_loop', 'buttobi', 'go_any_down', 'pl_act_down', 'damage_down')
GRAB_WORDS = ('catch', 'grab', 'hold')
COUNTERS = ('wall_aim_s', 'wall_blocks', 'wall_shots', 'los_blocks', 'look_walls_shot', 'behind_threat_s',
            'aim_away_s', 'aim_away_fixes', 'frozen_dots', 'sky_ticks', 'holds', 'deaths', 'dyings', 'dying',
            'tablets', 'tablet_presses', 'tablet_misses', 'heals', 'heal_starts', 'heal_failures',
            'mine_blast_hp_loss', 'mines_gone', 'bomb_self_hits', 'bombs_detonated', 'bomb_radius_cm',
            'down_s', 'hazard_marks', 'hits_taken', 'crowd_moves', 'escapes', 'burst_backoffs', 'max_within_4m')
WALL_COUNTERS = ('wall_aim_s', 'wall_blocks', 'wall_shots', 'los_blocks', 'look_walls_shot')
AWAY_COUNTERS = ('aim_away_s', 'behind_threat_s', 'frozen_dots', 'sky_ticks')
BOMB_COUNTERS = ('mine_blast_hp_loss', 'bomb_self_hits')

# The signatures, first match wins. (key, label, the rule in words)
SIGNATURES = (
    ('own_bomb', 'own bomb or mine within blast radius',
     'his own remote bomb (RE6) or proximity mine (RE5) lay within its blast radius of him, or the driver booked the '
     'loss to his own blast'),
    ('grabbed_from_behind', 'grabbed from behind',
     'a grab or hold (RAM: RE5 motion 100/106/107/113/114, RE6 state 8/9/25, a Catch/Grab action) with the nearest '
     'enemy more than 90 deg off his facing'),
    ('grabbed_front', 'grabbed from the front', 'a grab or hold with the nearest enemy within 90 deg of his facing'),
    ('fall_knockdown', 'fall, knockdown or dying chain',
     'knocked down, lying, crawling or dying at 1 HP (RE6 down actions, state 3), or a drop of 1.5 m in 2 s'),
    ('crowd_4_in_2m', 'crowd of 4+ within 2 m', 'four or more live enemies on his level within 2 m'),
    ('aimed_away_or_behind', 'aimed away or threat behind while hit',
     'his gun up with the nearest enemy within 4 m more than 45 deg off his aim, the nearest within 2 m more than '
     '90 deg behind him, or the driver\'s aim-away / behind-threat seconds rising since the previous hit'),
    ('wall_los_aim', 'aiming at a wall / no line of sight',
     'the driver\'s wall-aim / wall-shot / line-of-sight block counters rose since the previous hit'),
    ('low_hp_no_heal', 'low health with no tablet or heal',
     'at or under 30% health before the hit with no tablet (RE6) or heal item (RE5) left'),
    ('low_hp_heal_unused', 'low health with a heal in hand, not used',
     'at or under 30% health before the hit while a tablet or heal item was in the case'),
    ('ranged', 'ranged enemy or hazard (nobody within 2.5 m)',
     'no live enemy on his level within 2.5 m and not held: shots, thrown weapons, fire, gas or a boss reach'),
    ('faced_melee', 'melee by 1-3 enemies he faced',
     'one to three enemies within 2.5 m, in front of him: he let them reach him'),
    ('other', 'other', 'no rule matched (the top fields are listed)'),
)
ORDER = [s[0] for s in SIGNATURES]
LABELS = {s[0]: s[1] for s in SIGNATURES}
RULES = {s[0]: s[2] for s in SIGNATURES}
EX_KINDS = {'aim_away': 'aimed_away_or_behind', 'behind_threat': 'aimed_away_or_behind', 'sky': 'aimed_away_or_behind',
            'frozen_dot': 'aimed_away_or_behind', 'wall_shot': 'wall_los_aim', 'wall_block': 'wall_los_aim'}

_R5S, _R6S, _R5P = 'gbox/mercs/titles/re5_switch.py', 'gbox/mercs/titles/re6_switch.py', 'gbox/mercs/titles/re5_ps3.py'
# What each cluster implicates in each bot: (the decision suspected, [(file, function)])
CODE = {
    RE5_SWITCH: {
        'own_bomb': ('the mine guard lets him stand within BLAST_CM of his own bomb, or places one with Majini closing',
                     [('gbox/mercs/titles/re5_switch_mines.py', 'Mines.tick'),
                      ('gbox/mercs/titles/re5_switch_mines.py', 'Mines.due')]),
        'grabbed_from_behind': ('the threat pick and the 5 m rampage keep the gun on one ahead while one closes from '
                                'behind (behind_threat_s)', [(_R5S, 'Bot._threat_pick'), (_R5S, 'Bot._fault_tick'),
                                                             (_R5S, 'Bot._rampage')]),
        'grabbed_front': ('a Majini reaches arm\'s length in front: no shot, knife or back-off before the grab',
                          [(_R5S, 'Bot._rampage'), (_R5S, 'Bot._keep_moving'), (_R5S, 'Bot._tick')]),
        'fall_knockdown': ('dying and knockdowns: the resuscitate mash and getting clear after rising',
                           [(_R5S, 'Bot._tick'), (_R5S, 'Bot._escape')]),
        'crowd_4_in_2m': ('the crowd move / keep moving lets four or more close within 2 m before he relocates',
                          [(_R5S, 'Bot._keep_moving'), (_R5S, 'Bot._relocate'), (_R5S, 'Bot._escape')]),
        'aimed_away_or_behind': ('the aim is off the nearest threat (aim_away / behind_threat): the target choice '
                                 'and its correction', [(_R5S, 'Bot._threat_pick'), (_R5S, 'Bot._aim_away'),
                                                        (_R5S, 'Bot._choose')]),
        'wall_los_aim': ('the wall gate: the ray ends on geometry short of the target while others close',
                         [(_R5S, 'Bot._decide'), (_R5S, 'Bot._choose')]),
        'low_hp_no_heal': ('the heal supply ran out: heal items not picked up or the loadout carries too few',
                           [(_R5S, 'Bot._heal'), ('gbox/mercs/titles/re5_switch_mods.py', 'mine_loadout')]),
        'low_hp_heal_unused': ('the heal waits (HEAL_AT, HEAL_SAFE_R deferral) while Majini keep hitting him',
                               [(_R5S, 'Bot._heal')]),
        'ranged': ('ranged Majini (thrown weapons, crossbows, fire) are not prioritized as targets',
                   [(_R5S, 'Bot._threat_pick'), (_R5S, 'Bot._choose'), (_R5S, 'Bot._kcost')]),
        'faced_melee': ('a Majini he faced still reached him: the engagement range and the back-off',
                        [(_R5S, 'Bot._choose'), (_R5S, 'Bot._keep_moving'), (_R5S, 'Bot._trigger')]),
        'other': ('unclassified', [(_R5S, 'Bot._decide')]),
    },
    RE6_SWITCH: {
        'own_bomb': ('the remote bomb is set off or stood near inside its learned radius (BlastBook.safe)',
                     [(_R6S, 'Bot._bomb'), (_R6S, 'Bot._bomb_escape'), (_R6S, 'Bot._bomb_walk'),
                      (_R6S, 'BlastBook.safe')]),
        'grabbed_from_behind': ('zombies close from behind while he aims ahead: the crowd control turn and the look',
                                [(_R6S, 'Bot._crowd_control'), (_R6S, 'Bot._look_tick'), (_R6S, 'Bot._decide')]),
        'grabbed_front': ('a zombie reaches arm\'s length in front before the kick or quick shot',
                          [(_R6S, 'Bot._crowd_control'), (_R6S, 'Bot._decide')]),
        'fall_knockdown': ('down and dying: the fight from the ground, getting up and the tablet at 1 health',
                           [(_R6S, 'Bot._down_tick'), (_R6S, 'Bot._down_fight'), (_R6S, 'Bot._dying')]),
        'crowd_4_in_2m': ('crowd control lets four or more within 2 m: no flash, step back or kick in time',
                          [(_R6S, 'Bot._crowd_control'), (_R6S, 'Bot._nade')]),
        'aimed_away_or_behind': ('the aim lock is on one away from the nearest: target choice and turn',
                                 [(_R6S, 'Bot._aim'), (_R6S, 'Bot._lock'), (_R6S, 'Bot._decide')]),
        'wall_los_aim': ('the line-of-sight check: aiming through geometry', [(_R6S, 'Bot._los_tick'),
                                                                              (_R6S, 'Bot._on_line')]),
        'low_hp_no_heal': ('the tablet case is empty', [(_R6S, 'Bot._dying'), (_R6S, 'Bot._tablet_check')]),
        'low_hp_heal_unused': ('the tablet rule (TABLET_HP) waits or its press is missed while he is hit',
                               [(_R6S, 'Bot._decide'), (_R6S, 'Bot._tablet_check')]),
        'ranged': ('gunfire, thrown weapons or hazards (smoke, fire, acid) with nobody near: the hazard marks and '
                   'ranged targets', [(_R6S, 'Bot._hazard_tick'), (_R6S, 'Bot._decide')]),
        'faced_melee': ('a zombie he faced still reached him: engagement range and step back',
                        [(_R6S, 'Bot._crowd_control'), (_R6S, 'Bot._aim')]),
        'other': ('unclassified', [(_R6S, 'Bot._decide')]),
    },
    RE5_PS3: {
        'own_bomb': ('the mine retreat leaves him inside his own mine\'s blast', [(_R5P, 'Bot._mine_retreat'),
                     (_R5P, 'Bot._mine_placement_preflight'), ('gbox/mercs/titles/re5_mines.py', 'Controller')]),
        'grabbed_from_behind': ('threats behind him are not turned to', [(_R5P, 'Bot._threat'), (_R5P, 'Bot._tick')]),
        'grabbed_front': ('a Majini reaches arm\'s length in front', [(_R5P, 'Bot._threat'), (_R5P, 'Bot._tick')]),
        'fall_knockdown': ('knockdowns and dying', [(_R5P, 'Bot._tick')]),
        'crowd_4_in_2m': ('crowd handling lets four or more within 2 m', [(_R5P, 'Bot._tick'), (_R5P, 'Bot._threat')]),
        'aimed_away_or_behind': ('the aim is off the nearest threat', [('gbox/mercs/titles/re5_combat.py',
                                                                        'Combat._aim_begin'), (_R5P, 'Bot._threat')]),
        'wall_los_aim': ('aiming without line of sight', [(_R5P, 'Bot._lost_sight')]),
        'low_hp_no_heal': ('no heal item left', [(_R5P, 'Bot._heal'), (_R5P, 'Bot._seek_health')]),
        'low_hp_heal_unused': ('the heal waits while he is hit', [(_R5P, 'Bot._heal'), (_R5P, 'Bot._heal_safe')]),
        'ranged': ('ranged enemies are not prioritized', [(_R5P, 'Bot._threat')]),
        'faced_melee': ('a Majini he faced still reached him', [(_R5P, 'Bot._threat')]),
        'other': ('unclassified', [(_R5P, 'Bot._tick')]),
    },
}


def _num(v) -> bool:
    return type(v) in (int, float) and math.isfinite(v)


def _pos(v):
    return list(v[:3]) if isinstance(v, (list, tuple)) and len(v) >= 3 and all(_num(x) for x in v[:3]) else None


def _wrap_deg(a: float) -> float:
    return (a + 180.0) % 360.0 - 180.0


def title_of(game_id):
    return GAMES.get(str(game_id or ''))


def _decision(title, logic, held, p):
    """The bot's decision at the hit: RE6's act, the RE5 PS3 plan phase, else what the held buttons were doing."""
    act = logic.get('act')
    if isinstance(act, str) and act:
        return act[:40]
    keys = set(held)
    if keys & {'lleft', 'lright'} and not keys & {'lup', 'ldown', 'zl', 'zr', 'l1', 'r1', 'b'} and len(keys) <= 2:
        label = 'wiggle (break free)'
    elif 'y' in keys:
        label = 'heal (Y)'
    elif keys & AIM_KEYS and keys & {'zr', 'r1'}:
        label = 'fire'
    elif keys & AIM_KEYS:
        label = 'aim'
    elif 'b' in keys:
        label = 'run'
    elif keys & {'dup', 'ddown', 'dleft', 'dright'}:
        label = 'item (D-pad)'
    elif keys & {'lup', 'ldown', 'lleft', 'lright'}:
        label = 'walk'
    elif keys & {'rleft', 'rright', 'rup', 'rdown'}:
        label = 'turn'
    else:
        label = 'no input'
    phase = logic.get('phase')
    return (label + ' / ' + phase)[:40] if title == RE5_PS3 and isinstance(phase, str) and phase else label


def features(event, game_id=None) -> dict:
    """The incident record of one receipt event (pure: the cause rules read only this)."""
    if event.get('packed_context'):
        from .incident import unpack_context
        event = unpack_context(event)
    title = str(event.get('title') or title_of(game_id) or '')
    snap = event.get('snapshot') if isinstance(event.get('snapshot'), dict) else {}
    p = snap.get('player') if isinstance(snap.get('player'), dict) else {}
    logic = event.get('logic') if isinstance(event.get('logic'), dict) else {}
    held = sorted(str(k) for k in event.get('held') or () if isinstance(k, str))[:12]
    pos, rot = _pos(p.get('pos')), p.get('rot') if _num(p.get('rot')) else None
    near = []
    if pos:
        for e in snap.get('enemies') or ():
            if not isinstance(e, dict) or not _num(e.get('hp')) or e['hp'] <= 0:
                continue
            ep = _pos(e.get('pos'))
            if not ep or abs(ep[1] - pos[1]) > MAX_DY:
                continue
            dx, dz = ep[0] - pos[0], ep[2] - pos[2]
            deg = round(_wrap_deg(math.degrees(math.atan2(dx, dz) - rot))) if rot is not None else None
            near.append({'d': round(math.hypot(dx, dz)), 'deg': deg,
                         'cls': str(e['class'])[:16] if isinstance(e.get('class'), str) else None})
    near.sort(key=lambda n: n['d'])
    bombs = []
    if pos:
        candidates = []
        if _pos(snap.get('bomb_pos')):
            candidates.append(('bomb', _pos(snap['bomb_pos'])))
        mines = snap.get('ground_mines')
        for m in (mines.values() if isinstance(mines, dict) else mines if isinstance(mines, list) else ()):
            if isinstance(m, dict) and _pos(m.get('pos')):
                candidates.append(('mine', _pos(m['pos'])))
        for kind, bp in candidates:
            if abs(bp[1] - pos[1]) <= MAX_DY:
                bombs.append((round(math.hypot(bp[0] - pos[0], bp[2] - pos[2])), kind))
    bombs.sort()
    motion, state, action = p.get('motion'), p.get('state'), p.get('action')
    words = action.lower() if isinstance(action, str) else ''
    grabbed = bool((title == RE5_SWITCH and motion in HELD_MOTIONS) or (title == RE6_SWITCH and state in HELD_STATES)
                   or state == 'grabbed' or (title == RE5_PS3 and action == 4)
                   or any(w in words for w in GRAB_WORDS))
    hp_before, hp_after, hp_max = event.get('hp_before'), event.get('hp_after'), event.get('hp_max')
    dying = bool(title in (RE5_SWITCH, RE6_SWITCH) and hp_before == DYING_HP
                 or title == RE5_SWITCH and motion in DYING_MOTIONS)
    down = bool((title == RE6_SWITCH and state == 3) or any(w in words for w in DOWN_WORDS))
    at = event.get('observed_at') if _num(event.get('observed_at')) else 0.0
    history = [h for h in event.get('preceding_history') or () if isinstance(h, dict) and _num(h.get('at'))]
    fell = 0
    if pos:
        ys = [h['pos'][1] for h in history if at - h['at'] <= FALL_S and _pos(h.get('pos'))]
        fell = round(max(ys) - pos[1]) if ys and max(ys) - pos[1] > 0 else 0
    hps = [h.get('hp') for h in history if at - h['at'] <= 3.0 and _num(h.get('hp'))]
    hits_3s = sum(1 for a, b in zip(hps, hps[1:]) if b < a)
    tablets = p.get('tablets') if type(p.get('tablets')) is int else None
    inv = snap.get('inventory')
    heals = sum(int(s.get('rounds') or 0) for s in inv if isinstance(s, dict) and s.get('id') in HEAL_IDS) \
        if isinstance(inv, list) else None
    frame = event.get('frame_at_hit') if isinstance(event.get('frame_at_hit'), dict) else {}
    tail = logic.get('death_log') if isinstance(logic.get('death_log'), list) else []
    return {
        'schema': SCHEMA, 'title': title, 'game_id': game_id, 'event_id': event.get('event_id'),
        'run_id': event.get('run_id'), 'round_id': event.get('round_id'), 'session_id': event.get('session_id'),
        'observed_at': at, 'hp_before': hp_before, 'hp_after': hp_after, 'hp_max': hp_max,
        'loss': event.get('loss'), 'near': near[:6], 'near_2m': sum(1 for n in near if n['d'] <= CROWD_R),
        'near_4m': sum(1 for n in near if n['d'] <= NEAR4_R), 'live': len(near),
        'bomb_cm': bombs[0][0] if bombs else None, 'bomb_kind': bombs[0][1] if bombs else None,
        'grabbed': grabbed, 'down': down, 'dying': dying, 'fell_cm': fell, 'hits_3s': hits_3s,
        'aiming': bool(set(held) & AIM_KEYS), 'held': held, 'decision': _decision(title, logic, held, p),
        'motion': motion if type(motion) is int else None, 'state': state if type(state) in (int, str) else None,
        'action': str(action)[:60] if action is not None else None,
        'tablets': tablets, 'heals': heals,
        'counters': {k: logic[k] for k in COUNTERS if _num(logic.get(k))},
        'death_log_tail': [{k: d.get(k) for k in ('held', 'doing', 'why', 'lost_by_doing', 'near_2m', 'near_4m',
                                                  'bomb_phase', 'bomb_cm')} for d in tail[-2:] if isinstance(d, dict)],
        'heal_status': str(logic.get('heal_status') or logic.get('heal_deferred') or '')[:80] or None,
        'frame': {k: frame.get(k) for k in ('state', 'seq', 'age_s') if k in frame} or None,
    }


def _rose(inc, prev, names) -> list:
    """Counters that rose since the previous hit of the same round within PREV_S."""
    if not prev or prev.get('round_id') != inc.get('round_id') \
            or not 0 <= (inc.get('observed_at') or 0) - (prev.get('observed_at') or 0) <= PREV_S:
        return []
    a, b = prev.get('counters') or {}, inc.get('counters') or {}
    return [k for k in names if _num(a.get(k)) and _num(b.get(k)) and b[k] > a[k]]


def classify(inc, prev=None, death=None):
    """(signature, tags): every rule this hit matched in SIGNATURES order; the first is its signature. `prev`: the
    previous hit of the same run (counter deltas); `death`: the RE6 death_log entry when this is a death."""
    death = death or {}
    tags = []
    near = inc.get('near') or []
    first = near[0] if near else None
    nearest = first['d'] if first else None
    deg = abs(first['deg']) if first and _num(first.get('deg')) else None
    radius = MINE_R if inc.get('bomb_kind') == 'mine' else (inc.get('counters') or {}).get('bomb_radius_cm') or BOMB_R
    bomb = inc.get('bomb_cm')
    loss = inc.get('loss') or 0
    if (bomb is not None and bomb <= radius and (nearest is None or nearest > BOMB_CONTACT_R or loss >= BOMB_LOSS)) \
            or _rose(inc, prev, BOMB_COUNTERS) \
            or (_num(death.get('bomb_cm')) and death['bomb_cm'] <= radius
                and death.get('bomb_phase') in ('det', 'det_wait', 'det_aim', 'wait')):
        tags.append('own_bomb')
    grabbed = inc.get('grabbed') or death.get('held') is True
    if grabbed:
        tags.append('grabbed_from_behind' if deg is not None and deg > BEHIND_DEG
                    and (nearest is None or nearest <= GRAB_R) else 'grabbed_front')
    if inc.get('down') or inc.get('dying') or (inc.get('fell_cm') or 0) >= FALL_DY \
            or death.get('doing') in ('down', 'dying'):
        tags.append('fall_knockdown')
    if max(inc.get('near_2m') or 0, death.get('near_2m') if _num(death.get('near_2m')) else 0) >= CROWD_N:
        tags.append('crowd_4_in_2m')
    away = inc.get('aiming') and nearest is not None and nearest <= NEAR4_R and deg is not None and deg > AWAY_DEG
    behind = nearest is not None and nearest <= CROWD_R and deg is not None and deg > BEHIND_DEG
    if not grabbed and (away or behind or _rose(inc, prev, AWAY_COUNTERS)):  # a grab's own bearing is the grab's
        tags.append('aimed_away_or_behind')
    if _rose(inc, prev, WALL_COUNTERS):
        tags.append('wall_los_aim')
    hp, top = inc.get('hp_before'), inc.get('hp_max')
    if _num(hp) and _num(top) and top > 0 and hp / top <= LOW_HP and not inc.get('dying'):
        supply = inc.get('tablets') if inc.get('tablets') is not None else inc.get('heals')
        if supply == 0:
            tags.append('low_hp_no_heal')
        elif supply is not None:
            tags.append('low_hp_heal_unused')
    if not tags:                                     # the fallbacks: nothing more specific explains the hit
        tags.append('faced_melee' if nearest is not None and nearest <= CONTACT_R else 'ranged')
    tags = sorted(set(tags), key=ORDER.index)
    return (tags[0] if tags else 'other'), tags


def _death_entries(incidents):
    """RE6 death_log entries by death number: the driver appends one per death (its last 8; death number = the deaths
    counter at that time), each incident carrying the last two."""
    out = {}
    for inc in incidents:
        tail = inc.get('death_log_tail') or []
        deaths = (inc.get('counters') or {}).get('deaths')
        if not tail or not _num(deaths):
            continue
        for i, entry in enumerate(tail):
            out.setdefault(int(deaths) - len(tail) + i + 1, entry)
    return out


def label_run(incidents):
    """Classify one run's incidents in time order: [(incident, signature, tags)] and its deaths [(incident, signature,
    death_log entry)]."""
    incidents = sorted(incidents, key=lambda i: (i.get('observed_at') or 0, str(i.get('event_id'))))
    entries = _death_entries(incidents)
    out, deaths, prev, put_down = [], [], None, {}
    for inc in incidents:
        sig, tags = classify(inc, prev)
        out.append((inc, sig, tags))
        prev = inc
        rnd = inc.get('round_id')
        before, after = inc.get('hp_before'), inc.get('hp_after')
        if _num(after) and after <= DYING_HP and _num(before) and before > DYING_HP and after < before:
            put_down[rnd] = (inc, sig)                       # the hit that took him to dying (or straight to 0)
        if _num(after) and after <= 0:
            counters = inc.get('counters') or {}
            entry = entries.get(int(counters['deaths']) + 1) if _num(counters.get('deaths')) else None
            down = put_down.get(rnd)
            if down and 0 <= (inc.get('observed_at') or 0) - (down[0].get('observed_at') or 0) <= DOWN_LINK_S:
                cause, dsig = down
            else:
                cause, dsig = inc, sig
            if entry:
                dsig = classify(cause, None, entry)[0] if dsig in ('faced_melee', 'ranged', 'other') else dsig
            deaths.append((cause, dsig, entry))
            put_down.pop(rnd, None)
    return out, deaths


def cluster_id(game_id, signature):
    return hashlib.sha256(f'mercs-damage-cluster:{game_id}:{signature}'.encode()).hexdigest()[:16]


def request_id_for(cid):
    return hashlib.sha256(('mercs-damage-cluster-request:' + cid).encode()).hexdigest()[:16]


def _example(inc, tags, entry=None):
    near = inc.get('near') or []
    who = ', '.join(f"{n['d'] / 100:.1f} m at {n['deg']:+d} deg" + (f" ({n['cls']})" if n.get('cls') else '')
                    for n in near[:3] if _num(n.get('deg'))) or 'nobody on his level'
    sid, run = inc.get('session_id'), inc.get('run_id')
    out = {'event_id': inc.get('event_id'), 'at': inc.get('observed_at'), 'run_id': run, 'round_id': inc.get('round_id'),
           'hp': f"{inc.get('hp_before')} -> {inc.get('hp_after')} of {inc.get('hp_max')}",
           'nearest': who, 'within_2m': inc.get('near_2m'), 'within_4m': inc.get('near_4m'),
           'held': inc.get('held'), 'decision': inc.get('decision'), 'grabbed': inc.get('grabbed'),
           'down': inc.get('down') or inc.get('dying'), 'bomb_cm': inc.get('bomb_cm'), 'tags': tags,
           'tablets': inc.get('tablets'), 'heals': inc.get('heals'), 'action': inc.get('action'),
           'motion': inc.get('motion'), 'frame': inc.get('frame'),
           'ledger': f'/api/sessions/{sid}/damage/runs/{run}' if sid and run else None}
    if entry:
        out['death_log'] = entry
    return {k: v for k, v in out.items() if v not in (None, [], '')}


def examples(hits, deaths, n=EXAMPLES):
    """Up to two deaths (what put him down), then the hits that are not those, n in all."""
    dead = _pick_examples(deaths, min(2, n), death=True)
    used = {e.get('event_id') for e in dead}
    return dead + _pick_examples([h for h in hits if h[0].get('event_id') not in used], n - len(dead))


def _pick_examples(items, n=EXAMPLES, death=False):
    """Representative: spread over runs and time, preferring deaths and the biggest losses."""
    if n <= 0:
        return []
    ranked = sorted(items, key=lambda x: (-(x[0].get('loss') or 0), x[0].get('observed_at') or 0))
    out, runs = [], set()
    for inc, tags, entry in ranked:
        if inc.get('run_id') not in runs:
            out.append((inc, tags, entry))
            runs.add(inc.get('run_id'))
        if len(out) >= n:
            break
    for item in ranked:
        if len(out) >= n:
            break
        if item not in out:
            out.append(item)
    return [dict(_example(inc, tags, entry), **({'death': True} if death else {}))
            for inc, tags, entry in sorted(out, key=lambda x: x[0].get('observed_at') or 0)]


def _top(values, n=3):
    counts = {}
    for v in values:
        if v not in (None, ''):
            counts[v] = counts.get(v, 0) + 1
    return [[k, c] for k, c in sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))[:n]]


def summarize(incidents, *, now, window_s=WINDOW_S):
    """Clusters of `incidents` (any games): {(game_id, signature): cluster} with counts, deaths, trend per turn
    (autoplay run) and per hour, examples and the co-occurring fields. Pure."""
    by_run = {}
    for inc in incidents:
        by_run.setdefault((inc.get('game_id'), inc.get('run_id')), []).append(inc)
    clusters, totals = {}, {}
    run_meta = {}
    for (gid, run), items in by_run.items():
        labelled, deaths = label_run(items)
        start = min(i.get('observed_at') or 0 for i in items)
        rounds = len({i.get('round_id') for i in items})
        run_meta[(gid, run)] = {'start': start, 'rounds': rounds, 'hits': len(items), 'deaths': len(deaths)}
        tot = totals.setdefault(gid, {'hits': 0, 'deaths': 0, 'hp_lost': 0, 'runs': 0, 'rounds': 0})
        tot['runs'] += 1
        tot['rounds'] += rounds
        for inc, sig, tags in labelled:
            c = clusters.setdefault((gid, sig), {'hits': [], 'deaths': []})
            c['hits'].append((inc, tags, None))
            tot['hits'] += 1
            tot['hp_lost'] += inc.get('loss') or 0
        for inc, sig, entry in deaths:
            tags = classify(inc, None, entry)[1]
            clusters.setdefault((gid, sig), {'hits': [], 'deaths': []})['deaths'].append(
                (inc, [sig] + [t for t in tags if t != sig], entry))
            tot['deaths'] += 1
    out = {}
    for (gid, sig), c in clusters.items():
        hits, deaths = c['hits'], c['deaths']
        stamps = sorted(i.get('observed_at') or 0 for i, _t, _e in hits + deaths)
        title = title_of(gid)
        runs, last = {}, None
        for inc, _t, _e in sorted(hits, key=lambda x: (str(x[0].get('run_id')), x[0].get('observed_at') or 0)):
            r = runs.setdefault(inc.get('run_id'), [0, 0, 0])
            r[0] += 1
            key = (inc.get('run_id'), inc.get('round_id'))
            if last is None or last[0] != key or (inc.get('observed_at') or 0) - last[1] > EPISODE_S:
                r[2] += 1                                    # a new episode: a grab's drain or a beating is one
            last = (key, inc.get('observed_at') or 0)
        for inc, _t, _e in deaths:
            runs.setdefault(inc.get('run_id'), [0, 0, 0])[1] += 1
        turns = []
        for run, (h, d, ep) in runs.items():
            meta = run_meta.get((gid, run)) or {}
            rounds = max(1, meta.get('rounds') or 1)
            turns.append({'run_id': run, 'start': meta.get('start'), 'rounds': meta.get('rounds'), 'hits': h,
                          'episodes': ep, 'deaths': d, 'episodes_per_round': round(ep / rounds, 2),
                          'share': round(h / max(1, meta.get('hits') or 1), 3)})
        turns.sort(key=lambda t: t['start'] or 0)
        hours = [0] * max(1, int(window_s // 3600))
        for s in stamps:
            k = int((now - s) // 3600)
            if 0 <= k < len(hours):
                hours[len(hours) - 1 - k] += 1
        tag_counts = {}
        for _i, tags, _e in hits:
            for t in tags:
                if t != sig:
                    tag_counts[t] = tag_counts.get(t, 0) + 1
        suspect, code = (CODE.get(title) or {}).get(sig) or ('unclassified', [])
        recent = [t['episodes_per_round'] for t in turns[-2:]]
        earlier = [t['episodes_per_round'] for t in turns[:-2]]
        rate = lambda v: sum(v) / len(v) if v else 0.0
        trend = ('new' if not earlier else 'rising' if rate(recent) > 1.2 * rate(earlier)
                 else 'falling' if rate(recent) < 0.8 * rate(earlier) else 'flat')
        tot = totals.get(gid) or {}
        out[(gid, sig)] = {
            'id': cluster_id(gid, sig), 'game_id': gid, 'title': title, 'game': TITLE_NAMES.get(title, title or gid),
            'signature': sig, 'label': LABELS[sig], 'rule': RULES[sig], 'hits': len(hits),
            'episodes': sum(t['episodes'] for t in turns), 'deaths': len(deaths),
            'hp_lost': sum(i.get('loss') or 0 for i, _t, _e in hits),
            'share_of_hits': round(len(hits) / max(1, tot.get('hits') or 1), 3),
            'share_of_hp': round(sum(i.get('loss') or 0 for i, _t, _e in hits) / max(1, tot.get('hp_lost') or 1), 3),
            'share_of_deaths': round(len(deaths) / max(1, tot.get('deaths') or 1), 3),
            'first_at': stamps[0] if stamps else None, 'last_at': stamps[-1] if stamps else None,
            'runs': sorted(str(r) for r in runs), 'turns': turns[-12:], 'per_hour': hours, 'trend': trend,
            'examples': examples(hits, deaths),
            'co_tags': sorted(([LABELS[t], n] for t, n in tag_counts.items()), key=lambda x: -x[1])[:4],
            'top_fields': {'decision': _top(i.get('decision') for i, _t, _e in hits),
                           'held': _top(','.join(i.get('held') or []) or 'none' for i, _t, _e in hits),
                           'within_2m': _top(i.get('near_2m') for i, _t, _e in hits),
                           'nearest_class': _top(((i.get('near') or [{}])[0] or {}).get('cls') for i, _t, _e in hits),
                           'action': _top(i.get('action') or i.get('motion') for i, _t, _e in hits)},
            'suspect': suspect, 'code': [{'file': f, 'function': fn} for f, fn in code],
            '_stamps': stamps,
        }
    return out, totals


# --- storage ------------------------------------------------------------------------------------------------------------

def record_event(store, row, event):
    """At ingest (gbox.player_damage.ingest): one incident per ledger row of an RE game. Never raises."""
    try:
        gid = row.get('game_id')
        if title_of(gid) is None or store.get(INCIDENT, row['id']):
            return None
        inc = features(event, gid)
        inc.update(id=row['id'], session_id=row.get('session_id'), run_id=row.get('run_id'),
                   round_id=row.get('round_id'), observed_at=row.get('observed_at'))
        store.put(INCIDENT, row['id'], inc)
        return inc
    except Exception:          # noqa: BLE001 - the receipt is durable; the backfill classifies it later
        return None


def _rows(store, sql, args=()):
    """A read on the store's lock-free read connections (a thread holding the lock reads its own writes)."""
    with store.reading() as db:
        return db.execute(sql, args).fetchall()


FIELDS = ('id', 'event_id', 'run_id', 'round_id', 'session_id', 'game_id', 'observed_at', 'receipt', 'hp_before',
          'hp_after', 'loss')


def _ledger_rows(store, where, args, tail=''):
    """Ledger rows without an incident yet, just the fields the backfill reads (not their evidence lists)."""
    cols = ', '.join(f"json_extract(d.body,'$.{f}')" for f in FIELDS)
    found = _rows(store, f"SELECT {cols} FROM docs d LEFT JOIN docs i ON i.kind=? AND i.id=d.id "
                  f"WHERE d.kind=? AND i.id IS NULL AND {where} {tail}", (INCIDENT, LEDGER, *args))
    return [dict(zip(FIELDS, row)) for row in found]


def _in(values):
    return ','.join('?' * len(values))


def _chunks(values, n=400):
    values = sorted(values)
    return [values[i:i + n] for i in range(0, len(values), n)]


def run_counts(store, kind, runs):
    """{run_id: (documents of `kind`, earliest observed_at)} for these runs, one scan per chunk of runs."""
    out = {}
    for part in _chunks(runs):
        for run, n, first in _rows(store, "SELECT json_extract(body,'$.run_id'), COUNT(*), "
                                   "MIN(json_extract(body,'$.observed_at')) FROM docs WHERE kind=? "
                                   f"AND json_extract(body,'$.run_id') IN ({_in(part)}) GROUP BY 1", (kind, *part)):
            out[run] = (n, first)
    return out


class Clusters:
    """The background pass: backfill incidents, cluster, keep one batch request per cluster, link singles."""

    def __init__(self, store, data_dir=None, *, now=time.time, priority=None):
        self.store, self.now = store, now
        self.root = Path(data_dir) if data_dir else None
        self.priority = priority          # callable(list of open batch request ids, closed ids) -> None, or None
        self.last = None

    # backfill ---------------------------------------------------------------------------------------------------------
    def open_singles(self):
        out = []
        for (body,) in _rows(self.store, "SELECT body FROM docs WHERE kind='request' "
                             "AND json_extract(body,'$.source')='player_damage' "
                             "AND json_extract(body,'$.status') IN ('open','in_progress')"):
            req = json.loads(body)
            if title_of((req.get('context') or {}).get('game_id')):
                out.append(req)
        return out

    def backfill(self, singles, limit=BACKFILL_PER_PASS):
        """Read back receipts of ledger rows without an incident: the window first (newest first), then the newest
        BACKLOG_PER_RUN of each open single's run. Returns the number recorded."""
        start = self.now() - WINDOW_S
        games = tuple(GAMES)
        rows = _ledger_rows(self.store, f"json_extract(d.body,'$.game_id') IN ({_in(games)}) "
                            "AND json_extract(d.body,'$.observed_at')>=? "
                            "ORDER BY json_extract(d.body,'$.observed_at') DESC LIMIT ?", (*games, start, limit))
        runs = {(s.get('context') or {}).get('damage_run_id') for s in singles} - {None}
        if runs and len(rows) < limit:
            have = run_counts(self.store, INCIDENT, runs)
            want = [r for r in runs if (have.get(r) or (0, None))[0] < BACKLOG_PER_RUN]
            for part in _chunks(want):
                found = _ledger_rows(self.store, f"json_extract(d.body,'$.run_id') IN ({_in(part)}) "
                                     "AND json_extract(d.body,'$.observed_at')<?", (*part, start))
                by_run = {}
                for row in sorted(found, key=lambda r: -(r.get('observed_at') or 0)):
                    by_run.setdefault(row['run_id'], []).append(row)
                for run, items in sorted(by_run.items()):
                    rows += items[:max(0, BACKLOG_PER_RUN - (have.get(run) or (0, None))[0])]
        done = 0
        for row in rows[:limit]:
            if title_of(row.get('game_id')) is None:
                continue
            try:
                event = json.loads(self.store.read_artifact(row['receipt']))['event']
                error = None
            except Exception as exc:  # noqa: BLE001 - an unreadable receipt is still an incident ("other")
                event = {k: row.get(k) for k in ('event_id', 'hp_before', 'hp_after', 'loss', 'observed_at')}
                event['title'] = title_of(row.get('game_id'))
                error = type(exc).__name__
            inc = record_event(self.store, row, event)
            if inc is not None:
                if error:
                    self.store.put(INCIDENT, row['id'], dict(inc, receipt_error=error))
                done += 1
        return done

    # clustering -------------------------------------------------------------------------------------------------------
    def incidents(self, singles=(), game=None):
        """The window's incidents, and those of the open singles' runs from before it."""
        start = self.now() - WINDOW_S
        args, extra = [INCIDENT, start], ''
        if game:
            extra, args = " AND json_extract(body,'$.game_id')=?", args + [game]
        found = [json.loads(b) for (b,) in _rows(self.store, "SELECT body FROM docs WHERE kind=? "
                 "AND json_extract(body,'$.observed_at')>=?" + extra, tuple(args))]
        runs = {(s.get('context') or {}).get('damage_run_id') for s in singles} - {None}
        for part in _chunks(runs):
            for (b,) in _rows(self.store, "SELECT body FROM docs WHERE kind=? AND json_extract(body,'$.observed_at')<? "
                              f"AND json_extract(body,'$.run_id') IN ({_in(part)})", (INCIDENT, start, *part)):
                inc = json.loads(b)
                if not game or inc.get('game_id') == game:
                    found.append(inc)
        return found

    def fault_examples(self, title):
        """The RE5 Switch driver's ex_<fault> lines of rounds in the window (its Notebook): readable examples of the
        aim faults, attached to the clusters they explain."""
        if not self.root:
            return {}
        path = self.root / 'mercs/curriculum' / title / 'rounds.sqlite'
        if not path.is_file():
            return {}
        out = {}
        try:
            with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
                rows = db.execute('SELECT id, data FROM rounds WHERE ts>=? ORDER BY ts DESC LIMIT 200',
                                  (self.now() - WINDOW_S,)).fetchall()
        except sqlite3.Error:
            return {}
        for rid, data in rows:
            try:
                observed = json.loads(data)
            except ValueError:
                continue
            for kind, sig in EX_KINDS.items():
                line = observed.get('ex_' + kind)
                if isinstance(line, str) and line and len(out.setdefault(sig, [])) < 4:
                    out[sig].append({'round_id': rid, 'fault': kind, 'examples': line[:600]})
        return out

    def poll(self):
        singles = self.open_singles()
        backfilled = self.backfill(singles)
        clusters, totals = summarize(self.incidents(singles), now=self.now())
        faults = {}
        for gid, sig in clusters:
            title = title_of(gid)
            if title not in faults:
                faults[title] = self.fault_examples(title)
            if faults[title].get(sig):
                clusters[(gid, sig)]['fault_examples'] = faults[title][sig]
        batches = {}
        for key, c in clusters.items():
            doc = self.upsert(c, totals.get(c['game_id']) or {})
            if doc.get('request_id'):
                batches[c['id']] = doc
        linked = self.link_singles(singles, clusters, batches)
        self.sync_priority()
        self.last = {'at': self.now(), 'backfilled': backfilled, 'clusters': len(clusters), 'batches': len(batches),
                     'singles_closed': linked, 'totals': totals}
        self.store.put(STATE, 'pass', self.last)
        return self.last

    def upsert(self, c, total):
        """The cluster document, and its batch request once it has MIN_BATCH episodes + deaths."""
        now = self.now()
        stamps = c.get('_stamps') or []
        old = self.store.get(CLUSTER, c['id']) or {}
        doc = {**old, **{k: v for k, v in c.items() if not k.startswith('_')}, 'updated': now,
               'window_s': WINDOW_S, 'game_totals': total}
        doc.setdefault('created', now)
        doc['members'] = old.get('members') or []
        if c['episodes'] + c['deaths'] < MIN_BATCH and not old.get('request_id'):
            self.store.put(CLUSTER, c['id'], doc)
            return doc
        rid = old.get('request_id') or request_id_for(c['id'])
        if self.store.get('request', rid) is None:
            req = self._create_request(doc, rid, now)
            doc['summary_at'] = now
        else:
            with self.store.lock:                          # read-modify-write: Hermes may be updating it via the API
                req = self.store.get('request', rid)
                if (req.get('context') or {}).get('damage_cluster_id') != c['id']:
                    raise ValueError('Deterministic damage batch request identity collision; existing request kept')
                changed = False
                if req.get('status') == 'done':
                    since = (req.get('completed') or now) + REOPEN_GRACE_S
                    after = sum(1 for at in stamps if at >= since)
                    if after >= REOPEN_MIN:
                        req.update(status='open', completed=None)
                        req.setdefault('messages', []).append({'author': 'agent', 'ts': now,
                            'id': f'reopen-{int(now)}', 'attachments': [],
                            'text': f'Reopened: {after} more incidents of this cause {REOPEN_GRACE_S // 3600} h or '
                                    'more after it was closed. The change did not remove it yet (or is not deployed): '
                                    'start from the newest examples and the trend per turn.'})
                        doc['reopened'] = (old.get('reopened') or 0) + 1
                        old['summary_at'] = 0
                        changed = True
                if now - (old.get('summary_at') or 0) >= UPDATE_S:
                    self._refresh(req, doc, now)
                    doc['summary_at'] = now
                    changed = True
                if changed:
                    self.store.put('request', rid, req)
        doc.update(request_id=rid, number=req.get('number'), status=req.get('status'))
        self.store.put(CLUSTER, c['id'], doc)
        return doc

    def _create_request(self, doc, rid, now):
        body = render(doc)
        with self.store.lock:
            self.store.db.execute('BEGIN IMMEDIATE')
            try:
                row = self.store.db.execute("SELECT body FROM docs WHERE kind='request' AND id=?", (rid,)).fetchone()
                if row:
                    self.store.db.rollback()
                    return json.loads(row[0])
                number = self.store.db.execute("SELECT COALESCE(MAX(CAST(json_extract(body,'$.number') AS INT)),0)+1 "
                                               "FROM docs WHERE kind='request'").fetchone()[0]
                req = {'id': rid, 'number': number, 'title': title_line(doc), 'body': body,
                       'source': SOURCE, 'kind': 'report', 'author': 'agent', 'automated': True,
                       'context': {'auto_report': True, 'operator_requested': True, 'damage_cluster': True,
                                   'damage_cluster_id': doc['id'], 'signature': doc['signature'],
                                   'game_id': doc['game_id'], 'title': doc.get('title'),
                                   'preferred_inference_node': TARGET, 'hermes_size': 'large'},
                       'status': 'open', 'created': now, 'started': None, 'completed': None,
                       'parent_request_id': None, 'image': None, 'element': None,
                       'messages': [{'author': 'agent', 'text': body, 'ts': now, 'attachments': []}],
                       'metrics': {'tokens_in': 0, 'tokens_out': 0, 'tools': {}, 'files_changed': [],
                                   'duration_s': None, 'turns': 0}}
                self.store.db.execute('INSERT INTO docs VALUES(?,?,?)', ('request', rid, json.dumps(req)))
                try:
                    from ..store import append_audit
                    append_audit(self.store.db, 'gbox-mercs-damage', 'mercs.damage_cluster.batched', doc['id'],
                                 {'request_id': rid, 'game_id': doc['game_id'], 'signature': doc['signature'],
                                  'hits': doc['hits'], 'deaths': doc['deaths']}, ts=now)
                except ImportError:
                    pass
                self.store.db.commit()
                return req
            except BaseException:
                self.store.db.rollback()
                raise

    def _refresh(self, req, doc, now):
        """The batch request in place: its body is the current window; one summary message is replaced, not added."""
        body = render(doc)
        req['body'] = body
        req['title'] = title_line(doc)
        summary = {'id': 'damage-cluster-summary', 'author': 'agent', 'ts': now, 'attachments': [],
                   'text': f"Window update: {doc['hits']} hits, {doc['deaths']} deaths in the last "
                           f"{WINDOW_S // 3600} h (trend {doc['trend']}); {len(doc.get('members') or [])} single "
                           'reports batched. The request body holds the current examples.',
                   'damage_cluster': {k: doc.get(k) for k in ('id', 'hits', 'deaths', 'hp_lost', 'trend',
                                                              'first_at', 'last_at')}}
        req['messages'] = [m for m in req.get('messages') or [] if m.get('id') != summary['id']] + [summary]

    def link_singles(self, singles, clusters, batches):
        """Close the per-run damage requests whose classified events all sit in batched clusters."""
        by_run = {}
        for (gid, sig), c in clusters.items():
            for run in c['runs']:
                by_run.setdefault(run, {})[c['id']] = c
        start, closed, now = self.now() - WINDOW_S, 0, self.now()
        runs = {(r.get('context') or {}).get('damage_run_id') for r in singles} - {None}
        totals, classified = run_counts(self.store, LEDGER, runs), run_counts(self.store, INCIDENT, runs)
        for req in singles:
            ctx = req.get('context') or {}
            run = ctx.get('damage_run_id')
            members = by_run.get(run) or {}
            covered = [c for cid, c in members.items() if cid in batches]
            if not covered:
                continue                                    # its causes are not batched yet
            if req.get('status') == 'in_progress' and now - (req.get('started') or req.get('created') or 0) < 7200:
                continue                                    # a Hermes run on it right now: leave it to finish
            total, first = totals.get(run) or (0, None)
            have = (classified.get(run) or (0, None))[0]
            old_run = (first or now) < start
            if not total or have < (min(total, BACKLOG_PER_RUN) if old_run else total):
                continue                                    # not every event classified yet
            parts = sorted(covered, key=lambda c: ORDER.index(c['signature']))
            refs = [(batches[c['id']], c) for c in parts]
            small = [c['label'] for cid, c in members.items() if cid not in batches]
            text = ('Batched into ' + ', '.join(f"#{b.get('number')} ({c['label']})" for b, c in refs)
                    + f": this autoplay run's damage events (game {TITLE_NAMES.get(title_of(ctx.get('game_id')), '')})"
                    ' are members of those cause batches, which carry the fix (one logic change per cause). '
                    'Closed as batched, not deleted; the full ledger stays at '
                    f"/api/sessions/{ctx.get('session_id')}/damage/runs/{run}"
                    + (f' ({have} of {total} events classified: the newest of a run older than the window)'
                       if old_run and have < total else '') + '.'
                    + (' Causes too small to batch yet (GET /api/mercs/damage-clusters lists them): '
                       + ', '.join(small) + '.' if small else ''))
            with self.store.lock:
                current = self.store.get('request', req['id'])
                if not current or current.get('status') not in ('open', 'in_progress'):
                    continue
                current.setdefault('context', {}).update(batched_into=[b['request_id'] for b, _c in refs],
                    batched_numbers=[b.get('number') for b, _c in refs], batched_at=now)
                current.update(status='done', completed=now)
                current['messages'] = [m for m in current.get('messages') or [] if m.get('id') != 'damage-batched'] \
                    + [{'id': 'damage-batched', 'author': 'agent', 'ts': now, 'text': text, 'attachments': []}]
                self.store.put('request', req['id'], current)
            for b, c in refs:
                doc = self.store.get(CLUSTER, c['id']) or {}
                members_now = doc.get('members') or []
                if req['id'] not in members_now:
                    doc['members'] = (members_now + [req['id']])[-2000:]
                    self.store.put(CLUSTER, c['id'], doc)
            closed += 1
        return closed

    def sync_priority(self):
        """The PRIORITY_TOP open batches of each game (most deaths, then HP lost) on the Hermes priority list, after
        the operator's own entries; the rest and closed ones off it. Every open batch stays a verified RE report that
        sparkDeux takes first (gbox.hermes_work_queue.re_report); the list only orders them."""
        if self.priority is None:
            return
        ranked, shut = {}, []
        for (body,) in _rows(self.store, "SELECT body FROM docs WHERE kind=?", (CLUSTER,)):
            doc = json.loads(body)
            if not doc.get('request_id'):
                continue
            req = self.store.get('request', doc['request_id']) or {}
            if req.get('status') in ('open', 'in_progress'):
                ranked.setdefault(doc.get('game_id'), []).append(doc)
            else:
                shut.append(doc['request_id'])
        open_ids = []
        for docs in ranked.values():
            docs.sort(key=lambda d: (-(d.get('deaths') or 0), -(d.get('hp_lost') or 0), d['request_id']))
            open_ids += [d['request_id'] for d in docs[:PRIORITY_TOP]]
            shut += [d['request_id'] for d in docs[PRIORITY_TOP:]]
        state = self.store.get(STATE, 'priority') or {}
        if open_ids == state.get('open') and sorted(shut) == state.get('shut'):
            return
        try:
            self.priority(open_ids, shut)
        except Exception as exc:  # noqa: BLE001 - the queue lock is busy: the next pass tries again
            self.store.put(STATE, 'priority', {**state, 'error': f'{type(exc).__name__}: {exc}'[:200]})
            return
        self.store.put(STATE, 'priority', {'open': open_ids, 'shut': sorted(shut), 'at': self.now()})

    def listing(self, game=None, *, window_h=None, top=20):
        """GET /api/mercs/damage-clusters: computed from the incidents now (the batch requests are the pass's)."""
        window = WINDOW_S if not window_h else max(1, min(168, int(window_h))) * 3600
        gid = resolve_game(game)
        start = self.now() - window
        args, extra = [INCIDENT, start], ''
        if gid:
            extra, args = " AND json_extract(body,'$.game_id')=?", args + [gid]
        found = [json.loads(b) for (b,) in _rows(self.store, "SELECT body FROM docs WHERE kind=? "
                 "AND json_extract(body,'$.observed_at')>=?" + extra, tuple(args))]
        clusters, totals = summarize(found, now=self.now(), window_s=window)
        rows = []
        for c in clusters.values():
            doc = self.store.get(CLUSTER, c['id']) or {}
            c.pop('_stamps', None)
            c.update(request_id=doc.get('request_id'), number=doc.get('number'),
                     status=(self.store.get('request', doc['request_id']) or {}).get('status')
                     if doc.get('request_id') else None, members=len(doc.get('members') or []))
            rows.append(c)
        rows.sort(key=lambda c: (-c['deaths'], -c['hp_lost'], c['signature']))
        top_n = rows[:max(1, min(100, int(top)))]
        return {'window_s': window, 'generated_at': self.now(), 'game': gid, 'totals': totals,
                'what_kills_him': [f"{c['game']}: {c['label']} - {c['deaths']} deaths, {c['episodes']} episodes, "
                                   f"{c['hp_lost']} HP"
                                   + (f" (#{c['number']})" if c.get('number') else '') for c in top_n[:10]],
                'clusters': top_n, 'last_pass': self.store.get(STATE, 'pass')}


def resolve_game(game):
    """A game id, a title id or a short name (re5, re6, re5-switch, re5-ps3, re4) -> game id, or None for all."""
    if not game:
        return None
    g = str(game).strip().lower()
    if g in GAMES:
        return g
    names = {'re5': '52d15709be0fda1a', 're5-switch': '52d15709be0fda1a', 're6': '115f9cdbba115432',
             're6-switch': '115f9cdbba115432', 're5-ps3': 'e7ca89bbeb67360d', 're4': '78ab9efa2e310db4'}
    if g in names:
        return names[g]
    for gid, title in GAMES.items():
        if title.lower() == g:
            return gid
    return g if re.fullmatch(r'[a-f0-9]{16}', g) else None


def title_line(doc):
    return f"Damage batch: {doc['game']} - {doc['label']}"[:140]


def render(doc):
    """The batch request body: what Hermes reads (and the operator in the inbox)."""
    lines = [
        f"Batched damage incidents of {doc['game']} (game {doc['game_id']}), cause: {doc['label']}.",
        f"Rule (gbox/mercs/damage_clusters.py, deterministic): {doc['rule']}.",
        f"Last {WINDOW_S // 3600} h: {doc['deaths']} deaths ({doc['share_of_deaths']:.0%} of this game's deaths), "
        f"{doc['episodes']} episodes / {doc['hits']} HP-loss samples ({doc['share_of_hits']:.0%} of its samples), "
        f"{doc['hp_lost']} HP lost ({doc['share_of_hp']:.0%} of its HP lost), "
        f"from {_clock(doc.get('first_at'))} to {_clock(doc.get('last_at'))}, over {len(doc.get('runs') or [])} "
        f"autoplay runs (turns); trend {doc['trend']}. {len(doc.get('members') or [])} single damage reports are "
        "batched here (closed as members, ledgers kept).",
        'Trend per turn (run start: rounds, episodes, episodes per round, deaths): ' + '; '.join(
            f"{_clock(t.get('start'))}: {t.get('rounds')} rounds, {t['episodes']} ep, {t['episodes_per_round']}/round, "
            f"{t['deaths']} deaths"
            for t in (doc.get('turns') or [])[-8:]) + '.',
        f"Suspected bot decision: {doc['suspect']}.",
        'Code it implicates: ' + '; '.join(f"{c['file']} {c['function']}" for c in doc.get('code') or []) + '.',
    ]
    if doc.get('co_tags'):
        lines.append('Also true of these hits: ' + ', '.join(f'{t} ({n})' for t, n in doc['co_tags']) + '.')
    fields = doc.get('top_fields') or {}
    lines.append('Top fields at the hit: ' + '; '.join(f"{k} " + ', '.join(f'{v} ({n})' for v, n in vals)
                                                     for k, vals in fields.items() if vals) + '.')
    lines.append('Representative examples (fields recorded at the hit; frames, map and snapshot in each ledger):')
    for n, ex in enumerate(doc.get('examples') or [], 1):
        lines.append(f'{n}. ' + json.dumps(ex, sort_keys=True, separators=(',', ':'))[:700])
    for fault in doc.get('fault_examples') or []:
        lines.append(f"Driver fault examples ex_{fault['fault']} (round {fault['round_id'][:12]}): {fault['examples']}")
    lines.append(
        'Task: propose ONE logic change in the implicated bot code that would prevent the most incidents of this '
        'cluster (not one per example), with focused unit tests built from the example fields above, and publish it '
        "as a draft PR from this request's worktree. One change per batch; no unrelated fixes. Do not launch games, "
        'send input, or stop, restart or reset MercMode sessions or gBox; the live bots measure the change after a '
        f"deploy: GET /api/mercs/damage-clusters?game={doc['game_id']} lists this cluster's hits per turn. Post the "
        'PR link and the effect you expect on this request, then mark it done. This batch updates in place as the '
        f'window rolls and reopens itself if the cause keeps coming {REOPEN_GRACE_S // 3600} h after it closed.')
    return '\n'.join(lines)


def _clock(at):
    return time.strftime('%m-%d %H:%M', time.localtime(at)) if _num(at) and at > 0 else '?'


def queue_priority(open_ids, shut):
    """Put open batch requests on the Hermes work queue's priority list after the operator's own entries, and take
    closed ones off. Raises OSError while the queue pump holds its lock (the next pass retries)."""
    from .. import hermes_delivery, hermes_work_queue
    with hermes_delivery.locked('work-queue'):
        current = hermes_work_queue.get_priority()
        kept = [x for x in current if x not in set(shut)]
        kept += [x for x in open_ids if x not in kept]
        if kept != current:
            hermes_work_queue.set_priority(kept)


def install(app, store, config, auth, runner=None):
    """The background pass and the read endpoints."""
    from fastapi import Depends, HTTPException
    runner = runner or Clusters(store, config.data_dir, priority=queue_priority)
    stopped = threading.Event()
    thread = None

    def run():
        stopped.wait(20.0)                        # after startup's own work
        while not stopped.is_set():
            try:
                runner.poll()
            except Exception as exc:  # noqa: BLE001
                store.put(STATE, 'health', {'at': time.time(), 'error': f'{type(exc).__name__}: {exc}'[:300]})
            stopped.wait(PASS_S)

    def start():
        nonlocal thread
        thread = threading.Thread(target=run, name='mercs-damage-clusters', daemon=True)
        thread.start()

    def close():
        stopped.set()
        if thread:
            thread.join(3.0)

    app.on_event('startup')(start)
    app.on_event('shutdown')(close)

    @app.get('/api/mercs/damage-clusters')
    def listing(game: str = '', window_h: int = 0, top: int = 20, actor=Depends(auth)):
        return runner.listing(game or None, window_h=window_h or None, top=top)

    @app.get('/api/mercs/damage-clusters/{cid}')
    def one(cid: str, actor=Depends(auth)):
        doc = store.get(CLUSTER, cid)
        if doc is None:
            raise HTTPException(404, 'Unknown damage cluster')
        return doc

    return runner
