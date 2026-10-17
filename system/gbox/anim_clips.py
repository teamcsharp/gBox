"""Animation clips for collection entries (#1384): glTF animations a reader decoded, stored next to the model.

A collection entry (gbox.characters) records its clips in meta.json `animations`:
  3D  {name, duration_s, source, file, drives, channels}   file = the .glb holding the clip: the entry's model when the
      reader embedded it (FF7, Parasite Eve), else `<slug>.anims.glb`, a sibling GLB whose node names match the
      model's skeleton so a viewer binds its tracks to the model by name (three.js AnimationMixer on model + anims).
      drives: "skeleton" (bone TRS) | "controls" (native control parameters on helper nodes, not bones).
  2D  sprite_capture entries {clip, name, sheet, preview, webp, mp4, ...} are kept untouched.

DOA2 LE MOT banks (gbox.doa2_motion) hold 44 IK/control channels per clip, not 44 bones. They are exported as
control clips: 44 helper nodes `mot_chNN` under `doa2_mot_controls`, each channel's decoded value in its
translation.x per native frame (compact polynomials from FUN_8c0e86c2; raw int16x3 streams as their stored
integers). The mesh does not move from these: the native IK solver that maps them onto joints is not decoded.
"""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path

WIDTH = {"translation": 3, "rotation": 4, "scale": 3}
F32 = 5126
DOA2_FPS = 60.0                     # native frame clock assumed 60 Hz (Dreamcast DOA2 runs at 60); not runtime-verified
DOA2_CONTROL_ROOT = "doa2_mot_controls"


def _is_sprite(entry: dict) -> bool:
    return "clip" in entry or "sheet" in entry


# ------------------------------------------------------------------------------------------------ reading

def clips_in(path: Path) -> list[dict]:
    """The glTF animations a .glb/.gltf holds: [{name, duration_s, channels, nodes}]. Unreadable file -> []."""
    from .re4gc_models import _gltf_load
    try:
        gl, acc, _image = _gltf_load(Path(path))
    except (OSError, ValueError, KeyError, IndexError, struct.error):
        return []
    out = []
    for i, a in enumerate(gl.get("animations") or []):
        end = 0.0
        for s in a.get("samplers", []):
            meta = gl["accessors"][s["input"]]
            if meta.get("max"):
                end = max(end, float(meta["max"][0]))
            else:
                try:
                    end = max(end, float(acc(s["input"]).max()))
                except (ValueError, KeyError, IndexError):
                    pass
        out.append({"name": a.get("name") or f"clip{i:02d}", "duration_s": round(end, 4),
                    "channels": len(a.get("channels", [])),
                    "nodes": len({c.get("target", {}).get("node") for c in a.get("channels", [])})})
    return out


def skeleton_nodes(path: Path) -> list[dict]:
    """The model's skin joints (or every node when it has no skin) as [{name, parent, translation, rotation, scale}]
    with parent indices into this list: the skeleton an anims GLB shares with its model by node name."""
    from .re4gc_models import _gltf_load
    gl, _acc, _image = _gltf_load(Path(path))
    nodes = gl.get("nodes", [])
    keep = sorted({j for s in gl.get("skins", []) for j in s["joints"]}) or list(range(len(nodes)))
    index = {n: k for k, n in enumerate(keep)}
    parent = {c: p for p, n in enumerate(nodes) for c in n.get("children", [])}
    out = []
    for n in keep:
        node = nodes[n]
        if "matrix" in node:
            t, r, s = _decompose(node["matrix"])
        else:
            t, r, s = node.get("translation", [0, 0, 0]), node.get("rotation", [0, 0, 0, 1]), node.get("scale", [1, 1, 1])
        p = parent.get(n)
        while p is not None and p not in index:
            p = parent.get(p)
        out.append({"name": node.get("name") or f"node{n}", "parent": index.get(p) if p is not None else None,
                    "translation": list(t), "rotation": list(r), "scale": list(s)})
    return out


