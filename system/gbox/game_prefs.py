"""Settings chosen in a game's menus survive reloads, relaunches and restarts (operator 2026-10-26: "when i set the
settings in the right click menu for the mods / bot systems, retain those settings across reloads").

Recording: every verified operator change from those menus (RE5 modifiers, RE5 / RE6 team and training, RE4 modifiers)
is kept per game on the control plane when its job succeeds, whichever menu sent it (PiP menu, mini window, web UI).
Agents, bots, schedulers and these settings' own re-apply jobs are never recorded.

Re-applying: a session of that game that has not got the current settings yet (a relaunch, MercMode's next turn, a
service or worker restart: all new sessions), an F5 (bot_control forces it), or a change saved from another session gets
them back as ONE apply_saved job per tool on the session's worker. The worker applies each item as the operator's own
change, so re5_mods / re_mods keep it as an operator override and the bot's boot and round packages apply it instead of
their defaults. A game still booting answers "not ready": the job is retried with a growing pause, at most MAX_ATTEMPTS
times per saved revision. Only the operator's own sessions and the bot sessions they watch (MercMode / screensaver runs,
bot demos) receive them; agent test sessions keep their own setup, a paused warm game waits for its turn, and team roles
go to the operator's own sessions only (a saved co-op role must never stall a MercMode bot).

The PiP menu keeps its small per-game values here too (the save-state slot); those are only read back by the menu.

GET    /api/game-prefs                      every game's saved settings
GET    /api/game-prefs/{game_id}            one game's
GET    /api/sessions/{sid}/game-prefs       the session's game, plus whether each saved setting is on this session yet
PUT    /api/game-prefs/{game_id}/pip        {settings: {save_slot}}: the PiP menu's own values
DELETE /api/game-prefs/{game_id}?panel=&name=   forget (all, one panel, one setting); the running game is not changed
"""
from __future__ import annotations

import math
import threading
import time

from fastapi import Depends, HTTPException
from pydantic import BaseModel

KIND = 'game_prefs'                 # prefs key -> {key, game_ids, title, rev, updated, by, panels: {panel: {name: value}}}
APPLIED = 'game_prefs_applied'      # session id -> {session_id, key, ops: {tool.name: {...}}, tools: {tool: {...}}}
ACTOR = 'game-prefs'
VIA = 'game prefs'
TICK_S = 10.0
FIRST_DELAY_S = 30.0                # a new session boots before its first attempt
RETRY_S = (30.0, 60.0, 120.0)       # pause after the 1st, 2nd, 3rd+ failed attempt
MAX_ATTEMPTS = 12                   # per saved revision; F5 or a new change starts over
STALE_JOB_S = 300.0                 # an apply job still queued after this is given up on (its worker never took it)
FORCE_GAP_S = 20.0                  # F5 pressed twice: one re-apply
PRUNE_S = 600.0

RE5 = 'e7ca89bbeb67360d'
RE5_SWITCH = '52d15709be0fda1a'                         # RE5 on Switch: re5_mods routes it to re5_switch_mods (own key)
RE6 = '0871eee3b68cdea3'
RE4 = ('78ab9efa2e310db4', 'e42c9b780c07c437')          # Resident Evil 4 (USA) GameCube Disc 1 / Disc 2

RE5_TOGGLES = ('unlimited_health', 'infinite_ammo', 'infinite_spray', 'instant_qte')
RE5_SCALES = {'fire_rate': (0.1, 1000.0), 'bullet_damage': (0.1, 1000.0), 'turn_speed': (0.25, 50.0)}
RE5_ORDER = (*RE5_TOGGLES, *RE5_SCALES, 'kill_time', 'weapon_override', 'rotten_egg_only', 'mines')
RE4_TOGGLES = ('unlimited_health', 'infinite_ammo', 'combo_freeze', 'merc_timer_freeze', 'grenade_safe')
RE4_SCALES = {'merc_time_bonus': (1.0, 10.0), 'combo_time': (1.0, 10.0), 'aim_turn_speed': (0.5, 5.0)}
RE4_ORDER = ('mercenaries_unlock', *RE4_TOGGLES, *RE4_SCALES, 'spawn_multiplier', 'loadout')
TEAM_KEYS = ('role', 'training_profile', 'auto_reduce_mods')

