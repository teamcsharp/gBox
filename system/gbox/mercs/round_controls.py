"""Operator stage rotation, latched per session and executed at native menus.

Preferences survive restarts; replay requests do not escape their session. No
game memory is written here. A replay is consumed only by a verified round start
on the requested stage with a different character.
"""
from __future__ import annotations

import copy
import json
import math
import os
import random
import threading
import uuid
from collections import OrderedDict
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / 'gbox-data' / 'mercs' / 'stage-rotation.json'
_files = threading.RLock()
_attach = threading.RLock()
# gate 9 (docs/mercmode-adding-titles.md): the GameCube id is not the only RE4 map
MAPS = {'G4BE08': 're4', '010099A00BC1E000': 're4', '010018100CD46000': 're5', '01002A000CD48000': 're6'}
NAMES = {'re4': 'Resident Evil 4', 're5': 'Resident Evil 5', 're6': 'Resident Evil 6'}


def catalog(title):
    if title == 're4':
        from ..re4_menus import STAGES, PLAYERS
        return STAGES, PLAYERS
    if title == 're5':
        from .titles.re5_switch import STAGE_NAMES, CHARACTERS
        return STAGE_NAMES, CHARACTERS
    if title == 're6':
        from .titles.re6_switch import STAGES, CHARACTERS
        return STAGES, CHARACTERS
    return (), ()


