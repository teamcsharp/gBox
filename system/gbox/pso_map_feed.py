"""PSO map feed + directive writer - the "map agent" server side of docs/pso-map-directives.md.

The PSO bot (pso_coop + pso_map) already, from RAM: extracts each area's collision surface to
`<root>/pso-maps/<fingerprint>.json`, folds a `surface` summary into the crystal
`<root>/pso-knowledge.json` (the growing map DB index), polls the operator's directive from
`<root>/pso-directive.json` (by mtime), and echoes the active directive in telemetry
`stats["map_directive"]` (+ the live area in `stats["map_surface_fingerprint"]`).

This module is the half the Mercenaries Map viewer / 2D map client talks to:
  GET  /api/pso/map/<sid>                 the live map model: the current area's surface + the live
                                          players/floor/objective/active-directive + a crystal index
                                          of every learned area + optional live gate flag states.
  GET  /api/sessions/<sid>/pso-directive  the current directive file (pso-directive.json), if any.
  POST /api/sessions/<sid>/pso-directive  WRITE pso-directive.json (the operator's click); the bot
                                          polls it. Format + consumption: docs/pso-map-directives.md.

Everything is RAM-derived upstream; this is read-only except for the single directive file it writes
on an operator click. It never touches pso_coop; it imports pso_map only to reuse the directive
validator (pso_map.parse_directive) so the written file matches exactly what the bot consumes.

`<root>` is the campaign runtime root `<config.runtime>/autoplay/pso-coop/<card_id>/` (same as
pso_coop.play(): RoomMap + crystal + surfaces + directive all live there). This module finds the live
run's root as the one whose directive/crystal/surfaces were written most recently.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

# Verified 3OE2 stage-flag array (source of truth: gbox/pso_coop_gates.py). 18 groups x 32 bytes,
# group == floor, MSB-first bit array. Used to read a gate/switch's open|pressed state live.
STAGE_FLAG_BASE = 0x80515CC8
STAGE_GROUP_SIZE = 32
STAGE_FLAG_GROUPS = 18

SCHEMA = "gbox.pso.map/1"
_FINGERPRINT_RE = re.compile(r"\A[0-9a-f]{8,128}\Z")
_STAGE_CACHE_TTL = 1.0
_stage_cache: dict[str, tuple[float, bytes]] = {}


# ----------------------------------------------------------------------------- stage flags (pure)
def flag_set(group_bytes, index) -> bool | None:
    """True/False for stage flag `index` within one 32-byte group (MSB-first), or None out of range."""
    if not isinstance(group_bytes, (bytes, bytearray)) or type(index) is not int or not (0 <= index <= 255):
        return None
    byte = index // 8
    if byte >= len(group_bytes):
        return None
    return bool(group_bytes[byte] & (0x80 >> (index % 8)))


# ----------------------------------------------------------------------------- players (pure)
def players_from_steering(steering_json) -> list[dict]:
    """P1..Pn live positions from the newest steering event in stats.steering_evidence_json. P1 is
    the leader; the rest swarm. Uses each player's post-move `after` pose (else `before`)."""
    try:
        doc = json.loads(steering_json) if isinstance(steering_json, str) else steering_json
        events = (doc or {}).get("events") or []
        if not events:
            return []
        players = events[-1].get("players") or {}
    except (ValueError, TypeError, AttributeError):
        return []
    out = []
    for key in sorted(players, key=str):
        pose = players[key].get("after") or players[key].get("before") or {}
        try:
            slot = int(key)
        except (ValueError, TypeError):
            continue
        row = {"slot": slot, "role": "leader" if slot == 1 else "swarm"}
        for src, dst in (("x", "x"), ("y", "y"), ("z", "z"), ("hp", "hp"), ("room", "room"), ("heading_deg", "heading")):
            if isinstance(pose.get(src), (int, float)):
                row[dst] = pose[src]
        if "x" in row and "z" in row:
            out.append(row)
    return out


def players_from_surface(players_map) -> list[dict]:
    """Fallback: the surface file's `players` map {"1":[x,z], ...} as a player list."""
    out = []
    for key, xz in (players_map or {}).items():
        if isinstance(xz, (list, tuple)) and len(xz) >= 2 and all(isinstance(v, (int, float)) for v in xz[:2]):
            try:
                slot = int(key)
            except (ValueError, TypeError):
                continue
            out.append({"slot": slot, "role": "leader" if slot == 1 else "swarm", "x": xz[0], "z": xz[1]})
    return out


# ----------------------------------------------------------------------------- bounds (pure)
def bounds_list(bounds) -> list | None:
    """The surface bounds dict {min_x,min_z,max_x,max_z} as a [minx,minz,maxx,maxz] list."""
    if isinstance(bounds, dict) and all(k in bounds for k in ("min_x", "min_z", "max_x", "max_z")):
        v = [bounds["min_x"], bounds["min_z"], bounds["max_x"], bounds["max_z"]]
        if all(isinstance(q, (int, float)) for q in v):
            return [float(q) for q in v]
    return None