TOOLS = {
    're5_mods': {'games': (RE5, RE5_SWITCH), 'adapters': ('rpcs3', 'citron', 'eden'), 'label': 'RE5 modifiers',
                 'order': RE5_ORDER},
    're_mods': {'games': RE4, 'adapters': ('dolphin',), 'label': 'RE4 modifiers', 'order': RE4_ORDER},
    'mercs_team': {'games': (RE5, RE6), 'adapters': ('rpcs3', 'xenia'), 'label': 'Team and training',
                   'order': ('team',), 'operator_only': True},
}
CLIENT_PANELS = {'pip': {'save_slot': (0, 9)}}         # values the menus write themselves (int ranges)


def key_for(game_id: str | None) -> str:
    """One record per game: the discs of one game share it (RE4's Disc 1 / Disc 2), from MercMode's title table."""
    gid = str(game_id or '')
    try:
        from .mercmode import TITLES
        for spec in TITLES.values():
            ids = tuple(spec.get('game_ids') or ())
            if gid in ids:
                return ids[0]
    except Exception:                                    # noqa: BLE001 - no title table: the game id itself
        pass
    return gid


def _num(value, low, high):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and low <= x <= high else None


def _re5(op, inp, result, prev):
    if op == 'revert_all':
        return {'*': None} if result.get('verified') is True else {}
    if result.get('verified') is not True:
        return {}
    on = bool(inp.get('on', True))
    if op in RE5_TOGGLES:
        return {op: {'on': on}}
    if op in RE5_SCALES:
        if not on:
            return {op: {'on': False}}
        m = inp.get('multiplier')
        if m is None:
            return {op: {'on': True}}                    # the tool's own default
        if op == 'turn_speed' and isinstance(m, str) and m.strip().lower() in ('max', 'maximum', 'unlimited'):
            return {op: {'on': True, 'multiplier': 'max'}}
        x = _num(m, *RE5_SCALES[op])
        return {op: {'on': True, 'multiplier': x}} if x is not None else {}
    if op == 'kill_time':                                # on / off keeps the seconds set earlier (the panel's switch)
        x = _num(inp.get('multiplier'), 0.1, 30.0) if inp.get('multiplier') is not None else None
        seconds = x if x is not None else (prev or {}).get('multiplier')
        return {op: {'on': on, **({'multiplier': seconds} if seconds is not None else {})}}
    if op == 'mines':
        m = inp.get('multiplier')
        value = 'only' if str(m).strip().lower() == 'only' else _num(60 if m is None else m, 2.0, 300.0)
        return {op: {'on': on, 'multiplier': value}} if value is not None else {}
    if op == 'rotten_egg_only':
        x = _num(20 if inp.get('multiplier') is None else inp.get('multiplier'), 1.0, 20.0)
        return {op: {'on': on, 'multiplier': x}} if x is not None else {}
    if op == 'weapon_override':
        weapon = inp.get('weapon')
        if not on or weapon is None:
            return {op: {'on': False}}
        if type(weapon) is not int or not 0 <= weapon <= 255:
            return {}
        return {op: {'on': True, 'weapon': weapon, 'only': bool(inp.get('only'))}}
    return {}


def _re4(op, inp, result, prev):
    if result.get('verified') is not True:
        return {}
    on = bool(inp.get('on', True))
    if op in RE4_TOGGLES:
        return {op: {'on': on}}
    if op in RE4_SCALES:
        if not on:
            return {op: {'on': False}}
        x = _num(inp.get('multiplier'), *RE4_SCALES[op])
        return {op: {'on': True, 'multiplier': x}} if x is not None else {}
    if op == 'spawn_multiplier':
        count = inp.get('count') or 2
        if type(count) is not int or not 1 <= count <= 8:
            return {}
        return {op: {'on': on and count > 1, 'count': count}}
    if op == 'random_loadout' and on:
        damage = _num(inp.get('damage'), 0.1, 1000.0)
        return {'loadout': {'mode': 'random', 'character': str(inp.get('character') or 'leon')[:20],
                            **({'damage': damage} if damage is not None else {})}}
    if op == 'merc_loadout' and inp.get('reset'):
        return {'loadout': {'mode': 'default', 'character': str(inp.get('character') or 'leon')[:20]}}
    if op == 'mercenaries_unlock' and on:
        return {op: {'on': True}}
    return {}


def _team(op, inp, result, prev):
    if op != 'configure' or result.get('configuration_verified') is not True:
        return {}
    config = (result.get('status') or {}).get('config') or {}
    team = {k: config[k] for k in TEAM_KEYS if k in config}
    return {'team': team} if team else {}


EXTRACT = {'re5_mods': _re5, 're_mods': _re4, 'mercs_team': _team}


