"""The PSO interactive 2D map feed (operator 2026-11-02: "the 2d map is the real goal - once we look
at that we can point people on a 2d level where they want to go ... this game beaten with hooks and
intricate understanding because we are latched into the game code").

A read-only aggregator that assembles a top-down map model of the live PSO level ENTIRELY from the
game's RAM - no vision, no screenshots. It merges, in priority order:

  1. the live `telemetry.stats.pso_map` block the nav agent (pso_coop) emits each tick
     (players, enemies, switches/doors/warps, the walkable surface, P1's A* path, objective);
  2. the persisted crystal (pso-knowledge.json): the learned walkable surface + static objects per
     room fingerprint - the growing full-map DB, so learned areas render even when not live;
  3. a bounded stage-flag read (read_memory RPC) that resolves door/switch open|pressed live.

Any missing layer is simply omitted (graceful degradation): even with nothing but the existing
telemetry it shows the players, the current room and the objective (players are synthesized from
`stats.steering_evidence_json`). The feed never writes memory and never touches pso_coop.

Routes (installed from server.py):
  GET  /api/pso/map/<sid>             the map model (clients/web/viz/pso-map.js polls this)
  GET  /api/sessions/<sid>/pso-directive   the newest map directive (nav agent polls this)
  POST /api/sessions/<sid>/pso-directive   the operator's click -> a directive

Contracts (model shape, the pso_map block, the crystal surface schema, directive payloads):
docs/pso-map-directives.md.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

# Verified 3OE2 stage-flag array (source of truth: gbox/pso_coop_gates.py, reverse-engineered from
# the barrier flag accessor 0x80229220). 18 groups x 32 bytes, group == floor, MSB-first bit array.
STAGE_FLAG_BASE = 0x80515CC8
STAGE_GROUP_SIZE = 32
STAGE_FLAG_GROUPS = 18

SCHEMA = "gbox.pso.map/1"
_STAGE_CACHE_TTL = 1.0           # a live stage-flag read is cached this long per (sid, floor)
_CRYSTAL_CACHE: dict[str, tuple[float, dict]] = {}   # path -> (mtime, rooms)
_stage_cache: dict[str, tuple[float, bytes]] = {}


# ----------------------------------------------------------------------------- stage flags (pure)
def flag_set(group_bytes: bytes, index: int) -> bool | None:
    """True/False for stage flag `index` within one 32-byte group (MSB-first), or None if the group
    is short or the index is out of range."""
    if not isinstance(group_bytes, (bytes, bytearray)) or not (0 <= index <= 255):
        return None
    byte = index // 8
    if byte >= len(group_bytes):
        return None
    return bool(group_bytes[byte] & (0x80 >> (index % 8)))


# ----------------------------------------------------------------------------- players (pure)
def players_from_steering(steering_json) -> list[dict]:
    """P1..Pn positions from the newest steering event in stats.steering_evidence_json. P1 (slot 1)
    is the leader; the rest are swarm. Uses each player's post-move `after` pose (else `before`)."""
    try:
        doc = json.loads(steering_json) if isinstance(steering_json, str) else steering_json
        events = (doc or {}).get("events") or []
        if not events:
            return []
        players = events[-1].get("players") or {}
    except (ValueError, TypeError, AttributeError):
        return []
    out = []
    for key in sorted(players, key=lambda k: str(k)):
        pose = players[key].get("after") or players[key].get("before") or {}
        try:
            slot = int(key)
        except (ValueError, TypeError):
            continue
        row = {"slot": slot, "role": "leader" if slot == 1 else "swarm"}
        for src, dst in (("x", "x"), ("y", "y"), ("z", "z"), ("hp", "hp"), ("room", "room"),
                         ("heading_deg", "heading")):
            if isinstance(pose.get(src), (int, float)):
                row[dst] = pose[src]
        if "x" in row and "z" in row:
            out.append(row)
    return out


