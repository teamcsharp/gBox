"""Replacement readiness: every collected character carries the data a swap writer needs, and every target game slot
says what it accepts, so "who can replace this?" is answered from stored data, not by opening model files.

Operator requirement (2026-10-13): "every title we are extracting people from are also setting up retargeting and
rapid replacement data for our system and database to make mods and replacements without issue, seamless and quickly."

1. The entry standard (meta["readiness"], written by post_collect(), which characters.add() runs for every reader):

   model        format, up axis (+Y expected), height in model units, unit ("m" when 0.3..3 m tall, else "units" with
                a recorded to_metres estimate), ground, facing (+Z expected)
   rig          skinned, joints, inverse bind matrices, every one of retarget_profile.ROLES (18) either mapped
                (meta.rig.roles) or listed in roles_absent with the reason (creature, sprite, no clavicle joint ...),
                where the mapping came from (reader | auto:name | auto:tree | auto:pose), sanity problems
   bind         rest pose of the arms (T | A | arms_down) and their angles
   proportions  hip height, leg / arm length, shoulder width, arm span, head size: fractions of the figure height
   textures     images (size, type), materials, alpha, atlas (one image), largest side, texels
   mesh / skin  triangles, vertices, primitives; influences per vertex (max, mean, histogram), unweighted vertices
   kind         humanoid | creature | sprite | prop (meta["kind"] keeps the collection's own kind)
   hints        default retarget hints: up-axis fix, metres per unit, facing, pose, head-scale suggestion (chibi),
                rigid-only, triangles to decimate from
   status       ready | limited | blocked | n/a, with `missing` (what keeps it from ready) and `fixed` (what the step
                derived and stored: auto-mapped roles, stats)

   Readiness is versioned (READINESS_VERSION) and tied to the model file (size + mtime): a new version or a changed
   model recomputes it; nothing is re-extracted. post_collect() fixes what can be derived: body roles from joint
   names, else the joint tree, else the rest pose (characters.tree_roles / oot_swap.guess_roles); a guess is stored
   only when it passes the sanity check and never replaces roles a reader or the operator set.

2. Target slots: SPECS per writer (target skeleton, role map, budgets: triangles, vertices, texture side, influences
   per vertex, whether the writer decimates, donor restrictions), merged with the live constants of the writer
   module (MAX_TRIS, ORDER, *_ROLES ...) and a module's own REPLACEMENT_SPEC when it defines one; slot_table() lists
   every game with a writer and its slots (char_coverage.cast_slots).

3. The compatibility index (donor x writer): compatible?, budget fit (fits | decimate | over), decimation ratio,
   missing roles, notes; precomputed from the stored readiness only, kept in memory per library and in
   <library>/.replacement/index.json; put_meta() invalidates the donor (characters.put_meta -> invalidate()).
   candidates(game, slot) answers "who can replace this" for the pick whip, cast swap and Special builds.

4. report(): per game the reader, entries ready / not ready and why, the writer and its slots with compatible donors
   (characters op=readiness, GET /api/replacement/report, docs/replacement-readiness.md).
"""
from __future__ import annotations

import json
import math
import re
import struct
import threading
import time
from pathlib import Path

import numpy as np

from .retarget_profile import ROLES

READINESS_VERSION = 1
INDEX_VERSION = 1
INDEX_DIR = ".replacement"                    # inside the library root; no meta.json, so never a collection entry
RETARGET_ROLES = {"hip", "chest", "head", "l_upper", "l_fore", "l_hand", "r_upper", "r_fore", "r_hand",
                  "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot"}     # = doa2_swap.REQUIRED_ROLES
OPTIONAL_ROLES = set(ROLES) - RETARGET_ROLES   # neck, clavicles: many game skeletons have none
HUMANOID_CORE = {"hip", "head", "l_upper", "r_upper", "l_thigh", "r_thigh"}
PROP_KINDS = {"vehicle", "object", "environment"}
METRES = (0.3, 3.0)                           # a figure this tall in model units is taken to be in metres
HUMAN_M = 1.7
# titles of writer games whose module lists bare ids (a set, not {id: title}); the catalog overrides them when known
TITLES = {"0871eee3b68cdea3": ("Resident Evil 6", "xbox360"),
          "afd2fc507bb69843": ("Metal Gear Solid - VR Missions (USA)", "psx"),
          "f55555ee6513391b": ("Metal Gear Solid - VR Missions", "psx"),
          "f27552db74dffdeb": ("Metal Gear Solid (USA) (Disc 1)", "psx"),
          "b13795ef235edee3": ("Metal Gear Solid (USA) (Disc 2)", "psx"),
          "bc02bb68790ce2e7": ("Crazy Taxi (USA)", "gamecube")}
PLATFORMS = ("psx", "ps2", "n64", "dreamcast", "gamecube", "arcade", "windows_native", "pc_steam", "nds", "3ds",
             "psp", "xbox360", "wii", "genesis", "megadrive", "snes")


# ================================================================ glTF reading (no image decoding)

def _load_gltf(path: Path) -> tuple[dict, list[bytes]]:
    p = Path(path)
    if p.suffix.lower() == ".gltf":
        import base64
        gl = json.loads(p.read_text("utf-8"))
        bins = []
        for b in gl.get("buffers", []):
            u = b.get("uri", "")
            bins.append(base64.b64decode(u.split(",", 1)[1]) if u.startswith("data:") else (p.parent / u).read_bytes())
        return gl, bins
    d = p.read_bytes()
    if d[:4] != b"glTF":
        raise ValueError(f"{p.name} is not a glTF binary")
    jl = struct.unpack_from("<I", d, 12)[0]
    gl = json.loads(d[20:20 + jl])
    bins = [d[20 + jl + 8:]] if len(d) > 20 + jl + 8 else [b""]
    return gl, bins


_COMP = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def _acc(gl: dict, bins: list[bytes], i: int) -> np.ndarray:
    a = gl["accessors"][i]
    nc = _NCOMP[a["type"]]
    dt = np.dtype(_COMP[a["componentType"]])
    if "bufferView" not in a:
        return np.zeros((a["count"], nc), dt)
    v = gl["bufferViews"][a["bufferView"]]
    stride = v.get("byteStride", dt.itemsize * nc)
    base = v.get("byteOffset", 0) + a.get("byteOffset", 0)
    raw = bins[v.get("buffer", 0)]
    if stride == dt.itemsize * nc:
        arr = np.frombuffer(raw, dt, a["count"] * nc, base).reshape(a["count"], nc)
    else:
        rows = np.frombuffer(raw, np.uint8, stride * (a["count"] - 1) + dt.itemsize * nc, base)
        arr = np.stack([np.frombuffer(rows[k * stride:k * stride + dt.itemsize * nc].tobytes(), dt)
                        for k in range(a["count"])]) if a["count"] else np.zeros((0, nc), dt)
    if a.get("normalized") and dt.kind in "ui":
        arr = arr / float(np.iinfo(dt).max)
    return arr