def bounds_from_points(*collections) -> list | None:
    xs, zs = [], []
    for coll in collections:
        for it in coll or []:
            if isinstance(it, dict) and isinstance(it.get("x"), (int, float)) and isinstance(it.get("z"), (int, float)):
                xs.append(it["x"]); zs.append(it["z"])
    if not xs:
        return None
    pad = 200.0
    return [min(xs) - pad, min(zs) - pad, max(xs) + pad, max(zs) + pad]


# ----------------------------------------------------------------------------- crystal index (pure)
def learned_areas(rooms) -> list[dict]:
    """A browsable index of every area whose collision surface the crystal has recorded a summary of
    (bot folds `surface` = surface_summary into each room record)."""
    out = []
    for fp, rec in (rooms or {}).items():
        if not isinstance(rec, dict) or not isinstance(rec.get("surface"), dict):
            continue
        s = rec["surface"]
        out.append({"fingerprint": fp, "episode": s.get("episode"), "floor": s.get("floor"),
                    "room": s.get("room"), "cell_count": s.get("cell_count"),
                    "bounds": bounds_list(s.get("bounds")), "gates": s.get("gates"), "warps": s.get("warps")})
    out.sort(key=lambda a: (a.get("floor") or 0, a.get("room") or 0))
    return out


# ----------------------------------------------------------------------------- model assembly
def build_model(sid, tel, surface, rooms, *, peek=None, actor="agent", now=None) -> dict:
    """Assemble the read-only map model from telemetry + the current area's surface + the crystal
    index (+ an optional bounded live stage-flag read for gate open/pressed state)."""
    now = time.time() if now is None else now
    stats = (tel or {}).get("stats") or {}
    model = {
        "schema": SCHEMA, "sid": sid, "seq": int(now * 10) if (tel or {}).get("running") else 0,
        "live": bool((tel or {}).get("running")), "age_s": (tel or {}).get("age_s"),
        "title": (tel or {}).get("title", ""), "units": "pso",
        "episode": stats.get("episode"), "floor": stats.get("floor"), "room": None,
        "fingerprint": stats.get("map_surface_fingerprint"), "size": None, "bounds": None,
        "cells": [], "gates": [], "warps": [], "players": [], "enemies": [],
        "map_directive": stats.get("map_directive") if isinstance(stats.get("map_directive"), dict) else None,
        "objective": stats.get("forward_fallback_target") or "", "learned_areas": learned_areas(rooms),
        "stage_flags": None, "generated": now,
    }
    if isinstance(surface, dict):
        for k in ("episode", "floor", "room", "fingerprint", "size"):
            if surface.get(k) is not None:
                model[k] = surface[k]
        model["cells"] = surface.get("cells") or []
        model["gates"] = [dict(g) for g in (surface.get("gates") or []) if isinstance(g, dict)]
        model["warps"] = [dict(w) for w in (surface.get("warps") or []) if isinstance(w, dict)]
        model["bounds"] = bounds_list(surface.get("bounds"))
        surf_players = players_from_surface(surface.get("players"))
    else:
        surf_players = []

    model["players"] = players_from_steering(stats.get("steering_evidence_json")) or surf_players

    # Live gate/switch open|pressed from the stage-flag array (bounded, cached, read-only).
    floor = model.get("floor")
    need = any(g.get("flag") is not None for g in model["gates"])
    if peek is not None and type(floor) is int and 0 <= floor < STAGE_FLAG_GROUPS and need:
        group = _read_stage_group(sid, floor, peek, actor, now)
        if group is not None:
            model["stage_flags"] = {"floor": floor, "read": True, "group_hex": group.hex(" ")}
            for g in model["gates"]:
                if type(g.get("flag")) is int:
                    g["set"] = flag_set(group, g["flag"])        # switch pressed / gate open

    if not model["bounds"]:
        model["bounds"] = bounds_from_points(model["players"], model["gates"], model["warps"])
    return model


def _read_stage_group(sid, floor, peek, actor, now):
    cached = _stage_cache.get(sid)
    if cached and now - cached[0] < _STAGE_CACHE_TTL:
        return cached[1]
    try:
        data = bytes.fromhex(peek(sid, STAGE_FLAG_BASE + floor * STAGE_GROUP_SIZE, STAGE_GROUP_SIZE, actor))
    except Exception:                       # noqa: BLE001 - a missed read just leaves gate state unknown
        return None
    if len(data) != STAGE_GROUP_SIZE:
        return None
    _stage_cache[sid] = (now, data)
    if len(_stage_cache) > 64:
        for k in sorted(_stage_cache, key=lambda k: _stage_cache[k][0])[:-64]:
            _stage_cache.pop(k, None)
    return data


