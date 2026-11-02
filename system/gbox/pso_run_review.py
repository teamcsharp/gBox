"""Measured PSO map and run evidence. This module never sends game input.

The worker sampler uses the controller's existing snapshot; telemetry carries
its bounded result to the server. Unknown geometry, door predicates and room
completion stay unknown. An observed trail is not a collision mesh.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid

SCHEMA = "gbox.pso.run-frame/1"
FRAME_BYTES = 30 * 1024
RUN_ID = re.compile(r"[a-f0-9]{32}\Z")
SID = re.compile(r"[A-Za-z0-9_.-]{1,120}\Z")
MAX_DB_BYTES = 512 * 1024 * 1024
MAX_FRAMES = 4096


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and abs(value) <= 1e9


def timestamp(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 < value < 1e12


def actor(row):
    if not isinstance(row, dict) or not all(number(row.get(k)) for k in ("x", "y", "z")):
        return None
    out = {key: round(row[key], 3) for key in ("x", "y", "z")}
    for key in ("hp", "hp_max", "tp", "tp_max", "room", "entity_id", "heading_deg"):
        if number(row.get(key)):
            out[key] = row[key]
    for key in ("ptr", "class", "kind"):
        if isinstance(row.get(key), str):
            out[key] = row[key][:96]
    return out


def _cells(rows, maximum=160, origin=None):
    clean = [tuple(c) for c in rows if isinstance(c, (list, tuple)) and len(c) == 2
             and all(type(v) is int and abs(v) <= 100000 for v in c)]
    return [list(c) for c in sorted(clean, key=(lambda c:((c[0]-origin[0])**2+(c[1]-origin[1])**2,c))
                                   if origin is not None else None)[:maximum]]


class Sampler:
    """One immutable frame/second; events retain the last 32 observed changes.

    Ten minute segments bound review pages. Segment rollover is recording only,
    never evidence of finishing a room, zone, boss or campaign.
    """

    def __init__(self, session_id, game_id, *, clock=time.monotonic, wall=time.time):
        if not SID.fullmatch(session_id or "") or not SID.fullmatch(game_id or ""):
            raise ValueError("Exact session and game identifiers are required")
        self.sid, self.gid, self.clock, self.wall = session_id, game_id, clock, wall
        self.last = -float("inf")
        self.run, self.started, self.seq = uuid.uuid4().hex, clock(), 0
        self.previous, self.events, self.event_seq = None, [], 0
        self.stationary, self.stall_at = {}, {}

    def _event(self, kind, message, elapsed, **data):
        self.event_seq += 1
        self.events.append({"id": self.event_seq, "kind": kind, "at_s": round(elapsed, 3),
                            "message": message[:240], **data})
        self.events = self.events[-32:]

    def offer(self, state, controller, stats):
        now = self.clock()
        if now - self.last < 1:
            return False
        self.last = now
        if now - self.started >= 600:
            self.run, self.started, self.seq = uuid.uuid4().hex, now, 0
            self.events, self.event_seq, self.previous = [], 0, None
            self.stationary.clear(); self.stall_at.clear()
        self.seq += 1
        elapsed = now - self.started
        verified = state.get("verified") is True and not state.get("travelling")
        players = {}
        if verified:
            for slot, row in (state.get("players") or {}).items():
                if str(slot) in ("1", "2") and (clean := actor(row)) is not None:
                    players[str(slot)] = clean
        entities = [row for raw in state.get("entities", [])[:512]
                    if verified and (row := actor(raw)) is not None and row.get("kind") != "player"]
        # Keep nearby actors visible even when the native entity table is large.
        entities.sort(key=lambda e: min((math.hypot(e['x']-p['x'], e['z']-p['z'])
                                        for p in players.values()), default=0))
        frame = {"schema": SCHEMA, "run_id": self.run, "session_id": self.sid,
                 "game_id": self.gid, "build": "3OE2", "seq": self.seq,
                 "observed_at": self.wall(), "elapsed_s": round(elapsed, 3),
                 "verified": verified, "phase": state.get("phase"),
                 "episode": state.get("episode"), "floor": state.get("floor"),
                 "difficulty": state.get("difficulty"), "travelling": bool(state.get("travelling")),
                 "players": players, "entities": entities[:64],
                 "entities_omitted": max(0, len(entities)-64), "maps": [], "goals": [],
                 "action": str(stats.get("action", ""))[:160],
                 "thought": str(stats.get("thought", ""))[:500],
                 "completion_verified": stats.get("completion_verified") is True,
                 "room_clear_verified": False,
                 "door_requirements": {"state": "unverified", "reason": "No verified door predicate provider attached"},
                 "counters": {k: stats[k] for k in ("observed_enemy_damage", "observed_kills", "attack_inputs",
                    "remembered_blocked_edges", "completed_native_episode_routes", "completed_native_episode_pairs")
                    if number(stats.get(k))}}
        from . import pso_coop_nav as navigation
        for slot, p in players.items():
            key, persistent = navigation.room_key(state, p)
            view = getattr(navigation, 'geometry_view', lambda state, player: state)(state, p)
            goal = getattr(controller, "goals", {}).get(int(slot))
            if (isinstance(goal, dict) and goal.get("identity") == key
                    and all(number(goal.get(k)) for k in ("x", "z"))):
                frame["goals"].append({"player": int(slot), "x": goal['x'], "z": goal['z'],
                    "room": p.get('room'), "reason": str(goal.get('reason', ''))[:160],
                    "route_verified": False})
            maps = getattr(getattr(controller, "maps", None), "maps", {})
            nav = maps.get(key)
            row = {"player": int(slot), "room": p.get('room'), "identity": key,
                   "layout_bound": persistent, "geometry_available": False,
                   "geometry_reason": "Native collision geometry has not been verified for this layout",
                   "walked": [], "blocked": [], "walls": [], "floor": []}
            if nav is not None:
                origin = nav.cell((p['x'], p['z']))
                edges = sorted(nav.blocked, key=lambda edge:((edge[0][0]-origin[0])**2+(edge[0][1]-origin[1])**2,edge))
                row.update(size=nav.size, walked=_cells(nav.walked, origin=origin),
                           blocked=[[list(a), list(b)] for a, b in edges[:80]])
                row['observations_truncated'] = len(nav.walked) > 160 or len(nav.blocked) > 80
                if (view.get("geometry_identity") and view.get("geometry_layer") is not None
                        and nav.floor is not None):
                    row.update(geometry_available=True, geometry_reason="Verified native collision grid",
                               geometry_identity=view['geometry_identity'], geometry_layer=view['geometry_layer'],
                               floor=_cells(nav.floor, 240, origin), walls=_cells(nav.walls, 160, origin),
                               geometry_truncated=len(nav.floor)>240 or len(nav.walls)>160)
            frame['maps'].append(row)
        self._changes(frame, now)
        frame['events'] = list(self.events)
        # Deterministic reduction preserves critical events and objective text.
        while len(json.dumps(frame, allow_nan=False, separators=(',', ':')).encode()) > FRAME_BYTES:
            if len(frame['entities']) > 16:
                frame['entities'] = frame['entities'][:len(frame['entities'])//2]
                frame['entities_omitted'] = len(entities)-len(frame['entities'])
            else:
                for row in frame['maps']:
                    for key in ('walked', 'blocked', 'floor', 'walls'):
                        row[key] = row[key][:len(row[key])//2]
                    row['observations_truncated'] = row['geometry_truncated'] = True
                if not any(row['walked'] or row['blocked'] or row['floor'] or row['walls'] for row in frame['maps']):
                    raise ValueError('PSO review frame cannot fit its bounded telemetry block')
        self.previous = frame
        stats['pso_review'] = frame
        return True

    def _changes(self, frame, now):
        old = self.previous
        at = frame['elapsed_s']
        if old is None:
            self._event('recording_started', 'New observation segment; no completion inferred', at)
            return
        area = ('episode', 'floor', 'difficulty')
        same_area = all(old.get(k) == frame.get(k) for k in area)
        if not same_area:
            self._event('area_changed', f"Episode {frame['episode']}, floor {frame['floor']} observed", at)
            self.stationary.clear(); self.stall_at.clear()
        for slot, p in frame['players'].items():
            previous = old['players'].get(slot)
            if not previous or previous.get('ptr') != p.get('ptr') or not same_area:
                self.stationary.pop(slot, None)
                continue
            if p.get('room') != previous.get('room'):
                self._event('room_changed', f"Player {slot}: room {previous.get('room')} → {p.get('room')}", at,
                            player=int(slot), from_room=previous.get('room'), to_room=p.get('room'))
                self.stationary.pop(slot, None)
                continue
            if number(p.get('hp')) and number(previous.get('hp')) and p['hp'] < previous['hp']:
                self._event('damage_taken', f"Player {slot} lost {previous['hp']-p['hp']} HP", at, player=int(slot))
            anchor = self.stationary.setdefault(slot, (now, p['x'], p['z']))
            if math.hypot(p['x']-anchor[1], p['z']-anchor[2]) >= 6:
                self.stationary[slot] = (now, p['x'], p['z'])
            elif (now-anchor[0] >= 15 and now-self.stall_at.get(slot, -1e10) >= 30
                  and frame['verified'] and frame['phase'] == 14):
                self._event('stationary', f"Player {slot} stayed within 6 units for {int(now-anchor[0])}s; inspect objective/combat", at,
                            player=int(slot), combat_inferred=False)
                self.stall_at[slot] = now
        if same_area:
            previous = {(e.get('ptr'),e.get('entity_id'),e.get('class'),e.get('room')): e for e in old['entities']}
            for e in frame['entities']:
                before = previous.get((e.get('ptr'),e.get('entity_id'),e.get('class'),e.get('room')))
                if (e.get('kind') == 'enemy' and before and number(before.get('hp'))
                        and before['hp'] > 0 and e.get('hp') == 0):
                    self._event('enemy_hp_zero', f"{e.get('class', 'Enemy')} HP reached zero", at,
                                entity_id=e.get('entity_id'), attribution='unassigned')
        if frame['goals'] != old['goals']:
            self._event('objective_changed', 'Native controller goals changed', at)
        a, b = old['counters'].get('remembered_blocked_edges'), frame['counters'].get('remembered_blocked_edges')
        if number(a) and number(b) and b > a:
            self._event('blocked_edge_learned', f"{b-a} additional blocked edges observed", at)


def validate(frame, sid, game_id):
    if (not isinstance(frame, dict) or frame.get('schema') != SCHEMA
            or frame.get('session_id') != sid or frame.get('game_id') != game_id
            or not RUN_ID.fullmatch(str(frame.get('run_id', '')))
            or type(frame.get('seq')) is not int or not 1 <= frame['seq'] <= 1000000
            or not timestamp(frame.get('observed_at'))
            or not number(frame.get('elapsed_s')) or frame['elapsed_s'] < 0
            or not isinstance(frame.get('players'), dict) or len(frame['players']) > 2
            or not isinstance(frame.get('entities'), list) or len(frame['entities']) > 64
            or not isinstance(frame.get('events'), list) or len(frame['events']) > 32):
        raise ValueError('Invalid exact-session PSO review frame')
    raw = json.dumps(frame, allow_nan=False, separators=(',', ':'))
    if len(raw.encode()) > FRAME_BYTES:
        raise ValueError('PSO review frame exceeds bounded size')
    return raw


class ReviewStore:
    def __init__(self, data_dir, *, clock=time.time):
        self.path = Path(data_dir) / 'pso' / 'reviewer.sqlite3'
        self.lock, self.clock = threading.RLock(), clock
        self.error = ''

    @contextmanager
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=3)
        db.row_factory = sqlite3.Row
        db.executescript('''CREATE TABLE IF NOT EXISTS runs(
            id TEXT PRIMARY KEY,sid TEXT NOT NULL,gid TEXT NOT NULL,job TEXT NOT NULL,
            started REAL NOT NULL,updated REAL NOT NULL,frames INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS frames(run TEXT,seq INTEGER,received REAL,body TEXT,
            PRIMARY KEY(run,seq));
            CREATE INDEX IF NOT EXISTS run_updated ON runs(updated);
            CREATE TABLE IF NOT EXISTS events(run TEXT,id INTEGER,body TEXT,PRIMARY KEY(run,id));''')
        try:
            with db:
                yield db
        finally:
            db.close()

    def ingest(self, sid, frame, session, job=''):
        if not session or session.get('session_id') != sid:
            raise ValueError('Review evidence requires the exact known session')
        validate(frame, sid, session.get('game_id'))
        raw = json.dumps(frame | {'source_running_at_ingest': session.get('state') == 'running'},
                         allow_nan=False, separators=(',', ':'))
        rid, now = frame['run_id'], self.clock()
        with self.lock, self._connect() as db:
            prior = db.execute('SELECT * FROM runs WHERE id=?', (rid,)).fetchone()
            if prior and (prior['sid'] != sid or prior['gid'] != session['game_id']):
                raise ValueError('Run identity cannot be rebound to another session')
            if prior and db.execute('SELECT 1 FROM frames WHERE run=? AND seq=?',(rid,frame['seq'])).fetchone():
                return False # Bridge retransmission must not make an old sample fresh.
            if prior and (prior['frames'] >= MAX_FRAMES or db.execute(
                    'SELECT MAX(seq) FROM frames WHERE run=?', (rid,)).fetchone()[0] >= frame['seq']):
                return False
            if self.path.stat().st_size >= MAX_DB_BYTES:
                self.error = 'Review storage reached 512 MB; export/archive evidence to resume recording'
                return False
            db.execute('INSERT OR IGNORE INTO runs VALUES(?,?,?,?,?,?,0)',
                       (rid,sid,session['game_id'],str(job)[:120],now,now))
            db.execute('INSERT INTO frames VALUES(?,?,?,?)', (rid,frame['seq'],now,raw))
            for event in frame['events']:
                if isinstance(event, dict) and type(event.get('id')) is int:
                    db.execute('INSERT OR IGNORE INTO events VALUES(?,?,?)',
                               (rid,event['id'],json.dumps(event,allow_nan=False)))
            db.execute('UPDATE runs SET frames=frames+1,updated=? WHERE id=?', (now,rid))
        self.error = ''
        return True

    def runs(self, sid='', limit=50):
        with self.lock, self._connect() as db:
            rows = db.execute('SELECT * FROM runs WHERE (?="" OR sid=?) ORDER BY updated DESC LIMIT ?',
                              (sid,sid,min(50,max(1,limit)))).fetchall()
        return {'runs': [dict(r) for r in rows], 'recording_error': self.error}

    def run(self, rid, after=-1):
        if not RUN_ID.fullmatch(rid):
            raise ValueError('Invalid run identifier')
        with self.lock, self._connect() as db:
            run = db.execute('SELECT * FROM runs WHERE id=?', (rid,)).fetchone()
            if run is None:
                raise KeyError(rid)
            rows = db.execute('SELECT seq,received,body FROM frames WHERE run=? AND seq>? ORDER BY seq LIMIT 1200',
                              (rid,after)).fetchall()
            events = db.execute('SELECT body FROM events WHERE run=? ORDER BY id LIMIT 2001',(rid,)).fetchall()
        return {'run': dict(run), 'samples': [json.loads(r['body']) | {'received_at':r['received']} for r in rows],
                'events': [json.loads(e['body']) for e in events[:2000]],
                'events_truncated': len(events) > 2000,
                'next_after': rows[-1]['seq'] if rows else after,
                'has_more': len(rows)==1200, 'recording_error': self.error}

    def live(self, sid, active=None):
        with self.lock, self._connect() as db:
            row = db.execute('SELECT f.body,f.received FROM frames f JOIN runs r ON r.id=f.run '
                             'WHERE r.sid=? ORDER BY f.received DESC LIMIT 1',(sid,)).fetchone()
        if not row:
            return {'live':False,'reason':'No native PSO review samples have arrived', 'recording_error':self.error}
        age = max(0,self.clock()-row['received'])
        frame = json.loads(row['body'])
        source_age = self.clock()-frame['observed_at']
        live = (age <= 12 and -2 <= source_age <= 12
                and frame.get('source_running_at_ingest') is True and active is not False)
        return {'frame':frame,'age_s':age,'source_age_s':source_age,'live':live,
                'reason': '' if live else 'Source sample is stale, its clock differs, or the session is no longer running',
                'recording_error':self.error}


def install(app, config, auth, store):
    from fastapi import Depends, HTTPException
    review = ReviewStore(config.data_dir)
    app.state.pso_review = review

    @app.get('/api/pso/reviewer/runs')
    def runs(sid: str='', actor=Depends(auth)):
        return review.runs(sid)

    @app.get('/api/pso/reviewer/run/{rid}')
    def run(rid: str, after: int=-1, actor=Depends(auth)):
        try:
            return review.run(rid,after)
        except ValueError as error:
            raise HTTPException(422,str(error)) from error
        except KeyError as error:
            raise HTTPException(404,'Unknown PSO run segment') from error

    @app.get('/api/pso/reviewer/live/{sid}')
    def live(sid: str, actor=Depends(auth)):
        active = (store.get('session',sid) or {}).get('state') == 'running' if store is not None else None
        return review.live(sid, active=active)

    @app.get('/api/pso/reviewer/crystal/{rid}')
    def crystal(rid: str, actor=Depends(auth)):
        try:
            data = review.run(rid)
            samples = list(data['samples'])
            while data['has_more'] and len(samples) < MAX_FRAMES:
                data = review.run(rid, data['next_after'])
                samples.extend(data['samples'])
        except (KeyError, ValueError) as error:
            raise HTTPException(404,'Unknown PSO run segment') from error
        body = {'schema':'gbox.pso.run-crystal/1','run':data['run'], 'events':data['events'],
                'samples':samples, 'has_more':data['has_more'],
                'events_truncated':data['events_truncated'],
                'source':'native_runtime_observations', 'navigation_authority':False,
                'room_clear_inference':False}
        body['sha256'] = hashlib.sha256(json.dumps(body,sort_keys=True,allow_nan=False).encode()).hexdigest()
        return body