def canonical(tool: str, op: str) -> str:
    """The tool's own name for an op (re5_mods / re_mods accept aliases and report the canonical name back)."""
    op = str(op or '').strip().lower().replace(' ', '_').replace('-', '_')
    try:
        if tool == 're_mods':
            from .re_mods_tool import canonical as re4
            return re4(op)
    except Exception:                                    # noqa: BLE001
        pass
    return op


def extract(tool: str, inp: dict, result: dict, previous: dict | None = None) -> dict:
    """{setting name: saved value} from one succeeded job ({'*': None}: the tool's settings were reverted)."""
    fn = EXTRACT.get(tool)
    if not fn or not isinstance(result, dict):
        return {}
    op = canonical(tool, result.get('op') or inp.get('op'))
    name = op if op != 'random_loadout' and op != 'merc_loadout' else 'loadout'
    return fn(op, inp, result, (previous or {}).get(name))


def recordable(job: dict) -> bool:
    """A change the operator made in a game menu: the desktop app and the web UI send it as the operator (no actor header)
    with agent_use false. Agents (the in-app chat agent's jobs carry agent_use too), the bots and schedulers (their own
    actors) and these settings' own re-apply jobs are never recorded."""
    if job.get('agent_use') or (job.get('actor') or 'operator') != 'operator' or (job.get('origin') or {}).get('via') == VIA:
        return False
    return (job.get('input') or {}).get('op') != 'apply_saved'


def observe(store, job: dict, state, *, now: float | None = None) -> dict | None:
    """A finished job: keep the operator's verified menu change for this game (and note that this session has it)."""
    tool = job.get('tool')
    if tool not in TOOLS or str(state) != 'succeeded' or not recordable(job):
        return None
    inp = job.get('input') or {}
    result = (job.get('output') or {}).get('result') or {}
    if not extract(tool, inp, result, {}):                  # status reads and one-shot actions: nothing to keep
        return None
    sid = inp.get('session_id') or ''
    sess = store.get('session', sid) or {}
    gid = sess.get('game_id')
    if gid not in TOOLS[tool]['games']:
        return None
    now = time.time() if now is None else now
    key = key_for(gid)
    with store.lock:
        rec = store.get(KIND, key) or {'key': key, 'game_ids': [], 'title': '', 'rev': 0, 'panels': {}}
        panels = dict(rec.get('panels') or {})
        before = dict(panels.get(tool) or {})
        changes = extract(tool, inp, result, before)
        if not changes:
            return None
        after = {} if '*' in changes else dict(before)
        for name, value in changes.items():
            if name == '*':
                continue
            if value is None:
                after.pop(name, None)
            else:
                after[name] = value
        if after:
            panels[tool] = after
        else:
            panels.pop(tool, None)
        changed = after != before
        rec = rec | {'panels': panels, 'rev': int(rec.get('rev') or 0) + (1 if changed else 0), 'updated': now,
                     'by': job.get('actor') or 'operator', 'title': sess.get('title') or rec.get('title') or gid,
                     'game_ids': sorted(set(rec.get('game_ids') or []) | {gid})}
        store.put(KIND, key, rec)
        applied = store.get(APPLIED, sid) or {'session_id': sid, 'key': key, 'ops': {}, 'tools': {}}
        ops = applied.setdefault('ops', {})
        if '*' in changes:
            for k in [k for k in ops if k.startswith(tool + '.')]:
                ops.pop(k)
        for name, value in changes.items():
            if name != '*' and value is not None:
                ops[f'{tool}.{name}'] = {'value': value, 'state': 'applied', 'at': now, 'job': job.get('id'),
                                         'by': 'operator'}
        store.put(APPLIED, sid, applied)
    store.audit(job.get('actor') or 'operator', 'game_prefs.save', key,
                {'tool': tool, 'session_id': sid, 'changes': sorted(changes), 'rev': rec['rev']})
    return rec


def session_kind(store, sess: dict, runs=None) -> str:
    """Who this session belongs to, for the saved settings: operator | scheduler (MercMode / screensaver run) | bot_demo |
    agent (a test session: never) | warm (paused for its MercMode turn: later)."""
    from . import screensaver
    from .background_testing import agent_owned
    sid = sess.get('session_id') or ''
    label = store.get('slabel', sid) or {}
    if label.get('warm'):
        return 'warm'
    rows = store.all(screensaver.STATE) if runs is None else runs
    if any(r.get('session_id') == sid for r in rows):
        return 'scheduler'
    if screensaver.bot_demo(store, sid):
        return 'bot_demo'
    if agent_owned(label, store.get('job', sid.split('-', 1)[-1])):
        return 'agent'
    return 'operator'


