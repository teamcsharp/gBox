"""Structured fitting events: what the writers do to each model (scale / retarget / proportion / weights / decimate /
encode / write), with numbers and a mesh snapshot, for the live "Fitting" pop-up (clients/web/viz/process-popup.js).

Transport: an event rides on an ordinary progress line, after a marker - "Amy -> Kasumi: retarget #fit{json}" - so
every writer's progress wrapper (which rescales the percentage or prefixes the message) passes it through unchanged.
registry.Ctx.progress uploads a snapshot GLB / preview image the event names and swaps the local path for its URL;
the server (POST /api/jobs/{id}/progress) strips the marker from the visible message and folds the event into the
job's "fitting" record ({order, models: {key: {label, stages: {stage: {state, data, ts}}, snapshot, preview}}}).

Writers do not pass anything around: characters_tool opens a job sink (job()), and the shared retargets
(sm64_swap / doa2_weighted_retarget / re4gc_enemies .retarget) call auto_model() + stage(); a writer that knows its
model better (DOA2 per costume, the cast build's plan) names it with model(). Without a sink every call is a no-op.
"""
from __future__ import annotations

import contextvars
import json
import math
import os
import re
import struct
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import numpy as np

MARK = " #fit"
STAGES = ["scale", "retarget", "proportion", "weights", "decimate", "encode", "write"]
STATES = {"running", "done", "skipped", "failed"}
MAX_MODELS = 80
SNAPSHOT_TRIS = 3000

_sink = contextvars.ContextVar("gbox_fit_sink", default=None)        # {"progress", "dir", "plan", "current", "n"}


# ---------------------------------------------------------------- wire format

def encode(event: dict) -> str:
    return MARK + json.dumps(event, separators=(",", ":"), default=_plain)


def _plain(v):
    if isinstance(v, np.generic):
        return v.item()
    if isinstance(v, np.ndarray):
        return v.tolist()
    if isinstance(v, Path):
        return str(v)
    return str(v)


def split(msg: str) -> tuple[str, dict | None]:
    """'text #fit{...}' -> ('text', event); anything else -> (msg, None)."""
    msg = str(msg or "")
    i = msg.rfind(MARK + "{")
    if i < 0:
        return msg, None
    try:
        ev = json.loads(msg[i + len(MARK):])
    except ValueError:
        return msg, None
    return (msg[:i].rstrip(), ev) if isinstance(ev, dict) else (msg, None)


def _small(data, depth=0):
    """Numbers, short strings, small lists / dicts only (the event rides on every jobs poll)."""
    if isinstance(data, bool) or data is None:
        return data
    if isinstance(data, (int, np.integer)):
        return int(data)
    if isinstance(data, (float, np.floating)):
        f = float(data)
        return round(f, 4) if math.isfinite(f) else None
    if isinstance(data, str):
        return data[:160]
    if isinstance(data, dict) and depth < 2:
        return {str(k)[:40]: _small(v, depth + 1) for k, v in list(data.items())[:24]}
    if isinstance(data, (list, tuple, np.ndarray)) and depth < 2:
        return [_small(v, depth + 1) for v in list(data)[:24]]
    return str(data)[:80]


def fold(state: dict | None, event: dict, now: float | None = None) -> dict:
    """The server side: merge one event into a job's fitting record."""
    st = state if isinstance(state, dict) else {}
    st.setdefault("order", [])
    st.setdefault("models", {})
    ts = now if now is not None else time.time()
    for row in event.get("plan") or []:                     # the cast build announces every model up front
        key = str(row.get("model") or "")[:120]
        if key and key not in st["models"] and len(st["order"]) < MAX_MODELS:
            st["order"].append(key)
            st["models"][key] = {"label": str(row.get("label") or key)[:160], "stages": {}, "updated": ts,
                                 "state": "pending"}
    key = str(event.get("model") or "")[:120]
    if not key:
        return st
    m = st["models"].get(key)
    if m is None:
        if len(st["order"]) >= MAX_MODELS:
            return st
        st["order"].append(key)
        m = st["models"][key] = {"label": key, "stages": {}, "state": "pending"}
    if event.get("label"):
        m["label"] = str(event["label"])[:160]
    stage = event.get("stage")
    if stage:
        s = m["stages"].setdefault(str(stage)[:24], {})
        s["state"] = event.get("state") if event.get("state") in STATES else "running"
        if event.get("data") is not None:
            s["data"] = _small(event["data"])
        if event.get("text"):
            s["text"] = str(event["text"])[:200]
        s["ts"] = ts
        m["current"] = str(stage)[:24]
        m["state"] = "failed" if s["state"] == "failed" else ("done" if stage == "write" and s["state"] == "done"
                                                              else "running")
    for k in ("snapshot", "preview"):
        v = event.get(k)
        if isinstance(v, str) and v.startswith("/api/"):
            m[k] = v[:300]
            m[k + "_stage"] = str(stage or m.get("current") or "")[:24]
            m[k + "_ts"] = ts
    m["updated"] = ts
    st["current"] = key
    st["updated"] = ts
    return st


