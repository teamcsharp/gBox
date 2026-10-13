"""What the pick whip learned about a game, kept so the next pick / replace is instant.

Stored on the control plane in the game's profile (`GET/POST /api/profiles/{game_id}/pick`, merged into the store's
"profile" record) and mirrored in <data_dir>/pick_learned/<game_id>.json on the worker (works offline, and is what
tests use). Shape (every part optional):

  classes   {entity class / actor name: {slot, model (collection slug), struct_size, model_ptr: {offset, kind},
             skeleton_ptr: {...}, display_list_ptr: {...}, seen, last}}
  assets    {slot: {signatures: [{name, size, pieces: [{offset, hex}]}], mod, at}}  (live_inject.signatures)
  replace   {slot: {live_ok, method, reason, mod, at}}
  ghidra    {root address: {refs: [...], functions: [{name, entry}], job, at}}
  arenas    [[lo, hi]] free RAM the operator / an analysis declared safe for models that outgrow their footprint
"""
from __future__ import annotations

import json
import time
from pathlib import Path


def merge(a, b):
    """Deep merge: dicts merge key by key, everything else is replaced by b (None in b deletes the key)."""
    if not isinstance(a, dict) or not isinstance(b, dict):
        return b
    out = dict(a)
    for k, v in b.items():
        if v is None:
            out.pop(k, None)
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = v
    return out


def _path(cfg, gid: str) -> Path | None:
    d = getattr(cfg, "data_dir", None)
    if not d or not gid:
        return None
    safe = "".join(c for c in gid if c.isalnum() or c in "-_")[:64]
    return Path(d) / "pick_learned" / f"{safe}.json"


def _local(cfg, gid: str) -> dict:
    p = _path(cfg, gid)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p and p.is_file() else {}
    except (OSError, ValueError):
        return {}


def load(ctx, gid: str) -> dict:
    data = _local(getattr(ctx, "config", None), gid)
    if getattr(ctx, "server", None):
        try:
            import httpx
            r = httpx.get(f"{ctx.server}/api/profiles/{gid}/pick", headers=ctx.headers, timeout=10)
            if r.status_code == 200 and isinstance(r.json(), dict):
                data = merge(data, r.json())
        except Exception:                                    # noqa: BLE001 - the local copy still answers
            pass
    return data


def record(ctx, gid: str, patch: dict) -> dict:
    """Merge patch into the game's learned data (locally and on the control plane). Best effort: never fails a pick."""
    patch = json.loads(json.dumps(patch, default=str))
    cfg = getattr(ctx, "config", None)
    data = merge(_local(cfg, gid), patch)
    data["updated"] = time.time()
    p = _path(cfg, gid)
    if p:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            tmp.replace(p)
        except OSError:
            pass
    if getattr(ctx, "server", None):
        try:
            import httpx
            httpx.post(f"{ctx.server}/api/profiles/{gid}/pick", json=patch, headers=ctx.headers, timeout=10)
        except Exception:                                    # noqa: BLE001
            pass
    return data