def _read(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def normalize(rows, names):
    if not isinstance(rows, list) or len(rows) != len(names):
        raise ValueError('Provide every stage exactly once')
    parsed = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid stage row')
        i, enabled, weight = row.get('id'), row.get('enabled'), row.get('weight')
        if type(i) is not int or not 0 <= i < len(names) or i in parsed or type(enabled) is not bool:
            raise ValueError('Invalid or duplicate stage')
        if type(weight) not in (int, float) or not math.isfinite(weight) or not 0 <= weight <= 100:
            raise ValueError('Stage weights must be finite numbers from 0 to 100')
        parsed[i] = {'id': i, 'enabled': enabled, 'weight': float(weight) if enabled else 0.0}
    total = sum(row['weight'] for row in parsed.values())
    if total <= 0:
        raise ValueError('Enable at least one stage with a positive weight')
    return [dict(parsed[i], weight=parsed[i]['weight'] * 100 / total) for i in range(len(names))]


class Controls:
    selection = None  # old live instances also accept this field after a bot hot reload
    selection_consumed = None
    random_characters = False
    random_stages = False

    def __init__(self, title, sid=None, *, path=PATH, rng=None):
        self.title, self.sid, self.path = title, sid, Path(path)
        self.names, self.characters = catalog(title)
        self.lock, self.rng = threading.RLock(), rng or random.Random()
        self.rows = self.defaults()
        self.configured = False
        self.preference_stamp = None
        with _files:
            saved = _read(self.path).get(title)
        if saved is not None:
            try:
                self.rows = normalize(saved, self.names)
                self.configured = True
            except ValueError:
                pass
        self.current_stage = self.current_character = None
        self.stage = self.character = None
        self.loop_stage = None
        self.once = None
        self.selection = None
        self.selection_consumed = set()
        self.receipts = OrderedDict()
        self.seen_requests = set()
        self.reason = ''
        self.confirmed = {}

    def sync_preferences(self):
        """Other sessions of this title share saved weights, not replay state."""
        try:
            stamp = self.path.stat().st_mtime_ns
        except OSError:
            return
        if stamp == self.preference_stamp:
            return
        with _files:
            saved = _read(self.path).get(self.title)
        if saved is not None:
            try:
                self.rows, self.configured = normalize(saved, self.names), True
            except ValueError:
                return
        self.preference_stamp = stamp

    def defaults(self):
        return [{'id': i, 'enabled': True, 'weight': 100 / len(self.names)} for i in range(len(self.names))]

    @property
    def managed(self):
        with self.lock:
            self.sync_preferences()
            return (self.configured or self.random_characters or self.random_stages
                    or self.once is not None or self.loop_stage is not None or self.selection is not None)

    def configure_launch(self, game):
        """Consume MercMode's flags without persisting them as operator stage preferences."""
        merc = ((game or {}).get('launch') or {}).get('mercmode') or {}
        with self.lock:
            # RE6 keeps its character selection and random costume behavior.
            self.random_characters = self.title != 're6' and merc.get('random_characters') is True
            self.random_stages = merc.get('random_stages') is True

    def queue_selection(self, stage, character, request_id=None):
        """A session's DJ pick, consumed by one confirmed native round, never persisted."""
        with self.lock:
            if type(stage) is not int or not 0 <= stage < len(self.names) \
                    or type(character) is not int or not 0 <= character < self._character_count():
                raise ValueError('The requested native stage or character is not available')
            if request_id is not None and (not isinstance(request_id, str) or not request_id or len(request_id) > 128):
                raise ValueError('A round selection request_id must be a nonempty string of at most 128 characters')
            value_key = f'round:{stage}:{character}'
            key = f'request:{request_id}' if request_id is not None else value_key
            if self.selection_consumed is None:
                self.selection_consumed = set()
            receipt = {'stage': stage, 'character': character, 'state': 'queued', 'key': key, 'value_key': value_key}
            if key in self.selection_consumed:
                return dict(receipt, state='confirmed', already_played=True)
            if self.selection is not None:
                self.selection['state'] = 'replaced'
            self.selection = receipt
            self.stage = self.character = None
            self.confirmed.clear()
            return self.selection

    def cancel_selection(self, receipt):
        """Only the owner of this menu walk may cancel its still-pending pick."""
        with self.lock:
            if self.selection is receipt:
                receipt['state'] = 'cancelled'
                self.selection = None
                self.stage = self.character = None
                self.confirmed.clear()

    def holds_title(self):
        with self.lock:
            return self.once is not None or self.loop_stage is not None

    def choose_stage(self, unlocked):
        with self.lock:
            self.sync_preferences()
            allowed = [r for r in self.rows if r['enabled'] and r['weight'] > 0 and r['id'] in unlocked]
            replay = self.selection['stage'] if self.selection else self.once['stage'] if self.once else self.loop_stage
            if replay is not None:
                # The explicit replay overrides the random pool, but never a native lock.
                if replay not in unlocked:
                    self.reason = 'The replay stage is not currently unlocked; waiting at the menu'
                    return None
                self.stage = replay
            elif self.stage not in [r['id'] for r in allowed]:
                if not allowed:
                    self.reason = 'No enabled stage is currently unlocked; change the stage selection'
                    return None
                different = [r for r in allowed if r['id'] != self.current_stage]
                draw = different if self.random_stages and different else allowed
                self.stage = self.rng.choices([r['id'] for r in draw], [r['weight'] for r in draw], k=1)[0]
            self.reason = ''
            return self.stage

    def _character_count(self):
        if self.title == 're5':
            from .titles.re5_switch import character_count
            return max(len(self.characters), character_count())
        return len(self.characters)

    def _character_family(self, index):
        # The RE5 roster now includes the Reunion characters and can discover
        # additional native menu entries. Known costumes share a name; unknown
        # entries keep their own index until their character names are mapped.
        if self.title == 're5' and type(index) is int and 0 <= index < len(self.characters):
            return self.characters[index].split(' (', 1)[0].casefold()
        return index

    def choose_character(self, unlocked):
        with self.lock:
            count = self._character_count()
            choices = [i for i in unlocked if type(i) is int and 0 <= i < count]
            if self.selection is not None:
                chosen = self.selection['character']
                if chosen not in choices:
                    if not choices:
                        self.reason = 'No character is currently unlocked; waiting at the menu'
                        return None
                    # The pick came from a longer roster list than this build's native select (live 2026-11-11: the
                    # RE5 pick was character 12, the native roster has 10 entries, choose_character returned None, the
                    # select walked to the spare PLAYER_TARGET and sat there forever). Map the index into the native
                    # range instead of dead-locking the menu; the receipt records which character really played.
                    chosen = choices[chosen % len(choices)]
                    self.reason = (f'the pick {self.selection["character"]} is outside this build\'s native '
                                   f'roster: playing {chosen}')
                self.character = chosen
                return chosen
            previous = self.once['character'] if self.once else self.current_character
            # RE5's select ids include costumes: Wesker STARS after Midnight is
            # still Wesker, so a replay must change the actual character family.
            different = [i for i in choices if self._character_family(i) != self._character_family(previous)]
            if not different and self.holds_title():
                self.reason = 'A different unlocked character is required for replay'
                return None
            choices = different or choices
            if self.character not in choices:
                self.character = self.rng.choice(choices) if choices else None
            return self.character

    def observed(self, stage, character):
        """Called once at a native round start, with menu-confirmed/native identity."""
        with self.lock:
            if type(stage) is not int or not 0 <= stage < len(self.names):
                return
            self.current_stage = stage
            self.current_character = character if type(character) is int and 0 <= character < self._character_count() else None
            if self.selection is not None and (stage, character) == (self.selection['stage'], self.selection['character']):
                self.selection['state'] = 'confirmed'
                self.selection_consumed.update((self.selection['key'], self.selection['value_key']))
                self.selection = None
            if self.once and stage == self.once['stage'] and self.current_character is not None \
                    and self._character_family(self.current_character) != self._character_family(self.once['character']):
                rid = self.once['request_id']
                if rid in self.receipts:
                    self.receipts[rid][1].update(status='applied', stage_id=stage, character_id=character)
                self.once = None
            self.stage = self.character = None

    def native_identity(self, stage, character):
        """A continuously sampled native identity; do not reset a latched menu draw each tick."""
        with self.lock:
            if (stage, character) != (self.current_stage, self.current_character):
                self.observed(stage, character)

    def menu_pressed(self, screen, key):
        with self.lock:
            where, cursor = screen.get('where'), screen.get('cursor')
            if key == 'a' and type(cursor) is int and cursor == screen.get('target'):
                if where == 'select_stage':
                    self.confirmed['stage'] = cursor
                elif where == 'select_player':
                    self.confirmed['character'] = cursor

    def confirmed_round(self):
        with self.lock:
            if set(self.confirmed) == {'stage', 'character'}:
                stage, character = self.confirmed['stage'], self.confirmed['character']
                self.confirmed = {}
                self.observed(stage, character)
                return stage, character

    def quick_status(self):
        if self.title != 're6':
            return {'available': False}
        from . import bot_logic
        values = {r['name']: r['value'] for r in bot_logic.status('re6')['knobs']}
        return {'available': all(k in values for k in ('PERIODIC_QA', 'PERIODIC_QA_COUNT', 'PERIODIC_QA_INTERVAL_S')),
                'enabled': values.get('PERIODIC_QA', True), 'count': values.get('PERIODIC_QA_COUNT', 4),
                'interval_s': values.get('PERIODIC_QA_INTERVAL_S', 24), 'scope': 'this title on this worker'}

    def status(self):
        with self.lock:
            self.sync_preferences()
            receipts = [copy.deepcopy(v[1]) for v in self.receipts.values()]
            return {'session_id': self.sid, 'title': NAMES.get(self.title, self.title), 'title_id': self.title,
                    'available': bool(self.names), 'configured': self.configured, 'current_stage': self.current_stage,
                    'current_character': self.current_character,
                    'stages': [dict(r, name=self.names[r['id']], default_enabled=True) for r in self.rows],
                    'loop': {'enabled': self.loop_stage is not None, 'stage_id': self.loop_stage},
                    'replay_pending': self.once is not None, 'reason': self.reason,
                    'quick_attack': self.quick_status(), 'receipts': receipts,
                    'receipt': receipts[-1] if receipts else None}

    def command(self, body):
        if body.get('op', 'status') == 'status':
            return self.status()
        rid = body.get('request_id')
        if not isinstance(rid, str):
            raise ValueError('request_id must be a UUID string')
        uuid.UUID(rid)
        signature = json.dumps(body, sort_keys=True, allow_nan=False)
        with self.lock:
            if rid in self.receipts:
                if self.receipts[rid][0] != signature:
                    raise ValueError('This request_id already belongs to a different action')
                return self.status() | {'receipt': copy.deepcopy(self.receipts[rid][1])}
            if rid in self.seen_requests:
                return self.status() | {'receipt': {'request_id': rid, 'status': 'rejected',
                    'error': 'This request was already processed; its detailed receipt has expired'}}
            receipt = {'request_id': rid, 'status': 'applied', 'op': body['op']}
            try:
                self._change(body, receipt)
            except (ValueError, OSError) as exc:
                receipt.update(status='rejected', error=str(exc)[:300])
            self.receipts[rid] = (signature, receipt)
            self.seen_requests.add(rid)
            while len(self.receipts) > 128:
                # Keep the queued replay receipt until its verified start.
                old = next((key for key in self.receipts if not self.once or key != self.once['request_id']), None)
                if old is None:
                    break
                del self.receipts[old]
            return self.status() | {'receipt': copy.deepcopy(receipt)}

    def _change(self, body, receipt):
        op = body['op']
        if op == 'replay':
            mode = body.get('mode')
            if mode == 'loop' and body.get('enabled') is False:
                self.loop_stage = None
            elif mode in ('once', 'loop'):
                if self.current_stage is None or self.current_character is None:
                    raise ValueError('Wait for a native round start with a verified stage and character')
                if mode == 'once':
                    if self.once:
                        raise ValueError('A replay is already queued')
                    self.once = {'stage': self.current_stage, 'character': self.current_character,
                                 'request_id': body['request_id']}
                    receipt['status'] = 'queued'
                else:
                    if body.get('enabled') is not True:
                        raise ValueError('Loop requires enabled true or false')
                    self.loop_stage = self.current_stage
                receipt['stage_id'] = self.current_stage
            else:
                raise ValueError('Replay mode must be once or loop')
            self.stage = self.character = None
        elif op == 'stages':
            rows = self.defaults() if body.get('reset') is True else normalize(body.get('stages'), self.names)
            with _files:
                data = _read(self.path)
                data[self.title] = rows
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_name(self.path.name + '.' + uuid.uuid4().hex + '.tmp')
                try:
                    tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
                    os.replace(tmp, self.path)
                finally:
                    tmp.unlink(missing_ok=True)
            self.rows, self.configured, self.stage = rows, True, None
        elif op == 'quick_attack' and self.title == 're6':
            enabled, count, interval = body.get('enabled'), body.get('count'), body.get('interval_s')
            if type(enabled) is not bool or type(count) is not int or not 1 <= count <= 8 \
                    or type(interval) not in (int, float) or not math.isfinite(interval) or not 8 <= interval <= 120:
                raise ValueError('Quick attacks need enabled, count 1..8, and interval 8..120 seconds')
            from . import bot_logic
            if not self.quick_status().get('available'):
                raise ValueError('Refresh this worker to enable all quick-attack controls')
            values = {'PERIODIC_QA': enabled, 'PERIODIC_QA_COUNT': count, 'PERIODIC_QA_INTERVAL_S': interval}
            bot_logic.handle('re6', values=values)
        else:
            raise ValueError('Unsupported icon panel action')
        self.reason = ''


def attach(ad, map_id, sid=None):
    if ad is None or map_id not in MAPS:
        return None
    with _attach:
        control = getattr(ad, '_merc_round_controls', None)
        if control is not None and type(control) is not Controls and type(control).__module__ == __name__ \
                and type(control).__name__ == 'Controls':
            # Adapter-owned instances are outside hot_reload's module keep-list.
            # Preserve their locks, preferences and consumed picks, but bind the
            # current methods before a new bot calls the selection API.
            control.__class__ = Controls
        if control is None or control.title != MAPS[map_id] or (sid and control.sid and sid != control.sid):
            root = getattr(getattr(ad, 'config', None), 'data_dir', None)
            control = Controls(MAPS[map_id], sid, path=Path(root) / 'mercs' / 'stage-rotation.json' if root else PATH)
            try:
                ad._merc_round_controls = control
            except AttributeError:
                return None
        elif sid:
            control.sid = sid
        return control


def for_memory(m):
    return getattr(getattr(m, 'adapter', None), '_merc_round_controls', None)


def hold_boundary(m, stats):
    control = for_memory(m)
    hold = bool(control and control.holds_title())
    stats['icon_panel_holds_title'] = hold
    return hold


def authorize(store, config, sid, body):
    session = store.get('session', sid)
    if not session or session.get('state') != 'running':
        raise ValueError('Choose a running session')
    worker = store.get('worker', session.get('worker_id') or sid.split('-')[0]) or {}
    import time
    if time.time() - worker.get('last_seen', 0) > 60:
        raise ValueError('The emulator worker is offline')
    if body.get('op', 'status') != 'status' and 'execute' not in config.granted_permissions:
        raise PermissionError('execute permission is required for bot overrides')


def remember_preferences(store, sid, report):
    """Mirror acknowledged worker preferences so a parked excluded stage cannot bypass them."""
    if not report.get('configured') or report.get('session_id') != sid or report.get('title_id') not in NAMES:
        return
    session = store.get('session', sid) or {}
    worker = store.get('worker', session.get('worker_id') or sid.split('-')[0]) or {}
    if not worker.get('name'):
        return
    rows = report.get('stages') or []
    names = [r.get('name', '') for r in rows]
    normalized = normalize(rows, names)
    key = worker['name'] + ':' + report['title_id']
    store.put('merc-stage-rotation', key, {'stages': [dict(r, name=names[r['id']]) for r in normalized]})


def warm_stage_allowed(store, host, title, prepared):
    saved = store.get('merc-stage-rotation', host + ':' + title) or {}
    rows = saved.get('stages')
    if not rows:
        return True
    stage = (prepared or {}).get('stage_index')
    if type(stage) is not int:
        name = (prepared or {}).get('stage')
        stage = next((r['id'] for r in rows if name and r.get('name') == name), None)
    # Missing native identity cannot establish that a prepared round is included.
    return any(r['id'] == stage and r['enabled'] and r['weight'] > 0 for r in rows)


def execute(sid, body, ctx):
    from ..tools import SESSIONS
    ad, game = SESSIONS[sid]
    if body.get('op', 'status') != 'status' and (ctx is None or 'execute' not in ctx.config.granted_permissions):
        raise PermissionError('execute permission is required for bot overrides')
    control = getattr(ad, '_merc_round_controls', None)
    if control is None or control.sid != sid:
        report = {'session_id': sid, 'title': game.get('title', ''), 'available': False, 'stages': [],
                'current_stage': None, 'loop': {'enabled': False, 'stage_id': None}, 'replay_pending': False,
                'quick_attack': {'available': False},
                'reason': 'A supported Mercenaries autoplay session must initialize its native menu controls first'}
        if body.get('op', 'status') != 'status':
            report['receipt'] = {'request_id': body.get('request_id'), 'status': 'rejected', 'error': report['reason']}
        return report
    return control.command(body)