# ---------------------------------------------------------------- the worker side

@contextmanager
def job(progress, work_dir: str | Path | None = None):
    """Collect fitting events for one job: every stage()/model() inside sends to progress(pct, msg)."""
    if progress is None:
        yield None
        return
    d = Path(work_dir) if work_dir else Path(tempfile.gettempdir()) / "gbox-fitting" / f"{os.getpid()}-{id(progress):x}"
    token = _sink.set({"progress": progress, "dir": d, "plan": {}, "current": None, "n": 0, "m": 0})
    try:
        yield _sink.get()
    finally:
        _sink.reset(token)


def active() -> bool:
    return _sink.get() is not None


def _send(event: dict, text: str):
    sk = _sink.get()
    if sk is None:
        return
    fn = sk["progress"]
    pct = float(getattr(getattr(fn, "__self__", None), "_pct", 0.0) or 0.0)
    try:
        fn(pct, (text or event.get("stage") or "fitting") + encode(event))
    except Exception as e:                                   # noqa: BLE001 - cancellation still has to propagate
        if type(e).__name__ == "Cancelled":
            raise


def plan(rows: list[tuple[str, str, str]]):
    """The cast build's models before any of them is fitted: [(model key, donor slug, label)]. auto_model(slug)
    then takes the next planned key of that donor. A key already planned keeps its row (the cast swap plans every
    model, then the writer's own build_cast plans the same ones again when it runs alone)."""
    sk = _sink.get()
    if sk is None:
        return
    labels = sk.setdefault("labels", {})
    rows = [(str(k), s, lab) for k, s, lab in rows if str(k) not in labels]
    if not rows:
        return
    for key, slug, label in rows:
        sk["plan"].setdefault(str(slug), []).append((key, label))
        labels[key] = label
    _send({"plan": [{"model": k, "label": lab} for k, _s, lab in rows]}, f"Fitting {len(rows)} models")


def model(key: str, label: str | None = None, slug: str | None = None, explicit: bool = True) -> str | None:
    """Start (or switch to) one model: the following stage() calls belong to it. A writer's explicit model keeps
    every fit until the next model() (refits included); label defaults to the cast plan's label for the key."""
    sk = _sink.get()
    if sk is None:
        return None
    key = str(key)
    if sk.get("default") and sk["default"][0] == key:      # the job's own model, named by the writer: its label
        label = label or sk["default"][1]
        slug = slug or sk["default"][2]
        sk.pop("default")
    label = label or sk.get("labels", {}).get(key) or key
    for q in sk["plan"].values():                            # a planned key started by name is no longer pending
        q[:] = [row for row in q if row[0] != key]
    sk["current"] = {"key": key, "label": label, "slug": slug, "closed": False, "explicit": explicit,
                     "fitted": False}
    _send({"model": key, "label": label}, f"Fitting {label}")
    return key


def default_model(key: str, label: str | None = None, slug: str | None = None):
    """The model a job is about (characters op=use: one donor into one slot), started lazily by the first fit that
    no writer named itself - a writer that names its models (DOA2 per fighter) leaves no empty row behind."""
    sk = _sink.get()
    if sk is not None:
        sk["default"] = (str(key), label, slug)


def auto_model(source: str | Path | None = None) -> str | None:
    """The model a shared retarget is fitting: the writer's explicit model, or the current one when it is the same
    donor (a refit) and not written yet, else the donor's next planned slot, else a new one named after the donor's
    collection folder."""
    sk = _sink.get()
    if sk is None:
        return None
    slug = Path(source).parent.name if source else None
    cur = sk["current"]
    queue = sk["plan"].get(slug or "") or []
    if cur and not cur["closed"]:
        same = slug is None or cur.get("slug") in (None, slug)
        if cur.get("explicit") or (same and (not cur.get("fitted") or not queue)):
            if cur.get("slug") is None:
                cur["slug"] = slug
            return cur["key"]
    if queue:
        key, label = queue[0]
        return model(key, label, slug, explicit=False)
    if sk.get("default"):
        key, label, dslug = sk.pop("default")
        return model(key, label, dslug)
    sk["m"] += 1
    name = slug or f"model {sk['m']}"
    return model(name if sk["m"] == 1 else f"{name} #{sk['m']}", name, slug, explicit=False)