# ----------------------------------------------------------------------------- directive file (pure-ish)
def directive_raw(body: dict) -> dict:
    """A directive-file dict from a POST body, stamped with a fresh id + ts. The caller validates it
    with pso_map.parse_directive before writing (so the file is exactly what the bot consumes)."""
    raw = {"id": str(uuid.uuid4()), "ts": time.time()}
    for k in ("op", "x", "z", "flag", "ptr", "room", "episode", "floor"):
        if body.get(k) is not None:
            raw[k] = body[k]
    return raw


# ----------------------------------------------------------------------------- campaign root + files (I/O)
def _pso_coop_root(config):
    base = getattr(config, "runtime", None) or getattr(config, "data_dir", None)
    return Path(base) / "autoplay" / "pso-coop" if base else None


def live_root(config) -> Path | None:
    """The live run's campaign root (the pso-coop/<card_id> dir written most recently: its
    pso-directive.json, pso-knowledge.json or pso-maps/)."""
    root = _pso_coop_root(config)
    if not root or not root.is_dir():
        return None
    best, best_mtime = None, -1.0
    try:
        for d in root.iterdir():
            if not d.is_dir():
                continue
            mt = -1.0
            for name in ("pso-directive.json", "pso-knowledge.json", "pso-maps"):
                p = d / name
                try:
                    mt = max(mt, p.stat().st_mtime)
                except OSError:
                    pass
            if mt < 0:
                try:
                    mt = d.stat().st_mtime
                except OSError:
                    continue
            if mt > best_mtime:
                best, best_mtime = d, mt
    except OSError:
        return None
    return best


def load_surface(root: Path, fingerprint) -> dict | None:
    if not root or not isinstance(fingerprint, str) or not _FINGERPRINT_RE.match(fingerprint):
        return None
    f = root / "pso-maps" / (fingerprint + ".json")
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def load_crystal_rooms(root: Path) -> dict:
    if not root:
        return {}
    try:
        data = json.loads((root / "pso-knowledge.json").read_text(encoding="utf-8"))
        rooms = data.get("rooms") if isinstance(data, dict) else None
        return rooms if isinstance(rooms, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def read_directive(root: Path) -> dict | None:
    if not root:
        return None
    try:
        data = json.loads((root / "pso-directive.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def write_directive(root: Path, raw: dict) -> None:
    """Atomically write pso-directive.json (the bot polls it by mtime)."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / "pso-directive.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(raw, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


# ----------------------------------------------------------------------------- routes
def install(app, store, config, auth, *, peek=None):
    from fastapi import Depends, HTTPException
    from pydantic import BaseModel
    from .screensaver import telemetry_get
    from . import pso_map                 # reuse the bot's validator so the file matches what it reads

    @app.get("/api/pso/map/{sid}")
    def pso_map_feed(sid: str, actor=Depends(auth)):
        tel = telemetry_get(sid)
        root = live_root(config)
        fingerprint = ((tel or {}).get("stats") or {}).get("map_surface_fingerprint")
        surface = load_surface(root, fingerprint) if (root and fingerprint) else None
        rooms = load_crystal_rooms(root) if root else {}
        return build_model(sid, tel, surface, rooms, peek=peek, actor=str(actor))

    class PsoDirectiveIn(BaseModel):
        op: str
        x: float | None = None
        z: float | None = None
        flag: int | None = None
        ptr: str | None = None
        room: int | None = None
        episode: int | None = None
        floor: int | None = None

    @app.get("/api/sessions/{sid}/pso-directive")
    def pso_directive_get(sid: str, actor=Depends(auth)):
        root = live_root(config)
        return {"directive": read_directive(root) if root else None, "ops": ["goto", "press", "attack", "clear"]}

    @app.post("/api/sessions/{sid}/pso-directive")
    def pso_directive_post(sid: str, body: PsoDirectiveIn, actor=Depends(auth)):
        """The operator's map click: write pso-directive.json in the bot's own format (validated by
        pso_map.parse_directive). The PSO bot polls the file and makes P1 act on it."""
        root = live_root(config)
        if root is None:
            raise HTTPException(503, "No live PSO campaign run to steer")
        raw = directive_raw(body.model_dump())
        if pso_map.parse_directive(raw) is None:
            raise HTTPException(422, "Invalid directive (see docs/pso-map-directives.md): "
                                     "goto needs x,z; press needs flag 0..255; attack needs ptr or x,z")
        write_directive(root, raw)
        store.audit(actor, "pso.map_directive", sid, {k: raw[k] for k in raw if k != "ts"})
        return {"directive": raw}