def receives(tool: str, sess: dict, kind: str) -> bool:
    spec = TOOLS.get(tool)
    if not spec or kind in ('agent', 'warm'):
        return False
    if sess.get('game_id') not in spec['games'] or sess.get('adapter') not in spec['adapters']:
        return False
    return kind == 'operator' or not spec.get('operator_only')


def saved_op(tool: str, name: str, value: dict) -> dict:
    """One apply_saved item for the worker."""
    if tool == 're_mods' and name == 'loadout':
        if value.get('mode') == 'random':
            return {'name': name, 'op': 'random_loadout', 'on': True, 'character': value.get('character') or 'leon',
                    **({'damage': value['damage']} if value.get('damage') else {})}
        return {'name': name, 'op': 'merc_loadout', 'reset': True, 'character': value.get('character') or 'leon'}
    return {'name': name, 'op': name,
            **{k: v for k, v in value.items() if k in ('on', 'multiplier', 'weapon', 'only', 'count')}}


def batch_input(tool: str, sid: str, pending: dict) -> dict:
    if tool == 'mercs_team':
        team = pending.get('team') or {}
        return {'session_id': sid, 'op': 'configure', **{k: team[k] for k in TEAM_KEYS if k in team}}
    order = TOOLS[tool]['order']
    names = sorted(pending, key=lambda n: order.index(n) if n in order else len(order))
    return {'session_id': sid, 'op': 'apply_saved', 'ops': [saved_op(tool, n, pending[n]) for n in names]}


def verified(tool: str, job: dict, names) -> tuple[set, dict]:
    """Which of the sent settings the worker confirmed, and why the others were not."""
    result = ((job.get('output') or {}).get('result') or {}) if job.get('state') == 'succeeded' else {}
    error = str(job.get('error') or job.get('state') or 'not applied')[:200]
    if tool == 'mercs_team':
        ok = result.get('configuration_verified') is True
        return ({'team'} if ok else set()), ({} if ok else {'team': error})
    rows = result.get('results') if isinstance(result.get('results'), dict) else {}
    ok = {n for n in names if (rows.get(n) or {}).get('verified') is True}
    return ok, {n: str((rows.get(n) or {}).get('reason') or error)[:200] for n in names if n not in ok}


def view(store, *, game_id: str | None = None, sid: str | None = None, runs=None) -> dict:
    sess = None
    if sid:
        sess = store.get('session', sid)
        if not sess:
            raise HTTPException(404, 'Unknown game session.')
        game_id = sess.get('game_id')
    key = key_for(game_id)
    rec = store.get(KIND, key) or {}
    out = {'key': key, 'game_id': game_id, 'title': rec.get('title') or (sess or {}).get('title') or game_id,
           'rev': int(rec.get('rev') or 0), 'updated': rec.get('updated'), 'by': rec.get('by'),
           'panels': rec.get('panels') or {}}
    if sess is not None:
        kind = session_kind(store, sess, runs)
        applied = (store.get(APPLIED, sid) or {}).get('ops') or {}
        out['session_kind'] = kind
        out['applied'], out['receives'] = {}, {}
        for tool, settings in out['panels'].items():
            if tool not in TOOLS:
                continue
            out['receives'][tool] = receives(tool, sess, kind)
            for name, value in settings.items():
                a = applied.get(f'{tool}.{name}') or {}
                state = a.get('state') if a.get('value') == value and a.get('state') in ('applied', 'failed') else 'pending'
                out['applied'].setdefault(tool, {})[name] = {'state': state, **({'at': a['at']} if a.get('at') else {}),
                                                             **({'reason': a['reason']} if state == 'failed' else {})}
    return out