# ----------------------------------------------------------------------------- nav-agent live block
def merge_pso_block(model: dict, block: dict) -> None:
    """Fold the nav agent's live telemetry `pso_map` block into the model (the live layer)."""
    if not isinstance(block, dict):
        return
    area = block.get("area") or {}
    for k in ("episode", "floor", "room", "fingerprint"):
        if area.get(k) is not None:
            model[k] = area[k]
    if isinstance(block.get("surface"), dict):
        model["surface"] = block["surface"]
    if isinstance(block.get("players"), list) and block["players"]:
        model["players"] = block["players"]
    if isinstance(block.get("enemies"), list):
        model["enemies"] = block["enemies"]
    if isinstance(block.get("path"), list):
        model["path"] = block["path"]
    if isinstance(block.get("target"), dict):
        model["target"] = block["target"]
    if block.get("objective"):
        model["objective"] = str(block["objective"])
    for obj in block.get("objects") or []:
        if not isinstance(obj, dict):
            continue
        kind = obj.get("kind")
        base = {k: obj[k] for k in ("id", "x", "z", "flag_index") if k in obj}
        if kind == "switch":
            base["opens"] = obj.get("opens")
            base["pressed"] = {"pressed": True, "unpressed": False}.get(obj.get("state"))
            model["switches"].append(base)
        elif kind == "door":
            base["type"] = obj.get("type")
            base["to_room"] = obj.get("to_room")
            base["open"] = {"open": True, "locked": False}.get(obj.get("state"))
            model["doors"].append(base)
        elif kind == "warp":
            base["kind"] = obj.get("warp_kind") or "warp"
            base["to"] = obj.get("to")
            model["warps"].append(base)
        elif kind == "exit":
            model["exit"] = {"x": obj.get("x"), "z": obj.get("z"),
                             "kind": obj.get("warp_kind") or "teleporter"}


# ----------------------------------------------------------------------------- crystal (learned DB)
def crystal_area(rooms: dict, fingerprint) -> dict:
    """The persisted surface + static objects for this room fingerprint, or {}."""
    rec = (rooms or {}).get(fingerprint) if isinstance(rooms, dict) else None
    return rec if isinstance(rec, dict) else {}


def learned_areas(rooms: dict) -> list[dict]:
    """A browsable summary of every area the crystal has learned a surface/objects for."""
    out = []
    for fp, rec in (rooms or {}).items():
        if not isinstance(rec, dict):
            continue
        has_surface = isinstance(rec.get("surface"), dict)
        if not (has_surface or rec.get("switches") or rec.get("doors")):
            continue
        out.append({"fingerprint": fp, "episode": rec.get("episode"), "floor": rec.get("floor"),
                    "room": rec.get("room"), "has_surface": has_surface,
                    "switches": len(rec.get("switches") or []), "doors": len(rec.get("doors") or [])})
    out.sort(key=lambda a: (a.get("floor") or 0, a.get("room") or 0))
    return out


def apply_crystal(model: dict, rec: dict) -> None:
    """Add the crystal's static surface/objects where the live block did not already supply them."""
    if not rec:
        return
    if not model.get("surface") and isinstance(rec.get("surface"), dict):
        model["surface"] = rec["surface"]
    if not model["switches"]:
        for s in rec.get("switches") or []:
            if isinstance(s, dict):
                model["switches"].append({**s, "pressed": s.get("pressed")})
    if not model["doors"]:
        for d in rec.get("doors") or []:
            if isinstance(d, dict):
                model["doors"].append({**d, "open": d.get("open")})
    if not model["warps"]:
        for w in rec.get("warps") or []:
            if isinstance(w, dict):
                model["warps"].append(dict(w))
    if not model.get("exit") and isinstance(rec.get("exit"), dict):
        model["exit"] = dict(rec["exit"])


