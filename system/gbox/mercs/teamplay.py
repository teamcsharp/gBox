"""Exact-session team/training intent; runtime evidence never authorizes P1 fallback.

Saving choices changes no gameplay modifiers or controller input. Runtime consumers
must check effective_role/control_player on each transition and revalidate routes.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid

RE5 = 'e7ca89bbeb67360d'
RE6 = '0871eee3b68cdea3'
# Split screen on Switch (docs/research/switch-coop-bot.md): RE5 / RE6 in Citron or Eden, Player 2 a keyboard pad of its
# own (gbox.switch_coop), both players' own RAM (gbox.mercs.titles.switch_team). bots_p1_p2 is Switch only.
RE5_SWITCH, RE6_SWITCH = '52d15709be0fda1a', '115f9cdbba115432'
SWITCH = (RE5_SWITCH, RE6_SWITCH)
SWITCH_ADAPTERS = ('citron', 'eden')
SWITCH_MAPS = {RE5_SWITCH: '010018100CD46000', RE6_SWITCH: '01002A000CD48000'}
GAMES = (RE5, RE6, *SWITCH)
ROLES = ('solo_p1', 'teammate_p2', 'observe_human', 'bots_p1_p2')
HUMAN_ROLES = ('teammate_p2', 'observe_human')   # Player 1 is the human's: no pad takeover, no menus walk, no resets
PROFILES = ('assisted', 'unmodified_evaluation')
DEFAULT = {'role': 'solo_p1', 'training_profile': 'assisted', 'auto_reduce_mods': False,
           'assist_style': 'follow_protect', 'selected_route_id': None}
_LOCK = threading.RLock()
_EVIDENCE = {}
_EVIDENCE_TTL = 5.


def _sid(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', value):
        raise ValueError('An exact session ID is required')
    return value


def normalize(value):
    if not isinstance(value, dict) or set(value) - DEFAULT.keys():
        raise ValueError('Unknown team/training setting')
    out = {**DEFAULT, **value}
    if out['role'] not in ROLES or out['training_profile'] not in PROFILES:
        raise ValueError('Unsupported team role or training profile')
    if type(out['auto_reduce_mods']) is not bool or out['assist_style'] != 'follow_protect':
        raise ValueError('Expected explicit adaptive-training opt-in and follow/protect behavior')
    route = out['selected_route_id']
    if route is not None and (not isinstance(route, str) or not re.fullmatch('[a-f0-9]{32}', route)):
        raise ValueError('Select an adopted demonstration from the run reviewer')
    return out


def publish_runtime(session_id, adapter, evidence, *, now=None):
    """Worker-only bridge: native actor/controller proof belongs to the runtime.

    No client-supplied fields or prior session's evidence may enter this bridge.
    Fresh evidence expires; a session replacement must publish its own proof.
    """
    sid = _sid(session_id)
    if not isinstance(evidence, dict):
        raise ValueError('Native runtime evidence must be an object')
    fields = ('p2_verified', 'controller2_verified', 'p2_actor_verified', 'controller2_prepared',
              'camera2_verified', 'prompt2_verified', 'human_observer_verified',
              'unmodified_verified', 'improvement_verified')
    clean = {key: evidence.get(key) is True for key in fields}
    clean['reason'] = str(evidence.get('reason') or '')[:400]
    players = evidence.get('active_players')
    clean['active_players'] = []
    if isinstance(players, list):
        for player in players[:2]:
            if isinstance(player, dict) and type(player.get('slot')) is int and player['slot'] in (1, 2):
                clean['active_players'].append({key: player.get(key) for key in
                    ('slot', 'id', 'control', 'actor', 'provenance') if key in player})
    with _LOCK:
        stamp = time.monotonic() if now is None else now
        for key in list(_EVIDENCE):
            if stamp - _EVIDENCE[key][2] > _EVIDENCE_TTL:
                _EVIDENCE.pop(key, None)
        if len(_EVIDENCE) >= 256 and sid not in _EVIDENCE:
            _EVIDENCE.pop(next(iter(_EVIDENCE)))
        _EVIDENCE[sid] = (adapter, clean, stamp)


def runtime_evidence(session_id, adapter, *, now=None):
    stamp = time.monotonic() if now is None else now
    with _LOCK:
        row = _EVIDENCE.get(_sid(session_id))
        if row is None or row[0] is not adapter or not 0 <= stamp-row[2] <= _EVIDENCE_TTL:
            return {}
        return deepcopy(row[1])


class TeamStore:
    def __init__(self, data_dir):
        self.root = Path(data_dir) / 'mercs' / 'teamplay'

    def _path(self, session_id):
        return self.root / (hashlib.sha256(_sid(session_id).encode()).hexdigest()+'.json')

    def get(self, session_id):
        path = self._path(session_id)
        with _LOCK:
            if not path.exists():
                return dict(DEFAULT)
            if path.stat().st_size > 8192:
                raise ValueError('Team/training configuration exceeds its size limit')
            row = json.loads(path.read_text(encoding='utf-8'))
            if row.get('session_id') != session_id or row.get('version') != 1:
                raise ValueError('Team/training configuration belongs to a different session')
            return normalize(row.get('config'))

    def configure(self, session_id, patch, *, game_id, route_lookup=None):
        """Persist only operator intent. Never writes RAM, pads or modifier state."""
        if game_id not in GAMES:
            raise ValueError('Team/training controls currently cover Resident Evil 5 and 6')
        with _LOCK:
            merged = normalize({**self.get(session_id), **patch})
            if merged['role'] == 'bots_p1_p2' and game_id not in SWITCH:
                raise ValueError('Bots on both players is split screen on Resident Evil 5 / 6 for Switch')
            route_id = merged['selected_route_id']
            if route_id and 'selected_route_id' in patch:
                route = route_lookup(route_id) if route_lookup else None
                source = route.get('source') if isinstance(route, dict) else None
                if not isinstance(route, dict) or route.get('kind') != 'recorded_demonstration' \
                        or route.get('adopted') is not True or route.get('bot_eligible') is not True \
                        or route.get('title') != {RE5: 'BLUS30491', RE6: 'BH6', **SWITCH_MAPS}[game_id] \
                        or not isinstance(source, dict) or source.get('control') != 'human' \
                        or not isinstance(route.get('mode'), str) or not 1 <= len(route['mode']) <= 64 \
                        or not isinstance(route.get('geometry'), str) or not 1 <= len(route['geometry']) <= 256 \
                        or source.get('mode') != route['mode'] or source.get('geometry') != route['geometry'] \
                        or source.get('title') != route['title']:
                    raise ValueError('The selected route is not an adopted, validated human demonstration for this title')
            target = self._path(session_id)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name+'.'+uuid.uuid4().hex+'.partial')
            try:
                with temporary.open('x', encoding='utf-8') as handle:
                    json.dump({'version': 1, 'session_id': session_id, 'config': merged}, handle, allow_nan=False)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            return deepcopy(merged)

    def status(self, session_id, *, game_id, adapter, now=None, config=None):
        config = normalize(config) if config is not None else self.get(session_id)
        if game_id in SWITCH:
            return switch_status(config, runtime_evidence(session_id, adapter, now=now), adapter)
        evidence = runtime_evidence(session_id, adapter, now=now)
        is_re5 = game_id == RE5 and getattr(adapter, 'name', None) == 'rpcs3'
        players = evidence.get('active_players', [])
        actors = [p.get('actor') for p in players]
        verified_p2 = is_re5 and all(evidence.get(key) is True for key in
            ('p2_verified', 'p2_actor_verified', 'controller2_verified', 'camera2_verified', 'prompt2_verified')) \
            and len(players) == 2 and {p.get('slot') for p in players} == {1, 2} \
            and all(type(actor) is int and actor > 0 for actor in actors) and len(set(actors)) == 2 \
            and all(p.get('id') == f"p{p['slot']}"
                and isinstance(p.get('provenance'), dict)
                and p['provenance'].get('native_actor_verified') is True for p in players)
        reason = ('RE6 local Player 2 control and actor ownership are not verified in this runtime.' if game_id == RE6
                  else evidence.get('reason') or 'Waiting for verified local Player 2 actor and a separate controller input path.')
        role, player, phase = config['role'], 1, 'active'
        if role == 'teammate_p2':
            player, phase = (2, 'active') if verified_p2 else (None, 'waiting_p2')
        elif role == 'observe_human':
            player, phase = None, 'observing' if evidence.get('human_observer_verified') else 'observing_unverified'
        elif not is_re5:
            player, phase = None, 'unsupported'
        evaluation = config['training_profile'] == 'unmodified_evaluation'
        clean = is_re5 and evidence.get('unmodified_verified') is True
        if evaluation and not clean:
            player, phase = None, 'waiting_evaluation'
        return {'config': config, 'effective_role': role if phase == 'active' else phase,
                'control_player': player, 'phase': phase,
                'effective_training_profile': 'unmodified_evaluation' if evaluation and clean else 'assisted',
                'evaluation_pending': evaluation and not clean,
                'modifiers_changed': False, 'adaptive_reduction_ready': config['auto_reduce_mods'] and evidence.get('improvement_verified') is True,
                'capabilities': {'solo_p1': {'available': is_re5, 'reason': '' if is_re5 else 'RE6 autoplay ownership is not verified.'},
                    'teammate_p2': {'available': verified_p2, 'reason': '' if verified_p2 else reason},
                    'observe_human': {'available': is_re5, 'verified': evidence.get('human_observer_verified') is True,
                                      'reason': 'Input observation must verify human P1 ownership before labeling a demonstration.'},
                    'unmodified_evaluation': {'available': clean, 'reason': '' if clean else 'Requires verified original gameplay settings at a round boundary; current modifiers are kept.'}},
                'runtime': evidence}


def _verified_pair(evidence) -> bool:
    """Both players' native actors (slots 1 and 2, distinct, each read with its own index byte) and Player 2's pad,
    camera and prompts proved fresh by the worker (gbox.mercs.titles.switch_team.CoopDriver.readiness)."""
    players = evidence.get('active_players', [])
    actors = [p.get('actor') for p in players]
    return all(evidence.get(key) is True for key in
               ('p2_verified', 'p2_actor_verified', 'controller2_verified', 'camera2_verified', 'prompt2_verified')) \
        and len(players) == 2 and {p.get('slot') for p in players} == {1, 2} \
        and all(type(actor) is int and actor > 0 for actor in actors) and len(set(actors)) == 2 \
        and all(p.get('id') == f"p{p['slot']}" and isinstance(p.get('provenance'), dict)
                and p['provenance'].get('native_actor_verified') is True for p in players)


def switch_status(config, evidence, adapter) -> dict:
    """Split screen on RE5 / RE6 Switch. teammate_p2: the bot plays Player 2 once Player 2's actor and pad are proved;
    bots_p1_p2: the bot plays Player 1 at once (a bot's own player) and Player 2 too once proved; observe_human: no
    input. Live modifiers stay with the assisted profile (the team driver gives them to one player, the bot's);
    unmodified evaluation waits, as on PS3, because nothing proves original rules here yet."""
    switch = getattr(adapter, 'name', None) in SWITCH_ADAPTERS
    pair = switch and _verified_pair(evidence)
    p1_present = any(p.get('slot') == 1 for p in evidence.get('active_players', []))
    reason = evidence.get('reason') or 'Waiting for Player 2 in split screen with this launch\'s Player 2 pad.'
    role, player, partner, phase = config['role'], 1, None, 'active'
    if not switch:
        player, phase = None, 'unsupported'
    elif role == 'teammate_p2':
        player, phase = (2, 'active') if pair else (None, 'waiting_p2')
    elif role == 'bots_p1_p2':
        player, partner = 1, (2 if pair else None)
        phase = 'active' if pair else 'active_p1_waiting_p2' if p1_present else 'waiting_p2'
    elif role == 'observe_human':
        player, phase = None, 'observing' if evidence.get('human_observer_verified') else 'observing_unverified'
    evaluation = config['training_profile'] == 'unmodified_evaluation'
    if evaluation:
        player, partner, phase = None, None, 'waiting_evaluation'
    unavailable = '' if switch else 'Split screen needs this session in Citron or Eden.'
    return {'config': config, 'effective_role': role if phase.startswith('active') else phase,
            'control_player': player, 'partner_player': partner, 'phase': phase, 'split_screen': True,
            'effective_training_profile': 'assisted', 'evaluation_pending': evaluation,
            'modifiers_changed': False, 'adaptive_reduction_ready': False,
            'capabilities': {'solo_p1': {'available': switch, 'reason': unavailable},
                'teammate_p2': {'available': pair, 'reason': '' if pair else unavailable or reason},
                'bots_p1_p2': {'available': switch, 'verified': pair,
                               'reason': unavailable or ('' if pair else 'Player 1 plays now; Player 2 joins once ' + reason[0].lower() + reason[1:])},
                'observe_human': {'available': switch, 'verified': evidence.get('human_observer_verified') is True,
                                  'reason': 'Observation records positions, not the human\'s buttons.'},
                'unmodified_evaluation': {'available': False,
                                          'reason': 'Original gameplay rules are not verified on Switch yet; current modifiers are kept.'}},
            'runtime': evidence}
