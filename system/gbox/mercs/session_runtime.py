"""Session-local controller fencing and read-only demonstration provenance."""
from __future__ import annotations

import time

from .teamplay import TeamStore, publish_runtime
from .training import participant, re5_assistance


class SessionRuntime:
    def __init__(self, adapter, session_id, game_id, title, send, stats, *, clock=time.monotonic):
        self.adapter, self.sid, self.game_id, self.title = adapter, session_id, game_id, title
        self.raw_send, self.stats, self.clock = send, stats, clock
        self.store = TeamStore(adapter.config.data_dir)
        self.held = {1: set(), 2: set()}
        self.driver = None
        self.memory = None
        self.config = self.store.get(self.sid)
        self.assignment = (self.config['role'], self.config['training_profile'])
        self.assistance = {'classification': 'unknown', 'verified': False, 'effects': []}
        self.last_probe = -float('inf')
        self.evidence = {}

    def refresh(self):
        self.config = self.store.get(self.sid)
        return self.config

    def poll(self, memory=None, driver=None, snap=None):
        config = self.refresh()
        assignment = (config['role'], config['training_profile'])
        if assignment != self.assignment:
            self.release()
            self.assignment = assignment
        now = self.clock()
        if driver is not None:
            self.driver = driver
        if memory is not None:
            self.memory = memory
        if now-self.last_probe >= .5:
            self.evidence = {}
            readiness = getattr(self.driver, 'readiness', None)
            if callable(readiness) and self.memory is not None:
                try:
                    self.evidence = dict(readiness(self.memory))
                except Exception as error:
                    self.evidence = {'reason': 'Player ownership readback failed: '+type(error).__name__}
            if self.title == 'BLUS30491':
                self.assistance = re5_assistance(self.adapter)
            # This is intentionally not inferred from modifiers being unchecked.
            self.evidence['unmodified_verified'] = self.assistance.get('classification') == 'unmodified' \
                and self.assistance.get('verified') is True
            self.last_probe = now
        rows = []
        if snap is not None:
            native_participants = getattr(self.driver, 'participants', None)
            if callable(native_participants):
                try:
                    rows = list(native_participants(memory, snap))
                except Exception:
                    rows = []
            if not callable(native_participants) and self.title == 'BLUS30491':
                control = 'human' if config['role'] in ('observe_human', 'teammate_p2') else 'bot'
                row = participant(snap.get('player'), 1, control, source='BLUS30491.sPlayer+0x28')
                if row:
                    rows = [row]
            # P2 driver supplies both actor identities; assignment is made here,
            # after native proof, instead of inheriting a prior bot trace's label.
            for row in rows:
                row['control'] = ('human' if row.get('slot') == 1 else 'bot') \
                    if config['role'] == 'teammate_p2' else \
                    ('human' if row.get('slot') == 1 else 'unknown') if config['role'] == 'observe_human' else \
                    ('bot' if row.get('slot') == 1 else 'unknown')
                row['provenance'] = {**(row.get('provenance') or {}),
                    'control_source': 'operator_assignment_and_bot_input_fence', 'inputs_observed': False}
            self.evidence['active_players'] = rows
            snap['players'] = rows
            snap['assistance'] = dict(self.assistance)
            snap['input_provenance'] = {'source': 'human_buttons_not_captured' if config['role'] == 'observe_human'
                                        else 'bot_decisions', 'control_player': 2 if config['role'] == 'teammate_p2' else
                                        None if config['role'] == 'observe_human' else 1}
        self.evidence['human_observer_verified'] = config['role'] in ('observe_human', 'teammate_p2') \
            and not self.held[1] and any(row.get('slot') == 1
                and row.get('provenance', {}).get('native_actor_verified') is True
                for row in self.evidence.get('active_players', ()))
        if config['training_profile'] == 'unmodified_evaluation' and not self.evidence.get('unmodified_verified'):
            self.evidence['reason'] = self.assistance.get('reason') or 'Original gameplay rules have not been fully verified.'
        publish_runtime(self.sid, self.adapter, self.evidence)
        status = self.store.status(self.sid, game_id=self.game_id, adapter=self.adapter)
        if status['control_player'] is None:
            self.release()
        self.stats.update(team_role=config['role'], team_phase=status['phase'], bot_player=status['control_player'],
                          team_reason=status['runtime'].get('reason', ''), training_profile=config['training_profile'],
                          selected_route_id=config['selected_route_id'] or '')
        if memory is not None:
            memory.mercs_no_modifications = config['role'] != 'solo_p1' or config['training_profile'] != 'assisted'
        return status

    def signature(self):
        config = self.refresh()
        return config['role'], config['training_profile']

    def send(self, events):
        # Recheck persisted operator intent even for menu/QTE bursts between
        # engine ticks. A missing P2 never receives a fallback to P1.
        status = self.poll()
        player = status['control_player']
        grouped = {1: [], 2: []}
        for event in events or ():
            key = event.get('key')
            if not isinstance(key, str) or 'rpc' in event:
                continue
            if event.get('down', True):
                if player not in (1, 2):
                    continue
                if event.get('player', player) != player:
                    continue
                grouped[player].append({'key': key, 'down': True, 'player': player})
            else:
                # Only release this bot's actual keys, including after a role
                # change. Never release a human P1 button as a generic cleanup.
                for old in (1, 2):
                    if key in self.held[old]:
                        grouped[old].append({'key': key, 'down': False, 'player': old})
        for port, rows in grouped.items():
            if not rows:
                continue
            if port == 2:
                send = getattr(self.adapter, 'send_input_player', None)
                if not callable(send):
                    raise RuntimeError('Player 2 has no verified independent input path')
                send(rows, player=2)
            else:
                self.raw_send(rows)
            for row in rows:
                if row['down']:
                    self.held[port].add(row['key'])
                else:
                    self.held[port].discard(row['key'])

    def release(self):
        for port, keys in self.held.items():
            rows = [{'key': key, 'down': False, 'player': port} for key in sorted(keys)]
            if not rows:
                continue
            if port == 2:
                send = getattr(self.adapter, 'send_input_player', None)
                if callable(send):
                    send(rows, player=2)
            else:
                self.raw_send(rows)
            keys.clear()
