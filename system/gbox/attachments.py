"""Attachments: props modelled in Blender (hats, weapons, glasses ...) bound to a bone, carried into every game build.

Marking. A prop is a mesh node that is not skinned and hangs under a joint (Blender: an object parented to a bone, which
the glTF exporter writes as a child node of that joint). The gBox add-on also writes its custom properties as glTF
extras: {"gbox_prop": true, "gbox_bone": "<bone>"}. Library entries list their props in meta["props"]
(variants.find_props / blender_roundtrip); stamp() writes the marks into the stored model, so a writer that only gets the
file still finds them.

Carrying. The shared rig loaders (sm64_swap.load_rig, doa2_weighted_retarget.load_rig) flag those prims ("prop",
"prop_node"): rigid on the prop's bone (one joint per vertex, weight 1). The shared retargets move a prop with its
bone's rule and keep the flag; a prop doesn't make the head bigger or the figure taller. write_rigged names a prop's
material "gbox_prop:<node>:<n>", so read_rigged (after a Blender decimate) still knows which triangles are whose.

Budget report. characters_recorded opens a ledger(); the loaders, retargets and read_rigged note() each prop's
triangles (loaded -> fitted -> after the budget pass) and summary() says which props were kept, simplified or dropped
to fit the game's budget. A writer with its own encoder budget can note("budget", prims) itself.
"""
from __future__ import annotations

import base64
import contextvars
import json
import struct
from contextlib import contextmanager
from pathlib import Path

PROP_MAT = "gbox_prop:"


# ---------------------------------------------------------------- glTF / GLB files

def read_gltf(path: Path) -> tuple[dict, bytes | None]:
    """(json, BIN chunk) of a .glb, or (json, None) of a .gltf."""
    d = Path(path).read_bytes()
    if d[:4] == b"glTF":
        jl = struct.unpack_from("<I", d, 12)[0]
        gl = json.loads(d[20:20 + jl])
        rest = d[20 + jl:]
        b = None
        if len(rest) >= 8:
            bl, kind = struct.unpack_from("<II", rest, 0)
            if kind == 0x004E4942:
                b = rest[8:8 + bl]
        return gl, b
    return json.loads(d), None


def glb_bytes(gl: dict, blob: bytes | None) -> bytes:
    blob = bytes(blob or b"")
    blob += bytes(-len(blob) % 4)
    if blob:
        gl.setdefault("buffers", [{}])
        gl["buffers"][0] = {"byteLength": len(blob)}
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    out = struct.pack("<II", len(js), 0x4E4F534A) + js
    if blob:
        out += struct.pack("<II", len(blob), 0x004E4942) + blob
    return struct.pack("<III", 0x46546C67, 2, 12 + len(out)) + out


def write_like(path: Path, gl: dict, blob: bytes | None) -> Path:
    """Write back in the file's own format (.glb with its BIN chunk, or .gltf JSON)."""
    path = Path(path)
    if blob is not None or path.suffix.lower() == ".glb":
        path.write_bytes(glb_bytes(gl, blob))
    else:
        path.write_text(json.dumps(gl))
    return path


def pack(path: Path) -> tuple[dict, bytes]:
    """Any .glb / .gltf (external or data: buffers and images) -> (json, one BIN buffer): a self-contained GLB's parts."""
    path = Path(path)
    gl, blob = read_gltf(path)
    if blob is not None and len(gl.get("buffers") or []) <= 1 and not any(
            im.get("uri") for im in gl.get("images") or []):
        return gl, blob
    bins = []
    for k, b in enumerate(gl.get("buffers") or []):
        u = b.get("uri")
        if u is None:
            bins.append(blob or b"")
        elif u.startswith("data:"):
            bins.append(base64.b64decode(u.split(",", 1)[1]))
        else:
            bins.append((path.parent / u).read_bytes())
    out, at = bytearray(), []
    for b in bins:
        out.extend(bytes(-len(out) % 4))
        at.append(len(out))
        out.extend(b)
    for v in gl.get("bufferViews") or []:
        v["byteOffset"] = v.get("byteOffset", 0) + at[v.get("buffer", 0)]
        v["buffer"] = 0
    for im in gl.get("images") or []:
        u = im.pop("uri", None)
        if not u:
            continue
        if u.startswith("data:"):
            head, data = u.split(",", 1)
            raw = base64.b64decode(data)
            im.setdefault("mimeType", head[5:].split(";")[0] or "image/png")
        else:
            from urllib.parse import unquote
            raw = (path.parent / unquote(u)).read_bytes()
            im.setdefault("mimeType", "image/jpeg" if u.lower().endswith((".jpg", ".jpeg")) else "image/png")
        out.extend(bytes(-len(out) % 4))
        gl.setdefault("bufferViews", []).append({"buffer": 0, "byteOffset": len(out), "byteLength": len(raw)})
        out.extend(raw)
        im["bufferView"] = len(gl["bufferViews"]) - 1
    gl["buffers"] = [{"byteLength": len(out)}] if out else []
    return gl, bytes(out)


