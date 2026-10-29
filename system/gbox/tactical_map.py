"""The tactical map's control-plane side (docs/tactical_map.md): the newest frame of each session's Mercenaries round and
the stages those frames name, held in memory (a live view only: nothing here is kept across a restart - the worker's
publisher (gbox.mercs.tactical) sends a stage again when a frame's reply says need_stage).

    POST /api/autoplay/tactical/{sid}          a frame -> {"ok", "seq", "need_stage"}
    GET  /api/autoplay/tactical/{sid}?after=N  the newest frame with "seq", "age_s" and "live" (a frame within LIVE_S);
                                               {"seq", "same": true, "age_s", "live"} when N is that frame's seq already;
                                               {} when no frame came for TTL_S
    PUT  /api/autoplay/tactical/stage/{key}    a stage (the same key always carries the same layout)
    GET  /api/autoplay/tactical/stage/{key}    that stage, or 404
    GET  /api/mercs/portraits/{title}          the title's enemy portraits: {"portraits": {class: {name, at, dist}}}
    GET  /api/mercs/portraits/{title}/{cls}.jpg  one portrait (the legend's picture), or 404
Frames come at most 10 a second per session and are a few KB; a stage is up to a few hundred KB, once per stage.

Enemy portraits (operator 2026-10-29: "show them in the merc live map and run reviewer with profile pictures as a
legend"): a frame's portrait hint ({"class", "dist"}: the bot's laser dot is on an enemy of that class, so he is under
the crosshair) crops the session's newest picture around its centre - sized for his distance - into that class's
portrait, kept on disk (gbox-data/mercs/portraits/<title>/<class>.jpg). A class gets a new one at most every
PORTRAIT_EVERY_S, and only nearer PORTRAIT_BEST_CM than the one it has.
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
PORTRAIT_EVERY_S, PORTRAIT_BEST_CM, PORTRAIT_PX = 20.0, 350.0, 160
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


class Portraits:
    """Each title's enemy portraits on disk: offer(title, hint, jpeg) crops the picture (crop_portrait) when the class
    has none, or this one is nearer PORTRAIT_BEST_CM, at most every PORTRAIT_EVERY_S a class."""

    def __init__(self, root, clock=time.time):
        from pathlib import Path
        self.root, self.clock = Path(root), clock
        self.lock = threading.Lock()
        self.tried: dict = {}

    def _index_path(self, title):
        return self.root / title / "index.json"

    def index(self, title) -> dict:
        try:
            return json.loads(self._index_path(title).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def path(self, title, cls):
        from .mercs import enemy_kinds
        if not (enemy_kinds.valid_title(title) and enemy_kinds.valid_class(cls)):
            return None
        return self.root / title / f"{cls}.jpg"

    def offer(self, title, hint, jpeg) -> bool:
        from .mercs import enemy_kinds
        if not isinstance(hint, dict) or not jpeg:
            return False
        cls, dist = hint.get("class"), hint.get("dist")
        if not (enemy_kinds.valid_title(title) and enemy_kinds.valid_class(cls)) or not isinstance(dist, (int, float)):
            return False
        now = self.clock()
        with self.lock:
            if now - self.tried.get((title, cls), -1e9) < PORTRAIT_EVERY_S:
                return False
            have = self.index(title).get(cls)
            if have and abs(dist - PORTRAIT_BEST_CM) >= abs((have.get("dist") or 1e9) - PORTRAIT_BEST_CM):
                return False
            self.tried[(title, cls)] = now
        picture = crop_portrait(jpeg, dist)
        if picture is None:
            return False
        with self.lock:
            folder = self.root / title
            folder.mkdir(parents=True, exist_ok=True)
            tmp = folder / f".{cls}.tmp"
            tmp.write_bytes(picture)
            tmp.replace(folder / f"{cls}.jpg")
            idx = self.index(title)
            idx[cls] = {"name": enemy_kinds.name(title, cls), "at": round(now, 1), "dist": round(float(dist))}
            tmp = folder / ".index.tmp"
            tmp.write_text(json.dumps(idx, sort_keys=True), encoding="utf-8")
            tmp.replace(self._index_path(title))
        return True


def crop_portrait(jpeg: bytes, dist: float) -> bytes | None:
    """The square around the picture's centre (a touch above it: aimed at his chest, his head shows), its side the
    picture's height times 300 cm / his distance (bounded 18-60 %), as a PORTRAIT_PX JPEG. None when it can't decode."""
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(jpeg)).convert("RGB")
        w, h = im.size
        side = max(0.18 * h, min(0.6 * h, h * 300.0 / max(float(dist), 1.0)))
        cx, cy = w / 2, h * 0.45
        box = (int(max(0, cx - side / 2)), int(max(0, cy - side / 2)), int(min(w, cx + side / 2)), int(min(h, cy + side / 2)))
        out = io.BytesIO()
        im.crop(box).resize((PORTRAIT_PX, PORTRAIT_PX)).save(out, "JPEG", quality=85)
        return out.getvalue()
    except Exception:                                       # noqa: BLE001 - no portrait never costs a frame
        return None


def install(app, auth, frame_of=None, portraits_root=None) -> Store:
    """frame_of(sid) -> the session's newest JPEG (the portraits' source); portraits_root: where they are kept."""
    store = Store()
    app.state.tactical_map = store
    portraits = Portraits(portraits_root) if portraits_root is not None else None
    app.state.enemy_portraits = portraits

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
            frame = await body_of(request, FRAME_MAX)
            reply = store.put_frame(sid, frame)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        hint = frame.get("portrait") if isinstance(frame, dict) else None
        if hint and portraits is not None and frame_of is not None:
            try:
                jpeg = frame_of(sid)
            except Exception:                               # noqa: BLE001
                jpeg = None
            if jpeg:                                        # off the event loop: a decode and a crop
                threading.Thread(target=portraits.offer, args=(frame.get("title"), hint, jpeg), daemon=True,
                                 name="enemy-portrait").start()
        return reply

    @app.get("/api/mercs/portraits/{title}")
    async def enemy_portraits(title: str, actor=Depends(auth)):
        from .mercs import enemy_kinds
        if portraits is None or not enemy_kinds.valid_title(title):
            return {"portraits": {}}
        return {"portraits": portraits.index(title)}

    @app.get("/api/mercs/portraits/{title}/{name}")
    async def enemy_portrait(title: str, name: str, actor=Depends(auth)):
        from fastapi.responses import Response
        path = portraits.path(title, name.removesuffix(".jpg")) if portraits is not None else None
        if path is None or not path.is_file():
            raise HTTPException(404, "no portrait yet")
        return Response(path.read_bytes(), media_type="image/jpeg", headers={"cache-control": "max-age=60"})

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