def _decompose(m: list[float]):
    """Column-major glTF matrix -> TRS (no shear)."""
    cols = [m[0:3], m[4:7], m[8:11]]
    s = [math.sqrt(sum(x * x for x in c)) or 1.0 for c in cols]
    r = [[cols[c][k] / s[c] for c in range(3)] for k in range(3)]    # row-major rotation
    tr = r[0][0] + r[1][1] + r[2][2]
    if tr > 0:
        w = math.sqrt(tr + 1) * 2
        q = [(r[2][1] - r[1][2]) / w, (r[0][2] - r[2][0]) / w, (r[1][0] - r[0][1]) / w, 0.25 * w]
    else:
        i = max(range(3), key=lambda k: r[k][k])
        j, k = (i + 1) % 3, (i + 2) % 3
        w = math.sqrt(max(1e-12, 1 + r[i][i] - r[j][j] - r[k][k])) * 2
        q = [0.0] * 4
        q[i] = 0.25 * w
        q[j] = (r[j][i] + r[i][j]) / w
        q[k] = (r[k][i] + r[i][k]) / w
        q[3] = (r[k][j] - r[j][k]) / w
    return m[12:15], q, s


# ------------------------------------------------------------------------------------------------ writing

def check(nodes: list[dict], clips: list[dict]) -> list[str]:
    """Problems that would make the clip GLB invalid; empty = valid."""
    p, names = [], {n["name"]: i for i, n in enumerate(nodes)}
    if len(names) != len(nodes):
        p.append("node names must be unique (tracks bind by name)")
    for i, n in enumerate(nodes):
        if n.get("parent") is not None and not 0 <= n["parent"] < len(nodes):
            p.append(f"node {n['name']}: parent missing")
    for c in clips:
        if not c.get("channels"):
            p.append(f"clip {c.get('name')}: no channels")
        for ch in c.get("channels", []):
            tag = f"clip {c.get('name')} {ch.get('node')} {ch.get('path')}"
            if ch.get("node") not in names:
                p.append(f"{tag}: target node missing")
            if ch.get("path") not in WIDTH:
                p.append(f"{tag}: path must be translation | rotation | scale")
                continue
            t, v = ch["times"], ch["values"]
            if not t or len(t) != len(v):
                p.append(f"{tag}: times/values mismatch")
            if any(b <= a for a, b in zip(t, t[1:])):
                p.append(f"{tag}: times not strictly increasing")
            if any(len(x) != WIDTH[ch["path"]] for x in v):
                p.append(f"{tag}: value width != {WIDTH[ch['path']]}")
            if not all(math.isfinite(x) for x in t) or not all(math.isfinite(x) for row in v for x in row):
                p.append(f"{tag}: non-finite keys")
    return p