def _node_world(gl: dict) -> list[np.ndarray]:
    nodes = gl.get("nodes", [])
    parent = {c: i for i, nd in enumerate(nodes) for c in nd.get("children", [])}

    def local(nd):
        if "matrix" in nd:
            return np.array(nd["matrix"], float).reshape(4, 4).T
        x, y, z, w = nd.get("rotation", [0, 0, 0, 1])
        r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                      [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                      [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        m = np.eye(4)
        m[:3, :3] = r @ np.diag(nd.get("scale", [1, 1, 1]))
        m[:3, 3] = nd.get("translation", [0, 0, 0])
        return m
    out: list = [None] * len(nodes)

    def world(i, depth=0):
        if out[i] is None:
            p = parent.get(i)
            out[i] = local(nodes[i]) if p is None or depth > 256 else world(p, depth + 1) @ local(nodes[i])
        return out[i]
    for i in range(len(nodes)):
        world(i)
    return out


def _image_info(gl: dict, bins: list[bytes], path: Path, k: int) -> dict:
    src = gl["images"][k]
    mime = src.get("mimeType") or ""
    try:
        if "uri" in src:
            u = src["uri"]
            if u.startswith("data:"):
                import base64
                mime = mime or u[5:u.find(";")]
                data = base64.b64decode(u.split(",", 1)[1])
            else:
                data = (Path(path).parent / u).read_bytes()
                mime = mime or ("image/png" if u.lower().endswith(".png") else "image/jpeg")
        else:
            v = gl["bufferViews"][src["bufferView"]]
            data = bins[v.get("buffer", 0)][v.get("byteOffset", 0):v.get("byteOffset", 0) + v["byteLength"]]
        import io
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:            # header only: the pixels are never decoded
            return {"w": int(im.width), "h": int(im.height), "mime": mime or Image.MIME.get(im.format, ""),
                    "mode": im.mode}
    except Exception as e:                                 # noqa: BLE001 - an unreadable image is reported, not fatal
        return {"w": 0, "h": 0, "mime": mime, "error": str(e)[:80]}


# ================================================================ model analysis

def analyze_model(path: Path) -> dict:
    """Everything the standard needs from the model file. Private keys (leading "_") carry the joint positions and
    the hierarchy for role mapping and are not stored."""
    path = Path(path)
    if path.suffix.lower() == ".png":
        from PIL import Image
        with Image.open(path) as im:
            sheet = [int(im.width), int(im.height)]
        return {"format": "png", "sheet": sheet, "mesh": {"triangles": 0, "vertices": 0, "primitives": 0, "meshes": 0},
                "textures": {"count": 1, "max_side": max(sheet), "texels": sheet[0] * sheet[1], "atlas": True,
                             "images": [{"w": sheet[0], "h": sheet[1], "mime": "image/png"}]},
                "rig": {"skinned": False, "joints": 0}}
    gl, bins = _load_gltf(path)
    Wn = _node_world(gl)
    nodes = gl.get("nodes", [])
    skins = gl.get("skins") or []
    tris = verts = nprims = 0
    hist = np.zeros(9, np.int64)                           # influences per vertex 0..8
    rigid_v = unweighted = 0
    pts = []
    for ni, nd in enumerate(nodes):
        if "mesh" not in nd:
            continue
        sk = skins[nd["skin"]] if "skin" in nd and nd["skin"] < len(skins) else None
        if sk is not None:
            ibm = (_acc(gl, bins, sk["inverseBindMatrices"]).astype(float).reshape(-1, 4, 4).transpose(0, 2, 1)
                   if "inverseBindMatrices" in sk else np.tile(np.eye(4), (len(sk["joints"]), 1, 1)))
            skm = np.array([Wn[j] @ ibm[k] for k, j in enumerate(sk["joints"])]) if sk["joints"] else None
        for pr in gl["meshes"][nd["mesh"]].get("primitives", []):
            a = pr.get("attributes", {})
            if "POSITION" not in a:
                continue
            nprims += 1
            P = _acc(gl, bins, a["POSITION"]).astype(float)
            n = len(P)
            verts += n
            mode = pr.get("mode", 4)
            cnt = gl["accessors"][pr["indices"]]["count"] if "indices" in pr else n
            tris += cnt // 3 if mode == 4 else max(0, cnt - 2) if mode in (5, 6) else 0
            if sk is not None and "JOINTS_0" in a and "WEIGHTS_0" in a and skm is not None:
                J = [_acc(gl, bins, a["JOINTS_0"]).astype(int)]
                W = [_acc(gl, bins, a["WEIGHTS_0"]).astype(float)]
                if "JOINTS_1" in a and "WEIGHTS_1" in a:
                    J.append(_acc(gl, bins, a["JOINTS_1"]).astype(int))
                    W.append(_acc(gl, bins, a["WEIGHTS_1"]).astype(float))
                J, W = np.concatenate(J, 1), np.concatenate(W, 1)
                c = (W > 1e-4).sum(1)
                hist += np.bincount(np.minimum(c, 8), minlength=9)[:9]
                unweighted += int((c == 0).sum())
                k = np.clip(J[np.arange(n), W.argmax(1)], 0, len(skm) - 1)
                M = skm[k]
                Pw = np.einsum("nij,nj->ni", M[:, :3, :3], P) + M[:, :3, 3]
            else:
                rigid_v += n
                Pw = P @ Wn[ni][:3, :3].T + Wn[ni][:3, 3]
            if n:
                pts.append(Pw[:: max(1, n // 4000)])         # a sample is plenty for bounds / feet
    P = np.concatenate(pts) if pts else np.zeros((0, 3))
    joints = sorted({j for s in skins for j in s.get("joints", [])})
    jname = {j: nodes[j].get("name") or f"node{j}" for j in joints}
    parent_node = {c: i for i, nd in enumerate(nodes) for c in nd.get("children", [])}
    jparent = {}
    for j in joints:
        p = parent_node.get(j)
        while p is not None and p not in jname:
            p = parent_node.get(p)
        jparent[jname[j]] = jname.get(p) if p is not None else None
    jpos = {jname[j]: np.asarray(Wn[j][:3, 3], float) for j in joints}
    skinned_v = int(hist.sum())
    mats = gl.get("materials", [])
    texd = [m.get("pbrMetallicRoughness", {}).get("baseColorTexture") for m in mats]
    images = [_image_info(gl, bins, path, k) for k in range(len(gl.get("images", [])))]
    out = {
        "format": path.suffix.lower().lstrip("."),
        "mesh": {"triangles": int(tris), "vertices": int(verts), "primitives": nprims,
                 "meshes": len(gl.get("meshes", []))},
        "rig": {"skinned": bool(joints), "skins": len(skins), "joints": len(joints),
                "inverse_bind": bool(skins) and all("inverseBindMatrices" in s for s in skins)},
        "skin": {"max_influences": int(np.nonzero(hist)[0].max()) if skinned_v else 0,
                 "mean_influences": round(float((hist * np.arange(9)).sum() / skinned_v), 3) if skinned_v else 0.0,
                 "histogram": {str(i): int(v) for i, v in enumerate(hist) if v},
                 "skinned_vertices": skinned_v, "rigid_vertices": int(rigid_v), "unweighted_vertices": int(unweighted)},
        "textures": {"count": len(images), "images": images[:12],
                     "max_side": max([max(i["w"], i["h"]) for i in images] or [0]),
                     "texels": int(sum(i["w"] * i["h"] for i in images)),
                     "materials": len(mats), "textured_materials": sum(1 for t in texd if t),
                     "alpha": any((m.get("alphaMode") or "OPAQUE") != "OPAQUE" for m in mats),
                     "atlas": len(images) == 1 and len(mats) >= 1},
        "_points": P, "_joints": jpos, "_parent": jparent,
    }
    if len(P):
        lo, hi = P.min(0), P.max(0)
        out["bounds"] = {"min": [round(float(v), 4) for v in lo], "max": [round(float(v), 4) for v in hi]}
    return out


# ================================================================ body roles

_SIDE = {"l": "l", "left": "l", "lft": "l", "r": "r", "right": "r", "rgt": "r", "rt": "r", "lt": "l"}
_EXCLUDE = {"finger", "fingers", "thumb", "index", "middle", "ring", "pinky", "little", "nub", "end", "tip", "top",
            "toe", "toes", "ball", "jaw", "eye", "eyes", "brow", "lip", "tongue", "hair", "ik", "pole", "target",
            "twist", "roll", "helper", "ponytail", "skirt", "cape", "tail", "wing", "weapon", "prop", "breast"}
_ROLE_WORDS = [                                            # (role kind, joined name forms), first hit wins
    ("hand", {"hand", "wrist", "handdummy", "offhand", "offhanddummy"}),
    ("fore", {"forearm", "lowerarm", "armlower", "elbow", "loarm", "lowarm", "armlow", "fore"}),
    ("clav", {"clavicle", "clav", "collar", "collarbone", "shoulderblade"}),
    ("upper", {"upperarm", "armupper", "uparm", "humerus", "arm", "armup", "bicep", "upper"}),
    ("foot", {"foot", "ankle", "footback", "heel"}),
    ("shin", {"calf", "shin", "lowerleg", "leglower", "knee", "crus", "leg", "loleg", "legknee"}),
    ("thigh", {"thigh", "upleg", "upperleg", "legupper", "femur", "hip", "legup"}),
]
_CENTRE = [("hip", ["hips", "pelvis", "hip", "waist", "groin", "cog"]),
           ("chest", ["chest", "upperchest", "spine3", "spine2", "torso", "ribcage", "breastbone", "spine1", "spine"]),
           ("neck", ["neck", "neck1", "neck0"]),
           ("head", ["head", "head1", "head0"])]


def _tokens(name: str) -> list[str]:
    s = re.sub(r"^(mixamorig\d*|bip\d*|bone|jnt|jt|def|b|j)[:_ .\-]", "", str(name), flags=re.I)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    return re.findall(r"[a-z]+|\d+", s.lower())


def name_roles(names: list[str], parent: dict | None = None) -> dict[str, str]:
    """Body roles from joint names (Mixamo, Biped, Unreal / Unity humanoid, L_/R_ prefixes, .L/.R suffixes): the
    candidate nearest the root wins each role."""
    parent = parent or {}

    def depth(n):
        d, seen = 0, set()
        while parent.get(n) and n not in seen:
            seen.add(n)
            n, d = parent[n], d + 1
        return d
    cands: dict[str, list[str]] = {}
    for n in names:
        toks = _tokens(n)
        if not toks or set(toks) & _EXCLUDE:
            continue
        side = next((_SIDE[t] for t in toks if t in _SIDE), None)
        if side is None:                                   # "lthigh" / "rarm" glued forms
            m = re.fullmatch(r"([lr])(arm|forearm|hand|thigh|calf|shin|foot|leg|upleg|clavicle|shoulder|upperarm)\d*",
                             "".join(t for t in toks if not t.isdigit()))
            if m:
                side, toks = m.group(1), [m.group(2)]
        word = "".join(t for t in toks if t not in _SIDE and not t.isdigit())
        if side:
            if word == "shoulder":                         # shoulder: the clavicle when an upper arm exists too
                cands.setdefault(f"{side}_shoulder", []).append(n)
                continue
            for kind, forms in _ROLE_WORDS:
                if word in forms:
                    cands.setdefault(f"{side}_{kind}", []).append(n)
                    break
        else:
            full = "".join(t for t in toks if t not in _SIDE)
            for role, forms in _CENTRE:
                if full in forms or word in forms:
                    cands.setdefault(role + ":" + str(forms.index(full if full in forms else word)), []).append(n)
                    break
    out: dict[str, str] = {}
    for role, _forms in _CENTRE:
        keys = sorted((k for k in cands if k.startswith(role + ":")), key=lambda k: int(k.split(":")[1]))
        if keys:
            out[role] = min(cands[keys[0]], key=depth)
    for side in "lr":
        for kind, role in (("clav", "clav"), ("upper", "upper"), ("fore", "fore"), ("hand", "hand"),
                           ("thigh", "thigh"), ("shin", "shin"), ("foot", "foot")):
            if cands.get(f"{side}_{kind}"):
                out[f"{side}_{role}"] = min(cands[f"{side}_{kind}"], key=depth)
        sh = cands.get(f"{side}_shoulder")
        if sh:
            if f"{side}_upper" in out and f"{side}_clav" not in out:
                out[f"{side}_clav"] = min(sh, key=depth)
            elif f"{side}_upper" not in out:
                out[f"{side}_upper"] = min(sh, key=depth)
    if out.get("l_upper") and out.get("r_upper") and parent:   # chest = where the arms meet (spine numbering varies)
        def chain(n):
            c = [n]
            while parent.get(c[-1]) and len(c) < 512:
                c.append(parent[c[-1]])
            return c
        la, ra = chain(out.get("l_clav") or out["l_upper"]), chain(out.get("r_clav") or out["r_upper"])
        meet = next((x for x in la if x in ra), None)
        if meet and meet not in (out.get("hip"), out.get("head")):
            out["chest"] = meet
    return out


def sanity(roles: dict, pos: dict) -> list[str]:
    """Problems with a role map on the rest pose (+Y up). Empty = plausible."""
    P = {r: np.asarray(pos[b], float) for r, b in roles.items() if b in pos}
    probs = []
    unknown = sorted(r for r, b in roles.items() if b not in pos)
    if unknown:
        probs.append(f"roles name joints the model lacks: {', '.join(unknown[:6])}")
    if "hip" not in P:
        probs.append("no hip")
        return probs
    pts = np.array(list(P.values()))
    H = float(np.ptp(pts[:, 1])) or float(np.ptp(pts)) or 1.0
    if "head" in P and P["head"][1] <= P["hip"][1]:
        probs.append("head is not above the hip (+Y up)")
    for a, b in (("l_upper", "r_upper"), ("l_thigh", "r_thigh"), ("l_hand", "r_hand"), ("l_foot", "r_foot")):
        if a in P and b in P:
            if np.linalg.norm(P[a] - P[b]) < 0.01 * H:
                probs.append(f"{a} and {b} are the same point")
            elif (P[a][0] - P["hip"][0]) * (P[b][0] - P["hip"][0]) > 0 and abs(P[a][0] - P[b][0]) < 0.02 * H:
                probs.append(f"{a} and {b} are on the same side")
    for f in ("l_foot", "r_foot"):
        if f in P and P[f][1] > P["hip"][1]:
            probs.append(f"{f} is above the hip")
    core = [r for r in HUMANOID_CORE if r in roles]
    if len({roles[r] for r in core}) < len(core):
        probs.append("one joint holds two core roles")
    return probs


def _to_y_up(v: np.ndarray, up: str) -> np.ndarray:
    v = np.asarray(v, float)
    if up == "+Z":
        return np.stack([v[..., 0], v[..., 2], -v[..., 1]], -1)
    if up == "-Y":
        return np.stack([v[..., 0], -v[..., 1], -v[..., 2]], -1)
    if up == "+X":
        return np.stack([-v[..., 1], v[..., 0], v[..., 2]], -1)
    return v


def _up_axis(roles: dict, pos: dict, points: np.ndarray) -> str:
    if roles.get("hip") in pos and roles.get("head") in pos:
        d = np.asarray(pos[roles["head"]]) - np.asarray(pos[roles["hip"]])
        k = int(np.argmax(np.abs(d)))
        if abs(d[k]) > 1e-9:
            return {0: "+X", 1: "+Y", 2: "+Z"}[k] if d[k] > 0 else ("-Y" if k == 1 else "+Y")
    if len(points):
        ext = np.ptp(points, 0)
        if ext[2] > 1.25 * max(ext[1], 1e-9) and ext[2] >= ext[0]:
            return "+Z"
    return "+Y"


def geometry_roles(path: Path) -> tuple[dict, str]:
    """Body roles from the skeleton's shape when the names say nothing (node000..): characters.tree_roles, else
    oot_swap.guess_roles on the rest pose. -> (roles, source) or ({}, '')."""
    try:
        from . import characters as C
        r = C.tree_roles(Path(path))
        if r and "hip" in r:
            return r, "auto:tree"
    except Exception:                                      # noqa: BLE001 - not a humanoid tree
        pass
    try:
        from . import oot_swap
        r = oot_swap.guess_model_roles(Path(path))
        if r and "hip" in r:
            return r, "auto:pose"
    except Exception:                                      # noqa: BLE001
        pass
    return {}, ""


def reader_roles(meta: dict, model: Path, pos: dict) -> dict:
    """The entry's own reader's role reader (characters.ROLE_BACKFILL: PSO classes, SM64 Mario), when it has one and
    its answer is sane."""
    try:
        from . import cast_swap
        from . import characters as C
        fn = C.ROLE_BACKFILL.get(cast_swap.extractor_of(meta) or "")
        roles = fn(Path(model)) if fn else {}
    except Exception:                                      # noqa: BLE001 - the guessers come next
        return {}
    return roles if roles and "hip" in roles and not sanity(roles, pos) else {}


def auto_roles(path: Path, analysis: dict) -> tuple[dict, str, list[str]]:
    """The best role map this step can derive: names, then the tree, then the pose; only a sane one is returned."""
    pos, parent = analysis.get("_joints") or {}, analysis.get("_parent") or {}
    if len(pos) < 4:
        return {}, "", ["fewer than 4 joints"]
    tried = []
    r = name_roles(list(pos), parent)
    if HUMANOID_CORE <= set(r):
        p = sanity(r, pos)
        if not p:
            return r, "auto:name", []
        tried.append("names: " + "; ".join(p))
    if _up_axis({}, pos, analysis.get("_points", np.zeros((0, 3)))) == "+Y":
        g, src = geometry_roles(path)
        if g:
            p = sanity(g, pos)
            if not p and HUMANOID_CORE <= set(g):
                return g, src, []
            tried.append(f"{src}: " + ("; ".join(p) or "incomplete"))
    return {}, "", tried or ["no humanoid joint names or limb tree"]


def match_case(roles: dict, pos: dict) -> dict[str, str]:
    """Role bones that name no joint exactly but exactly one ignoring case ('smid' for the GLB's 'Smid'):
    {role: the joint's real name}. Writers look bones up by exact name, so these roles were silently lost."""
    low: dict[str, list[str]] = {}
    for n in pos:
        low.setdefault(n.casefold(), []).append(n)
    out = {}
    for r, b in roles.items():
        if isinstance(b, str) and b and b not in pos and len(low.get(b.casefold(), [])) == 1:
            out[r] = low[b.casefold()][0]
    return out


def structural_fill(roles: dict, pos: dict, parent: dict) -> dict[str, str]:
    """Roles the hierarchy gives away once the limbs are known: the chest where the arms meet, the neck above it, a
    clavicle between chest and upper arm, a lone child joint as the hand / foot / forearm / shin."""
    if not roles.get("hip") or roles["hip"] not in pos:
        return {}
    used = set(roles.values())
    kids: dict[str, list[str]] = {}
    for c, p in parent.items():
        if p:
            kids.setdefault(p, []).append(c)
    add: dict[str, str] = {}

    def chain(n):
        out = []
        while n and n not in out and len(out) < 512:
            out.append(n)
            n = parent.get(n)
        return out

    def free(n):
        return bool(n) and n in pos and n not in used and n not in add.values()
    hip_y = float(np.asarray(pos[roles["hip"]])[1])
    lu, ru = roles.get("l_upper"), roles.get("r_upper")
    if not roles.get("chest") and lu in pos and ru in pos:
        la, ra = chain(parent.get(lu)), chain(parent.get(ru))
        meet = next((x for x in la if x in ra), None)
        if free(meet) and float(np.asarray(pos[meet])[1]) > hip_y:
            add["chest"] = meet
        elif meet == roles["hip"] and roles.get("head") in pos:
            spine = list(reversed(chain(parent.get(roles["head"]))))     # hip ... the head's parent
            above = spine[spine.index(meet) + 1:] if meet in spine else []
            if above and free(above[0]) and float(np.asarray(pos[above[0]])[1]) > hip_y:
                add["chest"] = above[0]
    cur = roles | add
    if not cur.get("neck") and cur.get("head") in pos and cur.get("chest"):
        p = parent.get(cur["head"])
        if free(p) and p != cur["hip"] and cur["chest"] in chain(p):
            add["neck"] = p
    for side in "lr":
        cur = roles | add
        up = cur.get(f"{side}_upper")
        if not cur.get(f"{side}_clav") and up in pos and cur.get("chest"):
            p = parent.get(up)
            if free(p) and p not in (cur.get("neck"), cur["hip"]) and cur["chest"] in chain(p):
                add[f"{side}_clav"] = p
        for a, b in (("upper", "fore"), ("fore", "hand"), ("thigh", "shin"), ("shin", "foot")):
            cur = roles | add
            src = cur.get(f"{side}_{a}")
            if cur.get(f"{side}_{b}") or src not in pos:
                continue
            ch = [c for c in kids.get(src, []) if free(c)]
            if len(ch) == 1:
                add[f"{side}_{b}"] = ch[0]
    return add


def absent_reasons(roles: dict, pos: dict, parent: dict, body: str, suggested: dict | None = None) -> dict[str, str]:
    """Every role of the 18 that is not mapped, with why: the explicit 'absent' the standard asks for."""
    out = {}
    for r in ROLES:
        if roles.get(r):
            continue
        if (suggested or {}).get(r):
            out[r] = f"not mapped by the reader; the skeleton suggests {suggested[r]} (readiness.suggested_roles)"
        elif body in ("sprite", "prop"):
            out[r] = f"{body}: no skeleton"
        elif body == "creature":
            out[r] = "creature: not a humanoid skeleton"
        elif r == "neck" and roles.get("head") and parent.get(roles["head"]) in (roles.get("chest"), None):
            out[r] = "no neck joint (the head hangs off the chest)"
        elif r == "chest" and roles.get("hip") and roles.get("l_upper") and \
                parent.get(roles["l_upper"]) == roles["hip"]:
            out[r] = "no chest joint (the arms branch off the hip)"
        elif r.endswith("_clav") and roles.get(r[0] + "_upper") and \
                parent.get(roles[r[0] + "_upper"]) in (roles.get("chest"), roles.get("neck"), None):
            out[r] = "no clavicle joint (the arm hangs off the chest)"
        elif r[2:] in ("hand", "foot") and roles.get(r[:2] + ("fore" if r.endswith("hand") else "shin")) in pos and \
                not any(p == roles[r[:2] + ("fore" if r.endswith("hand") else "shin")] for p in parent.values()):
            out[r] = f"no {r[2:]} joint (the limb ends at the {'forearm' if r.endswith('hand') else 'shin'})"
        elif r in OPTIONAL_ROLES:
            out[r] = "no such joint identified (optional)"
        else:
            out[r] = "unidentified"
    return out


# ================================================================ proportions, pose, hints

def _dist(P, a, b):
    return float(np.linalg.norm(P[a] - P[b])) if a in P and b in P else None


def proportions(roles: dict, pos: dict, points: np.ndarray, up: str) -> dict:
    P = {r: _to_y_up(pos[b], up) for r, b in roles.items() if b in pos}
    pts = _to_y_up(points, up) if len(points) else np.array([v for v in P.values()] or [[0, 0, 0]])
    ground, top = float(pts[:, 1].min()), float(pts[:, 1].max())
    H = max(top - ground, 1e-9)
    out = {"height": round(H, 4), "ground": round(ground, 4)}
    if "hip" in P:
        out["hip_height"] = round((P["hip"][1] - ground) / H, 3)
    base = P.get("neck", P.get("head"))
    if base is not None:
        out["head"] = round((top - base[1]) / H, 3)
    for side in "lr":
        arm = [_dist(P, f"{side}_upper", f"{side}_fore"), _dist(P, f"{side}_fore", f"{side}_hand")]
        leg = [_dist(P, f"{side}_thigh", f"{side}_shin"), _dist(P, f"{side}_shin", f"{side}_foot")]
        if None not in arm:
            out[f"{side}_arm"] = round(sum(arm) / H, 3)
        if None not in leg:
            out[f"{side}_leg"] = round(sum(leg) / H, 3)
    if (s := _dist(P, "l_upper", "r_upper")) is not None:
        out["shoulders"] = round(s / H, 3)
    if (s := _dist(P, "l_hand", "r_hand")) is not None:
        out["arm_span"] = round(s / H, 3)
    return out


def bind_pose(roles: dict, pos: dict, up: str) -> dict:
    P = {r: _to_y_up(pos[b], up) for r, b in roles.items() if b in pos}
    ang = {}
    for side in "lr":
        a, b = P.get(f"{side}_upper"), P.get(f"{side}_hand", P.get(f"{side}_fore"))
        if a is not None and b is not None and np.linalg.norm(b - a) > 1e-9:
            d = (b - a) / np.linalg.norm(b - a)
            ang[side] = round(math.degrees(math.asin(max(-1.0, min(1.0, -d[1])))), 1)   # 0 = level, 90 = hanging
    if not ang:
        return {"pose": "unknown"}
    m = max(abs(v) for v in ang.values())
    pose = "T" if m <= 20 else "A" if m <= 60 else "arms_down"
    return {"pose": pose, "arm_drop_deg": ang}


def facing(roles: dict, pos: dict, points: np.ndarray, up: str) -> dict:
    """Facing from the role sides (left = +X when facing +Z) and, independently, from the feet (toes reach forward)."""
    P = {r: _to_y_up(pos[b], up) for r, b in roles.items() if b in pos}
    by_roles = by_feet = None
    for a, b in (("l_upper", "r_upper"), ("l_thigh", "r_thigh")):
        if a in P and b in P and abs(P[a][0] - P[b][0]) > 1e-6:
            by_roles = "+Z" if P[a][0] > P[b][0] else "-Z"
            break
    feet = [P[f] for f in ("l_foot", "r_foot") if f in P]
    if feet and len(points):
        pts = _to_y_up(points, up)
        H = float(np.ptp(pts[:, 1])) or 1.0
        low = pts[pts[:, 1] < pts[:, 1].min() + 0.06 * H]
        dz = float(low[:, 2].mean() - np.mean([f[2] for f in feet])) if len(low) else 0.0
        if abs(dz) > 0.01 * H:
            by_feet = "+Z" if dz > 0 else "-Z"
    out = {"facing": by_feet or by_roles or "unknown", "by_roles": by_roles, "by_feet": by_feet}
    if by_roles and by_feet and by_roles != by_feet:
        out["mirrored_suspect"] = True
    return out


# ================================================================ the post-collect step

def model_sig(path: Path) -> str:
    try:
        st = Path(path).stat()
        return f"{st.st_size}:{int(st.st_mtime)}"
    except OSError:
        return ""


def stale(root: Path, meta: dict) -> bool:
    """Does this entry need its readiness (re)computed?"""
    r = meta.get("readiness") or {}
    if r.get("version") != READINESS_VERSION:
        return True
    if r.get("roles_digest") != _roles_digest(meta):
        return True
    p = Path(root) / str(meta.get("slug") or "") / str(meta.get("model") or "")
    return bool(meta.get("model")) and p.is_file() and r.get("model_sig") != model_sig(p)


def _roles_digest(meta: dict) -> str:
    import hashlib
    roles = (meta.get("rig") or {}).get("roles") or {}
    return hashlib.sha1(json.dumps(roles, sort_keys=True).encode()).hexdigest()[:10]


def compute(root: Path | None, meta: dict, model: Path | None = None, fix: bool = True) -> tuple[dict, list[str]]:
    """meta with meta["readiness"] (re)computed, plus what was fixed. Pure apart from reading the model: the caller
    stores it (post_collect does). fix=False only reports."""
    meta = json.loads(json.dumps(meta, default=str))
    fixed: list[str] = []
    ckind = meta.get("kind") or "character"
    model = Path(model) if model else (Path(root) / meta.get("slug", "") / str(meta.get("model") or "")
                                       if root is not None else None)
    rd: dict = {"version": READINESS_VERSION, "computed": round(time.time(), 1)}
    blocking, limiting, warnings = [], [], []
    an: dict = {}
    if model is None or not model.is_file():
        blocking.append("model file missing")
    else:
        rd["model_sig"] = model_sig(model)
        try:
            an = analyze_model(model)
        except Exception as e:                             # noqa: BLE001 - the entry is reported, never dropped
            blocking.append(f"model unreadable: {str(e)[:120]}")
    pos, parent, points = an.pop("_joints", {}), an.pop("_parent", {}), an.pop("_points", np.zeros((0, 3)))
    rig = dict(meta.get("rig") or {})
    roles = dict(rig.get("roles") or {})
    src = rig.get("roles_source") or ("guessed" if rig.get("roles_guessed") else "reader" if roles else "")
    is_sprite = ckind == "sprites" or an.get("format") == "png"
    if fix and an and not is_sprite and ckind not in PROP_KINDS and pos:
        case = match_case(roles, pos)
        if case:
            roles = roles | case
            rig.update(roles=roles, roles_case_fixed=sorted(case))
            fixed.append(f"role bone names matched to the model's joints (case): {', '.join(sorted(case))}")
        had_hip = "hip" in roles
        extra: dict[str, str] = {}
        how = ""
        if not had_hip:
            got, how, tried = reader_roles(meta, model, pos), "reader backfill", []
            if not got:
                got, how, tried = auto_roles(model, an | {"_joints": pos, "_parent": parent, "_points": points})
            if got:
                keep = {r: b for r, b in roles.items() if r not in got and b in pos}
                roles = got | keep
                rig.update(roles=roles, roles_guessed=True, roles_source=how)
                src = how
                fixed.append(f"body roles mapped ({how}: {len(got)} roles)")
            elif tried:
                rd["role_mapping"] = tried[:3]
        else:
            got, how, _t = auto_roles(model, an | {"_joints": pos, "_parent": parent, "_points": points})
            if got and got.get("hip") == roles.get("hip"):
                add = {r: b for r, b in got.items() if r not in roles and b not in roles.values()}
                if add and not sanity(roles | add, pos):
                    extra = {r: (b, how) for r, b in add.items()}
        if "hip" in roles:
            cur = roles | {r: b for r, (b, _h) in extra.items()}
            st_add = structural_fill(cur, pos, parent)
            if st_add and not sanity(cur | st_add, pos):
                extra |= {r: (b, "hierarchy") for r, b in st_add.items()}
        # an entry that just got its roles takes everything; one the reader mapped takes only the retarget roles it
        # lacked (chest, a hand ...): the optional neck / clavicles stay suggestions, so builds that work today keep
        # fitting exactly as they did
        apply = {r: v for r, v in extra.items() if not had_hip or r in RETARGET_ROLES}
        suggest = {r: v[0] for r, v in extra.items() if r not in apply}
        if apply:
            roles = roles | {r: b for r, (b, _h) in apply.items()}
            rig.update(roles=roles)
            if had_hip:
                rig["roles_filled"] = sorted(set(rig.get("roles_filled") or []) | set(apply))
            srcs = sorted({h for _b, h in apply.values()})
            fixed.append(f"filled {len(apply)} missing roles ({', '.join(srcs)}): {', '.join(sorted(apply))}")
        if suggest:
            rd["suggested_roles"] = suggest
    if fix and an and not is_sprite:
        st = dict(meta.get("stats") or {})
        if not st.get("triangles") and an["mesh"]["triangles"]:
            meta["stats"] = st | {k: an["mesh"][k] for k in ("triangles", "vertices", "meshes")} | \
                {"textures": an["textures"]["count"]}
            fixed.append("stats")
        if not rig.get("joints") and an["rig"]["joints"]:
            rig.update(skinned=an["rig"]["skinned"], joints=an["rig"]["joints"])
            fixed.append("rig joint count")
    if rig != (meta.get("rig") or {}):
        meta["rig"] = rig
    # ------------------------------------------------ the body kind
    if is_sprite:
        body = "sprite"
    elif ckind in PROP_KINDS:
        body = "prop"
    elif not an.get("rig", {}).get("skinned"):
        body = "prop"
    elif HUMANOID_CORE <= set(r for r, b in roles.items() if b in pos) or (HUMANOID_CORE <= set(roles) and
                                                                         src == "reader"):
        body = "humanoid"
    else:
        body = "creature"
    rd["kind"] = body
    up = _up_axis(roles, pos, points) if pos else ("+Y" if not len(points) else _up_axis({}, {}, points))
    if an and not is_sprite:
        H_pts = _to_y_up(points, up) if len(points) else np.zeros((0, 3))
        H = float(np.ptp(H_pts[:, 1])) if len(H_pts) else 0.0
        metres = METRES[0] <= H <= METRES[1]
        rd["model"] = {"format": an["format"], "up": up, "height": round(H, 4),
                       "unit": "m" if metres else "units",
                       "to_metres": 1.0 if metres else (round(HUMAN_M / H, 6) if H > 0 else None),
                       "unit_basis": "measured (metres)" if metres else f"assumed {HUMAN_M} m figure"}
        rd["mesh"], rd["skin"], rd["textures"] = an["mesh"], an["skin"], an["textures"]
        rd["rig"] = dict(an["rig"])
        if an.get("bounds"):
            rd["model"]["bounds"] = an["bounds"]
    elif an:
        rd["model"] = {"format": "png", "sheet": an.get("sheet")}
        rd["textures"] = an["textures"]
        rd["mesh"] = an["mesh"]
        rd["rig"] = an["rig"]
        rd["sprites"] = {"clips": len([a for a in meta.get("animations") or [] if a.get("clip") or a.get("sheet")]),
                         "sheet": an.get("sheet")}
    mapped = sorted(r for r in ROLES if roles.get(r) and (roles[r] in pos or not pos))
    rd.setdefault("rig", {})
    rd["rig"].update(roles_mapped=len(mapped), roles_source=src or None,
                     roles_absent=absent_reasons(roles, pos, parent, body, rd.get("suggested_roles")))
    if body == "humanoid":
        rd["rig"]["sanity"] = sanity(roles, {b: _to_y_up(p, up) for b, p in pos.items()})
        rd["bind"] = bind_pose(roles, pos, up) | {"inverse_bind": an.get("rig", {}).get("inverse_bind", False)}
        rd["proportions"] = proportions(roles, pos, points, up)
        rd["facing"] = facing(roles, pos, points, up)
    elif body == "creature":
        rd["bind"] = {"pose": "unknown", "inverse_bind": an.get("rig", {}).get("inverse_bind", False)}
        rd["proportions"] = proportions({}, {}, points, up) if len(points) else {}
    # ------------------------------------------------ status
    if not blocking and not is_sprite and not (rd.get("mesh") or {}).get("triangles"):
        blocking.append("no triangles")
    if ckind == "character" and not is_sprite and an and not an.get("rig", {}).get("skinned"):
        blocking.append("no skeleton (skin): the reader must export a rig before it can be retargeted")
    if body == "humanoid":
        absent = rd["rig"]["roles_absent"]
        need = sorted(r for r in RETARGET_ROLES - set(mapped) if absent.get(r, "unidentified") == "unidentified")
        if need:
            limiting.append(f"roles unmapped: {', '.join(need)}")
        if rd["rig"].get("sanity"):
            limiting.append("role map: " + "; ".join(rd["rig"]["sanity"][:3]))
        if up != "+Y":
            limiting.append(f"model is {up} up: re-export it +Y up")
        if (rd.get("facing") or {}).get("mirrored_suspect"):
            warnings.append("left/right roles may be mirrored (the feet face the other way)")
        if (rd.get("bind") or {}).get("pose") == "arms_down":
            warnings.append("rest pose has the arms down (retarget aligns per bone; check the shoulders)")
    elif body == "creature" and ckind == "character":
        limiting.append("creature: no humanoid body roles; humanoid slots need a role map (Retarget editor)")
    if (rd.get("skin") or {}).get("unweighted_vertices"):
        warnings.append(f"{rd['skin']['unweighted_vertices']} vertices without skin weights")
    if body not in ("sprite",) and an and not (rd.get("textures") or {}).get("count"):
        warnings.append("untextured (vertex / material colours only)")
    if ckind in PROP_KINDS:
        status = "n/a"
    elif blocking:
        status = "blocked"
    elif limiting:
        status = "limited"
    else:
        status = "ready"
    rd["hints"] = hints(rd)
    rd.update(status=status, ready=status == "ready", missing=blocking + limiting, warnings=warnings, fixed=fixed,
              roles_digest="")
    meta["readiness"] = rd
    rd["roles_digest"] = _roles_digest(meta)
    return meta, fixed


def hints(rd: dict) -> dict:
    """Default retarget hints a writer / the Retarget editor can start from (never applied automatically)."""
    m, pr, b = rd.get("model") or {}, rd.get("proportions") or {}, rd.get("bind") or {}
    h: dict = {}
    if m.get("up") and m["up"] != "+Y":
        h["up_fix"] = {"+Z": "rotate -90 deg about X", "-Y": "rotate 180 deg about X", "+X": "rotate 90 deg about Z"}.get(m["up"])
    if m.get("to_metres"):
        h["to_metres"] = m["to_metres"]
    if (rd.get("facing") or {}).get("facing") not in (None, "unknown"):
        h["facing"] = rd["facing"]["facing"]
    if b.get("pose") and b["pose"] != "unknown":
        h["pose"] = b["pose"]
    if pr.get("head") and pr["head"] > 0.22:                # chibi / mascot proportions (Sonic, Mario)
        h["profile"] = {"head": round(max(0.5, min(1.0, 0.16 / pr["head"])), 2)}
        h["chibi"] = True
    sk = rd.get("skin") or {}
    if sk.get("max_influences"):
        h["rigid"] = sk["max_influences"] <= 1
    if (rd.get("mesh") or {}).get("triangles"):
        h["decimate_from"] = rd["mesh"]["triangles"]
    return h


def post_collect(root: Path, meta: dict, model: Path | None = None, write: bool = False) -> dict:
    """The shared step every reader's entry goes through (characters.add runs it before writing meta.json; collect()
    and op=readiness run it on stored entries). Never raises: a failure is recorded in meta['readiness']."""
    try:
        new, _fixed = compute(root, meta, model)
    except Exception as e:                                 # noqa: BLE001 - readiness never blocks a collection
        new = dict(meta)
        new["readiness"] = {"version": READINESS_VERSION, "status": "blocked", "ready": False,
                            "missing": [f"readiness check failed: {str(e)[:200]}"], "computed": round(time.time(), 1)}
    if write:
        from . import characters as C
        new = C.put_meta(root, new)
    return new


def ensure(root: Path, meta: dict, force: bool = False) -> dict:
    """post_collect for a stored entry when its readiness is missing / stale (written back)."""
    if not force and not stale(root, meta):
        return meta
    return post_collect(root, meta, write=True)


# ================================================================ target slots

# writer -> what its target accepts. tris / verts: the most a slot takes (None: a byte or sector budget the writer
# fits by decimating); tex: largest texture side the format keeps (the writer downsizes); influences: per vertex
# (1 = rigid, every vertex rides one joint); roles: a module attribute naming the target's role map, or a list;
# required: roles a donor must have (default {"hip"}, the cast swap's gate); donors: only these slugs (writer limits).
SPECS: dict[str, dict] = {
    "gbox.doa2_swap": {"skeleton": "DOA2 fighter: native model parts per body joint", "roles": "REQUIRED_ROLES",
                       "required": "REQUIRED_ROLES", "influences": 2, "tex": 256, "decimate": True,
                       "budget": "CHR/SUP bytes of the fighter's costume (decimated 0.8^k until it fits)"},
    "gbox.sm64_swap": {"skeleton": "Mario, 20 joints", "joints": 20, "roles": "ORDER", "tris": "MAX_TRIS", "tex": 64,
                       "influences": 1, "decimate": True, "budget": "Mario's 0x1CD20 bytes; textures RGBA16 <= 64x32"},
    "gbox.gta_stories_models": {"skeleton": "Toni, 24 bones", "joints": 24, "roles": "LCS_ROLES", "influences": 4,
                                "tex": 256, "decimate": True, "budget": "the outfit's IMG sectors (.mdl + .chk)"},
    "gbox.gta3_swap": {"skeleton": "Claude, 17 frames", "joints": 17, "roles": "GTA3_ROLES", "influences": 4,
                       "tex": 256, "decimate": True, "budget": "player.dff / .txd IMG slot sectors"},
    "gbox.gta_vc_swap": {"skeleton": "Tommy / ped HAnim skeleton", "roles": "all", "tris": "MAX_TRIS",
                         "influences": 1, "tex": 512, "decimate": True, "budget": "gta3.img (rebuilt, no fixed slot)"},
    "gbox.re6_tool": {"skeleton": "Leon (RE6, MT Framework)", "roles": "all", "influences": 4, "tex": 2048,
                      "decimate": False, "budget": "mod folder (no size budget)"},
    "gbox.metal_arms": {"skeleton": "Glitch / bot .ape skeleton", "roles": "GLITCH_ROLES", "tris": "MAX_TRIS",
                        "influences": 1, "tex": 256, "decimate": True, "budget": ".ape + .tga in a disc copy"},
    "gbox.aki_wrestling": {"skeleton": "AKI wrestler, 19 rigid parts", "joints": 19, "roles": "JOINTS",
                           "influences": 1, "tex": 64, "decimate": True,
                           "budget": "each part's own vertex / face pool (per-part decimation)"},
    "gbox.yukes_sd": {"skeleton": "Yuke's PS1 wrestler, rigid parts", "roles": "all", "influences": 1, "tex": 256,
                      "decimate": True, "budget": "CAPS: vertices / primitives per part"},
    "gbox.defjam_writer": {"skeleton": "Def Jam wrestler, 42-node BODY tree", "joints": 42, "roles": "all",
                           "tris": "MAX_TRIS", "influences": 1, "tex": 256, "decimate": True,
                           "budget": "WRS container (BODY / BODY2 + texture page)"},
    "gbox.pe_swap": {"skeleton": "Aya (PE1), rigid outfit bones", "roles": "all", "influences": 1, "tex": 64,
                     "decimate": True, "budget": "Aya's model bytes in the blob; one 256x256 4-bit page"},
    "gbox.pe2_swap": {"skeleton": "Aya (PE2), 19 bones", "joints": 19, "roles": "all", "verts": "MAX_VERTS",
                      "influences": 1, "tex": 64, "decimate": True, "budget": "one 256x256 8-bit page; table bytes"},
    "gbox.ff7_swap": {"skeleton": "Cloud field (22 bones) + battle", "joints": 22, "roles": "all", "influences": 1,
                      "tex": 0, "decimate": True, "budget": "field BCX + battle LZS; textures baked to vertex colours"},
    "gbox.sa2_chars": {"skeleton": "Sonic (SA2 Ninja chunk model)", "roles": "all", "tris": "BUDGETS",
                       "influences": 2, "tex": 256, "decimate": True, "budget": "the PRS's disc sectors"},
    "gbox.pso_player": {"skeleton": "PSO class / enemy Ninja tree", "roles": "PLAYER_ROLES", "tris": "PSO_BUDGETS",
                        "influences": 2, "tex": 256, "decimate": True, "budget": "BML / AFS sectors in a GD-ROM copy"},
    "gbox.jgr_swap": {"skeleton": "JGR skater (PLAYER.AFS body groups)", "roles": "all", "influences": 2, "tex": 256,
                      "decimate": True, "budget": "the PLAY entry's own AFS room"},
    "gbox.mgs_vr_swap": {"skeleton": "Snake, 16-bone KMD (soldiers and stage figures share it)", "joints": 16,
                         "roles": "SNAKE_ROLES", "influences": 1, "tex": 256, "decimate": True,
                         "budget": "the original KMD's bytes, shared per body part"},
    "gbox.twin_snakes_swap": {"skeleton": "MGS2 21-bone .kms (Snake, soldiers, bosses, NPCs)", "joints": 21,
                              "roles": "all", "influences": 1, "tex": 256, "decimate": True,
                              "budget": "the stock model's bytes; each stage stays in its own disc space"},
    "gbox.mgs2_swap": {"skeleton": "MGS2 kms (each model's own skeleton: Snake, Raiden, soldiers, bosses)", "roles": "all",
                       "influences": 2, "tex": 256, "decimate": True,
                       "budget": "the stock model's bytes; donor textures in one atlas inside the model's texture pack"},
    "gbox.mgs1_swap": {"skeleton": "Snake, 16-bone KMD", "joints": 16, "roles": "all", "influences": 1, "tex": 256,
                       "decimate": True, "budget": "the original KMD's bytes", "donors": ["hucast"]},
    "gbox.clayfighter_swap": {"skeleton": "sprite frames (no skeleton)", "kind": "sprite", "roles": [],
                              "required": [], "influences": 0, "tex": 0, "decimate": False,
                              "budget": "each frame keeps its size and hotspot"},
    "gbox.auf_swap": {"skeleton": "AUF body .gcm skeleton (2-bone blends)", "roles": "all", "influences": 2,
                      "tex": 256, "decimate": True, "budget": "1.2 x the slot body's own LOD triangles (>= 300)"},
    "gbox.crazy_taxi_swap": {"skeleton": "Crazy Taxi rigid .shp parts", "roles": "all", "influences": 1, "tex": 128,
                             "decimate": True, "budget": "each part's room in polDC0.all"},
    "gbox.etm_swap": {"skeleton": "ETM shared 89-joint skeleton", "joints": 89, "roles": "all", "influences": 1,
                      "tex": 256, "decimate": True, "budget": "the actor's .dcn in WAD1.DFU (rewritten in place)"},
    "gbox.doapp_swap": {"skeleton": "DOA++ fighter, 15 bones", "joints": 15, "roles": "all",
                        "verts": "SLOT_VERTEX_CAP", "influences": 1, "tex": 256, "decimate": True,
                        "budget": "the player work buffer; per-slot vertex caps"},
    "gbox.characters.build_re4 (+ re4wii)": {"skeleton": "Leon (RE4 GC / Wii)", "roles": "LEON_ROLES@characters",
                                             "influences": 4, "tex": 256, "decimate": True,
                                             "budget": "the costume pack (every costume)"},
    "gbox.oot_swap": {"skeleton": "Link, 21 limbs / NPC limb trees", "joints": 21, "roles": "LINK_ROLES",
                      "tris": "MAX_TRIS", "influences": 1, "tex": 64, "decimate": True,
                      "budget": "the object's room in the ROM; textures RGBA16 <= 64x32"},
}
DEFAULT_SPEC = {"skeleton": "?", "roles": "all", "required": ["hip"], "influences": None, "tex": None,
                "decimate": True, "budget": "writer-defined", "kind": "humanoid"}


def _module(writer: str):
    import importlib
    name = writer.split(" ")[0]
    if name.startswith("gbox.characters."):
        name = "gbox.characters"
    try:
        return importlib.import_module(name)
    except Exception:                                      # noqa: BLE001
        return None


def _resolve(value, mod, attr_kind: str):
    """A spec field naming a module constant -> its value (number / role list)."""
    if isinstance(value, str) and value not in ("all",):
        name, _, where = value.partition("@")
        m = _module(f"gbox.{where}") if where else mod
        v = getattr(m, name, None) if m is not None else None
        if v is None:
            return None
        if attr_kind == "roles":
            keys = list(v) if isinstance(v, (dict, list, tuple, set)) else []
            return [r for r in ROLES if r in keys]
        if attr_kind == "number":
            if isinstance(v, dict):
                return int(max(v.values())) if v else None
            if isinstance(v, (list, tuple)):
                return int(v[0]) if v else None
            return int(v)
    if value == "all" and attr_kind == "roles":
        return list(ROLES)
    return value


_SPEC_CACHE: dict = {}


def spec_for(writer: str | None) -> dict | None:
    """The merged target description of one writer (static SPECS + live module constants + REPLACEMENT_SPEC)."""
    if not writer:
        return None
    if writer in _SPEC_CACHE:
        return _SPEC_CACHE[writer]
    base = DEFAULT_SPEC | SPECS.get(writer, {})
    mod = _module(writer)
    own = getattr(mod, "REPLACEMENT_SPEC", None) if mod is not None else None
    if isinstance(own, dict):
        base = base | own
    roles = _resolve(base.get("roles"), mod, "roles")
    req = base.get("required", ["hip"])
    req = _resolve(req, mod, "roles") if isinstance(req, str) else list(req)
    out = {"writer": writer, "skeleton": base["skeleton"], "kind": base.get("kind", "humanoid"),
           "joints": base.get("joints"), "roles": roles if roles is not None else list(ROLES),
           "required": sorted(set(req or [])), "tris": _resolve(base.get("tris"), mod, "number"),
           "verts": _resolve(base.get("verts"), mod, "number"), "tex": base.get("tex"),
           "influences": base.get("influences"), "decimate": bool(base.get("decimate", True)),
           "budget": base.get("budget"), "donors": list(base.get("donors") or []) or None,
           "known": writer in SPECS or isinstance(own, dict)}
    dn = getattr(mod, "DONORS", None) if mod is not None else None
    if isinstance(dn, (list, tuple, set)) and dn:
        out["donors"] = sorted(dn)
    _SPEC_CACHE[writer] = out
    return out


def known_games(chars: list[dict] | None = None, catalog=None) -> dict[str, dict]:
    """Every game with a writer or a collected entry: {game_id: {game_id, title, platform}}."""
    from . import char_coverage as CC
    from . import characters as C
    games: dict[str, dict] = {}

    def put(gid, title=None, platform=None):
        if not gid:
            return
        g = games.setdefault(gid, {"game_id": gid, "title": title or gid, "platform": platform or ""})
        if title and g["title"] == gid:
            g["title"] = title
        if platform and not g["platform"]:
            g["platform"] = platform
    for name, *_r in CC.WRITERS:
        m = CC._mod(name)
        ids = getattr(m, "GAME_IDS", None) if m is not None else None
        for gid in (ids or {}):
            put(gid, ids.get(gid) if isinstance(ids, dict) else None)
    for gid, (t, plat) in TITLES.items():
        if gid in games:
            put(gid, t, plat)
    for gid, t in {**C.RE4GC, **C.RE4WII}.items():
        put(gid, t, "gamecube" if gid in C.RE4GC else "wii")
    for m in chars or []:
        s = m.get("source") or {}
        put(s.get("game_id"), s.get("game_title"), s.get("platform"))
    if catalog is not None:
        for gid, g in games.items():
            try:
                c = catalog(gid)
            except Exception:                              # noqa: BLE001
                c = None
            if c:
                g["title"] = c.get("title") or g["title"]
                g["platform"] = c.get("platform") or g["platform"]
    return games


def reader_for(game: dict) -> str | None:
    """The DEDICATED reader of a game (platform guessed from the title when the record has none)."""
    from . import characters as C
    t, plat = (game.get("title") or "").lower(), game.get("platform") or ""
    for p in ([plat] if plat else list(PLATFORMS)):
        for name, test, _r, _run in C.DEDICATED:
            try:
                if test(t, p):
                    return name
            except Exception:                              # noqa: BLE001
                continue
    return None


def slot_table(games: dict[str, dict]) -> dict[str, dict]:
    """{game_id: {title, platform, reader, writer, routed, spec, slots: [{slot, name, kind, status?}]}}."""
    from . import char_coverage as CC
    from . import cast_swap as CS
    out = {}
    for gid, g in games.items():
        try:
            w = CC.writer_for(g)
        except Exception:                                  # noqa: BLE001
            w = None
        row = {"game_id": gid, "title": g.get("title"), "platform": g.get("platform"), "reader": reader_for(g),
               "writer": (w or {}).get("writer"), "routed": bool((w or {}).get("routed")), "slots": []}
        if w:
            row["spec"] = w["writer"]
            try:
                rows = CS.slot_rows(g)
            except Exception as e:                         # noqa: BLE001 - a writer that can't list keeps its fixed slots
                rows = []
                row["slots_error"] = str(e)[:160]
            if not rows:
                rows = [{"slot": s, "name": s, "kind": "player" if s == "player" else "slot"}
                        for s in w.get("slots", []) if "<" not in s]
            row["slots"] = [{k: s.get(k) for k in ("slot", "name", "kind", "status", "size") if s.get(k) is not None}
                            for s in rows]
        out[gid] = row
    return out


# ================================================================ compatibility

def summary(meta: dict) -> dict:
    """The compact donor record the index keeps (everything compat() reads)."""
    rd = meta.get("readiness") or {}
    st = meta.get("stats") or {}
    rig = meta.get("rig") or {}
    roles = sorted(r for r in ROLES if (rig.get("roles") or {}).get(r))
    ckind = meta.get("kind") or "character"
    body = rd.get("kind") or ("sprite" if ckind == "sprites" else "prop" if ckind in PROP_KINDS else
                             "humanoid" if HUMANOID_CORE <= set(roles) else "creature" if rig.get("skinned") else
                             "humanoid" if roles else "prop")
    prof = {gid: sorted(r for p in (v or {}).values() for r, b in ((p or {}).get("roles") or {}).items() if b)
            for gid, v in (meta.get("retarget_profiles") or {}).items()}
    return {"name": meta.get("name"), "kind": ckind, "body": body,
            "source": (meta.get("source") or {}).get("game_title"),
            "source_game_id": (meta.get("source") or {}).get("game_id"),
            "variant_of": meta.get("variant_of"), "made_with": (meta.get("variant") or {}).get("made_with"),
            "status": rd.get("status") or "unchecked", "missing": (rd.get("missing") or [])[:4],
            "roles": roles, "tris": int((rd.get("mesh") or {}).get("triangles") or st.get("triangles") or 0),
            "verts": int((rd.get("mesh") or {}).get("vertices") or st.get("vertices") or 0),
            "influences": (rd.get("skin") or {}).get("max_influences"),
            "tex": (rd.get("textures") or {}).get("max_side"),
            "pose": (rd.get("bind") or {}).get("pose"), "up": (rd.get("model") or {}).get("up"),
            "profile_roles": {g: r for g, r in prof.items() if r}}


def compat(d: dict, spec: dict, game_id: str | None = None, slug: str | None = None) -> dict:
    """Can donor summary d go into a slot of this writer? {ok, fit, ratio, missing_roles, blocking, notes, score}."""
    blocking, notes = [], []
    roles = set(d.get("roles") or [])
    if game_id and (d.get("profile_roles") or {}).get(game_id):
        roles |= set(d["profile_roles"][game_id])
        notes.append("roles from the Retarget editor profile")
    if d.get("kind") in PROP_KINDS:
        blocking.append(f"{d['kind']}: not a character")
    if spec.get("kind") == "sprite":
        if d.get("body") != "sprite":
            blocking.append("this writer re-draws sprite frames: needs a sprites entry")
    else:
        if d.get("body") == "sprite":
            blocking.append("sprites entry: this writer needs a 3D model")
        elif d.get("body") == "prop" and d.get("kind") not in PROP_KINDS:
            blocking.append("no skeleton: the model can't be retargeted")
        miss_req = sorted(set(spec.get("required") or []) - roles)
        if miss_req:
            blocking.append(f"lacks required roles: {', '.join(miss_req)}")
        if d.get("up") and d["up"] != "+Y":
            blocking.append(f"model is {d['up']} up")
    if spec.get("donors") and slug not in spec["donors"]:
        blocking.append(f"writer accepts only {', '.join(spec['donors'])} today")
    if d.get("status") == "blocked":
        blocking.append("entry blocked: " + "; ".join(d.get("missing") or [])[:160])
    missing = sorted((set(spec.get("roles") or []) & set(ROLES)) - roles) if spec.get("kind") != "sprite" else []
    fit, ratio = "fits", None
    tris, verts = d.get("tris") or 0, d.get("verts") or 0
    if spec.get("tris") and tris > spec["tris"]:
        ratio = round(spec["tris"] / tris, 4)
        fit = "decimate" if spec.get("decimate") else "over"
    if spec.get("verts") and verts > spec["verts"]:
        r2 = round(spec["verts"] / verts, 4)
        ratio = min(ratio or 1.0, r2)
        fit = "decimate" if spec.get("decimate") else "over"
        notes.append(f"vertex cap {spec['verts']}")
    if fit == "over":
        blocking.append(f"{tris} triangles over the slot's {spec.get('tris') or spec.get('verts')} and the writer "
                        "can't decimate")
    if spec.get("influences") and (d.get("influences") or 0) > spec["influences"]:
        notes.append(f"{d['influences']} influences per vertex -> {spec['influences']}"
                     + (" (rigid)" if spec["influences"] == 1 else ""))
    if spec.get("tex") and (d.get("tex") or 0) > spec["tex"]:
        notes.append(f"textures {d['tex']} px -> <= {spec['tex']} px")
    if spec.get("tex") == 0 and d.get("tex"):
        notes.append("textures baked to vertex colours")
    if d.get("status") in ("limited", "unchecked"):
        notes.append(f"entry {d['status']}" + (": " + "; ".join(d.get("missing") or [])[:120] if d.get("missing") else ""))
    if d.get("pose") == "arms_down":
        notes.append("rest pose arms down")
    ok = not blocking
    score = 1.0
    score -= 0.04 * len(missing)
    if ratio:
        score -= 0.3 * (1 - ratio)
    score -= 0.05 * (d.get("status") == "limited") + 0.1 * (d.get("status") == "unchecked")
    score -= 0.03 * (d.get("pose") == "arms_down")
    row = {"ok": ok, "fit": fit, "score": round(max(0.0, score), 3) if ok else 0.0}
    if ratio:
        row["ratio"] = ratio
    if missing:
        row["missing_roles"] = missing
    if blocking:
        row["blocking"] = blocking
    if notes:
        row["notes"] = notes
    return row


# ================================================================ the index (in memory + <library>/.replacement)

_LOCK = threading.RLock()
_INDEX: dict[str, dict] = {}                   # str(root) -> {"donors": {slug: summary}, "rows": {slug: {writer: row}},
#                                                 "games": slot table, "specs": {...}, "dirty": set | None, ...}


def invalidate(root=None, slug: str | None = None) -> None:
    """A collection write: that donor's rows are recomputed on the next query (characters.put_meta calls this)."""
    with _LOCK:
        for key, ix in _INDEX.items():
            if root is not None and key != str(root):
                continue
            if slug:
                ix["dirty"].add(slug)
            else:
                ix["dirty"].add("*")


def code_digest() -> str:
    """Changes when the specs or the readiness standard change: a stored index from older code is rebuilt."""
    import hashlib
    return hashlib.sha1(json.dumps([READINESS_VERSION, INDEX_VERSION, SPECS, DEFAULT_SPEC],
                                   sort_keys=True).encode()).hexdigest()[:12]


QUIET_S = 30.0


def _games_key(chars):
    return tuple(sorted({(m.get("source") or {}).get("game_id") or "" for m in chars}))


def index(root: Path, chars: list[dict] | None = None, catalog=None, rebuild: bool = False) -> dict:
    """The compatibility index for a library, brought up to date with the entries that changed since."""
    from . import characters as C
    key = str(root)
    with _LOCK:
        ix = _INDEX.get(key)
        if chars is None and ix is not None and not ix["dirty"] and not rebuild \
                and time.time() - ix.get("checked", 0) < QUIET_S:
            return ix                                      # nothing written since the last look: answer at once
    if chars is None:
        chars = C.list_all(root)
    with _LOCK:
        ix = _INDEX.get(key)
        if ix is None and not rebuild:
            ix = _load_file(root)
            if ix is not None:
                ix["dirty"] = {"*"}                     # verify every donor against the live list once
                _INDEX[key] = ix
        if ix is None or rebuild or ix.get("games_key") != _games_key(chars):
            games = slot_table(known_games(chars, catalog))
            specs = {}
            for g in games.values():
                if g.get("spec") and g["spec"] not in specs:
                    specs[g["spec"]] = spec_for(g["spec"])
            ix = {"version": INDEX_VERSION, "code": code_digest(), "games": games, "specs": specs, "donors": {},
                  "rows": {}, "dirty": {"*"}, "games_key": _games_key(chars), "saved": 0.0, "built": time.time()}
            _INDEX[key] = ix
        by_slug = {m["slug"]: m for m in chars if m.get("slug")}
        changed = False
        # every donor's summary is compared (cheap, no file reads): writes from another process show up too; only
        # the changed ones get their rows recomputed. `dirty` (put_meta in this process) just ends the quiet window.
        for slug in set(by_slug) | set(ix["donors"]):
            m = by_slug.get(slug)
            if m is None:
                changed |= ix["donors"].pop(slug, None) is not None
                ix["rows"].pop(slug, None)
                continue
            s = summary(m)
            if ix["donors"].get(slug) == s and slug in ix["rows"]:
                continue
            ix["donors"][slug] = s
            ix["rows"][slug] = {w: compat(s, sp, slug=slug) for w, sp in ix["specs"].items()}
            changed = True
        ix["dirty"] = set()
        ix["checked"] = time.time()
        if changed:
            ix["updated"] = time.time()
        return ix


def save(root: Path, force: bool = False) -> Path | None:
    """Write the index to <library>/.replacement/index.json (at most every 30 s unless forced)."""
    with _LOCK:
        ix = _INDEX.get(str(root))
        if ix is None or (not force and time.time() - ix.get("saved", 0) < 30 and ix.get("saved")):
            return None
        d = Path(root) / INDEX_DIR
        d.mkdir(parents=True, exist_ok=True)
        data = {k: v for k, v in ix.items() if k not in ("dirty", "games_key", "saved", "checked")}
        data["games_key"] = list(ix.get("games_key") or [])
        tmp = d / f"index.{int(time.time() * 1000)}.tmp"
        tmp.write_text(json.dumps(data, separators=(",", ":"), default=str))
        tmp.replace(d / "index.json")
        ix["saved"] = time.time()
        return d / "index.json"


def _load_file(root: Path) -> dict | None:
    p = Path(root) / INDEX_DIR / "index.json"
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    if data.get("version") != INDEX_VERSION or data.get("code") != code_digest():
        return None
    data["games_key"] = tuple(data.get("games_key") or [])
    data["saved"] = p.stat().st_mtime
    return data


def candidates(ix: dict, game_id: str, slot: str | None = None, include_all: bool = False, limit: int = 0,
               kind: str | None = None) -> dict:
    """Who can replace this slot: donors ranked by score (compatible first), with fit and missing roles."""
    g = (ix.get("games") or {}).get(game_id)
    if not g:
        return {"game_id": game_id, "slot": slot, "status": "unknown_game", "candidates": [],
                "message": "no writer or collected entry for this game in the index"}
    w = g.get("spec")
    if not w:
        return {"game_id": game_id, "title": g.get("title"), "slot": slot, "status": "no_writer", "candidates": [],
                "message": f"{g.get('title')} has no character writer yet (characters op=coverage)"}
    sp = ix["specs"].get(w) or spec_for(w)
    out = []
    for slug, d in ix["donors"].items():
        if d.get("variant_of") and d.get("made_with") == "head size":
            continue
        if kind and d.get("body") != kind:
            continue
        row = (ix["rows"].get(slug) or {}).get(w) or compat(d, sp, slug=slug)
        if game_id in (d.get("profile_roles") or {}):
            row = compat(d, sp, game_id, slug)
        if not row["ok"] and not include_all:
            continue
        out.append({"slug": slug, "name": d.get("name"), "source": d.get("source"), "body": d.get("body"),
                    "status": d.get("status"), "tris": d.get("tris"), **row})
    out.sort(key=lambda r: (not r["ok"], -r["score"], r["fit"] != "fits", r.get("name") or ""))
    slots = g.get("slots") or []
    s = next((x for x in slots if x.get("slot") == slot), None) if slot else None
    return {"game_id": game_id, "title": g.get("title"), "slot": slot, "slot_name": (s or {}).get("name"),
            "writer": w, "routed": g.get("routed"), "spec": sp, "status": "ok" if g.get("routed") else "not_routed",
            "compatible": sum(1 for r in out if r["ok"]), "candidates": out[:limit] if limit else out}


def donor_view(ix: dict, slug: str) -> dict | None:
    """Where can this donor go: every game with a writer, compatible or why not."""
    d = ix["donors"].get(slug)
    if d is None:
        return None
    games = []
    for gid, g in ix["games"].items():
        if not g.get("spec"):
            continue
        sp = ix["specs"].get(g["spec"]) or spec_for(g["spec"])
        row = compat(d, sp, gid, slug) if gid in (d.get("profile_roles") or {}) else \
            (ix["rows"].get(slug) or {}).get(g["spec"]) or compat(d, sp, slug=slug)
        games.append({"game_id": gid, "title": g.get("title"), "writer": g["spec"], "routed": g.get("routed"),
                      "slots": len(g.get("slots") or []), **row})
    games.sort(key=lambda r: (not r["ok"], not r["routed"], r.get("title") or ""))
    return {"slug": slug, **d, "games": games, "compatible_games": sum(1 for r in games if r["ok"] and r["routed"])}


# ================================================================ the report

def report(ix: dict, chars: list[dict], game_id: str | None = None) -> dict:
    """Per game: its reader, the entries it produced (ready / limited / blocked / unchecked and why), and its writer
    with the slots and how many donors fit them."""
    from . import characters as C
    by_game: dict[str, list[dict]] = {}
    for m in chars:
        gid = (m.get("source") or {}).get("game_id") or (m.get("source") or {}).get("game_title") or "?"
        by_game.setdefault(gid, []).append(m)
    rows = []
    gids = [game_id] if game_id else sorted(set(ix["games"]) | set(by_game))
    for gid in gids:
        g = ix["games"].get(gid) or {"game_id": gid, "title": gid, "slots": []}
        ents = by_game.get(gid, [])
        if not g.get("spec") and not ents:
            continue
        counts = {"ready": 0, "limited": 0, "blocked": 0, "unchecked": 0, "n/a": 0}
        reasons: dict[str, list[str]] = {}
        fixed = 0
        for m in ents:
            rd = m.get("readiness") or {}
            st = rd.get("status") or "unchecked"
            if rd and rd.get("version") != READINESS_VERSION:
                st = "unchecked"
            counts[st] = counts.get(st, 0) + 1
            fixed += bool(rd.get("fixed"))
            for why in (rd.get("missing") or ([] if rd else ["readiness never computed"])):
                k = re.sub(r":.*", "", why) if why.startswith("roles unmapped") else why[:90]
                reasons.setdefault(k, []).append(m.get("slug"))
        reader = g.get("reader") or (reader_for({"title": (ents[0].get("source") or {}).get("game_title"),
                                                 "platform": (ents[0].get("source") or {}).get("platform")})
                                     if ents else None)
        rv = C.reader_version(reader) if reader else None
        row = {"game_id": gid, "title": g.get("title") if g.get("title") != gid or not ents else
               (ents[0].get("source") or {}).get("game_title"), "platform": g.get("platform"),
               "reader": reader, "reader_version": rv,
               "entries": {"total": len(ents), **counts, "auto_fixed": fixed,
                           "why_not_ready": {k: {"count": len(v), "examples": v[:5]}
                                             for k, v in sorted(reasons.items(), key=lambda x: -len(x[1]))}}}
        if g.get("spec"):
            w = g["spec"]
            sp = ix["specs"].get(w) or spec_for(w)
            ok = [s for s, rr in ix["rows"].items() if (rr.get(w) or {}).get("ok")]
            fits = [s for s in ok if ix["rows"][s][w]["fit"] == "fits"]
            row["writer"] = {"writer": w, "routed": g.get("routed"), "slots": len(g.get("slots") or []),
                             "slot_names": [s.get("slot") for s in (g.get("slots") or [])][:12],
                             "spec": {k: sp.get(k) for k in ("skeleton", "kind", "joints", "tris", "verts", "tex",
                                                             "influences", "decimate", "required", "donors", "budget",
                                                             "known")},
                             "compatible_donors": len(ok), "fit_without_decimation": len(fits),
                             "ready": bool(g.get("routed")) and bool(g.get("slots")) and bool(ok) and sp.get("known")}
            gaps = []
            if not g.get("routed"):
                gaps.append("writer not routed by characters op=use")
            if not g.get("slots"):
                gaps.append("writer lists no slots")
            if not sp.get("known"):
                gaps.append("no target spec (budgets / skeleton) recorded for this writer")
            if not ok:
                gaps.append("no compatible donor in the collection")
            row["writer"]["gaps"] = gaps
        else:
            row["writer"] = None
        rows.append(row)
    rows.sort(key=lambda r: (r["writer"] is None, (r["title"] or "").lower()))
    tot = {"games": len(rows), "entries": sum(r["entries"]["total"] for r in rows)}
    for k in ("ready", "limited", "blocked", "unchecked", "n/a", "auto_fixed"):
        tot[k] = sum(r["entries"].get(k, 0) for r in rows)
    tot["writers"] = sum(1 for r in rows if r["writer"])
    tot["writers_ready"] = sum(1 for r in rows if r["writer"] and r["writer"]["ready"])
    return {"version": READINESS_VERSION, "generated": time.time(), "summary": tot, "games": rows}


def markdown(rep: dict) -> str:
    s = rep["summary"]
    out = [f"Entries: {s['entries']} ({s['ready']} ready, {s['limited']} limited, {s['blocked']} blocked, "
           f"{s['unchecked']} unchecked, {s['n/a']} not characters; {s['auto_fixed']} fixed automatically). "
           f"Writers: {s['writers']} ({s['writers_ready']} with routed slots and compatible donors).", "",
           "| Game | Reader | Entries (ready / limited / blocked / unchecked) | Main reasons | Writer | Slots | "
           "Compatible donors (no decimation) | Writer gaps |", "|---|---|---|---|---|---|---|---|"]
    for r in rep["games"]:
        e = r["entries"]
        why = "; ".join(f"{k} ({v['count']})" for k, v in list(e["why_not_ready"].items())[:3]) or "-"
        w = r["writer"]
        wcell = (f"{w['writer']}" + ("" if w["routed"] else " (not routed)")) if w else "-"
        out.append(f"| {r['title']} | {r['reader'] or '-'}{'' if not r['reader_version'] else ' v' + str(r['reader_version'])}"
                   f" | {e['total']}: {e['ready']} / {e['limited']} / {e['blocked']} / {e['unchecked']}"
                   f"{' (+' + str(e['n/a']) + ' not characters)' if e.get('n/a') else ''} | "
                   f"{why.replace('|', '/')} | {wcell} | {w['slots'] if w else '-'} | "
                   f"{(str(w['compatible_donors']) + ' (' + str(w['fit_without_decimation']) + ')') if w else '-'} | "
                   f"{'; '.join(w['gaps']) if w and w['gaps'] else ('-' if w else 'no writer')} |")
    return "\n".join(out)


# ================================================================ the backfill pass (characters op=readiness)

def backfill(root: Path, chars: list[dict] | None = None, force: bool = False, game_id: str = "",
             slugs: list[str] | None = None, progress=lambda p, m: None, catalog=None) -> dict:
    """Compute / refresh readiness for every entry (or one game's / these), fix what can be derived, store it, then
    rebuild the compatibility index and return the report."""
    from . import characters as C
    chars = C.list_all(root) if chars is None else chars
    todo = [m for m in chars if (not game_id or (m.get("source") or {}).get("game_id") == game_id)
            and (not slugs or m.get("slug") in slugs)]
    done, failed, skipped = [], [], 0
    for i, m in enumerate(todo):
        if i % 10 == 0:
            progress(90 * i / max(1, len(todo)), f"Replacement readiness {i + 1}/{len(todo)}: {m.get('name')}")
        if not force and not stale(root, m):
            skipped += 1
            continue
        try:
            new = post_collect(root, m, write=True)
            done.append({"slug": m["slug"], "status": new["readiness"].get("status"),
                         "fixed": new["readiness"].get("fixed") or []})
        except Exception as e:                             # noqa: BLE001 - one entry never stops the pass
            failed.append({"slug": m.get("slug"), "error": str(e)[:200]})
    progress(95, "Building the replacement index")
    chars = C.list_all(root)
    ix = index(root, chars, catalog, rebuild=True)
    save(root, force=True)
    rep = report(ix, chars, game_id or None)
    return {"status": "done", "updated": len(done), "skipped_current": skipped, "failed": failed,
            "fixed": [d for d in done if d["fixed"]][:200], "report": rep}


# ================================================================ HTTP routes (server.py registers them)

def routes(app, auth, chars_fn, catalog=None) -> None:
    """GET /api/replacement/candidates?game_id&slot[&all][&limit][&kind]  who can replace this slot
    GET /api/replacement/donor/{slug}                                     where can this donor go
    GET /api/replacement/slots[?game_id]                                  the game slot table (writer, spec, slots)
    GET /api/replacement/report[?game_id][&format=md]                     readiness per game
    POST /api/replacement/refresh                                         rebuild the index from stored metas"""
    from fastapi import Depends, HTTPException
    from fastapi.responses import PlainTextResponse

    def ix(rebuild=False, listed=False):
        K, root = chars_fn()
        lst = K.list_all(root) if listed or rebuild else None
        return index(root, lst, catalog, rebuild=rebuild), lst, root

    @app.get("/api/replacement/candidates")
    def replacement_candidates(game_id: str, slot: str = "", all: bool = False, limit: int = 0, kind: str = "",
                               actor=Depends(auth)):
        x, _lst, root = ix()
        save(root)
        return candidates(x, game_id, slot or None, include_all=all, limit=max(0, limit), kind=kind or None)

    @app.get("/api/replacement/donor/{slug}")
    def replacement_donor(slug: str, actor=Depends(auth)):
        x, _lst, _root = ix()
        v = donor_view(x, slug)
        if v is None:
            raise HTTPException(404, "not in the collection")
        return v

    @app.get("/api/replacement/slots")
    def replacement_slots(game_id: str = "", actor=Depends(auth)):
        x, _lst, _root = ix()
        games = {game_id: x["games"].get(game_id)} if game_id else x["games"]
        return {"games": {k: v | ({"spec_detail": x["specs"].get(v.get("spec"))} if v and v.get("spec") else {})
                          for k, v in games.items() if v}}

    @app.get("/api/replacement/report")
    def replacement_report(game_id: str = "", format: str = "json", actor=Depends(auth)):
        x, lst, root = ix(listed=True)
        rep = report(x, lst, game_id or None)
        if format == "md":
            return PlainTextResponse(markdown(rep))
        return rep

    @app.post("/api/replacement/refresh")
    def replacement_refresh(actor=Depends(auth)):
        x, _lst, root = ix(rebuild=True)
        save(root, force=True)
        return {"donors": len(x["donors"]), "games": len(x["games"]), "specs": len(x["specs"])}
