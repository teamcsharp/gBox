"""Build records: the facts the Builds view (gbox/builds.py) reads from a build's .gbox-mod.json, written by the shared
build paths at build time so a build explains itself later.

Every field is optional; older markers are derived from what they have (gbox.builds.details). Writers keep writing
their own marker; the shared paths add these on top (stamp / stamp_marker):

  kind          cast | character | file | cheats | romhack | compile | showcase | test   (the Builds view's filter)
  job_id        the job that built it; built_on {worker_id, os, host}
  build_call    {tool, input}: the exact call that built it (characters builds also keep `recipe`, gbox.special_builds)
  file_changes  [{path, change: replaced | patched | new | image, size, base_size, patches: [{offset, length}], what}]
  slots         [{slot, slot_name, donor, donor_name, source}]: who went where (cast builds keep `cast` rows too)
  codes         [{type: cheat | code_patch | unlock | ram_write | patch, label, codes | address / value | offset,
                  tool}]: codes, cheats and hacks the build carries
  compile       {toolchain, flags, defines, target, source_patches: [{path, lines | summary}]}: decomp / recompile
  verified_in_game  false until the build was seen running (the writers' own flag)

The marker is part of a build's pinned file manifest (gbox.filemods.stage compares every file), so nothing here is
written after the build: renames live in the store (gbox.builds), never in the marker.
"""
from __future__ import annotations

import json
import platform
from pathlib import Path

MARKER = ".gbox-mod.json"
KINDS = ("cast", "character", "file", "cheats", "romhack", "compile", "showcase", "test")
FIELDS = ("kind", "job_id", "built_on", "build_call", "file_changes", "slots", "codes", "compile", "verified_in_game", "replacement_scope")
MAX_VALUE = 2000                      # a recorded call keeps short values only (no file bytes, no huge lists)
MAX_ROWS = 400


def _small(v, depth: int = 0):
    """A JSON-able, bounded copy of a call input: bytes and long strings become a size note."""
    if isinstance(v, (bytes, bytearray)):
        return f"<{len(v)} bytes>"
    if isinstance(v, str):
        return v if len(v) <= MAX_VALUE else f"<{len(v)} characters>"
    if v is None or isinstance(v, (bool, int, float)):
        return v
    if depth > 6:
        return "…"
    if isinstance(v, dict):
        return {str(k): _small(x, depth + 1) for k, x in list(v.items())[:MAX_ROWS]}
    if isinstance(v, (list, tuple, set)):
        return [_small(x, depth + 1) for x in list(v)[:MAX_ROWS]]
    if hasattr(v, "model_dump"):
        return _small(v.model_dump(), depth + 1)
    return str(v)[:MAX_VALUE]


def call_of(tool: str, inp) -> dict:
    """{tool, input}: the call as recorded (bounded; session-bound keys dropped)."""
    d = inp.model_dump() if hasattr(inp, "model_dump") else dict(inp or {})
    d = {k: v for k, v in d.items() if k not in ("session_id",) and v not in (None, "", [], {})}
    return {"tool": tool, "input": _small(d)}


def from_ctx(ctx) -> dict:
    """job_id + built_on from a tool's Ctx (empty without a job)."""
    out = {}
    jid = getattr(ctx, "job_id", None)
    if jid:
        out["job_id"] = str(jid)
    try:
        from .registry import HOST_OS
    except Exception:                                            # noqa: BLE001
        HOST_OS = ""
    on = {k: v for k, v in (("worker_id", getattr(ctx, "worker", None)), ("os", HOST_OS), ("host", platform.node()))
          if v}
    if on:
        out["built_on"] = on
    return out


def file_change(path: str, change: str, size: int | None = None, base_size: int | None = None,
                patches=None, what: str = "") -> dict:
    row = {"path": str(path), "change": change}
    if size is not None:
        row["size"] = int(size)
    if base_size is not None:
        row["base_size"] = int(base_size)
    if patches:
        row["patches"] = [{"offset": int(str(p.get("offset", 0)), 0) if isinstance(p, dict) else 0,
                           "length": len(bytes.fromhex(p["hex"])) if isinstance(p, dict) and p.get("hex") else 0}
                          for p in patches][:MAX_ROWS]
    if what:
        row["what"] = str(what)[:300]
    return row


def stamp(meta: dict, **fields) -> dict:
    """meta with the given record fields set (None / empty values are left out; unknown names refused)."""
    bad = [k for k in fields if k not in FIELDS]
    if bad:
        raise ValueError(f"not a build record field: {bad}")
    out = dict(meta)
    for k, v in fields.items():
        if v is None or v == [] or v == {} or v == "":
            continue
        if k == "kind" and v not in KINDS:
            raise ValueError(f"kind {v!r}: one of {', '.join(KINDS)}")
        out[k] = _small(v) if k in ("build_call", "codes", "compile", "slots", "file_changes", "replacement_scope") else v
    return out


def stamp_marker(where, **fields) -> bool:
    """Add record fields to a build's marker right after the build (a folder or the marker path). Never raises;
    False when the marker can't be read or written."""
    p = Path(where)
    if p.name != MARKER:
        p = p / MARKER
    try:
        meta = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(meta, dict):
            return False
        new = stamp(meta, **fields)
        if new == meta:
            return True
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(new, default=str), encoding="utf-8")
        tmp.replace(p)
        return True
    except (OSError, ValueError):
        return False