# ----------------------------------------------------------------------------- bounds (pure)
def surface_bounds(surface: dict) -> list | None:
    if not isinstance(surface, dict):
        return None
    b = surface.get("bounds")
    if isinstance(b, list) and len(b) == 4 and all(isinstance(v, (int, float)) for v in b):
        return [float(v) for v in b]
    origin, cell = surface.get("origin"), surface.get("cell")
    cols, rows = surface.get("cols"), surface.get("rows")
    if (isinstance(origin, list) and len(origin) == 2 and isinstance(cell, (int, float))
            and isinstance(cols, int) and isinstance(rows, int)):
        return [origin[0], origin[1], origin[0] + cols * cell, origin[1] + rows * cell]
    return None


def bounds_of(model: dict) -> list | None:
    """World extent to fit the camera to: the surface if present, else the players + objects."""
    b = surface_bounds(model.get("surface"))
    if b:
        return b
    xs, zs = [], []
    for coll in (model.get("players"), model.get("enemies"), model.get("switches"),
                 model.get("doors"), model.get("warps")):
        for it in coll or []:
            if isinstance(it, dict) and isinstance(it.get("x"), (int, float)) and isinstance(it.get("z"), (int, float)):
                xs.append(it["x"]); zs.append(it["z"])
    ex = model.get("exit")
    if isinstance(ex, dict) and isinstance(ex.get("x"), (int, float)) and isinstance(ex.get("z"), (int, float)):
        xs.append(ex["x"]); zs.append(ex["z"])
    if not xs:
        return None
    pad = 200.0
    return [min(xs) - pad, min(zs) - pad, max(xs) + pad, max(zs) + pad]


# ----------------------------------------------------------------------------- the model (assembly)
def build_model(sid: str, tel: dict, crystal_rooms: dict | None, *, peek=None, actor="agent",
                now: float | None = None) -> dict:
    """Assemble the read-only map model from telemetry + crystal (+ optional live stage-flag read)."""
    now = time.time() if now is None else now
    stats = (tel or {}).get("stats") or {}
    model = {
        "schema": SCHEMA, "sid": sid, "seq": 0,
        "live": bool((tel or {}).get("running")), "age_s": (tel or {}).get("age_s"),
        "title": (tel or {}).get("title", ""), "units": "pso",
        "episode": stats.get("episode"), "floor": stats.get("floor"),
        "room": stats.get("forward_room"), "fingerprint": None,
        "surface": None, "rooms": [], "switches": [], "doors": [], "warps": [], "exit": None,
        "enemies": [], "players": [], "path": [], "target": None,
        "objective": stats.get("forward_fallback_target") or "", "learned_areas": [],
        "stage_flags": None, "generated": now,
    }
    # seq: a cheap change signal for the client (telemetry age + bot's action)
    model["seq"] = int(now * 10) if model["live"] else 0

    block = stats.get("pso_map") if isinstance(stats.get("pso_map"), dict) else None
    if block:
        merge_pso_block(model, block)
    if not model["players"]:
        model["players"] = players_from_steering(stats.get("steering_evidence_json"))

    rooms = crystal_rooms if isinstance(crystal_rooms, dict) else {}
    apply_crystal(model, crystal_area(rooms, model.get("fingerprint")))
    model["learned_areas"] = learned_areas(rooms)

    # Live door/switch state from the stage-flag array (bounded, cached, read-only).
    floor = model.get("floor")
    need_flags = any(o.get("flag_index") is not None and o.get("pressed") is None for o in model["switches"]) or \
                 any(o.get("flag_index") is not None and o.get("open") is None for o in model["doors"])
    if peek is not None and isinstance(floor, int) and 0 <= floor < STAGE_FLAG_GROUPS and need_flags:
        group = _read_stage_group(sid, floor, peek, actor, now)
        if group is not None:
            model["stage_flags"] = {"floor": floor, "read": True, "group_hex": group.hex(" ")}
            for s in model["switches"]:
                if s.get("flag_index") is not None and s.get("pressed") is None:
                    s["pressed"] = flag_set(group, int(s["flag_index"]))
            for d in model["doors"]:
                if d.get("flag_index") is not None and d.get("open") is None:
                    d["open"] = flag_set(group, int(d["flag_index"]))

    model["bounds"] = bounds_of(model)
    return model