class Reapplier:
    """The control plane's loop that puts saved settings on sessions that lack them (see the module docstring)."""

    def __init__(self, store, *, submit, workers, wid, clock=time.time, spawn=None):
        self.store, self.submit, self.workers, self.wid = store, submit, workers, wid
        self.clock = clock
        self.spawn = spawn or (lambda fn: threading.Thread(target=fn, daemon=True).start())
        self.lock = threading.RLock()
        self.pruned = 0.0

    def force(self, sid: str) -> bool:
        """F5: this session gets every saved setting again, at once (twice within FORCE_GAP_S: once)."""
        now = self.clock()
        with self.lock:
            rec = self.store.get(APPLIED, sid) or {}
            if now - float(rec.get('forced') or 0) < FORCE_GAP_S:
                return False
            self.store.put(APPLIED, sid, {'session_id': sid, 'key': rec.get('key'), 'ops': {}, 'tools': {}, 'forced': now})
        self.spawn(lambda: self.tick(only=sid, now=now, ignore_delay=True))
        return True

    def tick(self, only: str | None = None, now: float | None = None, ignore_delay: bool = False) -> dict:
        now = self.clock() if now is None else now
        out = {}
        with self.lock:
            prefs = {r.get('key'): r for r in self.store.all(KIND) if r.get('panels')}
            running = self.store.running_sessions()
            if not only and now - self.pruned >= PRUNE_S:
                self.prune(running, now)
            due = [(s, prefs[key_for(s.get('game_id'))]) for s in running
                   if (not only or s.get('session_id') == only) and '-' in (s.get('session_id') or '')
                   and key_for(s.get('game_id')) in prefs
                   and (ignore_delay or now - float(s.get('started') or now) >= FIRST_DELAY_S)]
            if not due:
                return out
            from . import screensaver
            runs = self.store.all(screensaver.STATE)
            online = {w.get('id'): w for w in self.workers() if w.get('online')}
            active = self.store.jobs(states=('queued', 'running'))
            for sess, p in due:
                sid = sess['session_id']
                kind = session_kind(self.store, sess, runs)
                w = online.get(self.wid(sid.split('-', 1)[0]))
                if not w:
                    continue
                result = self.session(sess, p, kind, w, active, now)
                if result:
                    out[sid] = result
        return out

    def session(self, sess, p, kind, w, active, now) -> dict:
        from .server import JobRequest
        sid = sess['session_id']
        rec = self.store.get(APPLIED, sid) or {'session_id': sid, 'key': p['key'], 'ops': {}, 'tools': {}}
        rec.setdefault('ops', {})
        rec.setdefault('tools', {})
        done, changed = {}, False
        for tool in TOOLS:
            settings = (p.get('panels') or {}).get(tool) or {}
            if not settings or not receives(tool, sess, kind) or tool not in (w.get('tools') or []):
                continue
            t = dict(rec['tools'].get(tool) or {})
            if t.get('job'):
                job = self.store.get('job', t['job']) or {}
                if job.get('state') in ('queued', 'running') and now - float(job.get('created') or now) < STALE_JOB_S:
                    continue
                self.settle(rec, tool, t, job, now)
                changed = True
                t = dict(rec['tools'][tool])
            pending = {n: v for n, v in settings.items()
                       if not ((rec['ops'].get(f'{tool}.{n}') or {}).get('state') == 'applied'
                               and (rec['ops'].get(f'{tool}.{n}') or {}).get('value') == v)}
            if not pending:
                continue
            if t.get('rev') != p.get('rev'):
                t = {'attempts': 0, 'next_at': 0, 'rev': p.get('rev')}
            if t.get('attempts', 0) >= MAX_ATTEMPTS or now < float(t.get('next_at') or 0):
                continue
            if any(j.get('tool') == tool and (j.get('input') or {}).get('session_id') == sid for j in active):
                continue                                 # the operator's own change (or ours) is still on its way
            inp = batch_input(tool, sid, pending)
            try:
                job = self.submit(JobRequest(tool=tool, input=inp, agent_use=False, require_worker=w['id']), ACTOR,
                                  {'via': VIA, 'session_id': sid, 'key': p['key'], 'rev': p.get('rev')})
                jid = getattr(job, 'id', None) or (job.get('id') if isinstance(job, dict) else None)
                state = str(getattr(job, 'state', None) or (job.get('state') if isinstance(job, dict) else '') or '')
                error = getattr(job, 'error', None) or (job.get('error') if isinstance(job, dict) else None)
            except HTTPException as exc:
                jid, state, error = None, 'rejected', str(exc.detail)
            rec['tools'][tool] = t | {'job': jid, 'at': now, 'values': pending, 'rev': p.get('rev')}
            if state == 'rejected' or not jid:
                self.settle(rec, tool, rec['tools'][tool], {'id': jid, 'state': 'rejected', 'error': error}, now)
            done[tool] = sorted(pending)
            changed = True
        if changed:
            self.store.put(APPLIED, sid, rec)
        return done

    def settle(self, rec, tool, t, job, now):
        values = t.get('values') or {}
        ok, why = verified(tool, job, list(values))
        for name, value in values.items():
            entry = {'value': value, 'at': now, 'job': job.get('id')}
            rec['ops'][f'{tool}.{name}'] = entry | ({'state': 'applied'} if name in ok
                                                   else {'state': 'failed', 'reason': why.get(name, 'not applied')})
        attempts = int(t.get('attempts') or 0) + 1 if why else 0
        pause = RETRY_S[min(attempts, len(RETRY_S)) - 1] if attempts else 0.0
        since = min(now, float(job.get('finished') or now))        # the pause runs from when the attempt ended
        rec['tools'][tool] = {'attempts': attempts, 'next_at': since + pause, 'rev': t.get('rev'),
                              'last_job': job.get('id'), 'last_state': job.get('state')}

    def prune(self, running, now):
        self.pruned = now
        live = {s.get('session_id') for s in running}
        for row in self.store.all(APPLIED):
            if row.get('session_id') not in live:
                self.store.delete(APPLIED, row.get('session_id', ''))