# ---------------------------------------------------------------- which nodes are props

def extras(nd: dict) -> dict:
    e = nd.get("extras")
    return e if isinstance(e, dict) else {}


def is_marked(nd: dict) -> bool:
    e = extras(nd)
    return "mesh" in nd and "skin" not in nd and e.get("gbox_part") != "body" and bool(e.get("gbox_prop") or e.get("gbox_bone"))


def prop_nodes(gl: dict, explicit=()) -> set[str]:
    """Node names of the props: the explicit list (meta["props"] nodes) + every node the add-on marked."""
    out = {n for n in (explicit or ()) if n}
    for i, nd in enumerate(gl.get("nodes") or []):
        if is_marked(nd):
            out.add(nd.get("name", f"node{i}"))
    return out


def stamp(path: Path, props: list[dict]) -> int:
    """Mark the props (meta["props"] rows: node, bone) in the model file itself -> how many nodes were marked."""
    want = {p.get("node"): p for p in props or [] if p.get("node")}
    if not want:
        return 0
    gl, blob = read_gltf(path)
    n = 0
    for nd in gl.get("nodes") or []:
        p = want.get(nd.get("name"))
        if p is None or "mesh" not in nd or "skin" in nd:
            continue
        e = dict(extras(nd))
        e.update({"gbox_prop": True, **({"gbox_bone": p["bone"]} if p.get("bone") else {})})
        nd["extras"] = e
        n += 1
    if n:
        write_like(path, gl, blob)
    return n


def material_name(node: str, n: int) -> str:
    return f"{PROP_MAT}{node}:{n}"


def node_of_material(name: str | None) -> str | None:
    if name and name.startswith(PROP_MAT):
        return name[len(PROP_MAT):].rsplit(":", 1)[0]
    return None


# ---------------------------------------------------------------- budget ledger

_L = contextvars.ContextVar("gbox_attachments", default=None)
STAGES = ("loaded", "fitted", "budget")


@contextmanager
def ledger():
    """Collect what happens to the props during one build (characters_recorded opens it around a tool call)."""
    led = {"models": {}, "current": None}
    tok = _L.set(led)
    try:
        yield led
    finally:
        _L.reset(tok)


@contextmanager
def paused():
    """Reading an intermediate (a fitted / decimated file) through a donor loader: nothing is noted meanwhile."""
    tok = _L.set(None)
    try:
        yield
    finally:
        _L.reset(tok)


def by_node(prims) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in prims or []:
        if p.get("prop"):
            k = p.get("prop_node") or "prop"
            out[k] = out.get(k, 0) + int(len(p.get("tris", ())))
    return out


def note(stage: str, prims, source=None, **info) -> None:
    """Record the props' triangles at a stage (loaded | fitted | budget). No ledger open: a no-op."""
    led = _L.get()
    if led is None:
        return
    if source is not None:
        led["current"] = str(source)
    key = led["current"] or "model"
    t = by_node(prims)
    if stage == "loaded" and not t:
        return
    m = led["models"].get(key)
    if m is None:
        if stage != "loaded":
            return                                          # a model without props
        m = led["models"][key] = {"stages": {}, "info": {}}
    if stage == "budget" and not t and m["stages"].get("budget"):
        return                                              # a body-only file read after the props' own budget pass
    m["stages"][stage] = t
    m["info"].update({k: v for k, v in info.items() if v is not None})


def summary(led: dict | None = None) -> dict | None:
    """-> {"models": {source: {props: [{node, triangles, kept, state}], measured_at}}, "dropped": [...],
    "message"} or None (no props went through a writer)."""
    led = led if led is not None else _L.get()
    if not led:
        return None
    models, dropped, parts = {}, [], []
    for key, m in led["models"].items():
        st = m["stages"]
        loaded = st.get("loaded") or {}
        if not loaded:
            continue
        at = next((s for s in reversed(STAGES) if s in st), "loaded")
        final = st[at]
        rows = []
        for node, n in loaded.items():
            k = int(final.get(node, 0))
            state = "kept" if k >= n else "dropped" if k == 0 else "simplified"
            rows.append({"node": node, "triangles": n, "kept": k, "state": state})
            if state == "dropped":
                dropped.append(node)
            parts.append(f"{node} " + ({"kept": f"kept ({n} triangles)", "dropped": "DROPPED for the budget",
                                         "simplified": f"simplified {n} -> {k} triangles for the budget"}[state]))
        models[Path(key).name if key != "model" else key] = {"props": rows, "measured_at": at, **m["info"]}
    if not models:
        return None
    where = {"budget": "after the budget pass", "fitted": "after the fit (the writer's own encoder budget isn't measured)",
             "loaded": "as loaded"}
    ats = {v["measured_at"] for v in models.values()}
    return {"models": models, "dropped": dropped,
            "message": "attachments: " + "; ".join(parts) + f" ({', '.join(where[a] for a in sorted(ats))})"}