def _read_stage_group(sid, floor, peek, actor, now):
    cached = _stage_cache.get(sid)
    if cached and now - cached[0] < _STAGE_CACHE_TTL:
        return cached[1]
    try:
        data = bytes.fromhex(peek(sid, STAGE_FLAG_BASE + floor * STAGE_GROUP_SIZE, STAGE_GROUP_SIZE, actor))
    except Exception:                       # noqa: BLE001 - a missed read just leaves live state unknown
        return None
    if len(data) != STAGE_GROUP_SIZE:
        return None
    _stage_cache[sid] = (now, data)
    if len(_stage_cache) > 64:
        for k in sorted(_stage_cache, key=lambda k: _stage_cache[k][0])[:-64]:
            _stage_cache.pop(k, None)
    return data


# ----------------------------------------------------------------------------- crystal location (I/O)
def _crystal_root(config):
    base = getattr(config, "runtime", None) or getattr(config, "data_dir", None)
    return Path(base) / "autoplay" / "pso-coop" if base else None


def load_crystal_rooms(config) -> dict:
    """The rooms map of the most-recently-written pso-knowledge.json under the pso-coop runtime (the
    live run's crystal), cached by path+mtime. {} when none / unreadable."""
    root = _crystal_root(config)
    if not root or not root.is_dir():
        return {}
    newest, newest_mtime = None, -1.0
    try:
        for f in root.glob("*/pso-knowledge.json"):
            try:
                mt = f.stat().st_mtime
            except OSError:
                continue
            if mt > newest_mtime:
                newest, newest_mtime = f, mt
    except OSError:
        return {}
    if newest is None:
        return {}
    key = str(newest)
    cached = _CRYSTAL_CACHE.get(key)
    if cached and cached[0] == newest_mtime:
        return cached[1]
    try:
        data = json.loads(newest.read_text(encoding="utf-8"))
        rooms = data.get("rooms") if isinstance(data, dict) else None
        rooms = rooms if isinstance(rooms, dict) else {}
    except (OSError, ValueError, TypeError):
        rooms = {}
    _CRYSTAL_CACHE.clear()
    _CRYSTAL_CACHE[key] = (newest_mtime, rooms)
    return rooms


# ----------------------------------------------------------------------------- routes
def install(app, store, config, auth, *, peek=None):
    from fastapi import Depends, HTTPException
    from pydantic import BaseModel
    from .screensaver import telemetry_get
    from . import pso_directive

    @app.get("/api/pso/map/{sid}")
    def pso_map_feed(sid: str, actor=Depends(auth)):
        """The RAM-derived top-down map model for this PSO session (read-only, bounded)."""
        tel = telemetry_get(sid)
        rooms = load_crystal_rooms(config)
        return build_model(sid, tel, rooms, peek=peek, actor=str(actor))

    class PsoDirectiveIn(BaseModel):
        kind: str
        x: float | None = None
        z: float | None = None
        floor: int | None = None
        room: int | None = None
        switch_id: str | None = None
        enemy_id: str | None = None
        door_id: str | None = None

    @app.get("/api/sessions/{sid}/pso-directive")
    def pso_directive_get(sid: str, actor=Depends(auth)):
        return {"directive": pso_directive.latest(sid), "kinds": list(pso_directive.KINDS)}

    @app.post("/api/sessions/{sid}/pso-directive")
    def pso_directive_post(sid: str, body: PsoDirectiveIn, actor=Depends(auth)):
        """The operator's map click: a structured order for P1 (the nav agent consumes it)."""
        try:
            row = pso_directive.post(sid, body.kind, body.model_dump(exclude={"kind"}), source=str(actor))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        store.audit(actor, "pso.map_directive", sid, {k: v for k, v in row.items() if k not in ("at", "until")})
        return {"directive": row}
