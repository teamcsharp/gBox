"""Structured map directives for the PSO co-op bot (operator 2026-11-02: "point people on a 2d
level where they want to go ... double-click an area and they navigate to it like an RTS").

The operator clicks the 2D map (clients/web/viz/pso-map.js); the client POSTs a structured order
here (a world point, a switch, an enemy, a door, or "clear"). The control plane keeps the newest per
session (post / latest), exactly like the Mercenaries directive channel (gbox/mercs/directives.py).
The PSO nav agent (pso_coop) polls it and makes P1 act on it; P2+ swarm-follow. The payload format
and how the nav agent consumes it are documented in docs/pso-map-directives.md.

In-memory, bounded, best-effort. A directive never presses a key by itself: it changes what P1
decides, so every normal navigation/combat safeguard stays in force.
"""
from __future__ import annotations

import math
import threading
import time

KINDS = ("goto", "press", "attack", "open", "clear")
TTL_S = 600.0                                    # a standing order lasts this long, then the bot is autonomous again
MAX_SESSIONS = 64
_COORD_LIMIT = 1_000_000.0                       # PSO world coords are small; reject anything absurd / non-finite

_LATEST: dict[str, dict] = {}
_LOCK = threading.Lock()
_SEQ = [0]


def _finite(v):
    return isinstance(v, (int, float)) and math.isfinite(v) and abs(v) <= _COORD_LIMIT


def _opt_coord(v):
    """A world coordinate that may be omitted (None) or must be a finite number in range."""
    if v is None:
        return None
    if not _finite(v):
        raise ValueError("x/z must be finite world coordinates")
    return float(v)


def _opt_id(v):
    if v is None:
        return None
    s = str(v)
    if not 1 <= len(s) <= 64:
        raise ValueError("id must be 1..64 chars")
    return s


def _opt_int(v):
    if v is None:
        return None
    if type(v) is bool or not isinstance(v, int):
        raise ValueError("floor/room must be integers")
    return int(v)


def build(kind: str, body: dict) -> dict:
    """Validate a POST body into a stored directive (without seq/at). Raises ValueError on bad input."""
    if kind not in KINDS:
        raise ValueError("kind must be one of: " + ", ".join(KINDS))
    out = {"kind": kind}
    if kind == "clear":
        return out
    x, z = _opt_coord(body.get("x")), _opt_coord(body.get("z"))
    if kind == "goto":
        if x is None or z is None:
            raise ValueError("goto needs world x and z")
        out.update(x=x, z=z, floor=_opt_int(body.get("floor")), room=_opt_int(body.get("room")))
        return out
    id_field = {"press": "switch_id", "attack": "enemy_id", "open": "door_id"}[kind]
    ident = _opt_id(body.get(id_field))
    if ident is None and (x is None or z is None):
        raise ValueError(f"{kind} needs either {id_field} or world x and z")
    out[id_field] = ident
    if x is not None and z is not None:
        out.update(x=x, z=z)
    return out


def post(sid: str, kind: str, body: dict | None = None, now: float | None = None,
         source: str = "operator") -> dict:
    """Store the newest directive for the session. Returns the stored row (seq + at + until)."""
    row = build(kind, body or {})
    now = time.time() if now is None else now
    with _LOCK:
        _SEQ[0] += 1
        row = {"seq": _SEQ[0], **row, "at": now, "until": now + TTL_S, "source": str(source)}
        _LATEST[sid] = row
        for old in sorted(_LATEST, key=lambda k: _LATEST[k]["at"])[:-MAX_SESSIONS]:
            _LATEST.pop(old, None)
    return dict(row)


def latest(sid: str, now: float | None = None) -> dict | None:
    """The newest directive, or None when there is none or it has expired."""
    now = time.time() if now is None else now
    with _LOCK:
        row = _LATEST.get(sid)
        if row and now - row["at"] > TTL_S:
            _LATEST.pop(sid, None)
            row = None
    return dict(row) if row else None


def clear(sid: str) -> None:
    with _LOCK:
        _LATEST.pop(sid, None)