def current() -> str | None:
    sk = _sink.get()
    return sk["current"]["key"] if sk and sk["current"] else None


def stage(name: str, state: str = "done", data: dict | None = None, text: str | None = None, prims=None,
          preview: str | Path | None = None):
    """One stage of the current model. prims (fitted geometry) become a snapshot GLB the pop-up can show."""
    sk = _sink.get()
    if sk is None:
        return
    if sk["current"] is None:
        auto_model(None)
    cur = sk["current"]
    ev = {"model": cur["key"], "stage": name, "state": state}
    if data:
        ev["data"] = _small(data)
    if prims is not None:
        try:
            snap = Path(sk["dir"]) / f"{re.sub(r'[^A-Za-z0-9_.-]+', '_', cur['key'])[:60]}-{name}-{sk['n']}.glb"
            sk["n"] += 1
            ev["snapshot"] = str(snapshot_glb(prims, snap))
        except Exception:                                    # noqa: BLE001 - a snapshot never fails a build
            pass
    if preview:
        ev["preview"] = str(preview)
    if name == "retarget" and state == "done":
        cur["fitted"] = True
    if name == "write" and state in ("done", "failed"):
        cur["closed"] = True
        sk.setdefault("written", set()).add(cur["key"])
    label = cur.get("label") or cur["key"]
    _send(ev, text or f"{label}: {name}" + (f" ({state})" if state != "done" else ""))


def written(key: str) -> bool:
    """The model's write stage already ended (done / failed): a writer that reports its own write (with the object's
    new place, bytes...) keeps it - the cast swap's generic write row is only for writers that report none."""
    sk = _sink.get()
    return bool(sk) and str(key) in sk.get("written", ())


# ---------------------------------------------------------------- numbers the writers report

