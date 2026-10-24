"""The tactical map's control-plane side (docs/tactical_map.md): the newest frame of each session's Mercenaries round and
the stages those frames name, held in memory (a live view only: nothing here is kept across a restart - the worker's
publisher (gbox.mercs.tactical) sends a stage again when a frame's reply says need_stage).

    POST /api/autoplay/tactical/{sid}          a frame -> {"ok", "seq", "need_stage"}
    GET  /api/autoplay/tactical/{sid}?after=N  the newest frame with "seq", "age_s" and "live" (a frame within LIVE_S);
                                               {"seq", "same": true, "age_s", "live"} when N is that frame's seq already;
                                               {} when no frame came for TTL_S
    PUT  /api/autoplay/tactical/stage/{key}    a stage (the same key always carries the same layout)
    GET  /api/autoplay/tactical/stage/{key}    that stage, or 404
Frames come at most 10 a second per session and are a few KB; a stage is up to a few hundred KB, once per stage.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from collections import OrderedDict

from fastapi import Depends, HTTPException, Request

FORMAT = 1
FRAME_MAX = 64 * 1024
STAGE_MAX = 4 * 1024 * 1024
TTL_S = 600.0                     # a session's last frame is forgotten this long after it came
LIVE_S = 3.0                      # a frame younger than this is live (the publisher sends 1-10 a second)
STAGES_KEEP = 24
KEY_RE = re.compile(r"[A-Za-z0-9._-]{1,120}")
SID_RE = re.compile(r"[\w.-]{1,120}")


class Store:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.frames: dict[str, dict] = {}          # sid -> {"frame", "seq", "at"}
        self.stages: OrderedDict[str, dict] = OrderedDict()
        self.seq = 0
        self.goals: dict[str, dict] = {}
        self.lock = threading.Lock()

    def put_frame(self, sid: str, frame: dict) -> dict:
        if not SID_RE.fullmatch(sid or ""):
            raise ValueError("bad session id")
        if not isinstance(frame, dict) or frame.get("v") != FORMAT:
            raise ValueError(f"not a gbox.tactical/{FORMAT} frame")
        key = frame.get("stage") or ""
        if key and not KEY_RE.fullmatch(str(key)):
            raise ValueError("bad stage key")
        now = self.clock()
        with self.lock:
            self.seq += 1
            self.frames[sid] = {"frame": frame, "seq": self.seq, "at": now}
            for k in [k for k, v in self.frames.items() if now - v["at"] > TTL_S]:
                self.frames.pop(k, None)
                self.goals.pop(k, None)
            reply = {"ok": True, "seq": self.seq, "need_stage": bool(key) and key not in self.stages}
            goal = self.goals.get(sid)
            if goal and (goal['round'] != frame.get('goal_round') or goal['stage'] != key or now > goal['expires']):
                self.goals.pop(sid, None)
                goal = None
            if goal:
                reply['operator_goal'] = dict(goal)
            return reply

    def command(self, sid: str, body: dict) -> dict:
        """A live, observed entity only. The game worker remains the sole input owner."""
        if not isinstance(body, dict):
            raise ValueError('Invalid map command')
        with self.lock:
            row = self.frames.get(sid)
            if not row or self.clock() - row['at'] >= LIVE_S:
                raise ValueError('Waiting for fresh gameplay before accepting a map goal')
            frame = row['frame']
            if frame.get('screen') != 'playing' or not frame.get('player') or not frame.get('goal_round'):
                raise ValueError('This session is not ready for map commands')
            if body == {'cancel': True}:
                goal = self.goals.get(sid)
                if goal:
                    goal = self.goals[sid] = dict(goal, id=uuid.uuid4().hex, state='cancelled')
                    return dict(goal)
                return {'state': 'cancelled', 'label': 'Map goal'}
            if set(body) != {'round', 'stage', 'kind', 'id', 'seq'} or body['round'] != frame.get('goal_round') \
                    or body['stage'] != frame.get('stage') or type(body['seq']) is not int or not 0 < body['seq'] <= row['seq']:
                raise ValueError('The map round changed; choose the item again')
            kind, entity_id = body['kind'], body['id']
            if kind not in ('bonus', 'item') or kind not in frame.get('goal_capabilities', []) or type(entity_id) is not int:
                raise ValueError('This entity does not support collection commands')
            entities = frame.get('bonuses' if kind == 'bonus' else 'items', [])
            entity = next((e for e in entities if e.get('id') == entity_id and not e.get('taken')), None)
            if not entity:
                raise ValueError('This item is no longer present in the live game')
            label = entity.get('name') or ('Combo bonus' if entity.get('kind') == 'combo' else 'Time bonus')
            goal = {'id': uuid.uuid4().hex, 'round': body['round'], 'stage': body['stage'],
                    'kind': kind, 'entity_id': entity_id, 'pos': entity['pos'], 'label': str(label)[:80],
                    'state': 'queued', 'expires': self.clock()+300.}
            self.goals[sid] = goal
            return dict(goal)

    def get_frame(self, sid: str, after: int | None = None) -> dict:
        now = self.clock()
        with self.lock:
            row = self.frames.get(sid)
        if not row or now - row["at"] > TTL_S:
            return {}
        age = round(now - row["at"], 2)
        head = {"seq": row["seq"], "age_s": age, "live": age < LIVE_S}
        if after is not None and after == row["seq"]:
            return head | {"same": True}
        return row["frame"] | head

    def put_stage(self, key: str, stage: dict) -> dict:
        if not KEY_RE.fullmatch(key or ""):
            raise ValueError("bad stage key")
        if not isinstance(stage, dict) or stage.get("v") != FORMAT or stage.get("kind") not in ("mesh", "grid"):
            raise ValueError(f"not a gbox.tactical/{FORMAT} stage")
        with self.lock:
            self.stages[key] = dict(stage, key=key)
            self.stages.move_to_end(key)
            while len(self.stages) > STAGES_KEEP:
                self.stages.popitem(last=False)
        return {"ok": True}

    def get_stage(self, key: str) -> dict | None:
        with self.lock:
            st = self.stages.get(key)
            if st is not None:
                self.stages.move_to_end(key)
            return st


def install(app, auth) -> Store:
    store = Store()
    app.state.tactical_map = store

    async def body_of(request: Request, limit: int):
        raw = await request.body()
        if len(raw) > limit:
            raise HTTPException(413, f"larger than {limit // 1024} KB")
        try:
            return json.loads(raw)
        except ValueError:
            raise HTTPException(422, "not JSON") from None

    @app.post("/api/autoplay/tactical/{sid}")
    async def tactical_frame_put(sid: str, request: Request, actor=Depends(auth)):
        try:
            return store.put_frame(sid, await body_of(request, FRAME_MAX))
        except ValueError as e:
            raise HTTPException(422, str(e)) from None

    @app.get("/api/autoplay/tactical/stage/{key}")
    async def tactical_stage_get(key: str, actor=Depends(auth)):
        st = store.get_stage(key)
        if st is None:
            raise HTTPException(404, f"no stage {key}")
        return st

    @app.put("/api/autoplay/tactical/stage/{key}")
    async def tactical_stage_put(key: str, request: Request, actor=Depends(auth)):
        try:
            return store.put_stage(key, await body_of(request, STAGE_MAX))
        except ValueError as e:
            raise HTTPException(422, str(e)) from None

    @app.get("/api/autoplay/tactical/{sid}")
    async def tactical_frame_get(sid: str, after: int | None = None, actor=Depends(auth)):
        return store.get_frame(sid, after)

    @app.post("/api/autoplay/tactical/{sid}/goal")
    async def tactical_goal(sid: str, request: Request, actor=Depends(auth)):
        try:
            return store.command(sid, await body_of(request, 2048))
        except ValueError as e:
            raise HTTPException(422, str(e)) from None

    return store