def build_glb(nodes: list[dict], clips: list[dict], name: str = "clips", extras: dict | None = None) -> bytes:
    """A self-contained GLB: the nodes (skeleton or helper nodes, no mesh) + one glTF animation per clip.
    nodes: [{name, parent, translation?, rotation?, scale?}]; clips: [{name, channels: [{node (name), path, times,
    values, interpolation?}], extras?}]. Channels sharing one times list share one input accessor."""
    problems = check(nodes, clips)
    if problems:
        raise ValueError("animation clips: " + "; ".join(problems[:8]))
    blob, views, accs = bytearray(), [], []

    def add(flat: list[float], count: int, typ: str, minmax: bool = False) -> int:
        while len(blob) % 4:
            blob.append(0)
        data = struct.pack(f"<{len(flat)}f", *flat)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data)})
        blob.extend(data)
        acc = {"bufferView": len(views) - 1, "componentType": F32, "count": count, "type": typ}
        if minmax:
            acc["min"], acc["max"] = [min(flat)], [max(flat)]
        accs.append(acc)
        return len(accs) - 1

    index = {n["name"]: i for i, n in enumerate(nodes)}
    gl_nodes = []
    for n in nodes:
        g = {"name": n["name"]}
        for k, dflt in (("translation", [0, 0, 0]), ("rotation", [0, 0, 0, 1]), ("scale", [1, 1, 1])):
            if n.get(k) is not None and list(n[k]) != dflt:
                g[k] = [float(x) for x in n[k]]
        gl_nodes.append(g)
    for i, n in enumerate(nodes):
        if n.get("parent") is not None:
            gl_nodes[n["parent"]].setdefault("children", []).append(i)
    anims = []
    for c in clips:
        samplers, channels, inputs = [], [], {}
        for ch in c["channels"]:
            key = tuple(ch["times"])
            if key not in inputs:
                inputs[key] = add([float(t) for t in ch["times"]], len(key), "SCALAR", minmax=True)
            out = add([float(x) for row in ch["values"] for x in row], len(ch["values"]),
                      "VEC4" if ch["path"] == "rotation" else "VEC3")
            samplers.append({"input": inputs[key], "output": out, "interpolation": ch.get("interpolation", "LINEAR")})
            channels.append({"sampler": len(samplers) - 1, "target": {"node": index[ch["node"]], "path": ch["path"]}})
        a = {"name": c["name"], "samplers": samplers, "channels": channels}
        if c.get("extras"):
            a["extras"] = c["extras"]
        anims.append(a)
    while len(blob) % 4:
        blob.append(0)
    roots = [i for i, n in enumerate(nodes) if n.get("parent") is None]
    gl = {"asset": {"version": "2.0", "generator": "gbox anim_clips"}, "scene": 0,
          "scenes": [{"name": name, "nodes": roots}], "nodes": gl_nodes, "animations": anims,
          "accessors": accs, "bufferViews": views, "buffers": [{"byteLength": len(blob)}]}
    if extras:
        gl["extras"] = {"gbox": extras}
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    return (struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob))
            + struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob))


def read_glb(data: bytes) -> tuple[dict, bytes]:
    if data[:4] != b"glTF":
        raise ValueError("not a GLB")
    jl = struct.unpack_from("<I", data, 12)[0]
    bl = struct.unpack_from("<I", data, 20 + jl)[0]
    return json.loads(data[20:20 + jl]), data[28 + jl:28 + jl + bl]


# ------------------------------------------------------------------------------------------------ DOA2 MOT

def doa2_clips(mot: bytes, source: str, fps: float = DOA2_FPS, limit: int | None = None) -> tuple[list[dict], list[dict], dict]:
    """A DOA2 compact44/mixed44 MOT bank -> (control nodes, clips, report). One clip per unique clip table; every
    channel sampled at each native frame 0..duration. Raises doa2_motion.MotionFormatError for other containers."""
    from . import doa2_motion as M
    info = M.inspect_mot(mot, include_clips=True, include_tracks=True, encoding="compact44")
    tracks = {t["offset"]: t for t in info["tracks"]}
    polys = {}
    nodes = [{"name": DOA2_CONTROL_ROOT, "parent": None}] + [
        {"name": f"mot_ch{k:02d}", "parent": 0} for k in range(M.CHANNELS)]
    clips, skipped, seen = [], [], {}
    stem = Path(source).stem.lower()
    for cid, off in zip(info["clip_ids"], info["clip_offsets"]):
        if off in seen:                                   # an alias of a clip table already exported
            seen[off].setdefault("extras", {}).setdefault("aliases", []).append(cid)
            continue
        table = next(t for t in info["clip_tables"] if t["offset"] == off)
        n = int(table["duration"])
        frames = list(range(n + 1))
        times = [f / fps for f in frames] if n else [0.0, 1 / fps]    # a one-key pose holds for one frame
        channels, missing = [], []
        for k, ptr in enumerate(table["channel_offsets"]):
            tr = tracks[ptr]
            if tr["encoding"] == "compact-scalar":
                if ptr not in polys:
                    polys[ptr] = M.scalar_polynomials(tr)
                vals = [_poly_at(polys[ptr], tr, f) for f in frames]
            elif tr["encoding"] == "raw-i16x3" and tr.get("samples") == n + 1:
                group = [i for i, p in enumerate(table["channel_offsets"]) if p == ptr]
                comp = group.index(k)
                raw = bytes.fromhex(tr["payload_hex"])
                vals = [float(struct.unpack_from("<h", raw, 6 * f + 2 * comp)[0]) for f in frames]
            else:
                missing.append(k)
                continue
            if not n:
                vals = vals * 2
            channels.append({"node": f"mot_ch{k:02d}", "path": "translation", "times": times,
                             "values": [[v, 0.0, 0.0] for v in vals]})
        if not channels:
            skipped.append({"clip_id": cid, "reason": "no decodable channel"})
            continue
        clip = {"name": f"{stem}_{cid:03d}", "channels": channels,
                "extras": {"source": source, "clip_id": cid, "table_offset": off, "native_frames": n,
                           "fps_assumed": fps, "drives": "controls", "undecoded_channels": missing}}
        seen[off] = clip
        clips.append(clip)
        if limit and len(clips) >= limit:
            break
    report = {"format": info["format"], "clips": len(info["clip_offsets"]), "exported": len(clips),
              "skipped": skipped, "fps_assumed": fps, "drives": "controls",
              "note": "44 native IK/control channels per clip (value in translation.x of mot_chNN); "
                      "the solver that maps them onto joints is not decoded, so the mesh does not move from them",
              "runtime_interpolation_verified": False, "sha256": info["sha256"]}
    return nodes, clips, report