class PrefsIn(BaseModel):
    settings: dict = {}
    title: str = ''


def routes(app, store, auth, *, submit, workers, wid):
    reapplier = Reapplier(store, submit=submit, workers=workers, wid=wid)
    app.state.game_prefs = reapplier

    @app.get('/api/game-prefs')
    def game_prefs_all(actor=Depends(auth)):
        return store.all(KIND)

    @app.get('/api/game-prefs/{game_id}')
    def game_prefs_get(game_id: str, actor=Depends(auth)):
        return view(store, game_id=game_id)

    @app.get('/api/sessions/{sid}/game-prefs')
    def game_prefs_session(sid: str, actor=Depends(auth)):
        return view(store, sid=sid)

    @app.put('/api/game-prefs/{game_id}/{panel}')
    def game_prefs_put(game_id: str, panel: str, body: PrefsIn, actor=Depends(auth)):
        spec = CLIENT_PANELS.get(panel)
        if spec is None:
            raise HTTPException(422, 'Modifier settings are saved when the game confirms them; only the PiP menu '
                                     'values are written here.')
        clean = {}
        for name, value in (body.settings or {}).items():
            if name not in spec:
                raise HTTPException(422, f'Unknown {panel} setting: {name}')
            low, high = spec[name]
            if type(value) is not int or not low <= value <= high:
                raise HTTPException(422, f'{name}: a whole number {low}..{high}')
            clean[name] = value
        key = key_for(game_id)
        with store.lock:
            rec = store.get(KIND, key) or {'key': key, 'game_ids': [], 'title': '', 'rev': 0, 'panels': {}}
            panels = dict(rec.get('panels') or {})
            panels[panel] = dict(panels.get(panel) or {}) | clean
            rec = rec | {'panels': panels, 'updated': time.time(), 'by': actor,
                         'title': body.title[:120] or rec.get('title') or game_id,
                         'game_ids': sorted(set(rec.get('game_ids') or []) | {game_id})}
            store.put(KIND, key, rec)
        store.audit(actor, 'game_prefs.put', key, {'panel': panel, 'settings': clean})
        return view(store, game_id=game_id)

    @app.delete('/api/game-prefs/{game_id}')
    def game_prefs_forget(game_id: str, panel: str = '', name: str = '', actor=Depends(auth)):
        key = key_for(game_id)
        with store.lock:
            rec = store.get(KIND, key)
            if not rec:
                return view(store, game_id=game_id)
            panels = dict(rec.get('panels') or {})
            if not panel:
                panels = {}
            elif not name:
                panels.pop(panel, None)
            elif name in (panels.get(panel) or {}):
                panels[panel] = {k: v for k, v in panels[panel].items() if k != name}
                if not panels[panel]:
                    panels.pop(panel)
            store.put(KIND, key, rec | {'panels': panels, 'rev': int(rec.get('rev') or 0) + 1, 'updated': time.time(),
                                        'by': actor})
        store.audit(actor, 'game_prefs.forget', key, {'panel': panel, 'name': name})
        return view(store, game_id=game_id)

    stopped = threading.Event()

    def loop():
        while not stopped.wait(TICK_S):
            try:
                reapplier.tick()
            except Exception as e:                       # noqa: BLE001 - one bad tick never ends the loop
                print(f'game prefs tick failed: {type(e).__name__}: {e}', flush=True)
    app.on_event('startup')(lambda: threading.Thread(target=loop, daemon=True, name='game-prefs').start())
    app.on_event('shutdown')(stopped.set)
    return reapplier