def triangles(prims) -> int:
    return int(sum(len(np.asarray(p["tris"]).reshape(-1, 3)) if p.get("tris") is not None
                   else len(np.asarray(p["pos"]).reshape(-1, 3)) // 3 for p in prims))


def height(prims) -> float:
    """Vertical extent (+Y up) of the prims, in their own units."""
    ys = [np.asarray(p["pos"], float).reshape(-1, 3)[:, 1] for p in prims if len(np.asarray(p["pos"]).reshape(-1))]
    return round(float(np.ptp(np.concatenate(ys))), 4) if ys else 0.0


def donor(rig: dict, basis=None) -> list[dict]:
    """The donor as loaded (its own units and bind pose), turned upright by the writer's facing basis (rows: left,
    up, front) so the snapshot stands like the fitted one."""
    B = None if basis is None else np.asarray(basis, float)
    out = []
    for p in rig.get("prims") or []:
        P = np.asarray(p["pos"], float).reshape(-1, 3)
        out.append({"pos": P @ B.T if B is not None else P, "tris": p.get("tris")})
    return out


def donor_numbers(rig: dict, basis=None, **extra) -> dict:
    """The scale stage's donor facts: original height (source units), vertices, triangles, joints, body roles."""
    pr = donor(rig, basis)
    return {"donor_height": height(pr), "donor_vertices": int(sum(len(p["pos"]) for p in pr)),
            "donor_triangles": triangles(pr),
            "donor_joints": len(rig["parent"] if rig.get("parent") is not None else rig.get("joints", [])),
            "donor_roles": len(rig.get("roles") or {}), **extra}


def weights(prims, jmap: dict | None = None, mode: str = "rigid per bone (one bone per vertex)",
            skeleton: int | None = None, word: str = "bone", owner=None, names: dict | list | None = None, **extra):
    """The weights stage: vertices per target bone / limb, named by the body role that maps to it ("head (bone 7)")
    or by names[j]."""
    if _sink.get() is None:
        return
    nm = dict(names) if isinstance(names, dict) else {i: n for i, n in enumerate(names or [])}
    for r, j in (jmap or {}).items():
        try:
            nm[int(j)] = f"{r} ({word} {int(j)})"
        except (TypeError, ValueError):
            pass
    counts = per_limb(prims, nm, owner)
    stage("weights", data={"mode": mode, "limbs": len(counts), "skeleton_limbs": skeleton,
                           "vertices": int(sum(counts.values())), "per_limb": counts, **extra})


def mesh(parts, pos: str = "P", tris: str = "F") -> list[dict]:
    """Writer parts ({P, F} dicts, or (P, N, ..., F) tuples) -> snapshot prims."""
    out = []
    for p in parts:
        if isinstance(p, dict):
            out.append({"pos": p[pos], "tris": p[tris]})
        else:
            out.append({"pos": p[0], "tris": p[-1]})
    return out


def per_limb(prims, names: dict | list | None = None, owner=None) -> dict:
    """Vertices per target limb / bone (the strongest influence of each vertex; owner(j) folds a limb onto the one
    that draws it), largest first, named by names[j] when given."""
    js = []
    for p in prims:
        J = p.get("J") if p.get("J") is not None else p.get("jid")
        if J is None:
            continue
        J = np.asarray(J)
        if J.ndim == 2:
            W = p.get("W")
            J = J[np.arange(len(J)), np.asarray(W).argmax(1)] if W is not None else J[:, 0]
        js.append(J.astype(np.int64).reshape(-1))
    if not js:
        return {}
    J = np.concatenate(js)
    if owner is not None:
        J = np.asarray([owner(int(j)) for j in J], np.int64) if callable(owner) else np.asarray(owner)[J]
    ids, n = np.unique(J, return_counts=True)

    def name(j):
        if isinstance(names, dict) and j in names:
            return str(names[j])
        if isinstance(names, (list, tuple)) and 0 <= j < len(names):
            return str(names[j])
        return f"limb {j}"
    return {name(int(j)): int(c) for j, c in sorted(zip(ids, n), key=lambda x: -x[1])}


# ---------------------------------------------------------------- a small mesh snapshot

def snapshot_glb(prims, path: str | Path, max_tris: int = SNAPSHOT_TRIS) -> Path:
    """Positions + triangles of fitted prims as a minimal GLB (no textures), at most max_tris triangles (an even
    sample), coloured per prim so the parts read apart."""
    P_all, F_all, C_all, base = [], [], [], 0
    palette = [(0.56, 0.9, 0.66), (0.31, 0.55, 1.0), (1.0, 0.71, 0.42), (0.85, 0.6, 1.0), (0.95, 0.9, 0.5)]
    for i, p in enumerate(prims):
        P = np.asarray(p["pos"], np.float32).reshape(-1, 3)
        F = np.asarray(p.get("tris", np.arange(len(P) // 3 * 3).reshape(-1, 3)), np.int64).reshape(-1, 3)
        if not len(P) or not len(F):
            continue
        P_all.append(P)
        F_all.append(F + base)
        C_all.append(np.tile(np.array(palette[i % len(palette)] + (1.0,), np.float32), (len(P), 1)))
        base += len(P)
    if not P_all:
        raise ValueError("no geometry to snapshot")
    P, F, C = np.concatenate(P_all), np.concatenate(F_all), np.concatenate(C_all)
    if len(F) > max_tris:
        F = F[np.linspace(0, len(F) - 1, max_tris).astype(np.int64)]
    used = np.unique(F)
    remap = np.full(len(P), -1, np.int64)
    remap[used] = np.arange(len(used))
    P, C, F = P[used], C[used], remap[F].astype(np.uint32)
    pos_b, col_b, idx_b = P.tobytes(), C.tobytes(), F.reshape(-1).tobytes()
    blob = pos_b + col_b + idx_b
    blob += b"\0" * (-len(blob) % 4)
    gl = {"asset": {"version": "2.0", "generator": "gBox fit_events"},
          "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": "fitted"}],
          "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0,
                                                  "roughnessFactor": 0.8}, "doubleSided": True}],
          "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "COLOR_0": 1}, "indices": 2, "material": 0}]}],
          "buffers": [{"byteLength": len(blob)}],
          "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pos_b), "target": 34962},
                          {"buffer": 0, "byteOffset": len(pos_b), "byteLength": len(col_b), "target": 34962},
                          {"buffer": 0, "byteOffset": len(pos_b) + len(col_b), "byteLength": len(idx_b),
                           "target": 34963}],
          "accessors": [{"bufferView": 0, "componentType": 5126, "count": len(P), "type": "VEC3",
                         "min": P.min(0).tolist(), "max": P.max(0).tolist()},
                        {"bufferView": 1, "componentType": 5126, "count": len(C), "type": "VEC4"},
                        {"bufferView": 2, "componentType": 5125, "count": int(F.size), "type": "SCALAR"}]}
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob))
                    + struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(blob), 0x004E4942) + blob)
    return out


def fit_numbers(rep: dict, keys=("scale", "torso_up", "torso_down", "shoulder_widen", "head_scale")) -> dict:
    return {k: rep[k] for k in keys if k in rep}