def _poly_at(polys: list[dict], track: dict, frame: int) -> float:
    from .doa2_motion import BASE_SCALE
    for p in polys:
        if frame < p["start"] + p["duration"]:
            t, c = frame - p["start"], p["coefficients"]
            return ((c[3] * t + c[2]) * t + c[1]) * t + c[0]
    return track["final_quantized_base"] * BASE_SCALE


# ------------------------------------------------------------------------------------------------ collection meta

def entries_for(clips: list[dict], file: str, source: str, drives: str) -> list[dict]:
    """meta.animations rows for clips written to `file` (duration from each clip's last key). Kept small: a DOA2 bank
    lists hundreds of clips and /api/characters returns every entry's meta."""
    rows = []
    for c in clips:
        end = max((ch["times"][-1] for ch in c["channels"]), default=0.0)
        rows.append({"name": c["name"], "duration_s": round(float(end), 4), "source": source, "file": file,
                     "drives": drives})
    return rows


def embedded_entries(model: Path, file: str | None = None) -> list[dict]:
    """meta.animations rows for the clips a reader already embedded in the model GLB (FF7, Parasite Eve, ...)."""
    file = file or Path(model).name
    return [{"name": c["name"], "duration_s": c["duration_s"], "source": f"embedded in {file}", "file": file,
             "drives": "skeleton"} for c in clips_in(model)]


def merge(existing: list[dict], rows: list[dict], file: str) -> list[dict]:
    """Replace the rows of one clip file, keep sprite clips and other files' rows."""
    keep = [a for a in existing or [] if _is_sprite(a) or a.get("file") != file]
    return keep + rows


def attach(root: Path, slug: str, nodes: list[dict], clips: list[dict], source: str, drives: str,
           extras: dict | None = None) -> dict:
    """Write <slug>.anims.glb into the collection entry and record its clips in meta.animations."""
    from . import characters as C
    meta = C.get(root, slug)
    file = f"{slug}.anims.glb"
    data = build_glb(nodes, clips, name=f"{slug} clips", extras={"source": source, "drives": drives, **(extras or {})})
    d = Path(root) / slug
    tmp = d / (file + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(d / file)
    meta["animations"] = merge(meta.get("animations"), entries_for(clips, file, source, drives), file)
    meta["anims_file"] = file
    return C.put_meta(root, meta)
