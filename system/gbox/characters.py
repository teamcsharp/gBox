"""Universal character library: every character model gBox extracted from the operator's games, reusable in any other
game ("play as Leon in ...", "replace this character with Aya").

Library (on the control-plane node, <cache>/characters, e.g. /home/ehm_eckx/gbox-cache/characters):
  <slug>/meta.json      name, source game (title + game_id), extraction tool, rig (joints, body roles), stats,
                        licence note, targets {game_id: [{slot, mod, nodes, rig}]} = built swap mods per target game
  <slug>/<model>        the cleanest source model (.glb / .gltf, textures embedded or next to it)
  <slug>/preview.png    headless software render (3/4 front view)
  <slug>/targets/       the model retargeted onto a target game's skeleton (meta rigs: {"re4gc_leon": "targets/..."})

The `characters` tool (op list | get | use): use = launch a built swap mod for the game, else build it with the game's
swap writer (RE4 GameCube today) and launch it, else report exactly what that game still lacks and file a request.
Every model here was extracted from the operator's own copy of the game, for local use only; nothing is downloaded.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import struct
import time
from pathlib import Path

import numpy as np
from pydantic import BaseModel, Field, model_validator

from .agent_contracts import require_character

LICENCE = "extracted from the operator's own copy, local use only"
RE4GC = {"78ab9efa2e310db4": "Resident Evil 4 (USA) (Disc 1)", "e42c9b780c07c437": "Resident Evil 4 (USA) (Disc 2)"}
RE4WII = {"79c3a3eccb34fe62": "Resident Evil 4: Wii Edition (USA)"}       # same pack formats: gbox/re4wii.py
LEON_ROLES = {"pelvis": "b017", "hip": "b001", "chest": "b002", "neck": "b003", "head": "b004",
              "r_clav": "b005", "r_upper": "b007", "r_fore": "b008", "r_hand": "b009", "l_clav": "b011",
              "l_upper": "b013", "l_fore": "b014", "l_hand": "b015", "r_thigh": "b018", "r_shin": "b019",
              "r_foot": "b020", "l_thigh": "b022", "l_shin": "b023", "l_foot": "b024"}


# ---------------------------------------------------------------- library

def library_root(cfg=None) -> Path:
    if os.environ.get("GBOX_CHARACTERS"):
        return Path(os.environ["GBOX_CHARACTERS"])
    return Path(cfg.cache if cfg is not None else "/home/ehm_eckx/gbox-cache") / "characters"


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def list_all(root: Path, game_id: str = "") -> list[dict]:
    out = []
    for p in sorted(Path(root).glob("*/meta.json")):
        try:
            m = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if game_id:
            m["ready"] = [t for t in m.get("targets", {}).get(game_id, []) if t.get("mod") and not t.get("needs_rebuild")]
        out.append(m)
    return sorted(out, key=lambda m: (m.get("source", {}).get("game_title", ""), m["name"]))


def get(root: Path, slug: str) -> dict:
    p = Path(root) / slug / "meta.json"
    if not p.is_file():
        raise KeyError(slug)
    return json.loads(p.read_text())


def find(chars: list[dict], query: str) -> dict | None:
    """slug, name or alias; then a word match ('my PSO character' -> the HUcast)."""
    q = query.strip().lower()
    for m in chars:
        if q in (m["slug"], m["name"].lower()) or q in [a.lower() for a in m.get("aliases", [])]:
            return m
    words = set(re.findall(r"[a-z0-9]+", q)) - {"my", "the", "character", "as", "with", "from", "a", "of", "play", "model"}
    best, score = None, 0
    for m in chars:
        hay = set(re.findall(r"[a-z0-9]+", " ".join([m["slug"], m["name"], *m.get("aliases", [])]).lower()))
        s = len(words & hay)
        if s > score:
            best, score = m, s
    return best


def put_meta(root: Path, meta: dict) -> dict:
    d = Path(root) / meta["slug"]
    d.mkdir(parents=True, exist_ok=True)
    import uuid
    tmp = d / f"meta.{uuid.uuid4().hex}.tmp"
    tmp.write_text(json.dumps(meta, indent=1))
    tmp.replace(d / "meta.json")
    return meta


def set_target(root: Path, slug: str, game_id: str, entry: dict) -> dict:
    """Record a built swap mod (or a retargeted rig) for a target game; merges by (slot, mod)."""
    m = get(root, slug)
    lst = m.setdefault("targets", {}).setdefault(game_id, [])
    for t in lst:
        if t.get("slot") == entry.get("slot") and (t.get("mod") == entry.get("mod") or not t.get("mod")):
            nodes = sorted(set(t.get("nodes", [])) | set(entry.get("nodes", [])))
            t.update({k: v for k, v in entry.items() if v not in (None, "", [])}, nodes=nodes)
            break
    else:
        lst.append(entry)
    return put_meta(root, m)


def add(root: Path, slug: str, name: str, files: list[Path], source: dict, tool: str, rig: dict | None = None,
        aliases: list[str] = (), targets: dict | None = None, notes: str = "", kind: str = "character",
        preview: dict | None = None, extra: dict | None = None) -> dict:
    """Copy (never move) a model into the library, render its preview and write meta.json. files[0] is the model;
    the rest (texture folders, a UAP manifest, the captured frame) are copied next to it. kind: character | vehicle |
    object | environment; preview: render_preview options (yaw, persp)."""
    d = Path(root) / slug
    d.mkdir(parents=True, exist_ok=True)
    for f in files:
        f = Path(f)
        if f.is_dir():
            shutil.copytree(f, d / f.name, dirs_exist_ok=True)
        elif f.resolve() != (d / f.name).resolve():
            shutil.copy2(f, d / f.name)
    model = d / Path(files[0]).name
    # 2D sprite sheets (PNG) are valid "models" for sprite-based games; skip glTF stats/render.
    if str(model).lower().endswith('.png'):
        kind = 'sprites'
        preview_path = d / "preview.png"
        _sprite_preview(model, preview_path, size=preview.get('size', 384) if preview else 384)
        st = {"triangles": 0, "vertices": 0, "textures": 1, "meshes": 0}
        rig_out = rig or {}
    else:
        st = model_stats(model)
        render_preview(model, d / "preview.png", **(preview or {}))
        rig_out = {**st.pop("rig"), **(rig or {})}
    meta = {"slug": slug, "name": name, "kind": kind, "aliases": list(aliases), "source": source, "extraction_tool": tool,
            "model": model.name, "preview": "preview.png", "rig": rig_out, "stats": st,
            "licence": LICENCE, "notes": notes, "targets": targets or {}, "added": time.time(), **(extra or {})}
    old = d / "meta.json"
    if old.exists():                                       # keep targets recorded by earlier builds
        prev = json.loads(old.read_text())
        for gid, lst in prev.get("targets", {}).items():
            meta["targets"].setdefault(gid, [])
            meta["targets"][gid] += [t for t in lst if t not in meta["targets"][gid]]
    return put_meta(root, meta)


def _sprite_preview(src: Path, out: Path, size: int = 384) -> Path:
    """Use the sprite sheet itself as the collection preview, fitted to a square."""
    from PIL import Image
    im = Image.open(src).convert("RGBA")
    if im.width and im.height and max(im.size) < size:
        # a handful of 8x8 tiles would cover <1% of the canvas: enlarge pixel-exact so check_preview judges the sprites
        f = size // max(im.size)
        im = im.resize((im.width * f, im.height * f), Image.NEAREST)
    im.thumbnail((size, size))
    canvas = Image.new("RGBA", (size, size), (38, 40, 48, 255))
    canvas.paste(im, ((size - im.width) // 2, (size - im.height) // 2), im)
    canvas.save(out, "PNG")
    return out


# ---------------------------------------------------------------- glTF helpers

def _load(path: Path):
    from .re4gc_models import _gltf_load, _node_world
    gl, acc, image = _gltf_load(path)
    return gl, acc, image, _node_world(gl)


def model_stats(path: Path) -> dict:
    gl, acc, _img, _w = _load(path)
    tris = verts = 0
    for me in gl.get("meshes", []):
        for pr in me["primitives"]:
            n = gl["accessors"][pr["attributes"]["POSITION"]]["count"]
            verts += n
            tris += (gl["accessors"][pr["indices"]]["count"] if "indices" in pr else n) // 3
    joints = sorted({j for s in gl.get("skins", []) for j in s["joints"]})
    names = [gl["nodes"][j].get("name", f"node{j}") for j in joints]
    return {"triangles": tris, "vertices": verts, "textures": len(gl.get("images", [])), "meshes": len(gl.get("meshes", [])),
            "rig": {"skinned": bool(joints), "joints": len(joints), "joint_names": names[:200]}}


def merge_gltf(paths: list[Path], out: Path) -> Path:
    """Several glTFs -> one .glb (each keeps its own nodes/skin; scene = all roots). Used for multi-part models
    (RE4 Leon: body + head + hair + jacket BINs)."""
    gl_out = {"asset": {"version": "2.0", "generator": "gbox characters"}, "scene": 0, "scenes": [{"nodes": []}]}
    keys = ["nodes", "meshes", "skins", "materials", "accessors", "bufferViews", "images", "textures", "samplers"]
    for k in keys:
        gl_out[k] = []
    blob = bytearray()
    for p in paths:
        from .re4gc_models import _gltf_load
        gl = json.loads(Path(p).read_text()) if str(p).endswith(".gltf") else None
        if gl is None:
            d = Path(p).read_bytes()
            jl = struct.unpack_from("<I", d, 12)[0]
            gl, bins = json.loads(d[20:20 + jl]), [d[20 + jl + 8:]]
        else:
            bins = [base64.b64decode(b["uri"].split(",", 1)[1]) if b["uri"].startswith("data:") else (Path(p).parent / b["uri"]).read_bytes()
                    for b in gl["buffers"]]
        off = {k: len(gl_out[k]) for k in keys}
        boff = []
        for b in bins:
            blob += bytes(-len(blob) % 4)
            boff.append(len(blob))
            blob += b
        for v in gl.get("bufferViews", []):
            gl_out["bufferViews"].append({**v, "buffer": 0, "byteOffset": v.get("byteOffset", 0) + boff[v["buffer"]]})
        for a in gl.get("accessors", []):
            gl_out["accessors"].append({**a, "bufferView": a["bufferView"] + off["bufferViews"]})
        for im in gl.get("images", []):
            gl_out["images"].append({**im, **({"bufferView": im["bufferView"] + off["bufferViews"]} if "bufferView" in im else {})})
        gl_out["samplers"] += gl.get("samplers", [])
        for t in gl.get("textures", []):
            gl_out["textures"].append({**t, "source": t["source"] + off["images"],
                                       **({"sampler": t["sampler"] + off["samplers"]} if "sampler" in t else {})})
        for m in gl.get("materials", []):
            m = json.loads(json.dumps(m))
            bct = m.get("pbrMetallicRoughness", {}).get("baseColorTexture")
            if bct:
                bct["index"] += off["textures"]
            gl_out["materials"].append(m)
        for me in gl.get("meshes", []):
            prims = []
            for pr in me["primitives"]:
                pr = json.loads(json.dumps(pr))
                pr["attributes"] = {k: v + off["accessors"] for k, v in pr["attributes"].items()}
                if "indices" in pr:
                    pr["indices"] += off["accessors"]
                if "material" in pr:
                    pr["material"] += off["materials"]
                prims.append(pr)
            gl_out["meshes"].append({**me, "primitives": prims})
        for s in gl.get("skins", []):
            gl_out["skins"].append({**s, "joints": [j + off["nodes"] for j in s["joints"]],
                                    **({"inverseBindMatrices": s["inverseBindMatrices"] + off["accessors"]} if "inverseBindMatrices" in s else {}),
                                    **({"skeleton": s["skeleton"] + off["nodes"]} if "skeleton" in s else {})})
        for n in gl["nodes"]:
            n = dict(n)
            if "children" in n:
                n["children"] = [c + off["nodes"] for c in n["children"]]
            if "mesh" in n:
                n["mesh"] += off["meshes"]
            if "skin" in n:
                n["skin"] += off["skins"]
            gl_out["nodes"].append(n)
        gl_out["scenes"][0]["nodes"] += [r + off["nodes"] for r in gl["scenes"][gl.get("scene", 0)]["nodes"]]
    # images given as data URIs stay URIs (valid in a .glb too)
    for k in keys:
        if not gl_out[k]:
            del gl_out[k]
    gl_out["buffers"] = [{"byteLength": len(blob)}]
    js = json.dumps(gl_out, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    blob += bytes(-len(blob) % 4)
    Path(out).write_bytes(struct.pack("<III", 0x46546C67, 2, 28 + len(js) + len(blob)) + struct.pack("<II", len(js), 0x4E4F534A)
                          + js + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob))
    return Path(out)


def _skin_world(gl, acc, W, nd, P, a):
    """Skinned vertices -> where the skin puts them (strongest joint): Blender exports (Live Link variants) keep the mesh
    in its own space, so the raw positions aren't the model's pose; props are placed by their node's world matrix."""
    sk = gl["skins"][nd["skin"]]
    if "JOINTS_0" not in a or "WEIGHTS_0" not in a:
        return P
    ibm = (acc(sk["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1) if "inverseBindMatrices" in sk
           else np.tile(np.eye(4), (len(sk["joints"]), 1, 1)))
    skm = np.array([W[j] @ ibm[k] for k, j in enumerate(sk["joints"])])
    J, Wt = acc(a["JOINTS_0"]).astype(int), acc(a["WEIGHTS_0"]).astype(float)
    M = skm[J[np.arange(len(P)), Wt.argmax(1)]]
    return np.einsum("nij,nj->ni", M[:, :3, :3], P) + M[:, :3, 3]


def _triangles(path: Path):
    """[(world positions (3,3), uvs (3,2), texture RGBA | None, colour)] in the bind pose."""
    gl, acc, image, W = _load(path)
    texcache, out = {}, []
    for ni, nd in enumerate(gl["nodes"]):
        if "mesh" not in nd:
            continue
        M = np.eye(4) if "skin" in nd else W[ni]               # skinned meshes are in bind (model) space
        for pr in gl["meshes"][nd["mesh"]]["primitives"]:
            a = pr["attributes"]
            P = acc(a["POSITION"]).astype(float) @ M[:3, :3].T + M[:3, 3]
            if "skin" in nd:
                P = _skin_world(gl, acc, W, nd, P, a)
            UV = acc(a["TEXCOORD_0"]).astype(float) if "TEXCOORD_0" in a else np.zeros((len(P), 2))
            idx = acc(pr["indices"]).reshape(-1) if "indices" in pr else np.arange(len(P))
            img, col = None, np.array([200.0, 200, 200])
            if (mi := pr.get("material")) is not None:
                pbr = gl["materials"][mi].get("pbrMetallicRoughness", {})
                if "baseColorFactor" in pbr:
                    col = np.array(pbr["baseColorFactor"][:3]) * 255
                if (bct := pbr.get("baseColorTexture")) is not None:
                    if bct["index"] not in texcache:
                        try:
                            texcache[bct["index"]] = image(bct["index"])
                        except Exception:
                            texcache[bct["index"]] = None
                    img = texcache[bct["index"]]
            for k in range(0, len(idx) - 2, 3):
                t = idx[k:k + 3]
                out.append((P[t], UV[t], img, col))
    return out


def render_preview(path: Path, out: Path, size: int = 384, yaw: float = -30.0, persp: tuple | None = None) -> Path:
    """Headless preview (no GPU): flat-shaded, textured per triangle (corner + centre samples), painter's order,
    3/4 front view of a character facing +Z. persp=(P00, P11): perspective from the origin looking down -Z instead
    (a captured scene seen through the game's own camera)."""
    from PIL import Image, ImageDraw
    tris = _triangles(path)
    if not tris:
        raise ValueError(f"{path}: no triangles")
    c, s = np.cos(np.radians(yaw)), np.sin(np.radians(yaw))
    R = np.eye(3) if persp else np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    ss, W, H = 2, size, size                               # supersample, then downscale
    if persp:
        W = int(round(size * persp[1] / persp[0]))
        cen = np.zeros(3)

        def to2d(q):                                       # view space -> NDC (-1..1)
            z = -q[:, 2]
            return None if (z < 1e-3).any() else np.stack([q[:, 0] * persp[0] / z, q[:, 1] * persp[1] / z], 1)
    else:
        allp = np.concatenate([t[0] for t in tris]) @ R.T
        lo, hi = allp.min(0), allp.max(0)
        cen, ext = (hi + lo) / 2, max(hi[0] - lo[0], hi[1] - lo[1]) * 1.08

        def to2d(q):
            return q[:, :2] * 2 / ext
    im = Image.new("RGB", (W * ss, H * ss), (38, 40, 48))
    dr = ImageDraw.Draw(im)
    light = np.array([0.35, 0.55, 0.75])
    light /= np.linalg.norm(light)
    items = []
    for P, UV, img, col in tris:
        q = (P @ R.T) - cen
        xy = to2d(q)
        if xy is None or (persp and (np.abs(xy) > 4).all()):
            continue
        n = np.cross(q[1] - q[0], q[2] - q[0])
        ln = np.linalg.norm(n)
        if ln < 1e-12:
            continue
        if img is not None:
            h, w = img.shape[:2]
            cs = [img[min(h - 1, int((v % 1.0) * h)), min(w - 1, int((u % 1.0) * w))] for u, v in list(UV) + [UV.mean(0)]]
            cs = [x for x in cs if x[3] > 40] or cs
            colr = np.mean([x[:3] for x in cs], 0).astype(float)
        else:
            colr = col
        shade = 0.4 + 0.6 * abs(float(n @ light) / ln)
        pts = [(W * ss / 2 * (1 + x), H * ss / 2 * (1 - y)) for x, y in xy]
        items.append((q[:, 2].mean(), pts, tuple(int(v) for v in np.clip(colr * shade, 0, 255))))
    items.sort(key=lambda t: t[0])
    for _, pts, colr in items:
        dr.polygon(pts, fill=colr)
    im.resize((W, H), Image.LANCZOS).save(out)
    return Path(out)


def check_preview(path: Path) -> dict:
    """Is there a model in this preview? (coverage = share of non-background pixels, colours = distinct colour cells)"""
    from PIL import Image
    a = np.asarray(Image.open(path).convert("RGB")).astype(int)
    fg = np.abs(a - np.array([38, 40, 48])).sum(2) > 24
    cols = len(np.unique(a[fg] // 16, axis=0)) if fg.any() else 0
    cov = float(fg.mean())
    return {"coverage": round(cov, 3), "colours": int(cols), "ok": cov > 0.02 and cols >= 3}


def verify_entry(root: Path, meta: dict) -> dict:
    """What a caller may claim: the model file exists, has triangles, and the preview shows something."""
    d = Path(root) / meta["slug"]
    model, prev = d / meta["model"], d / meta.get("preview", "preview.png")
    out = {"model": str(model), "model_bytes": model.stat().st_size if model.is_file() else 0,
           "triangles": meta.get("stats", {}).get("triangles", 0), "textures": meta.get("stats", {}).get("textures", 0)}
    out["preview"] = check_preview(prev) if prev.is_file() else {"ok": False, "error": "no preview"}
    if meta.get("kind") == "sprites":
        out["ok"] = bool(out["model_bytes"] and out["preview"].get("ok"))
    else:
        out["ok"] = bool(out["model_bytes"] and out["triangles"] and out["preview"].get("ok"))
    return out


def rig_from_gltf(path: Path, roles: dict[str, str]) -> dict:
    """A skinned glTF + {role: joint name} -> the generic rig gbox.re4gc_enemies.retarget takes (joints world xyz,
    parents, roles, prims with a per-vertex owner joint = largest weight)."""
    gl, acc, image, W = _load(path)
    skin = gl["skins"][0]
    jn = skin["joints"]
    names = [gl["nodes"][j].get("name", f"node{j}") for j in jn]
    parent_node = {c: i for i, nd in enumerate(gl["nodes"]) for c in nd.get("children", [])}
    pos_of = {j: k for k, j in enumerate(jn)}
    parent = []
    for j in jn:
        p = parent_node.get(j)
        while p is not None and p not in pos_of:
            p = parent_node.get(p)
        parent.append(pos_of[p] if p is not None else -1)
    rmap = {r: names.index(n) for r, n in roles.items() if n in names}
    texcache, prims = {}, []
    for ni, nd in enumerate(gl["nodes"]):
        if "mesh" not in nd:
            continue
        sk = gl["skins"][nd["skin"]] if "skin" in nd else None
        loc = {k: pos_of.get(j, 0) for k, j in enumerate(sk["joints"])} if sk else {}
        for pr in gl["meshes"][nd["mesh"]]["primitives"]:
            a = pr["attributes"]
            P = acc(a["POSITION"]).astype(float)
            if sk is None:
                P = P @ W[ni][:3, :3].T + W[ni][:3, 3]
            else:
                P = _skin_world(gl, acc, W, nd, P, a)
            N = acc(a["NORMAL"]).astype(float) if "NORMAL" in a else np.tile([0, 1.0, 0], (len(P), 1))
            UV = acc(a["TEXCOORD_0"]).astype(float) if "TEXCOORD_0" in a else np.zeros((len(P), 2))
            if sk is not None and "JOINTS_0" in a:
                J, Wt = acc(a["JOINTS_0"]).astype(int), acc(a["WEIGHTS_0"]).astype(float)
                owner = np.array([loc.get(int(J[k, Wt[k].argmax()]), 0) for k in range(len(P))])
            else:                                          # a prop (hat): rigid on its nearest joint ancestor
                q = parent_node.get(ni)
                while q is not None and q not in pos_of:
                    q = parent_node.get(q)
                owner = np.full(len(P), pos_of.get(q, 0))
            idx = acc(pr["indices"]).reshape(-1, 3) if "indices" in pr else np.arange(len(P)).reshape(-1, 3)
            tex, color, alpha_mode = None, (255, 255, 255, 255), "OPAQUE"
            if (mi := pr.get("material")) is not None:
                alpha_mode = gl["materials"][mi].get("alphaMode", "OPAQUE")
                pbr = gl["materials"][mi].get("pbrMetallicRoughness", {})
                color = tuple(int(c * 255) for c in pbr.get("baseColorFactor", [1, 1, 1, 1]))
                if (bct := pbr.get("baseColorTexture")) is not None:
                    if bct["index"] not in texcache:
                        texcache[bct["index"]] = image(bct["index"])
                    tex = texcache[bct["index"]]
            prims.append({"pos": P, "nrm": N, "uv": UV, "tris": idx, "owner": owner, "tex": tex, "color": color,
                          "alpha_mode": alpha_mode, "name": f"m{len(prims)}"})
    return {"joints": np.array([W[j][:3, 3] for j in jn]), "parent": parent, "roles": rmap, "prims": prims}


# ---------------------------------------------------------------- Leon (RE4 GC) export

LEON_BINS = {0: "body", 2: "head", 4: "face", 5: "hair", 6: "jacket", 7: "eyes"}


def export_leon(iso: Path, out_dir: Path, pack: str = "em/pl00.drs") -> Path:
    """Leon (chapter 1 outfit) from an RE4 GC disc image: body + head/face/hair/jacket/eyes BINs -> one leon.glb."""
    from . import re4gc_models as R
    from .re4gc_enemies import tpl_of
    pk = R.load_pack_from_iso(Path(iso), pack)
    out_dir = Path(out_dir)
    tmp = out_dir / "_parts"
    tmp.mkdir(parents=True, exist_ok=True)
    parts = []
    for i, nm in LEON_BINS.items():
        m = R.bin_read(pk.items[i][1])
        tj = tpl_of(pk, i)
        texs = [t.rgba() for t in R.tpl_read(pk.items[tj][1])] if tj is not None else None
        parts.append(R.bin_to_gltf(m, texs, tmp / f"leon_{nm}.gltf", 0.001, f"leon_{nm}"))
    out = merge_gltf(parts, out_dir / "leon.glb")
    shutil.rmtree(tmp)
    return out


# ---------------------------------------------------------------- what other games need (docs/model_swaps.md)

def needs_for(game: dict) -> dict:
    """No writer for this game yet: what would have to exist (formats, tools, the target skeleton)."""
    t, plat = (game.get("title") or "").lower(), game.get("platform") or ""
    if "ocarina" in t or "ship of harkinian" in t or ("zelda" in t and plat == "n64"):
        return {"target": "Link (21-limb rigid skeleton, OoT animations)", "format": "zzplayas play-as .zobj (ROM / ModLoader64) "
                "or Fast64 .o2r (Ship of Harkinian)", "steps": ["read Link's limb hierarchy from the ROM (Z64 object_link_boy)",
                "retarget onto Link's 21 limbs (scripts/retarget_rigid.py + a map)", "write the .zobj / .o2r incl. equipment display lists"],
                "have": "nothing for OoT models yet"}
    if ("grand theft auto" in t or t.startswith("gta")) and "liberty city stories" in t and plat == "ps2":
        return {"target": "Toni (every outfit: player, plr..plr16 in MODELS/GTA3PS2.IMG)", "format": "Stories .mdl + .chk (PS2)",
                "steps": [], "have": "gbox/gta_stories_models.py reads, extracts and writes them; characters op=use builds "
                "lcs_<character> (checked in game on the Spark: walking, driving)"}
    if ("grand theft auto" in t or t.startswith("gta")) and "stories" in t:
        return {"target": "the player (Vic / Toni)", "format": "Stories .mdl models + .chk textures (PSP/PS2)",
                "steps": ["port gbox/gta_stories_models.py: VCS RslNode has no node ids (+1 field), RslRasterPS2 has 2 more "
                          "words, CStreaming/ResourceImage differ (leedsgta.h VCS branches); PSP: sPspGeometry vertex "
                          "formats instead of PS2 VIF batches", "find Vic's outfit models (special-model directory in GAME.DTZ)",
                          "Ghidra the ELF/EBOOT for FindPlayerPed / RequestSpecialModel like LCS (docs/model_swaps.md)"],
                "have": "the LCS PS2 reader/writer (gbox/gta_stories_models.py); VCS and PSP are not done"}
    if "grand theft auto" in t or t.startswith("gta"):
        return {"target": "the player ped (17 rigid frames: Swaist, Smid, Storso, Shead, arms, legs)",
                "format": "RenderWare .dff + .txd in MODELS/GTA3.IMG (all IMG copies on the PS2 disc)",
                "steps": ["retarget onto the ped frames by name", "gta_rw.geometry_build per frame + a PS2 TXD", "replace player.dff/.txd "
                          "(must fit the old sector count)"],
                "have": "gbox/gta_rw.py reads/writes DFF, TXD and IMG (GTA III PS2); the character writer is not wired yet. "
                        "LCS/VCS use .mdl (no writer anywhere)."}
    if "phantasy star online" in t:
        return {"target": "a PSO player class or enemy (Ninja node tree; motions index nodes)", "format": "Ninja .nj (DC/GC) / .xj "
                "(BB) in .bml/.afs", "steps": ["fit the model to the class's node tree", "a Ninja .nj chunk writer", "repack the .afs/.bml"],
                "have": "gbox/ninja.py + gbox/pso_player.py read PSO models; no .nj writer yet"}
    if "super mario 64" in t:
        return {"target": "Mario (20 rigid joints)", "format": "F3D display lists in segment 04 + geo layout 0x17",
                "steps": ["Blender bone map scripts/retarget_<character>_to_sm64mario.json", "gbox/sm64_writer.py write_mod"],
                "have": "gbox/sm64_writer.py (the writer) exists; a bone map exists only for some characters"}
    if "resident evil 4" in t and (game.get("system") or "").lower().endswith("xbox 360"):
        return {"target": "Leon (pl00 in the HD port's .udas/.das packs)", "format": "RE4 HD (2011, PC-2007 lineage) BIN/TPL, "
                "Xenon-tiled textures", "steps": ["read the X360 disc (XDVD, gbox/re6.py has the reader)", "port the UHD BIN "
                "writer (below) to big-endian + Xenon tiling", "Xenia folder mod like gbox/re6_tool.py"],
                "have": "the GC/Wii writer (gbox/re4gc_models.py + gbox/re4wii.py); see docs/mercenaries.md"}
    if "resident evil 4" in t and plat in ("windows_native", "ps_modern"):
        return {"target": "Leon (pl00 .udas)", "format": "RE4 UHD BIN/TPL in pl*.udas", "steps": ["port gbox/re4gc_models.py "
                "(GC BIN) to the UHD BIN layout", "write pl00.udas into a mod folder"], "have": "the GameCube writer only"}
    if "resident evil 4" in t and plat == "ps2":
        return {"target": "Leon (pl00 in the PS2 .das packs)", "format": "RE4 PS2 model packs (PS2 BIN variant, TIM2-like "
                "textures)", "steps": ["read the PS2 DVD (ISO9660) packs", "a PS2 BIN reader/writer (the GC BIN layout differs: "
                "VIF-packed vertices)", "a file mod image like gbox/gta_stories_models.py does for PS2"],
                "have": "the GC/Wii writer only; the game runs on the Spark (pcsx2 libretro) with EE RAM access"}
    if "mercenaries 3d" in t:
        return {"target": "a Mercenaries 3D character (MT Framework Mobile .mod/.tex in .arc)", "format": "MTF Mobile arc",
                "steps": ["romfs extract (Citra)", "MTF Mobile model writer", "Citra/Azahar mod folder (LayeredFS)"],
                "have": "nothing (the game runs on the Spark in citra_libretro; no memory map for gBox)"}
    if "smash bros" in t and "melee" in t:
        return {"target": "a fighter (Pl<Xx>Nr.dat JObj tree)", "format": "HAL HSD .dat (JObj/DObj/PObj, GX display lists)",
                "steps": ["fit onto the fighter's joints (PlCo common bone ids)", "an HSD DAT writer"], "have": "gbox/melee_models.py "
                "reads fighters; no writer"}
    if "resident evil" in t and plat in ("psx", "dreamcast", "gamecube") and ("nemesis" in t or "resident evil 3" in t or plat == "psx"):
        return {"target": "the player's PLD (RE3: Jill / Mercenaries Carlos, Mikhail, Nicholai; ~15 rigid parts, per-part "
                "TIM page)", "format": "RE3 PLD (+ PLW weapon models) in CD_DATA/PLD; DC/GC ports keep the PLD layout",
                "steps": ["rigid retarget per body part (scripts/retarget_rigid.py)", "a PLD writer (vertex/normal/prim tables, "
                "one 256x256 TIM)", "rebuild the disc image (PSX raw 2352 sectors / GDI / GC image)"],
                "have": "nothing yet; see docs/mercenaries.md"}
    if "mario kart 64" in t:
        return {"target": "a driver (pre-rendered sprites)", "format": "sprite sheets (SpaghettiKart .o2r)", "steps": ["render the "
                "character in a kart from every angle (Blender headless)", "pack the .o2r"], "have": "nothing"}
    return {"target": "the game's player model", "format": f"unknown for {plat or 'this platform'}",
            "steps": ["find the character model files and their format (reader)", "a writer for that format",
                      "a bone map from the library rig onto the game's skeleton"], "have": "nothing for this game yet"}


# ---------------------------------------------------------------- the `characters` tool

from .models import Permission as P  # noqa: E402
from .registry import HOST_OS, tool  # noqa: E402


class CharIn(BaseModel):
    op: str = "list"                       # list | get | collect | use | live_use | overlay | extract | add | blender | environments | swap | place | unplace | coverage
    character: str = Field(default="", description="Required for use, live_use, overlay and place: exact collection slug or name. Copy the character supplied in the request; use list to find a name. Optional for list, collect and extraction.")
    session_id: str = ""                   # use / extract: the game this session runs (and the node it runs on)
    game_id: str = ""                      # use / extract: or a catalog game id / title
    game: str = ""
    slot: str = "player"                   # player | enemies (RE4: Mercenaries Village Ganados, built mods only; PSO Ver.2: every mapped enemy) | roster (DOA2: every fighter, see pairs) | GTA Vice City PC: player (Tommy) | ped:<dff name> | peds:all (every ped on Tommy's skeleton) | all | Clay Fighter SC (N64): fighter:<name>[:flip] (bmf, blob, bonker, booger, kiln, ewj, highfive, houngan, icky, kungpow, liberty, lockjaw, sumo, taffy, thoppy, zappa; player = Bad Mr. Frosty; :flip mirrors the donor) re-draws that fighter's sprites from a sprites entry
    slot: str = "player"                   # player | enemies (RE4: Mercenaries Village Ganados, built mods only; PSO Ver.2: every mapped enemy) | roster (DOA2: every fighter, see pairs) | GTA Vice City PC: player (Tommy) | ped:<dff name> | peds:all (every ped on Tommy's skeleton) | all | Jet Grind Radio: player (Beat, the new-game skater, unless active_id) | character:<name> (beat, gum, corn, combo, code, nuts, reco, bis, yoyo, plug, goji, pots, rival_lshocker, rival_ntank, rival_pjam, rival_snpjam) | id:N (native ID) | NN (PLAYER.AFS archive index)
    active_id: int | None = Field(default=None, ge=0, le=15, strict=True,
                                 description="Jet Grind Radio only: native character ID (0-15) of the character being played, for slot=player. Omitted, slot=player means Beat (native ID 0), the character a new game starts with; the result says so. Use slot=character:<name> or id:N to target anyone else.")
    rebuild: bool = False                  # use: build again even if a mod exists
    launch: bool = True                    # use: launch after building
    kind: str = "character"                # extract / add: character | vehicle | object | environment
    x: float | None = None                 # extract: the thing's screen point, fractions of the game picture (0..1)
    y: float | None = None
    from_clipboard: bool = False           # add: the model last sent to the gBox clipboard (Blender add-on "Send to gBox")
    artifact: str = ""                     # add: or an artifact sha256 (.glb / .gltf)
    path: str = ""                         # add: or a model file on the control-plane node
    base: str = ""                         # add: store as a variant of this character (gbox.variants; Blender Live Link)
    replace: str = ""                      # add base=...: update this variant in place (Live Link push)
    props: list[dict] = []                 # add base=...: [{object, bone}] the Blender add-on bound
    rig_roles: dict[str, str] = {}         # add: semantic body role -> joint node name in the imported model
    scale: dict = {}                       # add base=...: {"head": k} head-bone scale
    head_scale: float = 0.0                # use: build a "<name> - big head" variant (0.5..3) and use that
    a: str = ""                            # swap (OoT): who gets B's looks: "link" (default) | a name | "x,y" picture point
    b: str = ""                            # swap: whose looks: a name ("Saria", "kokiri boy") | "x,y" picture point
    one_way: bool = False                  # swap: only A <- B ("play as B"), B keeps its own model
    pos: list[float] = []                  # place (OoT): world x, y, z (default: in front of the player)
    near: str = ""                         # place: next to this actor ("Saria", "Deku Tree")
    yaw: float | None = None               # place: facing, degrees (default: towards the player)
    size: float = 0.0                      # place: statue height x adult Link-ish 75 units (default 1)
    pairs: list[dict] = []                 # match (No Mercy): [{character, slot = a wrestler's name}] -> one ROM; use slot=roster (DOA2): [{character, slot?}], unassigned donors are dealt over the rest
    title: str = ""                        # match: the mod card title ("Mario vs Princess Peach")

    @model_validator(mode="after")
    def require_named_character(self):
        require_character(self.op, self.character)
        return self


class CharOut(BaseModel):
    result: dict


def _api(ctx, method, path, **kw):
    import httpx
    r = httpx.request(method, f"{ctx.server}{path}", headers=ctx.headers, timeout=kw.pop("timeout", 60), **kw)
    r.raise_for_status()
    return r.json() if "json" in r.headers.get("content-type", "") else r.content


def _local_or_fetch(ctx, meta: dict, rel: str) -> Path:
    """A library file on this node: the library itself on the control plane, else a node-local copy from the API."""
    p = library_root(ctx.config) / meta["slug"] / rel
    if p.is_file():
        return p
    p = Path(ctx.config.cache) / "characters_mirror" / meta["slug"] / rel
    if not p.is_file():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(_api(ctx, "GET", f"/api/characters/{meta['slug']}/file/{rel}", timeout=300))
    return p


def _blender(cfg) -> str | None:
    """A Blender that runs on this node (the Spark's /usr/local/bin/blender is an x86-64 build; /usr/bin's is arm64)."""
    import subprocess
    from .provision import find_blender
    from .re4gc_enemies import blender_exe
    for b in dict.fromkeys(x for x in (find_blender(cfg), "/usr/bin/blender", blender_exe()) if x and Path(x).exists()):
        try:
            if subprocess.run([b, "--version"], capture_output=True, timeout=60).returncode == 0:
                return str(b)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None


def _game(ctx, inp) -> dict:
    gid = inp.game_id or (inp.game if re.fullmatch(r"[0-9a-f]{16}", inp.game or "") else "")   # a catalog id passed as game
    if inp.session_id and not gid:
        s = next((s for s in _api(ctx, "GET", "/api/sessions") if s.get("session_id") == inp.session_id), None)
        if not s:
            raise ValueError(f"no session {inp.session_id}")
        gid = s["game_id"]
    if not gid and inp.game:
        hits = _api(ctx, "GET", "/api/catalog/best", params={"q": inp.game, "limit": 5})   # ranked: the real game first
        hits = hits.get("items", hits) if isinstance(hits, dict) else hits
        if not hits:
            raise ValueError(f"no game matching {inp.game!r} in the catalog")
        gid = hits[0]["game_id"]
    if not gid:
        raise ValueError("use needs session_id, game_id or game")
    return _api(ctx, "GET", f"/api/catalog/{gid}")


def _launch(ctx, gid: str, mod: str, node: str) -> dict:
    j = _api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": mod, "node": node}})
    return {"job": j.get("id"), "state": j.get("state"), "node": node}


def _request(ctx, meta: dict, game: dict, need: dict) -> dict:
    title = f"Character swap: {meta['name']} into {game['title']}"
    for r in _api(ctx, "GET", "/api/requests", params={"status": "open,in_progress"}):
        if r.get("title") == title:
            return {"number": r.get("number"), "id": r["id"], "existing": True}
    body = (f"Put {meta['name']} (library character '{meta['slug']}', from {meta['source'].get('game_title')}) into "
            f"{game['title']} (game {game['game_id']}). No swap writer for this game yet.\n" + json.dumps(need, indent=1))
    r = _api(ctx, "POST", "/api/requests", json={"title": title, "body": body, "source": "characters", "kind": "text",
                                                "parent_request_id": getattr(ctx, "parent_request_id", None),
                                                "context": {"character": meta["slug"], "game_id": game["game_id"], "job_id": ctx.job_id}})
    return {"number": r.get("number"), "id": r["id"], "existing": False}


def build_re4(ctx, meta: dict, game: dict, progress) -> dict:
    """RE4 GC: the character replaces Leon (pl00/08/09/10). Uses the library's Leon-rigged model when there is one
    (rigs.re4gc_leon, from the Blender bone maps), else retargets the library rig's body roles in numpy."""
    from . import char_swap as C, filemods, re4gc_enemies as E, re4gc_models as R  # noqa: F401
    from .models import CatalogEntry
    from .tools import rom_path
    gid, cfg = game["game_id"], ctx.config
    work = Path(cfg.cache) / "characters_build" / meta["slug"]
    work.mkdir(parents=True, exist_ok=True)
    rom = rom_path(CatalogEntry.model_validate(game), cfg)
    base = filemods.base_dir(cfg, gid) / (rom.stem + ".iso")
    wii = gid in RE4WII
    if wii:                                               # Wii: the extracted disc folder (same pack formats as GC)
        from . import re4wii
        base = re4wii.ensure_base(cfg, gid, rom, progress)
    elif not base.exists():                               # one vanilla ISO per node (the staged copy may be a mod image)
        base.parent.mkdir(parents=True, exist_ok=True)
        progress(5, f"Vanilla disc image from {rom.name}")
        if rom.suffix.lower() == ".gcz":
            filemods.gcz_to_iso(rom, base.with_suffix(".part"), lambda p, m: progress(5 + p * 0.3, m))
        else:
            shutil.copy2(rom, base.with_suffix(".part"))
        base.with_suffix(".part").replace(base)
    scale = (meta.get("rig") or {}).get("scale") or {}
    rig = meta.get("rigs", {}).get("re4gc_leon") if not scale else None    # a head-size change needs the numpy retarget
    if rig:
        rigged = _local_or_fetch(ctx, meta, rig)
        how = f"library rig {rig}"
    else:
        roles = meta.get("rig", {}).get("roles")
        if not roles:
            raise ValueError(f"{meta['name']} has no body roles in meta.json (rig.roles) and no RE4 rig: can't retarget")
        progress(30, f"Retargeting {meta['name']} onto Leon's skeleton")
        src = _local_or_fetch(ctx, meta, meta["model"])
        tmpl = R.bin_read(R.load_pack_from_iso(base, "em/pl00.drs").items[0][1])
        prims = E.retarget(rig_from_gltf(src, roles), tmpl, scale=scale)
        rigged = E.write_rigged_gltf(prims, tmpl, work / "re4gc_leon.gltf", meta["slug"])
        how = "numpy rigid retarget (body roles)"
    drs = work / "drs"
    bl, srcs, rep, last = _blender(cfg), [rigged], None, None
    for k in range(4):                                     # a pack must not grow: smaller textures, then decimate
        for mt in (128, 64, 32):
            try:
                progress(40 + k * 10, f"Writing Leon's packs (textures {mt}px{', decimated' if k else ''})")
                rep = C.swap_packs(base, srcs[-1], drs, max_tex=mt)
                break
            except ValueError as e:
                last = e
        if rep or not bl or k == 3:                        # k == 3: the last decimation has been tried too
            break
        srcs.append(E.decimate(rigged, work / f"dec{k}.glb", (0.5, 0.3, 0.2)[k], bl))
    if not rep:
        raise ValueError(f"{meta['name']} doesn't fit Leon's packs on the disc ({last}); "
                         + ("decimating didn't help" if bl else "no Blender on this node to decimate"))
    if wii:
        name = f"re4wii_{meta['slug']}"
        progress(70, f"Building the Wii mod tree {name}")
        res = re4wii.build_mod(cfg, gid, base, name, {f"em/{p.name}": p for p in sorted(drs.glob("pl*.drs"))},
                               {"character": meta["slug"]})
        return {"mod": name, "packs": rep, "how": how, "decimated": len(srcs) > 1, "dir": res["dir"]}
    name = f"re4_{meta['slug']}" + ("_d2" if gid == "e42c9b780c07c437" else "")
    image = f"RE4 {meta['name']} (Disc {'2' if gid == 'e42c9b780c07c437' else '1'}).iso"
    progress(70, f"Building the disc image {image}")
    res = filemods.build_image(cfg, gid, base, name, {f"em/{p.name}": {"from": str(p)} for p in sorted(drs.glob("pl*.drs"))})
    d = filemods.mod_dir(cfg, gid, name)
    Path(res["image"]).replace(d / image)                  # own file name: staging reuses a same-name + same-size image
    mj = json.loads((d / ".gbox-mod.json").read_text())
    (d / ".gbox-mod.json").write_text(json.dumps(mj | {"image": image, "character": meta["slug"]}))
    stale = Path(cfg.cache) / gid / image
    if stale.exists():
        stale.unlink()
    props = meta.get("props") or []
    out = {"mod": name, "image": image, "packs": rep, "how": how, "decimated": len(srcs) > 1}
    if props:
        out["props"] = {"triangles": sum(p.get("triangles", 0) for p in props), "meshes": len(props),
                        "simplified": len(srcs) > 1, **({"why": "disc-1 pack size: the whole model (props included) was decimated "
                                                                f"to {(0.5, 0.3, 0.2)[len(srcs) - 2]:.0%}"} if len(srcs) > 1 else {})}
    return out


# ---------------------------------------------------------------- op=extract: any running game -> the collection
#
# Routes, in order: (a) already in the collection (same game) -> return it; (b) the game has a dedicated extractor
# (DEDICATED: reads the model straight from the disc, rigged) -> extract + add; (c) the session can be captured with
# RenderDoc (gbox.scene_capture) -> cut the draws at the screen point out of the frame (or keep the whole scene for an
# environment) -> add; (d) say exactly what's missing and file a request. Every added entry gets a rendered preview
# that is checked (verify_entry) before anything is called extracted.

KINDS = ("character", "vehicle", "object", "environment")
STOP = {"my", "the", "a", "an", "of", "as", "with", "from", "in", "this", "that", "his", "her", "its", "s", "model",
        "character", "play", "into", "collection", "extract"}


def env_root(cfg=None) -> Path:
    """Environments (whole captured scenes minus the HUD) live next to the characters: <cache>/environments/<slug>/."""
    return library_root(cfg).parent / "environments"


def _words(s) -> set:
    return set(re.findall(r"[a-z0-9]+", str(s or "").lower())) - STOP


def _names(e: dict) -> list[str]:
    return [str(x) for x in (e.get("slug"), e.get("name"), e.get("key"), *e.get("aliases", [])) if x not in (None, "")]


def best_match(entries: list[dict], query: str, min_score: float = 0.34) -> dict | None:
    """Exact slug / name / alias, else the best word overlap (Jaccard >= min_score); None when nothing is close
    (unlike find(), which always returns its best guess)."""
    q = query.strip().lower()
    # A canonical identifier must win over another character's shared alias.
    for e in entries:
        if q and q == str(e.get("slug", "")).lower():
            return e
    for e in entries:
        if q and q in [n.lower() for n in _names(e)]:
            return e
    qw, best, score = _words(q), None, 0.0
    for e in entries:
        hw = _words(" ".join(_names(e)).replace("_", " "))
        s = len(qw & hw) / len(qw | hw) if qw and hw else 0.0
        if s > score:
            best, score = e, s
    return best if score >= min_score else None


def _same_game(meta: dict, game: dict | None) -> bool:
    if not game:
        return True
    s = meta.get("source", {})
    norm = lambda t: re.sub(r"\s*\(disc \d+\)", "", (t or "").lower()).strip()   # noqa: E731
    return s.get("game_id") == game.get("game_id") or (bool(s.get("game_title")) and norm(s["game_title"]) == norm(game.get("title")))


def free_slug(root: Path, base: str) -> str:
    base = slugify(base)[:48] or "model"
    slug, n = base, 2
    while (Path(root) / slug).exists():
        slug, n = f"{base}_{n}", n + 1
    return slug


def _brief(meta: dict, env: bool = False) -> dict:
    api = "environments" if env or meta.get("kind") == "environment" else "characters"
    return {k: meta.get(k) for k in ("slug", "name", "aliases", "model", "stats", "notes")} | {
        "kind": meta.get("kind") or ("environment" if env else "character"),
        "source": meta.get("source", {}).get("game_title"), "preview_url": f"/api/{api}/{meta['slug']}/preview",
        "model_url": f"/api/{api}/{meta['slug']}/file/{meta.get('model')}"}


# --- disc access on the control-plane node

def _rom(ctx, game) -> Path:
    from .models import CatalogEntry
    from .tools import rom_path
    p = rom_path(CatalogEntry.model_validate(game), ctx.config)
    if not p.exists():
        raise FileNotFoundError(f"{game['title']}: {p} isn't readable on this node")
    return p


def _gc_iso(ctx, game) -> Path:
    from . import filemods
    rom = _rom(ctx, game)
    if rom.suffix.lower() in (".iso", ".gcm"):
        return rom
    if rom.suffix.lower() != ".gcz":
        raise ValueError(f"{rom.name}: GameCube images are read as ISO/GCM/GCZ (convert RVZ with Dolphin first)")
    base = filemods.base_dir(ctx.config, game["game_id"]) / (rom.stem + ".iso")
    if not base.exists():                                  # one vanilla ISO per game (shared with the swap builder)
        base.parent.mkdir(parents=True, exist_ok=True)
        ctx.progress(5, f"Unpacking {rom.name} (once per game)")
        filemods.gcz_to_iso(rom, base.with_suffix(".part"), lambda p, m: ctx.progress(5 + p * 0.2, m))
        base.with_suffix(".part").replace(base)
    return base


def _dc_gdi(ctx, game) -> Path:
    import subprocess
    rom = _rom(ctx, game)
    if rom.suffix.lower() in (".gdi", ".cdi"):
        return rom
    if rom.is_dir():                                     # an already-extracted disc set
        gdi = next(rom.glob("*.gdi"), None)
        if gdi is None:
            raise ValueError(f"{rom.name}: extracted Dreamcast disc has no .gdi descriptor")
        return gdi
    d = Path(ctx.config.cache) / "dc" / game["game_id"]
    if (d / "disc.gdi").exists():
        return d / "disc.gdi"
    if rom.suffix.lower() == ".7z":                      # archived GDI set: extract once, flatten,
        exe = next((p for n in ("7z", "7zz") if (p := shutil.which(n))), None)
        if exe is None:
            raise ValueError(f"{rom.name}: reading an archived Dreamcast disc needs the 7z CLI on this node")
        tmp = d.with_name(d.name + ".part")              # keep tracks beside disc.gdi (GDRom resolves
        shutil.rmtree(tmp, ignore_errors=True)           # track paths relative to the descriptor)
        tmp.mkdir(parents=True)
        ctx.progress(5, f"Unpacking the GD-ROM archive {rom.name} (7z, once per game)")
        subprocess.run([exe, "x", "-y", f"-o{tmp}", str(rom)], check=True,
                       capture_output=True, timeout=1800)
        for p in [p for p in tmp.rglob("*") if p.is_file() and p.parent != tmp]:
            p.rename(tmp / p.name)
        for sub in sorted((p for p in tmp.rglob("*") if p.is_dir()), reverse=True):
            sub.rmdir()
        gdi = next(tmp.glob("*.gdi"), None)
        if gdi is None:
            shutil.rmtree(tmp, ignore_errors=True)
            raise ValueError(f"{rom.name}: archive contains no .gdi descriptor")
        if gdi.name != "disc.gdi":
            shutil.copyfile(gdi, tmp / "disc.gdi")
        shutil.rmtree(d, ignore_errors=True)
        tmp.rename(d)
        return d / "disc.gdi"
    if rom.suffix.lower() != ".chd" or not shutil.which("chdman"):
        raise ValueError(f"{rom.name}: reading a Dreamcast disc needs a GDI, or a CHD plus chdman on this node")
    tmp = d.with_name(d.name + ".part")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    ctx.progress(5, f"Unpacking the GD-ROM {rom.name} (chdman, once per game)")
    subprocess.run(["chdman", "extractcd", "-f", "-i", str(rom), "-o", str(tmp / "disc.gdi")], check=True,
                   capture_output=True, timeout=1800)
    shutil.rmtree(d, ignore_errors=True)
    tmp.rename(d)
    return d / "disc.gdi"


def _roles_by_name(path: Path, roles: dict[str, list[str]]) -> dict[str, str]:
    """{role: [joint name or name suffix, ...]} -> {role: the first joint of the model that matches}."""
    gl = _load(path)[0]
    names = [gl["nodes"][j].get("name", "") for s in gl.get("skins", []) for j in s["joints"]]
    out = {}
    for role, cands in roles.items():
        hit = next((n for c in cands for n in names if n == c or n.endswith("_" + c)), None)
        if hit:
            out[role] = hit
    return out


# --- dedicated extractors: (roster of what's on the disc, run(ctx, game, entry, work) -> files + provenance)

def _melee_roster():
    from .melee_models import FIGHTERS
    nice = {"CaptainFalcon": "Captain Falcon", "DonkeyKong": "Donkey Kong", "GameAndWatch": "Mr. Game & Watch",
            "DrMario": "Dr. Mario", "YoungLink": "Young Link", "Popo": "Popo (Ice Climbers)", "Nana": "Nana (Ice Climbers)",
            "Mario": "Mario (Melee)", "MasterHand": "Master Hand", "CrazyHand": "Crazy Hand", "GigaBowser": "Giga Bowser",
            "WireframeMale": "Male Fighting Wire Frame", "WireframeFemale": "Female Fighting Wire Frame"}
    more = {"Popo": ["Ice Climbers"], "GameAndWatch": ["Game and Watch"], "Jigglypuff": ["Purin"], "Mario": ["Mario"]}
    return [{"key": k, "slug": f"melee_{k.lower()}", "name": nice.get(k, k), "kind": "character",
             "aliases": [k, f"Melee {nice.get(k, k)}", f"{nice.get(k, k)} (Smash)", *more.get(k, [])]} for k, _ in FIGHTERS]


def _melee_run(ctx, game, e, work):
    from . import melee_models as M
    out = work / f"melee_{e['key']}.gltf"
    M.export_fighter(_gc_iso(ctx, game), e["key"], out)
    code = M.CODE[e["key"]]
    roles = {r: [M.COMMON[c] for c in [cid] + M.ROLE_FALLBACK.get(r, [])] for r, cid in M.ROLE_IDS.items()}
    return {"files": [out], "tool": "gbox.melee_models (export_fighter, default costume Nr)",
            "source_files": [f"Pl{code}Nr.dat", f"Pl{code}.dat", "PlCo.dat"], "roles": _roles_by_name(out, roles)}


SA2_CHARS = [("SONIC", "Sonic", ["Sonic the Hedgehog", "SA2 Sonic"], "character"),
             ("TERIOS", "Shadow", ["Shadow the Hedgehog", "SA2 Shadow"], "character"),
             ("MILES", "Tails", ["Miles Prower", "Miles Tails Prower", "SA2 Tails"], "character"),
             ("KNUCK", "Knuckles", ["Knuckles the Echidna", "SA2 Knuckles"], "character"),
             ("ROUGE", "Rouge", ["Rouge the Bat", "SA2 Rouge"], "character"),
             ("EGG", "Dr. Eggman", ["Eggman", "Robotnik", "Dr. Robotnik", "SA2 Eggman"], "character"),
             ("AMY", "Amy Rose", ["Amy", "SA2 Amy"], "character"),
             ("METALSONIC", "Metal Sonic", [], "character"),
             ("TICAL", "Tikal", ["Tikal the Echidna"], "character"),
             ("CHAOS0", "Chaos 0", ["Chaos"], "character"),
             ("SSONIC", "Super Sonic", [], "character"),
             ("SSHADOW", "Super Shadow", [], "character"),
             ("TWALK", "Cyclone", ["Tails' Cyclone", "Tails mech", "Tails walker"], "vehicle"),
             ("EWALK", "Egg Walker", ["Eggman's mech", "Eggman walker"], "vehicle")]


def _sa2_run(ctx, game, e, work):
    from . import ninja, sa2_chars
    from .gdrom import GDRom
    gdi = str(_dc_gdi(ctx, game))
    mdl = ninja.prs_decompress(GDRom(gdi).read(f"SONIC2/{e['key']}MDL.PRS"))
    table = sa2_chars.mdl_table(mdl)                       # ids differ per character; the full model is the
    tris = {}                                              # biggest of the first few (lower ones are LODs / parts)
    for i in sorted(table)[:4]:
        try:
            tris[i] = sum(len(v) for v in sa2_chars.load_object(mdl, table[i]).tris.values())
        except Exception:                                  # noqa: BLE001
            pass
    glb = sa2_chars.export(gdi, str(work), e["key"], max(tris, key=tris.get))
    out = {"files": [glb, work / "textures", work / "manifest.json"], "tool": "gbox.sa2_chars + gbox.ninja",
           "source_files": [f"SONIC2/{e['key']}MDL.PRS", f"SONIC2/{e['key']}TEX.PRS"]}
    if e.get("kind", "character") == "character":
        try:
            out["roles"] = tree_roles(glb)
        except Exception:                                  # noqa: BLE001 - no humanoid tree (Chao, blobs): no roles
            pass
    return out


def tree_roles(path: Path) -> dict[str, str]:
    """Body roles of a humanoid skeleton from its joint tree + rest positions (+Y up, facing +Z, left = +X), for rigs
    with generic joint names (SA2's node000..): feet = the lowest leaves left/right, pelvis = their common ancestor,
    hands = the outermost leaves outside the pelvis subtree below mid-head height, chest = the parent of the hands'
    common ancestor, head = the first branching joint toward the top of the model; limb joints = the position groups
    along each chain (shoulder / elbow / wrist; hip / knee nearest mid-leg / ankle). Reproduces SA2 Sonic's hand-picked
    roles."""
    gl = _load(path)[0]
    from .re4gc_models import _node_world
    W = _node_world(gl)
    sk = max(gl.get("skins") or [{"joints": []}], key=lambda x: len(x["joints"]))["joints"]
    if len(sk) < 8:
        raise ValueError("no skeleton")
    name = {j: gl["nodes"][j].get("name", f"node{j}") for j in sk}
    pos = {j: np.asarray(W[j])[:3, 3] for j in sk}
    par = {c: i for i, n in enumerate(gl["nodes"]) for c in n.get("children", []) if c in name and i in name}
    kids = {j: [c for c in gl["nodes"][j].get("children", []) if c in name] for j in sk}

    def anc(j):
        out = [j]
        while out[-1] in par:
            out.append(par[out[-1]])
        return out

    def lca(a, b):
        A = anc(a)
        return next(x for x in anc(b) if x in A)

    P = np.array([pos[j] for j in sk])
    H = float(np.ptp(P[:, 1]))
    y0, ytop = float(P[:, 1].min()), float(P[:, 1].max())

    def groups(chain):
        G = []
        for j in chain:
            if G and np.linalg.norm(pos[j] - pos[G[-1][-1]]) < 0.02 * H:
                G[-1].append(j)
            else:
                G.append([j])
        return G

    def path(a, leaf):                                     # joints below a, toward leaf
        A = list(reversed(anc(leaf)))
        return A[A.index(a) + 1:]
    leaves = [j for j in sk if not kids[j]]
    lf = min([j for j in leaves if pos[j][0] > 0.02 * H], key=lambda j: pos[j][1])
    rf = min([j for j in leaves if pos[j][0] < -0.02 * H], key=lambda j: pos[j][1])
    pelvis = lca(lf, rf)
    upper = [j for j in leaves if pelvis not in anc(j) and pos[j][1] < pos[pelvis][1] + 0.5 * (ytop - pos[pelvis][1])]
    lh, rh = max(upper, key=lambda j: pos[j][0]), min(upper, key=lambda j: pos[j][0])
    sh = lca(lh, rh)
    hip = lca(sh, pelvis)
    chest = par[sh] if sh in par and pos[par[sh]][1] > pos[hip][1] else sh
    top = max(sk, key=lambda j: (round(pos[j][1] / H, 2), -sk.index(j)))
    hd = path(sh, top)[0] if sh in anc(top) and sh != top else top
    while len(kids[hd]) == 1:
        hd = kids[hd][0]
    roles = {"hip": name[hip], "chest": name[chest], "head": name[hd]}
    for side, hand, foot in (("l", lh, lf), ("r", rh, rf)):
        G = groups(path(sh, hand))
        roles[f"{side}_upper"] = name[G[0][-1]]
        if len(G) > 2:
            roles[f"{side}_fore"], roles[f"{side}_hand"] = name[G[1][0]], name[G[2][0]]
        G = groups(path(pelvis, foot))
        hy = pos[G[0][0]][1]
        roles[f"{side}_thigh"] = name[G[0][-1]]
        fg = [g for g in G[1:] if pos[g[0]][1] - y0 > 0.15 * (hy - y0)]
        if fg:
            ft = fg[-1]
            roles[f"{side}_foot"] = name[ft[-1]]
            ay = pos[ft[0]][1]
            mid = [g for g in G[1:] if g is not ft and pos[g[0]][1] > ay]
            if mid:
                roles[f"{side}_shin"] = name[min(mid, key=lambda g: abs(pos[g[0]][1] - (hy + ay) / 2))[0]]
    return roles


FF7_CHARS = [("CLOUD", "Cloud Strife (battle)", ["FF7 Cloud battle"]), ("HICLOUD", "Cloud Strife", ["Cloud", "FF7 Cloud"]),
             ("TIFA", "Tifa Lockhart", ["Tifa"]), ("BARRETT", "Barret Wallace", ["Barret", "Barrett"]),
             ("EARITH", "Aerith Gainsborough", ["Aerith", "Aeris"]), ("RED13", "Red XIII", ["Nanaki", "Red 13"]),
             ("CID", "Cid Highwind", ["Cid"]), ("YUFI", "Yuffie Kisaragi", ["Yuffie"]), ("VINSENT", "Vincent Valentine", ["Vincent"]),
             ("KETCY", "Cait Sith", []), ("SEFIROS", "Sephiroth", []), ("GALL", "Galian Beast", []),
             ("HELLMASK", "Hellmasker", []), ("DEATHGIG", "Death Gigas", []), ("CHAOS", "Chaos (Vincent)", [])]


def _ff7_field_roster():
    from .ff7_models import FIELD_BCX
    return [{"key": f"FIELD:{k}", "slug": f"ff7_{k.lower()}_field", "name": n, "kind": "character",
             "aliases": [n.replace(" (field)", " field"), "FF7 " + n]} for k, n in FIELD_BCX.items()]


def _ff7_run(ctx, game, e, work):
    from . import ff7_models as F
    if e["key"].startswith("FIELD:"):                      # field model (FIELD/<NAME>.BCX), body roles from its topology
        from .ff7_swap import field_target
        nm = e["key"][6:]
        fm = F.field_from_disc(_rom(ctx, game), nm)
        out = work / f"ff7_{nm.lower()}_field.gltf"
        F.field_to_gltf(fm, out)
        try:
            roles = {r: f"j{b:02d}" for r, b in field_target(fm)["jmap"].items()}
        except ValueError:
            roles = None
        return {"files": [out], "tool": "gbox.ff7_models (field model, read_field_model)", "source_files": [f"FIELD/{nm}.BCX"],
                "roles": roles, "notes": "FF7 field model (bind pose = frame 0 of its standing animation); Gouraud colours, "
                                         "the few textured face polygons drawn in their vertex colours"}
    model = F.from_disc(_rom(ctx, game), f"ENEMY6/{e['key']}.LZS")
    out = work / f"ff7_{e['key'].lower()}.gltf"
    names = {i: f"j{i:02d}" for i in range(len(model["bones"]))}
    try:
        F.to_gltf(model, out, anim=0, names=names)
    except Exception:                                      # some models have no usable animation 0: bind pose only
        F.to_gltf(model, out, anim=0, names=names, animate=False)
    return {"files": [out], "tool": "gbox.ff7_models (battle model)", "source_files": [f"ENEMY6/{e['key']}.LZS"],
            "notes": "FF7 battle model (bind pose = frame 0 of animation 0); no body roles yet (rig.roles) for swaps"}


AYA_ROLES = {"hip": "j00", "head": "j10", "l_clav": "j03", "l_upper": "j04", "l_fore": "j05", "l_hand": "j06",
             "r_clav": "j13", "r_upper": "j14", "r_fore": "j15", "r_hand": "j16", "l_thigh": "j22", "l_shin": "j23",
             "l_foot": "j24", "r_thigh": "j26", "r_shin": "j27", "r_foot": "j28"}


def _pe_roster():
    from .parasite_eve import AYA_OUTFITS_NAMES
    return [{"key": i, "slug": "aya" if n == "jacket_jeans" else f"aya_{n}", "name": f"Aya Brea ({n.replace('_', ' ')})",
             "kind": "character", "aliases": [f"Aya {n.replace('_', ' ')}"] + (["Aya", "Aya Brea"] if n == "jacket_jeans" else [])}
            for i, n in enumerate(AYA_OUTFITS_NAMES)]


def _pe_run(ctx, game, e, work):
    from . import parasite_eve as PE
    from .pe_swap import OUTFIT_BONES, aya_target
    out = work / f"aya_{PE.AYA_OUTFITS_NAMES[e['key']]}.glb"
    pe = PE.PEData(_rom(ctx, game))
    PE.export_aya(pe, out, e["key"])
    # every outfit has its own bone layout: roles from gbox.pe_swap's per-outfit map (left/right from the geometry)
    t = aya_target(pe, e["key"])
    ob = OUTFIT_BONES[e["key"]]
    roles = {r: f"j{b:02d}" for r, b in t["jmap"].items()} | {"neck": f"j{ob['neck']:02d}"}
    for side in ("l", "r"):
        arm = next(a for a in (ob["armA"], ob["armB"]) if a[1] == t["jmap"][f"{side}_upper"])
        roles[f"{side}_clav"] = f"j{arm[0]:02d}"
    return {"files": [out], "tool": "gbox.parasite_eve (export_aya)", "source_files": ["PE.IMG (Aya common blobs)", "SLUS_006.62"],
            "roles": roles}


def _pso_roster():
    from . import pso_enemy
    from .pso_player import CLASSES
    return [{"key": "ABCDEFGHI"[i], "slug": "hucast" if c == "HUcast" else f"pso_{c.lower()}", "name": c, "kind": "character",
             "aliases": [f"PSO {c}", f"Phantasy Star Online {c}"]} for i, c in enumerate(CLASSES)] + pso_enemy.roster_entries()


def _pso_run(ctx, game, e, work):
    from . import pso_enemy, pso_player
    if e.get("kind") == "enemy":                               # an enemy body (slot enemy:<name>) off its pack
        key = e["key"].split(":", 1)[1]
        glb = pso_enemy.export(str(_dc_gdi(ctx, game)), str(work), key)
        return {"files": [glb, work / "textures", work / "manifest.json"], "tool": "gbox.pso_enemy",
                "source_files": [f"{e['file']}:{e['entry']}"], "roles": pso_enemy.export_roles(key),
                "notes": "an enemy body on its own node tree; the game's motions (.njm in the same pack) aren't exported"}
    from .gdrom import GDRom
    gdi = _dc_gdi(ctx, game)
    glb = pso_player.export(str(gdi), str(work), e["key"])
    k = e["key"]
    # every class body is the same 64-node tree: the role map, checked against this class's own PL<x>BDY00.NJ (#1485)
    roles = pso_player.joint_roles(pso_player.body_roles(GDRom(str(gdi)).read(f"PSO/PL{k}BDY00.NJ"), k))
    return {"files": [glb, work / "textures", work / "manifest.json"], "tool": "gbox.pso_player (head 0, colour 0)",
            "source_files": [f"PSO/PL{k}BDY00.NJ", f"PSO/PL{k}HED00.NJ", f"PSO/PL{k}TEX.AFS"], "roles": roles,
            "notes": "" if k == "C" else "this class's texture layout isn't mapped yet (gbox.pso_player): colours may be wrong"}


def _shenmue_run(ctx, game, e, work):
    from . import shenmue_mt5
    glb = shenmue_mt5.export(str(_dc_gdi(ctx, game)), str(work))
    return {"files": [glb, work / "textures", work / "manifest.json"], "tool": "gbox.shenmue_mt5",
            "source_files": ["MISC/COLDINIT.PKS", "MISC/COLDINIT.PKF (YKB_M.CHRM)"]}


SM64_MARIO_CHAINS = [("hip", "chest", "head"), ("chest", "l_upper", "l_fore", "l_hand"),
                     ("chest", "r_upper", "r_fore", "r_hand"), ("hip", "l_thigh", "l_shin", "l_foot"),
                     ("hip", "r_thigh", "r_shin", "r_foot")]


def sm64_mario_roles(path: Path) -> dict[str, str]:
    """Body roles of gbox.sm64_mario's glTF. Its joints j00..j19 are Mario's geo-layout animated parts in the order
    gbox.sm64_swap.MARIO indexes (and the writer keeps), so the roles are {role: f"j{index:02d}"}. A model whose joint
    names, tree (each limb a parent chain below the torso) or frame (+Y up, Mario's left +X, face toward +Z) differ is
    refused instead of being mapped by position."""
    from .sm64_swap import MARIO
    gl, _acc, _img, Wn = _load(path)
    sk = max(gl.get("skins") or [{"joints": []}], key=lambda s: len(s["joints"]))["joints"]
    names = [gl["nodes"][j].get("name", f"node{j}") for j in sk]
    if names != [f"j{k:02d}" for k in range(20)]:
        raise ValueError(f"{Path(path).name}: not gbox.sm64_mario's 20-joint skeleton ({len(sk)} joints)")
    roles = validate_rig_roles(Path(path), {r: f"j{k:02d}" for r, k in MARIO.items()})
    node = {r: sk[names.index(n)] for r, n in roles.items()}
    par = {c: i for i, nd in enumerate(gl["nodes"]) for c in nd.get("children", [])}

    def below(a, b):                                       # is role b's joint a descendant of role a's?
        k = par.get(node[b])
        while k is not None and k != node[a]:
            k = par.get(k)
        return k == node[a]
    bad = [f"{b} under {a}" for ch in SM64_MARIO_CHAINS for a, b in zip(ch, ch[1:]) if not below(a, b)]
    p = {r: np.asarray(Wn[j])[:3, 3] for r, j in node.items()}
    if not p["head"][1] > p["chest"][1] > p["hip"][1] > max(p["l_foot"][1], p["r_foot"][1]):
        bad.append("+Y up (head > chest > hip > feet)")
    bad += [f"left +X ({s})" for s in ("upper", "fore", "hand", "thigh", "shin", "foot")
            if not p["l_" + s][0] > 0 > p["r_" + s][0]]
    if not p["head"][2] > p["chest"][2]:
        bad.append("face toward +Z")
    if bad:
        raise ValueError(f"{Path(path).name}: Mario's joint layout differs: " + ", ".join(bad))
    return roles


def _sm64_run(ctx, game, e, work):
    from . import sm64_mario as S, n64_rom
    data = n64_rom.read(_rom(ctx, game))
    out = work / "sm64_mario.gltf"
    S.to_gltf(S.extract(data, anim=197), out)
    return {"files": [out], "tool": "gbox.sm64_mario", "source_files": ["ROM segment 04 + geo 0x17002DD4 (anim 197 pose)"],
            "roles": sm64_mario_roles(out)}


def _doa2_roster():
    from . import doa2_chars
    return doa2_chars.roster()


def _doa2_run(ctx, game, e, work):
    from . import doa2_chars
    cache = Path(ctx.config.data_dir) / 'analysis' / 'doa2' / game['game_id'] / 'native-cloth-cache'
    r = doa2_chars.export(str(_dc_gdi(ctx, game)), str(work), e["key"], (e.get("costumes") or ["0"])[0],
                         native_cache=cache if (cache / 'verification.json').is_file() else None)
    m = r["manifest"]
    return {"files": [work / f for f in r["files"]], "tool": "gbox.doa2_chars native NaomiLib decoder",
            "source_files": m["source"]["resource_ids"], "roles": r.get("roles", {}),
            "extra": {"native_source_assembly": r["assembly"]},
            "notes": f"{m['container_facts']['n_models']} native mesh parts and "
                     f"{m['container_facts']['n_textures']} textures decoded. Assembly: {r['assembly']}. "
                     "Complete source includes native accessory, chain and cloth draws when its verified cache is available. "
                     "SUP source skin approximates curved deformation; motion and procedural limits are in core-report.json."}


def _doa2_needs_refresh(ctx, game, meta):
    """Upgrade a cached body-only extraction when the complete native cache exists."""
    from . import doa2_chars
    if not game or game.get('game_id') not in doa2_chars.GAME_IDS:
        return False
    if 'gbox.doa2_chars' not in meta.get('extraction_tool', ''):
        return False
    cache = Path(ctx.config.data_dir) / 'analysis' / 'doa2' / game['game_id'] / 'native-cloth-cache'
    return (meta.get('native_source_assembly') != 'complete_native_source'
            and (cache / 'verification.json').is_file())


def _re4_run(ctx, game, e, work):
    out = export_leon(_gc_iso(ctx, game), work)
    return {"files": [out], "tool": "gbox.re4gc_models (characters.export_leon)", "source_files": ["em/pl00.drs (BINs 0, 2, 4, 5, 6, 7)"],
            "roles": _roles_by_name(out, {k: [v] for k, v in LEON_ROLES.items()})}


def _lcs():
    from . import gta_stories_models
    return gta_stories_models


def _one(key, slug, name, aliases):
    return lambda: [{"key": key, "slug": slug, "name": name, "aliases": aliases, "kind": "character"}]


def _oot_run(ctx, game, entry, work):
    from . import oot_swap
    rom, _ = oot_swap.rom_of(ctx.config, game)
    target = oot_swap.resolve(ctx, rom, None, entry['key'])
    result = oot_swap.extract_target(rom, target, Path(work) / (entry['slug'] + '.gltf'), entry['name'])
    return {'files': [result['path']], 'roles': result['roles'], 'tool': 'gbox.oot_swap',
            'source_files': [entry['key']], 'notes': 'Native Link skeleton, display lists and textures.'}


# Snake's 16 KMD objects (= motion bones) by body role. The MetalMintSolid glTF keeps KMD object i as node i but
# names the nodes in its own order (object 2 = "bone_4"), so roles are resolved to node names per decode.
MGS_VR_SNAKE_OBJECTS = {"hip": 0, "chest": 1, "neck": 5, "head": 6,
                        "r_upper": 2, "r_fore": 3, "r_hand": 4, "l_upper": 7, "l_fore": 8, "l_hand": 9,
                        "r_thigh": 10, "r_shin": 11, "r_foot": 12, "l_thigh": 13, "l_shin": 14, "l_foot": 15}
MGS_VR_SNAKE_PARENTS = [-1, 0, 1, 2, 3, 1, 5, 1, 7, 8, 0, 10, 11, 0, 13, 14]   # KMD object parent indices


def mgs_vr_snake_roles(path: Path) -> dict[str, str]:
    """Body roles {role: joint name} of the decoded VR Missions Snake. tree_roles can't read this rig (the legs and the
    spine both hang off the root, arms hang down), so the fixed KMD object map is used, after checking that the
    decoded glTF really is Snake's tree (same parents) in the library frame (+Y up, left = +X, toes toward +Z)."""
    gl = _load(path)[0]
    from .re4gc_models import _node_world
    nodes, n = gl["nodes"], len(MGS_VR_SNAKE_PARENTS)
    joints = set(max(gl.get("skins") or [{"joints": []}], key=lambda s: len(s["joints"]))["joints"])
    if len(nodes) < n or not set(range(n)) <= joints:
        raise ValueError(f"not the 16-object VR Missions Snake rig ({len(joints)} joints)")
    par = {c: i for i, nd in enumerate(nodes) for c in nd.get("children", [])}
    got = [par.get(i, -1) if par.get(i, -1) < n else -1 for i in range(n)]
    if got != MGS_VR_SNAKE_PARENTS:
        raise ValueError(f"joint tree {got} is not Snake's KMD tree {MGS_VR_SNAKE_PARENTS}")
    W = _node_world(gl)
    pos = {r: np.asarray(W[i])[:3, 3] for r, i in MGS_VR_SNAKE_OBJECTS.items()}
    for limb in ("upper", "fore", "hand", "thigh", "shin", "foot"):
        if not pos[f"l_{limb}"][0] > 0 > pos[f"r_{limb}"][0]:
            raise ValueError(f"{limb}: left/right are mirrored (left must be +X)")
    ys = [p[1] for p in pos.values()]
    if not (pos["head"][1] == max(ys) and min(pos["l_foot"][1], pos["r_foot"][1]) == min(ys)
            and pos["chest"][1] <= pos["neck"][1] < pos["head"][1]):
        raise ValueError("rig is not upright (+Y up, head highest, feet lowest)")
    names = [nodes[i].get("name", f"node{i}") for i in range(n)]
    roles = {r: names[i] for r, i in MGS_VR_SNAKE_OBJECTS.items()}
    rig = rig_from_gltf(path, roles)
    for side in "lr":                                      # toes point forward: the foot mesh lies toward +Z
        j = rig["roles"][f"{side}_foot"]
        foot = np.concatenate([p["pos"][p["owner"] == j] for p in rig["prims"]])
        if not len(foot) or foot[:, 2].mean() <= rig["joints"][j][2]:
            raise ValueError("rig does not face +Z (the toes point backward)")
    return roles


def _mgs_vr_run(ctx, game, entry, work):
    """Decode the original Snake from the owned US disc, using a Windows worker for MetalMintSolid."""
    from . import mgs_vr_swap
    out = Path(work) / 'mgs_vr_snake.glb'
    if HOST_OS == 'windows':
        mgs_vr_swap.decode_original_player(ctx.config, out, ctx.progress)
    else:
        workers = [w for w in _api(ctx, 'GET', '/api/workers')
                   if w.get('os') == 'windows' and w.get('online') and 'characters' in (w.get('tools') or [])]
        workers.sort(key=lambda w: len(w.get('tools') or []), reverse=True)
        failures = []
        for worker in workers:
            job = _job(ctx, 'characters', {'op': 'mgs_vr_decode', 'game_id': game['game_id']}, worker['id'], 900)
            if job.get('state') != 'succeeded':
                failures.append(f"{worker.get('name')}: {job.get('error') or job.get('state')}")
                continue
            receipt = _api(ctx, 'GET', f"/api/receipts/{job['receipt_id']}")
            model = next((a for a in receipt.get('artifacts', []) if a.get('name') == 'mgs-vr-snake.glb'), None)
            if model:
                out.write_bytes(_api(ctx, 'GET', f"/api/artifacts/{model['sha256']}", timeout=300))
                break
            failures.append(f"{worker.get('name')}: decoded model artifact was absent")
        if not out.is_file():
            raise RuntimeError('No Windows worker could decode the VR Missions Snake model: ' + '; '.join(failures))
    return {'files': [out], 'roles': mgs_vr_snake_roles(out), 'tool': 'gbox.mgs_vr_swap / MetalMintSolid',
            'source_files': ['MGS/STAGE.DIR', 'init.stg', '0_0.dar:39213.kmd', '1_0.dar:PS1 textures'],
            'notes': 'Original US VR Missions Snake mesh, 16 KMD joints and embedded PS1 textures. Body roles from '
                     'the fixed KMD object map (characters.MGS_VR_SNAKE_OBJECTS), checked against the decoded tree.'}


# (name, does this extractor read the game? (title lower, platform), roster(), run)
DEDICATED = [
    ("mvc2", lambda t, p: "marvel vs. capcom 2" in t and p == "dreamcast",
     lambda: __import__("gbox.mvc2_chars", fromlist=["x"]).roster(),
     lambda ctx, game, e, work: __import__("gbox.mvc2_chars", fromlist=["x"]).extract_run(ctx, game, e, work)),
    ("mgs_vr", lambda t, p: 'metal gear solid' in t and 'vr missions' in t and p == 'psx',
     _one('SNAKE', 'mgs_vr_snake', 'Solid Snake (VR Missions)', ['Snake', 'MGS VR Snake']), _mgs_vr_run),
    ('oot', lambda t, p: 'ocarina of time' in t and p == 'n64',
     lambda: [{'key': f'{age} link', 'slug': f'oot_link_{age}', 'name': label,
               'aliases': [f'{age} link'], 'kind': 'character'}
              for age, label in [('adult', 'Link (adult, OoT)'), ('child', 'Young Link (OoT)')]], _oot_run),
    ("melee", lambda t, p: "smash bros" in t and "melee" in t, _melee_roster, _melee_run),
    ("sa2", lambda t, p: "sonic adventure 2" in t and p == "dreamcast",
     lambda: [{"key": k, "slug": "sonic" if k == "SONIC" else f"sa2_{slugify(n)}", "name": n, "aliases": a, "kind": kd}
              for k, n, a, kd in SA2_CHARS], _sa2_run),
    ("ff7", lambda t, p: re.search(r"final fantasy vii\b", t) is not None and p == "psx",
     lambda: [{"key": k, "slug": "cloud" if k == "HICLOUD" else f"ff7_{k.lower()}", "name": n, "aliases": a, "kind": "character"}
              for k, n, a in FF7_CHARS] + _ff7_field_roster(), _ff7_run),
    ("parasite_eve", lambda t, p: re.match(r"parasite eve(?! ii)", t) is not None and p == "psx", _pe_roster, _pe_run),
    # Parasite Eve II (both discs): Aya's five field outfits, STAGE0.CDF class-1 files (gbox.pe2_inventory / pe2_models)
    ("pe2", lambda t, p: re.match(r"parasite eve ii\b", t) is not None and p == "psx",
     lambda: __import__("gbox.pe2_models", fromlist=["x"]).roster(),
     lambda ctx, game, e, work: __import__("gbox.pe2_models", fromlist=["x"]).extract_run(ctx, game, e, work)),
    ("pso", lambda t, p: "phantasy star online ver. 2" in t and p == "dreamcast", _pso_roster, _pso_run),
    ("jgr", lambda t, p: ("jet grind radio" in t or "jet set radio" in t) and "future" not in t and p == "dreamcast",
     lambda: __import__("gbox.jgr", fromlist=["x"]).roster(),
     lambda ctx, game, e, work: __import__("gbox.jgr", fromlist=["x"]).extract_run(ctx, game, e, work)),
    ("doa2", lambda t, p: "dead or alive 2" in t and p == "dreamcast", _doa2_roster, _doa2_run),
    ("shenmue", lambda t, p: re.match(r"shenmue(?! ii)", t) is not None and p == "dreamcast",
     _one("YKB", "ryo", "Ryo Hazuki", ["Ryo", "Shenmue Ryo"]), _shenmue_run),
    ("sm64", lambda t, p: "super mario 64" in t and p == "n64",
     _one("MARIO", "mario", "Mario", ["SM64 Mario", "Super Mario 64 Mario"]), _sm64_run),
    ("tetris_ds", lambda t, p: t.startswith("tetris ds") and p == "nds",
     lambda: __import__("gbox.tetris_ds", fromlist=["x"]).roster(),
     lambda ctx, game, e, work: __import__("gbox.tetris_ds", fromlist=["x"]).extract_run(ctx, game, e, work)),
    ("re4gc", lambda t, p: "resident evil 4" in t and p == "gamecube",
     _one("LEON", "leon", "Leon S. Kennedy", ["Leon", "Leon Kennedy", "RE4 Leon"]), _re4_run),
    ("crazy_taxi", lambda t, p: "crazy taxi" in t and p == "gamecube",
     lambda: __import__("gbox.crazy_taxi", fromlist=["x"]).roster(),
     lambda ctx, game, e, work: __import__("gbox.crazy_taxi", fromlist=["x"]).extract_run(ctx, game, e, work)),
    ("gta3", lambda t, p: ("grand theft auto iii" in t or t.startswith("gta iii") or t == "gta 3") and p == "ps2",
     lambda: __import__("gbox.gta3_models", fromlist=["x"]).roster(),
     lambda ctx, game, e, work: __import__("gbox.gta3_models", fromlist=["x"]).extract_run(ctx, game, e, work)),
    ("gta_lcs", lambda t, p: "liberty city stories" in t and p == "ps2", lambda: _lcs().roster(),
     lambda ctx, game, e, work: _lcs().extract_run(ctx, game, e, work)),
    # GTA Vice City, classic RenderWare PC port (models/gta3.img): Tommy + peds. The owned windows_native entries
    # (5eacc9f11d9a5956, 1fd42f50b10252e6) are HyperSpin launchers; gta_vc_models.locate_install tells the classic
    # port from the UE4 Definitive Edition (no gta3.img) and from the PS2 .chd the first entry points at.
    ("gta_vc_pc", lambda t, p: "vice city" in t and "stories" not in t and p == "windows_native",
     lambda: __import__("gbox.gta_vc_models", fromlist=["x"]).roster(),
     lambda ctx, game, e, work: __import__("gbox.gta_vc_models", fromlist=["x"]).extract_run(ctx, game, e, work)),
    # RE4 (2023, Steam): the Windows PC unpacks the paks + converts in Blender (gbox/re4r.py), the result lands here
    ("re4r", lambda t, p: "resident evil 4" in t and p == "pc_steam", lambda: __import__("gbox.re4r", fromlist=["x"]).roster(),
     lambda ctx, game, e, work: __import__("gbox.re4r", fromlist=["x"]).extract_run(ctx, game, e, work)),
    ("nomercy", lambda t, p: "no mercy" in t and p == "n64", lambda: __import__("gbox.aki_wrestling", fromlist=["x"]).roster_entries(),
     lambda ctx, game, e, work: __import__("gbox.aki_wrestling", fromlist=["x"]).extract_run(ctx, game, e, work)),
    ("smackdown2", lambda t, p: "smackdown! 2" in t and p == "psx", lambda: __import__("gbox.yukes_sd", fromlist=["x"]).roster_entries(),
     lambda ctx, game, e, work: __import__("gbox.yukes_sd", fromlist=["x"]).extract_run(ctx, game, e, work)),
    ("worldtour", lambda t, p: "world tour" in t and "wcw" in t and p == "n64", lambda: __import__("gbox.aki_wcw", fromlist=["x"]).roster_entries(),
     lambda ctx, game, e, work: __import__("gbox.aki_wcw", fromlist=["x"]).extract_run(ctx, game, e, work)),
    ("revenge", lambda t, p: "revenge" in t and "wcw" in t and p == "n64",
     lambda: __import__("gbox.aki_wcw", fromlist=["x"]).revenge_roster(),
     lambda ctx, game, e, work: __import__("gbox.aki_wcw", fromlist=["x"]).extract_run(ctx, game, e, work)),
    # Clay Fighter: Sculptor's Cut (N64): the 16 fighters' sprite frames as sprites entries; slots fighter:<name>
    ("clayfighter", lambda t, p: ("clay fighter" in t or "clayfighter" in t) and "sculptor" in t and p == "n64",
     lambda: __import__("gbox.clayfighter_swap", fromlist=["x"]).roster_entries(),
     lambda ctx, game, e, work: __import__("gbox.clayfighter_swap", fromlist=["x"]).extract_run(ctx, game, e, work)),
    ("metal_arms", lambda t, p: "metal arms" in t and p == "gamecube", lambda: __import__("gbox.metal_arms", fromlist=["x"]).roster(),
     lambda ctx, game, e, work: __import__("gbox.metal_arms", fromlist=["x"]).extract_run(ctx, game, e, work)),
    # Def Jam: Vendetta (GDTE69 rev 0): static model-space meshes from data/sNNNx/*.gpl; rig not decoded yet
    ("defjam_vendetta", lambda t, p: "def jam" in t and "vendetta" in t and p == "gamecube",
     lambda: __import__("gbox.defjam_vendetta", fromlist=["x"]).roster(),
     lambda ctx, game, e, work: __import__("gbox.defjam_vendetta", fromlist=["x"]).extract_run(ctx, game, e, work)),
    # Def Jam: Vendetta PS2 (SLUS_206.39 v1.00): the 58 data.bin WRS wrestlers, BODY + FACE + hands on one rigged
    # skeleton with body roles and the fighter's texture page (#1305; formats in docs/defjam_pipeline.md)
    ("defjam_vendetta_ps2", lambda t, p: "def jam" in t and "vendetta" in t and p == "ps2",
     lambda: __import__("gbox.defjam_models", fromlist=["x"]).roster(),
     lambda ctx, game, e, work: __import__("gbox.defjam_models", fromlist=["x"]).extract_run(ctx, game, e, work)),
    # Dead Or Alive ++ (arcade, Tecmo TPS; MAME doapp / doappk): 11 fighters x 4 costumes, rigged with the game's own
    # stance-frame bone matrices (motion player + skeleton build run on the decoded program; #1340,
    # docs/doapp_pipeline.md). Needs doapp.zip + coh1002m.zip beside the catalog's zip.
    ("doapp", lambda t, p: t.startswith("dead or alive ++") and p == "arcade",
     lambda: __import__("gbox.doapp_chars", fromlist=["x"]).roster(),
     lambda ctx, game, e, work: __import__("gbox.doapp_chars", fromlist=["x"]).extract_run(ctx, game, e, work)),
]


def dedicated_entries(config, game, name, roster):
    """WCW's ROM tables include hidden wrestlers and differ between titles."""
    if name in ("worldtour", "revenge"):
        from . import aki_wcw, aki_wrestling
        from .models import CatalogEntry
        from .tools import rom_path
        rom = aki_wrestling.rom_bytes(rom_path(CatalogEntry.model_validate(game), config))
        prefix = "wt" if name == "worldtour" else "rv"
        return [{"key": f"{w['group']}-{w['member']}",
                 "slug": ("wt_" + slugify(w['name']).replace('-', '_')) if name == 'worldtour' and
                         (f"{w['group']}-{w['member']}", w['name']) in aki_wcw.WT_NAMES
                         else f"{prefix}_{w['group']}_{w['member']}_{slugify(w['name'])}",
                 "name": w['name'], "aliases": [f"{game['title']} {w['name']}", f"{w['group']}-{w['member']}"],
                 "kind": "character"} for w in aki_wcw.roster(rom)]
    root = library_root(config)
    entries = []
    for entry in roster():
        entry = dict(entry)
        if (root / entry['slug'] / 'meta.json').is_file() and not _same_game(get(root, entry['slug']), game):
            entry['slug'] += '_' + game['game_id']
        entries.append(entry)
    return entries


# extractor -> body roles read from an entry's stored model, for entries collected before the reader reported roles
ROLE_BACKFILL = {"sm64": sm64_mario_roles,
                 "pso": lambda path: __import__("gbox.pso_player", fromlist=["x"]).model_roles(path)}


def backfill_roles(root: Path, extractor: str, meta: dict) -> dict:
    """A verified entry collected before its reader reported body roles (rig.roles) gets them from its own model file,
    so collect() can call it retargetable without re-extracting. A model the role reader refuses stays unmapped."""
    rig = dict(meta.get("rig") or {})
    fn = ROLE_BACKFILL.get(extractor)
    if fn is None or rig.get("roles"):
        return meta
    try:
        roles = fn(Path(root) / meta["slug"] / meta["model"])
    except (OSError, KeyError, IndexError, ValueError):
        return meta
    if not roles:
        return meta
    return put_meta(root, {**meta, "rig": {**rig, "roles": roles}})


def collect(ctx, inp):
    """Collect a supported disc roster without vision/LLM calls or gameplay interruption."""
    game, root = _game(ctx, inp), library_root(ctx.config)
    title, platform = game['title'].lower(), game['platform']
    reader = next((r for r in DEDICATED if r[1](title, platform)), None)
    if reader is None:
        return {"status": "unsupported", "game_id": game['game_id'],
                "message": "No native model reader for this game; no unrigged capture was substituted."}
    name, _, roster, _ = reader
    # Characters always; other kinds only when the reader opts a fully assembled entry in (`collect`: True), e.g. the
    # posed cab the operator drives in Crazy Taxi (#1369). Those need a verified model, not a mapped rig.
    entries = [e for e in dedicated_entries(ctx.config, game, name, roster)
               if e.get('kind', 'character') == 'character' or e.get('collect') is True]
    results = []
    for i, e in enumerate(entries):
        total = max(1, len(entries))
        ctx.progress(100 * i / total, f"Collecting {e['name']} ({i + 1}/{total})")
        # Native extractors report progress for one character. Scale that into
        # this roster's range so a long collection does not appear stuck at 85%.
        class EntryContext:
            def __getattr__(self, key):
                return getattr(ctx, key)

            def progress(self, pct, message):
                overall = None if pct is None else 100 * (i + max(0, min(100, pct)) / 100) / total
                ctx.progress(overall, f"{e['name']} ({i + 1}/{total}): {message}")

        try:
            res = extract_dedicated(EntryContext(), game, e['slug'], root, (name, entries))
            meta = get(root, res['entry']['slug'])
            checked = verify_entry(root, meta)
            roles = (meta.get('rig') or {}).get('roles') or {}
            ready = checked['ok'] and bool(roles)
            kind = meta.get('kind', e.get('kind', 'character'))
            done = ready or (kind != 'character' and checked['ok'])
            results.append({'slug': meta['slug'], 'name': meta['name'], 'kind': kind, 'status': res['status'],
                            'verified': checked['ok'], 'retargetable': ready,
                            'message': '' if done else ('Model needs verification.' if kind != 'character' else
                                                        'Model or mapped rig needs verification before retargeting.')})
        except Exception as exc:
            results.append({'slug': e['slug'], 'name': e['name'], 'kind': e.get('kind', 'character'),
                            'status': 'failed', 'verified': False, 'retargetable': False, 'error': str(exc)})
    chars = [r for r in results if r['kind'] == 'character']
    noun = 'characters' if len(chars) == len(entries) else 'models'
    ctx.progress(100, f"Collected {len(entries)} {noun} from {game['title']}")
    from . import char_coverage
    return collection_status(results) | {
        'game_id': game['game_id'], 'extractor': name,
        # the slots this game's writer can put a collection character into (the cast menu: player, enemy:<name>...)
        'slots': char_coverage.cast_slots(game)}


def collection_status(results: list[dict]) -> dict:
    """A roster's collection summary from its entry rows: complete when every entry is verified and every character
    (kind 'character'; props, vehicles and sprite sets don't need a rig) is retargetable (verified + body roles)."""
    chars = [r for r in results if r.get('kind', 'character') == 'character']
    good = sum(bool(r.get('verified')) for r in results)
    mapped = sum(bool(r.get('retargetable')) for r in chars)
    return {'status': 'complete' if results and good == len(results) and mapped == len(chars) else 'partial',
            'collected': good, 'total': len(results), 'retargetable': mapped, 'characters': len(chars),
            'entries': results}


def refresh_collection(root: Path, result: dict) -> dict:
    """A stored partial collect() result re-checked against the collection as it is now: entries whose model was
    verified but lacked body roles get them from the extractor's role backfill (backfill_roles: e.g. PSO classes
    collected before extraction reported roles, #1485), so a fixed reader turns the status complete without
    re-extracting or re-queueing the roster. Failed / missing entries stay as they were."""
    if not result or result.get('status') != 'partial' or not result.get('entries'):
        return result
    rows = []
    for r in result['entries']:
        r = dict(r)
        p = Path(root) / str(r.get('slug') or '') / 'meta.json'
        if r.get('slug') and r.get('status') != 'failed' and p.is_file():
            try:
                meta = backfill_roles(root, result.get('extractor') or '', get(root, r['slug']))
                checked = verify_entry(root, meta)
            except (OSError, KeyError, ValueError):
                rows.append(r)
                continue
            kind = meta.get('kind') or r.get('kind') or 'character'
            ready = checked['ok'] and bool((meta.get('rig') or {}).get('roles'))
            r.update(kind=kind, verified=checked['ok'], retargetable=ready)
            if ready or (kind != 'character' and checked['ok']):
                r['message'] = ''
        rows.append(r)
    return result | collection_status(rows)


def extract_dedicated(ctx, game: dict, what: str, root: Path, prepared=None) -> dict | None:
    """The game's own extractor, when it has one: None = no extractor for this game."""
    t, plat = (game.get("title") or "").lower(), game.get("platform") or ""
    for name, test, roster, run in DEDICATED:
        if not test(t, plat):
            continue
        ros = prepared[1] if prepared and prepared[0] == name else dedicated_entries(ctx.config, game, name, roster)
        e = best_match(ros, what)
        if e is None:
            return {"status": "not_in_roster", "extractor": name, "roster": [r["name"] for r in ros]}
        refresh = False
        if (Path(root) / e["slug"] / "meta.json").is_file():
            existing = get(root, e["slug"])
            refresh = _doa2_needs_refresh(ctx, game, existing) or (
                name == "jgr" and __import__("gbox.jgr", fromlist=["x"]).needs_refresh(existing))   # #1396
            if verify_entry(root, existing)['ok'] and not refresh:
                return {"status": "in_collection", "extractor": name, "entry": backfill_roles(root, name, existing)}
        work = Path(ctx.config.cache) / "characters_build" / "extract" / e["slug"]
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        ctx.progress(20, f"Extracting {e['name']} from {game['title']} (gBox's {name} extractor)")
        r = run(ctx, game, e, work)
        ctx.progress(85, "Adding it to the collection (preview render)")
        meta = add(root, e["slug"], e["name"], r["files"],
                   {"game_title": game["title"], "game_id": game["game_id"], "platform": plat, "files": r["source_files"]},
                   r["tool"], rig={"roles": r["roles"]} if r.get("roles") else None, aliases=e["aliases"],
                   notes=r.get("notes", ""), kind=e.get("kind", "character"), extra=r.get('extra'))
        if refresh:
            for targets in meta.get('targets', {}).values():
                for target in targets:
                    target['needs_rebuild'] = True
            meta = put_meta(root, meta)
        shutil.rmtree(work, ignore_errors=True)
        return {"status": "extracted", "extractor": name, "entry": meta}
    return None


# --- route (c): cut the thing out of a RenderDoc capture of the frame (gbox.scene_capture writes the scene.glb)

def _read_glb(p: Path) -> tuple[dict, bytes]:
    d = Path(p).read_bytes()
    jl = struct.unpack_from("<I", d, 12)[0]
    bl = struct.unpack_from("<I", d, 20 + jl)[0]
    return json.loads(d[20:20 + jl]), d[28 + jl:28 + jl + bl]


def _scene_draws(src: Path) -> tuple[dict, dict]:
    """Scene-layer draws of a captured scene.glb -> {node: {P, T, lo, hi, zmin, zmax, level, flat}} + glTF extras."""
    from .re4gc_models import _gltf_load
    gl, acc, _img = _gltf_load(src)
    out = {}
    for i, nd in enumerate(gl["nodes"]):
        if "mesh" not in nd or (nd.get("extras") or {}).get("layer", "scene") != "scene":
            continue
        pr = gl["meshes"][nd["mesh"]]["primitives"][0]
        P = acc(pr["attributes"]["POSITION"]).astype(float)
        T = acc(pr["indices"]).reshape(-1, 3).astype(int) if "indices" in pr else np.arange(len(P) // 3 * 3).reshape(-1, 3)
        if not len(T):
            continue
        V = P[np.unique(T)]
        z = -V[:, 2]
        zmin, zmax = max(float(z.min()), 1e-6), float(z.max())
        sd = np.sort(np.linalg.svd(V - V.mean(0), compute_uv=False)) if len(V) >= 3 else np.zeros(3)
        out[i] = {"P": P, "T": T, "V": V, "draw": int((nd.get("extras") or {}).get("draw", i)), "lo": V.min(0), "hi": V.max(0), "zmin": zmin, "zmax": zmax,
                  "level": (zmax - zmin) / zmin > 1.5,       # reaches deep into the picture: floor, walls, terrain, sky
                  "flat": bool(sd[-1] > 0 and sd[0] < 0.02 * sd[-1])}
    return out, gl.get("extras") or {}


def _min_dist(a: np.ndarray, b: np.ndarray) -> float:
    best = np.inf
    for k in range(0, len(a), 512):
        d = ((a[k:k + 512, None, :] - b[None, :, :]) ** 2).sum(-1)
        best = min(best, float(d.min()))
    return best ** 0.5


def cut_scene(src: Path, x: float, y: float) -> dict:
    """Which draws make up the object at screen point (x, y) (fractions of the picture, 0..1 from the top left)?
    Seed: the frontmost draw whose triangle covers the point (draws that reach deep into the scene - level geometry -
    aren't objects). Then every non-level draw inside the object's bounds or touching it (character parts, wheels),
    except large flat surfaces (the floor under the feet). -> {nodes, seed, depth, size, hits}"""
    D, ex = _scene_draws(src)
    p00, p11 = float(ex.get("P00") or 1.0), float(ex.get("P11") or 1.0)
    hits = []
    for i, d in D.items():
        P, T = d["P"], d["T"]
        z = -P[:, 2]
        ok = z > 1e-4
        zs = np.where(ok, z, 1.0)
        S = np.stack([np.where(ok, (P[:, 0] * p00 / zs + 1) / 2, np.nan), np.where(ok, (1 - P[:, 1] * p11 / zs) / 2, np.nan)], 1)
        a, b, c = S[T[:, 0]], S[T[:, 1]], S[T[:, 2]]
        lo, hi = np.minimum(np.minimum(a, b), c), np.maximum(np.maximum(a, b), c)
        k = np.nonzero((lo[:, 0] <= x) & (hi[:, 0] >= x) & (lo[:, 1] <= y) & (hi[:, 1] >= y))[0]
        if not len(k):
            continue
        v0, v1, v2 = c[k] - a[k], b[k] - a[k], np.array([x, y]) - a[k]
        d00, d01, d11 = (v0 * v0).sum(1), (v0 * v1).sum(1), (v1 * v1).sum(1)
        d20, d21 = (v2 * v0).sum(1), (v2 * v1).sum(1)
        den = d00 * d11 - d01 * d01
        with np.errstate(all="ignore"):
            u, v = (d11 * d20 - d01 * d21) / den, (d00 * d21 - d01 * d20) / den
        inside = (u >= -1e-6) & (v >= -1e-6) & (u + v <= 1 + 1e-6) & (np.abs(den) > 1e-18)
        if inside.any():
            kk = k[inside]
            depth = (1 - u[inside] - v[inside]) * z[T[kk, 0]] + u[inside] * z[T[kk, 2]] + v[inside] * z[T[kk, 1]]
            hits.append((float(depth.min()), i))
    hits.sort()
    summary = [{"draw": i, "depth": round(dz, 3), "level": D[i]["level"]} for dz, i in hits[:8]]
    if not hits:
        raise LookupError(f"nothing is drawn at ({x:.2f}, {y:.2f}) in the captured frame (HUD and 2D layers don't count)")
    objs = [(dz, i) for dz, i in hits if not D[i]["level"]]
    if not objs:
        raise LookupError(f"only level geometry (floor / walls / terrain / sky) at ({x:.2f}, {y:.2f}): point at the object "
                          "itself, or extract kind=environment")
    d0, seed = objs[0]
    if d0 > hits[0][0] * 1.3 + 1e-6:
        raise LookupError(f"the nearest object at ({x:.2f}, {y:.2f}) is hidden behind level geometry")
    sel, lo, hi = {seed}, D[seed]["lo"].copy(), D[seed]["hi"].copy()
    thin = lambda V: V[::max(1, len(V) // 1500)]          # noqa: E731
    for _ in range(10):
        size = float(np.linalg.norm(hi - lo)) or 1e-3
        selv = np.concatenate([thin(D[i]["V"]) for i in sel])
        added = False
        for i, d in D.items():
            if i in sel or d["level"]:
                continue
            isz = float(np.linalg.norm(d["hi"] - d["lo"]))
            m = 0.1 * size
            if isz > 2.0 * size or (d["lo"] > hi + m).any() or (d["hi"] < lo - m).any():
                continue
            if d["flat"] and isz > 0.25 * size:            # floor / wall panels / billboards near the object
                continue
            inside = bool((d["lo"] >= lo - m).all() and (d["hi"] <= hi + m).all()) and isz <= 0.5 * size
            near_draw = min(abs(d["draw"] - D[j]["draw"]) for j in sel) <= 12   # one model's parts are drawn together
            if not near_draw or not inside and _min_dist(thin(d["V"]), selv) > 0.02 * size:
                continue
            sel.add(i)
            lo, hi, added = np.minimum(lo, d["lo"]), np.maximum(hi, d["hi"]), True
        if not added:
            break
    return {"nodes": sorted(sel), "seed": seed, "depth": round(d0, 4), "size": [round(float(v), 4) for v in hi - lo],
            "hits": summary, "P00": p00, "P11": p11}


def subset_glb(src: Path, node_ids: list[int], out: Path, name: str = "model", recenter: bool = True) -> Path:
    """A new .glb with only these (mesh) nodes of a scene_capture glb, their buffers, materials and textures, under
    one root node; recenter: feet (min y) at 0, centred in x/z (the capture is in the game camera's view space)."""
    gl, blob = _read_glb(src)
    B, maps = bytearray(), {k: {} for k in ("view", "acc", "img", "tex", "mat")}
    o = {"bufferViews": [], "accessors": [], "images": [], "textures": [], "materials": [], "meshes": [], "nodes": []}

    def add_(kind, key, idx, make):
        if idx not in maps[kind]:
            o[key].append(make(idx))
            maps[kind][idx] = len(o[key]) - 1
        return maps[kind][idx]

    def view(vi):
        def mk(vi):
            v = gl["bufferViews"][vi]
            st = v.get("byteOffset", 0)
            B.extend(bytes(-len(B) % 4))
            nv = {k: val for k, val in v.items() if k not in ("buffer", "byteOffset")} | {"buffer": 0, "byteOffset": len(B)}
            B.extend(blob[st:st + v["byteLength"]])
            return nv
        return add_("view", "bufferViews", vi, mk)

    acc = lambda ai: add_("acc", "accessors", ai, lambda ai: gl["accessors"][ai] | {"bufferView": view(gl["accessors"][ai]["bufferView"])})  # noqa: E731
    img = lambda ii: add_("img", "images", ii, lambda ii: gl["images"][ii] | ({"bufferView": view(gl["images"][ii]["bufferView"])}  # noqa: E731
                                                                               if "bufferView" in gl["images"][ii] else {}))
    tex = lambda ti: add_("tex", "textures", ti, lambda ti: gl["textures"][ti] | {"source": img(gl["textures"][ti]["source"])})  # noqa: E731

    def mat(mi):
        def mk(mi):
            m = json.loads(json.dumps(gl["materials"][mi]))
            bct = m.get("pbrMetallicRoughness", {}).get("baseColorTexture")
            if bct:
                bct["index"] = tex(bct["index"])
            return m
        return add_("mat", "materials", mi, mk)
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    kids = []
    for ni in node_ids:
        nd = gl["nodes"][ni]
        prims = []
        for pr in gl["meshes"][nd["mesh"]]["primitives"]:
            q = {"attributes": {k: acc(v) for k, v in pr["attributes"].items()}}
            if "indices" in pr:
                q["indices"] = acc(pr["indices"])
            if "material" in pr:
                q["material"] = mat(pr["material"])
            a = gl["accessors"][pr["attributes"]["POSITION"]]
            if "min" in a:
                lo, hi = np.minimum(lo, a["min"]), np.maximum(hi, a["max"])
            prims.append(q)
        o["meshes"].append({"name": gl["meshes"][nd["mesh"]].get("name", f"m{ni}"), "primitives": prims})
        o["nodes"].append({k: v for k, v in nd.items() if k not in ("children", "mesh")} | {"mesh": len(o["meshes"]) - 1})
        kids.append(len(o["nodes"]) - 1)
    root = {"name": name, "children": kids}
    if recenter and np.isfinite(lo).all():
        root["translation"] = [float(-(lo[0] + hi[0]) / 2), float(-lo[1]), float(-(lo[2] + hi[2]) / 2)]
    o["nodes"].append(root)
    res = {"asset": {"version": "2.0", "generator": "gbox characters (scene_capture cut)"}, "scene": 0,
           "scenes": [{"nodes": [len(o["nodes"]) - 1]}], **{k: v for k, v in o.items() if v},
           "extras": {**(gl.get("extras") or {}), "cut_from_nodes": list(node_ids)}}
    if o["textures"] and gl.get("samplers"):
        res["samplers"] = gl["samplers"]
    if gl.get("extensionsUsed"):
        res["extensionsUsed"] = gl["extensionsUsed"]
    B.extend(bytes(-len(B) % 4))
    res["buffers"] = [{"byteLength": len(B)}]
    js = json.dumps(res, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    Path(out).write_bytes(struct.pack("<III", 0x46546C67, 2, 28 + len(js) + len(B)) + struct.pack("<II", len(js), 0x4E4F534A)
                          + js + struct.pack("<II", len(B), 0x004E4942) + bytes(B))
    return Path(out)


def _job(ctx, tool_name: str, inp: dict, worker: str | None = None, limit: float = 900) -> dict:
    parent = getattr(ctx, "parent_request_id", None)
    j = _api(ctx, "POST", "/api/jobs", json={"tool": tool_name, "input": inp,
             **({"require_worker": worker} if worker else {}),
             **({"parent_request_id": parent} if parent else {}),
             "agent_use": bool(getattr(ctx, "agent_use", False))})
    t0 = time.time()
    while j.get("state") in ("queued", "running") and time.time() - t0 < limit:
        time.sleep(1)
        j = _api(ctx, "GET", f"/api/jobs/{j['id']}")
    return j


def _session(ctx, sid: str) -> dict | None:
    return next((s for s in _api(ctx, "GET", "/api/sessions") if s.get("session_id") == sid), None) if sid else None


def capture_blockers(ctx, sess: dict | None) -> str | None:
    """Why a RenderDoc frame capture (scene_capture) can't run on this session; None = it can."""
    if not sess or sess.get("state") != "running":
        return ("no running session of this game: launch it on the PC (launch_game where=local; Examine 3D is on by default "
                "there), get the thing on screen, then extract again with that session_id and the point")
    wid = sess["session_id"].split("-")[0]
    w = next((w for w in _api(ctx, "GET", "/api/workers") if w["id"] == wid), None)
    d = sess.get("detail") or {}
    if not w or w.get("os") != "windows":
        return (f"RenderDoc frame capture runs on the Windows node; this session runs on {(w or {}).get('name', wid)}: relaunch "
                "the game on the PC (launch_game where=local) and extract again")
    if "scene_capture" not in (w.get("tools") or []):
        return f"the PC worker {w['name']} hasn't loaded the scene_capture tool yet (it needs a restart after the update)"
    if not d.get("examine"):
        return (f"this session runs without RenderDoc inside the emulator ({sess.get('adapter')}, "
                f"{d.get('renderer') or Path(str(d.get('core') or 'default renderer')).name}): it was started before Examine 3D "
                "existed, or this renderer can't be hooked (RenderDoc needs D3D11/D3D12/Vulkan/OpenGL). Save a state, relaunch "
                "with Examine 3D on, and extract again")
    return None


def extract_from_capture(ctx, game: dict, sess: dict, what: str, kind: str, x: float | None, y: float | None,
                         root: Path, eroot: Path) -> dict:
    sid = sess["session_id"]
    wid = sid.split("-")[0]
    ctx.progress(10, "Capturing the frame on screen (RenderDoc)")
    j = _job(ctx, "scene_capture", {"session_id": sid}, wid, 900)
    work = Path(ctx.config.cache) / "characters_build" / "capture" / sid
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        if j.get("state") != "succeeded":
            raise RuntimeError(f"scene_capture {j.get('state')}: {j.get('error') or j.get('detail')}")
        (work / "scene.glb").write_bytes(_api(ctx, "GET", f"/api/artifacts/{j['output']['glb']}", timeout=300))
        arts = {a["name"]: a["sha256"] for a in _api(ctx, "GET", f"/api/receipts/{j['receipt_id']}").get("artifacts", [])}
        if arts.get("frame.png"):
            (work / "frame.png").write_bytes(_api(ctx, "GET", f"/api/artifacts/{arts['frame.png']}", timeout=120))
    finally:                                               # scene_capture leaves the game paused on the frame
        try:
            _api(ctx, "POST", "/api/jobs", json={"tool": "session_op", "require_worker": wid,
                                                 "input": {"session_id": sid, "op": "resume"}})
        except Exception:
            pass
    return add_from_scene(work, game, sid, j["output"].get("summary", {}) | {"scene_glb": j["output"]["glb"],
                          "frame_png": arts.get("frame.png")}, what, kind, x, y, root, eroot)


def add_from_scene(work: Path, game: dict, sid: str, summ: dict, what: str, kind: str, x: float | None, y: float | None,
                   root: Path, eroot: Path) -> dict:
    """work/scene.glb (+ frame.png) of a capture -> a collection entry: the object at (x, y), or the whole scene."""
    src = {"game_title": game["title"], "game_id": game["game_id"], "platform": game.get("platform"), "session_id": sid,
           "captured_at": time.time(), "method": "gbox.scene_capture (RenderDoc frame capture)",
           "capture": {k: summ.get(k) for k in ("api", "mode", "draws_exported", "projection_source", "fovy_deg",
                                                 "scene_glb", "frame_png")}}
    extra_files = [work / "frame.png"] if (work / "frame.png").exists() else []
    if kind == "environment":
        D, ex = _scene_draws(work / "scene.glb")
        name = what or re.sub(r"\s*[\(\[].*?[\)\]]", "", game["title"]) + " scene"
        slug = free_slug(eroot, name)
        out = subset_glb(work / "scene.glb", sorted(D), work / f"{slug}.glb", name, recenter=False)
        meta = add(eroot, slug, name, [out, *extra_files], src | {"draws": len(D)}, "gbox.scene_capture (whole scene minus HUD)",
                   aliases=[what] if what else [], kind="environment", preview={"persp": (float(ex.get("P00") or 1), float(ex.get("P11") or 1))},
                   notes="the frame on screen as a 3D scene (scene layer, HUD dropped), in the game camera's view space "
                         "(camera at the origin looking down -Z); game units; geometry posed as it was drawn")
        return {"entry": meta, "env": True}
    cx, cy = (0.5 if x is None else x), (0.5 if y is None else y)
    pick = cut_scene(work / "scene.glb", cx, cy)
    name = what or f"{kind} from {game['title']}"
    slug = free_slug(root, name)
    out = subset_glb(work / "scene.glb", pick["nodes"], work / f"{slug}.glb", name)
    meta = add(root, slug, name, [out, *extra_files], src | {"point": [cx, cy], "draws": pick["nodes"]},
               "gbox.scene_capture + characters.cut_scene", aliases=[what] if what else [], kind=kind, preview={"yaw": 0.0},
               notes=f"cut from a RenderDoc capture of the frame: {len(pick['nodes'])} draw call(s) at the point, posed as on "
                     "screen, oriented as the game camera saw it, game units, not rigged (needs a rig before op=use)",
               extra={"capture_pick": {k: pick[k] for k in ("seed", "depth", "size", "hits")}})
    return {"entry": meta, "env": False}


def _extract_request(ctx, game: dict | None, what: str, kind: str, need: dict) -> dict:
    title = f"Model extraction: {what or kind} from {(game or {}).get('title', 'an unknown game')}"
    for r in _api(ctx, "GET", "/api/requests", params={"status": "open,in_progress"}):
        if r.get("title") == title:
            return {"number": r.get("number"), "id": r["id"], "existing": True}
    r = _api(ctx, "POST", "/api/requests", json={"title": title, "source": "characters", "kind": "text",
                                                 "body": f"Extract {what or kind} ({kind}) from {(game or {}).get('title')} into the "
                                                         f"collection. Nothing in gBox can do it yet:\n" + json.dumps(need, indent=1),
                                                 "parent_request_id": getattr(ctx, "parent_request_id", None),
                                                 "context": {"what": what, "kind": kind, "game_id": (game or {}).get("game_id"), "job_id": ctx.job_id}})
    return {"number": r.get("number"), "id": r["id"], "existing": False}


GHIDRA_CPU = {"dreamcast": "SuperH4:LE:32:default (1ST_READ.BIN)", "psx": "MIPS:LE:32:default (SLUS/SCUS executable)",
              "gamecube": "PowerPC:BE:32:Gekko_Broadway (main.dol)", "wii": "PowerPC:BE:32:Gekko_Broadway (main.dol)",
              "ps2": "MIPS R5900 (SLUS/SCUS ELF)", "n64": "MIPS:BE:32 (the ROM's code)"}


def extract(ctx, inp: CharIn) -> dict:
    root, eroot = library_root(ctx.config), env_root(ctx.config)
    if not root.is_dir():
        raise ValueError("op=extract runs on the control-plane node, where the collection lives (the agent sends it there)")
    what, kind = inp.character.strip(), (inp.kind if inp.kind in KINDS else "object")
    if not what and kind != "environment":
        raise ValueError("extract needs character=<what to extract: a name or a short description>")
    sess = _session(ctx, inp.session_id)
    game = _game(ctx, inp) if (inp.session_id or inp.game_id or inp.game) else None
    out = {"what": what, "kind": kind, "game": (game or {}).get("title"), "game_id": (game or {}).get("game_id")}
    lib = list_all(eroot if kind == "environment" else root)
    hit = best_match([m for m in lib if _same_game(m, game)], what) if what else None
    if hit and not _doa2_needs_refresh(ctx, game, hit):                                          # (a)
        return out | {"status": "in_collection", "route": "collection", "entry": _brief(hit, kind == "environment"),
                      "message": f"{hit['name']} is already in the collection (from {hit['source'].get('game_title')})."}
    if not game:
        others = best_match(lib, what) if what else None
        if others:
            return out | {"status": "in_collection", "route": "collection", "entry": _brief(others)}
        raise ValueError(f"{what!r} isn't in the collection; to extract it, pass session_id (or game) of the game it's in")
    need, tried = {}, []
    from . import oot_swap
    if kind != "environment" and oot_swap.is_oot(game):                                      # (b) OoT: point / name
        try:
            return out | oot_swap.extract_cmd(ctx, game, inp, root)
        except (LookupError, ValueError) as e:
            tried.append(f"gBox's OoT extractor: {e}")
    if kind != "environment" and sess and game["game_id"] == "23a346e48b6368a6" and sess.get("game_id") == game["game_id"]:
        from . import aki_wrestling                       # (b) No Mercy session: the wrestler at x, y / by name, exact look
        try:
            return out | aki_wrestling.extract_cmd(ctx, game, inp, root)
        except (LookupError, ValueError, RuntimeError) as e:
            tried.append(f"gBox's No Mercy session extractor: {e}")
    if kind != "environment":                                                                 # (b)
        r = extract_dedicated(ctx, game, what, root)
        if r and r["status"] in ("extracted", "in_collection"):
            return out | {"status": r["status"], "route": f"dedicated:{r['extractor']}", "entry": r["entry"]}
        if r:
            tried.append(f"gBox's {r['extractor']} extractor reads only: {', '.join(r['roster'])}")
        else:
            need["dedicated_extractor"] = (f"none for {game['title']} (gBox has: Melee, Sonic Adventure 2, FF7, Parasite Eve, "
                                           "PSO Ver.2, Shenmue, Super Mario 64, RE4 GameCube, RE4 2023 (Steam))")
    blocker = capture_blockers(ctx, sess if sess and sess.get("game_id") == game["game_id"] else None)   # (c)
    if not blocker:
        try:
            r = extract_from_capture(ctx, game, sess, what, kind, inp.x, inp.y, root, eroot)
            return out | {"status": "extracted", "route": "scene_capture", "entry": r["entry"], "env": r["env"]}
        except LookupError as e:                           # captured fine, but nothing to cut at that point
            return out | {"status": "not_found", "route": "scene_capture", "message": str(e),
                          "hint": "pass x/y = the thing's position on the picture (fractions), or kind=environment"}
        except Exception as e:                             # noqa: BLE001
            blocker = f"the frame capture failed: {type(e).__name__}: {e}"
    need["frame_capture"] = blocker                                                           # (d)
    plat = game.get("platform") or "?"
    need["format_reader"] = (f"no reader for {game['title']}'s model files: find the model loader in the executable with Ghidra "
                             f"(analyze_binary / ghidra_script, processor {GHIDRA_CPU.get(plat, 'for ' + plat)}), "
                             "then write a reader like gbox/sa2_chars.py and add it to characters.DEDICATED")
    if tried:
        need["tried"] = tried
    req = _extract_request(ctx, game, what, kind, need)
    return out | {"status": "missing", "missing": need, "request": req,
                  "message": f"Can't extract {what or kind} from {game['title']} yet; "
                             + (f"request #{req.get('number')} is already open." if req.get("existing") else f"filed request #{req.get('number')}.")}


def _model_bytes(ctx, inp: CharIn) -> tuple[bytes, str]:
    if inp.from_clipboard:
        item = _api(ctx, "GET", "/api/clipboard")
        if not item.get("sha256") or item.get("kind") not in ("gltf", "bytes"):
            raise ValueError("the gBox clipboard holds no model (in Blender: gBox panel > Send to gBox)")
        return _api(ctx, "GET", f"/api/artifacts/{item['sha256']}", timeout=300), item.get("name") or "model"
    if inp.artifact:
        return _api(ctx, "GET", f"/api/artifacts/{inp.artifact}", timeout=300), "model"
    if inp.path and Path(inp.path).is_file():
        return Path(inp.path).read_bytes(), Path(inp.path).stem
    raise ValueError("add needs from_clipboard=true, artifact=<sha256> or path=<a .glb/.gltf on the control-plane node>")


def validate_rig_roles(model: Path, roles: dict[str, str]) -> dict:
    """Reject stale or ambiguous joint mappings before registering an edited donor."""
    if not roles:
        return {}
    gl, _, _, _ = _load(model)
    joints = {j for skin in gl.get('skins', []) for j in skin['joints']}
    if any(type(j) is not int or not 0 <= j < len(gl.get('nodes', [])) for j in joints):
        raise ValueError('Rig contains an invalid skin joint node index')
    names = [gl['nodes'][j].get('name', f'node{j}') for j in joints]
    for role, name in roles.items():
        if not role.strip() or not name.strip() or names.count(name) != 1:
            raise ValueError(f'Rig role {role!r} must identify one named skin joint: {name!r}')
    return dict(roles)


def add_model(ctx, inp: CharIn) -> dict:
    """A model edited elsewhere (Blender) -> a new collection entry."""
    name = inp.character.strip()
    if not name:
        raise ValueError("add needs character=<name for the new entry>")
    data, _src = _model_bytes(ctx, inp)
    if inp.base:                                           # a variant (Blender Live Link): base rig, props, scale
        from . import variants
        root = library_root(ctx.config)
        work = Path(ctx.config.cache) / "characters_build" / "add" / ("variant_" + slugify(name))
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        f = work / f"{slugify(name) or 'variant'}.glb"
        if data[:4] != b"glTF":
            raise ValueError("a variant must be sent as .glb (the Live Link add-on exports GLB)")
        f.write_bytes(data)
        base = inp.base if (root / inp.base / "meta.json").is_file() else (best_match(list_all(root), inp.base) or {}).get("slug")
        if not base:
            raise ValueError(f"no collection character {inp.base!r} to make a variant of")
        meta = variants.store(ctx, root, base, name, f, scale=inp.scale, hints=inp.props, replace=inp.replace)
        shutil.rmtree(work, ignore_errors=True)
        return {"status": "added", "entry": meta, "env": False, "variant_of": meta["variant_of"],
                "props": meta.get("props"), "skeleton": meta["variant"]["skeleton"]}
    env = inp.kind == "environment"
    root = env_root(ctx.config) if env else library_root(ctx.config)
    slug = free_slug(root, name)
    work = Path(ctx.config.cache) / "characters_build" / "add" / slug
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    f = work / f"{slug}.{'glb' if data[:4] == b'glTF' else 'gltf'}"
    if f.suffix == ".gltf" and not data.lstrip()[:1] == b"{":
        raise ValueError("that file isn't a glTF / GLB model")
    f.write_bytes(data)
    mapped_roles = validate_rig_roles(f, inp.rig_roles)
    game = _game(ctx, inp) if (inp.session_id or inp.game_id or inp.game) else None
    src = {"game_title": (game or {}).get("title") or "edited model", "game_id": (game or {}).get("game_id"),
           "from": "clipboard" if inp.from_clipboard else inp.artifact or inp.path}
    meta = add(root, slug, name, [f], src, "characters op=add (edited model)", kind=inp.kind if inp.kind in KINDS else "character",
               aliases=[name], rig={"roles": mapped_roles} if mapped_roles else None)
    shutil.rmtree(work, ignore_errors=True)
    return {"status": "added", "entry": meta, "env": env}


def to_blender(ctx, inp: CharIn) -> dict:
    """Put a collection model on the gBox clipboard; Ctrl+Shift+V in Blender (gBox add-on) imports it."""
    root, eroot = library_root(ctx.config), env_root(ctx.config)
    pool = [(m, root) for m in list_all(root)] + [(m, eroot) for m in list_all(eroot)]
    m = best_match([p[0] for p in pool], inp.character)
    if not m:
        raise ValueError(f"nothing in the collection matches {inp.character!r}")
    base = next(r for x, r in pool if x is m)
    f = base / m["slug"] / m["model"]
    data = f.read_bytes()
    if f.suffix == ".gltf":                                # one self-contained file: external buffers/images inlined
        gl = json.loads(data)
        for coll, mt in (("buffers", "application/octet-stream"), ("images", "image/png")):
            for it in gl.get(coll, []):
                if it.get("uri") and not it["uri"].startswith("data:"):
                    it["uri"] = f"data:{mt};base64," + base64.b64encode((f.parent / it["uri"]).read_bytes()).decode()
        data = json.dumps(gl).encode()
    item = _api(ctx, "POST", "/api/clipboard", json={"kind": "gltf", "name": m["slug"], "b64": base64.b64encode(data).decode(),
                                                     "meta": {"character": m["slug"], "model": m["model"]}}, timeout=300)
    return {"status": "on_clipboard", "entry": _brief(m), "clipboard_seq": item.get("seq"),
            "message": f"{m['name']} is on the gBox clipboard: in Blender press Ctrl+Shift+V (gBox add-on). After editing, "
                       "use the gBox panel's 'Send to gBox', then characters op=add from_clipboard=true character=<new name>."}


def _finish(ctx, res: dict) -> dict:
    """An entry was added or found: attach the checked preview (verify_entry) and the preview as an artifact."""
    m = res.get("entry")
    if not m or "slug" not in m:
        return res
    env = res.pop("env", False) or m.get("kind") == "environment"
    root = env_root(ctx.config) if env else library_root(ctx.config)
    if not (root / m["slug"] / "meta.json").is_file():
        return res
    full = get(root, m["slug"])
    chk = verify_entry(root, full)
    res["entry"] = _brief(full, env)
    res["checked"] = chk
    prev = root / m["slug"] / full.get("preview", "preview.png")
    if prev.is_file():
        data = prev.read_bytes()
        ctx.artifact("preview.png", data, "image/png", character=m["slug"])
        from .store import sha256
        res["artifact"] = sha256(data)
    if res.get("status") in ("extracted", "added") and not chk["ok"]:
        res["status"] += "_unverified"
        res["message"] = f"files were written but the check failed ({chk}); don't call it done."
    elif res.get("status") in ("extracted", "added"):
        res["message"] = (f"{full['name']} is in the collection ({full.get('kind', 'character')}, "
                          f"{chk['triangles']} triangles, {chk['textures']} textures; preview checked).")
    return res


@tool("characters", "1.3", CharIn, CharOut, capabilities=["mod", "asset", "extract"], permissions=[P.EXECUTE], timeout_s=14400,
      artifacts=["preview.png"],
      side_effects=["use: may build a disc-image mod under cache/mods and launch it", "use/extract: may file a request",
                    "extract/add: writes a collection entry (characters/ or environments/ in the cache)",
                    "extract: may capture the frame (pauses the session briefly)", "blender: replaces the gBox clipboard"])
def characters_tool(inp: CharIn, ctx):
    """gBox's collection: characters, vehicles, objects (and environments) extracted from the operator's own games,
    reusable through supported game writers. op=list [kind] | get character=<name> | environments |
    collect game_id: extract the native reader's character roster, reuse verified files, report individual failures
    and mapped rig readiness, and list the writer's slots (PSO Ver.2: enemy:booma, enemy:gobooma, enemy:gigobooma,
    enemy:boomas, the other BM_ENE packs); unsupported games return unsupported without capture or an LLM call. |
    live_use character=<name> session_id [x,y|slot]: bounded in-engine OoT NTSC 1.2 single-object NPC swap,
    preserving the session and pause state. Changes all loaded actors sharing that model until object reload.
    Link, compound objects and other games return unsupported_live_swap; never relaunch or substitute an overlay. |
    extract character=<what> kind=character|vehicle|object|environment session_id (or game) [x, y = the thing's point
    on the picture, 0..1]: returns it if it's already in the collection, else runs the game's own extractor, else cuts it
    out of a RenderDoc capture of the frame (environment = the whole scene minus the HUD), else says what's missing
    and files a request | use character=<name> session_id|game: launch/build the swap mod (RE4 GC replaces Leon, SM64 Mario, GTA LCS
    PS2 every Toni outfit, OoT Link both ages or [x, y | slot=<NPC name>] the NPC there, Parasite Eve Aya (all outfits),
    FF7 Cloud (field + battle), Clay Fighter SC slot=fighter:<name> (a sprites entry re-draws that fighter)), else the overlay (when the game runs) + a gap report so the writer gets built |
    FF7 Cloud (field + battle), Jet Grind Radio slot=player (Beat unless active_id) | character:<name>), else the overlay (when the game runs) + a gap report so the writer gets built |
    coverage: per studied game, can gBox rip its characters and reimport any character into it (slots) | swap a=<who> b=<who> session_id (OoT; who = "link", an NPC name or a picture point
    "x,y"): A gets B's model and B gets A's (one_way=true: only A <- B, "play as B") | place character=<name>
    session_id [pos | x, y | near=<actor>] [size, yaw] (OoT): a statue of it in the world (default in front of you) |
    unplace [character] session_id | overlay character=<name> session_id [x, y]: draw it over the player on screen in the
    desktop app now, any game (an overlay, not in-engine) | blender character=<name>: put it on the gBox clipboard for Blender (Ctrl+Shift+V) |
    add character=<new name> from_clipboard=true|artifact|path: store an edited model."""
    if inp.op == "mgs_vr_decode":                    # internal Windows handoff for the native reader
        from . import mgs_vr_swap
        game = _game(ctx, inp)
        if HOST_OS != "windows" or game["game_id"] not in mgs_vr_swap.GAME_IDS:
            raise ValueError("VR Missions disc decoding requires a Windows worker and the US VR Missions game")
        out = Path(ctx.config.cache) / "characters_build" / "mgs_vr_decode" / f"{ctx.job_id}.glb"
        mgs_vr_swap.decode_original_player(ctx.config, out, ctx.progress)
        data = out.read_bytes()
        ctx.artifact("mgs-vr-snake.glb", data, "model/gltf-binary", game_id=game["game_id"])
        out.unlink(missing_ok=True)
        return {"result": {"status": "decoded", "model": "Solid Snake (VR Missions)", "bytes": len(data)}}
    if inp.op == "collect":
        return {"result": collect(ctx, inp)}
    if inp.op in ("extract", "add", "blender"):
        res = {"extract": extract, "add": add_model, "blender": to_blender}[inp.op](ctx, inp)
        return {"result": _finish(ctx, res) if inp.op != "blender" else res}
    if inp.op == "environments":
        envs = _api(ctx, "GET", "/api/environments")
        return {"result": {"environments": [_brief(m, True) for m in envs]}}
    if inp.op == "coverage":                                  # rip / reimport matrix per studied game (gbox.char_coverage)
        from . import char_coverage
        return {"result": char_coverage.coverage(ctx, _api)}
    q = {"game_id": inp.game_id} if inp.game_id else {}
    chars = _api(ctx, "GET", "/api/characters", params=q)
    if inp.op == "list":
        return {"result": {"characters": [{k: m.get(k) for k in ("slug", "name", "aliases", "ready", "variant_of")} |
                                          {"kind": m.get("kind", "character"), "source": m["source"].get("game_title"),
                                           "targets": sorted(m.get("targets", {}))}
                                          for m in chars if inp.kind in ("", "character") or m.get("kind", "character") == inp.kind]}}
    if inp.op == "match":                                     # wrestling games: several characters, one ROM / disc
        from . import aki_wrestling, defjam_writer, yukes_sd
        pr = [(p.get("character", ""), p.get("slot", "")) for p in inp.pairs] or \
            [(inp.character, "" if inp.slot == "player" else inp.slot), (inp.b, inp.a)]
        g = _game(ctx, inp)
        mod = yukes_sd if g["game_id"] in yukes_sd.GAME_IDS else aki_wrestling   # SmackDown! 2 (PS1) | No Mercy (N64)
        mod = defjam_writer if g["game_id"] in defjam_writer.GAME_IDS else mod   # Def Jam Vendetta (PS2)
        return {"result": mod.match(ctx, chars, g, inp, [x for x in pr if x[0]], inp.title or None)}
    if inp.op in ("swap", "unplace"):                         # OoT: in-game characters / statues (gbox.oot_swap)
        from . import oot_swap
        r = oot_swap.tool(ctx, inp, None)
        if r is None:
            raise ValueError(f"op={inp.op} works for Zelda: Ocarina of Time (N64) only")
        return {"result": r}
    meta = (best_match(chars, inp.character) or find(chars, inp.character)) if inp.character else None
    if inp.op in ("use", "live_use", "place") and inp.character and not best_match(chars, inp.character):
        return {"result": {"status": "not_in_collection", "character": inp.character,
                           "message": f"{inp.character!r} isn't in the collection yet: run characters op=extract first "
                                      f"(have: {', '.join(m['name'] for m in chars)})"}}
    if not meta:
        raise ValueError(f"no library character matches {inp.character!r}; have: {', '.join(m['name'] for m in chars)}")
    if inp.op == "live_use":
        from . import oot_hot_swap
        return {"result": oot_hot_swap.use(ctx, meta, _game(ctx, inp), inp)}
    if inp.op == "use" and inp.head_scale and abs(inp.head_scale - 1) > 0.01:   # sidebar "Head size": a variant
        if not library_root(ctx.config).is_dir():
            cp = next((w["id"] for w in _api(ctx, "GET", "/api/workers") if w.get("os") == "linux" and w.get("online")), None)
            j = _job(ctx, "characters", inp.model_dump() | {"session_id": "", "game_id": _game(ctx, inp)["game_id"],
                                                             "launch": False}, cp, 1800)
            if j.get("state") != "succeeded":
                raise RuntimeError(f"head-size build on the control plane {j.get('state')}: {j.get('error')}")
            meta = _api(ctx, "GET", f"/api/characters/{j['output']['result']['slug']}")
            inp = inp.model_copy(update={"head_scale": 0.0, "character": meta["slug"]})
        else:
            from . import variants
            meta = variants.head_variant(ctx, library_root(ctx.config), meta["slug"], inp.head_scale, inp.rebuild)
            inp = inp.model_copy(update={"head_scale": 0.0, "character": meta["slug"]})
    if inp.op == "get":
        return {"result": meta}
    if inp.op in ("use", "place") and (inp.session_id or inp.game_id or inp.game):
        from . import oot_swap                                # OoT: Link / any NPC / statues (gbox.oot_swap, oot_place)
        r = oot_swap.tool(ctx, inp, meta)
        if r is not None:
            return {"result": r}
        if inp.op == "place":
            raise ValueError("op=place (a statue in the world) works for Zelda: Ocarina of Time (N64) only")
    if inp.op == "overlay":                                   # any game, right now: drawn over the player in the desktop app
        from . import overlay_swap
        return {"result": overlay_swap.start(ctx, _api, meta, inp.session_id, inp.x, inp.y)}
    if inp.op != "use":
        raise ValueError(f"unknown op {inp.op} (list | get | use | overlay | extract | add | blender | environments | coverage)")
    game = _game(ctx, inp)
    gid = game["game_id"]
    out = {"character": meta["name"], "slug": meta["slug"], "game": game["title"], "game_id": gid}
    if meta["source"].get("game_id") == gid and inp.slot == "player" and meta.get("native_player"):
        return {"result": out | {"status": "native", "message": f"{meta['name']} is this game's own player character."}}
    from . import doa2_swap
    if gid in doa2_swap.GAME_IDS:
        return {"result": out | doa2_swap.use(ctx, meta, game, inp)}
    from . import sm64_swap
    if gid in sm64_swap.GAME_IDS and inp.slot == "player":        # SM64: build sm64_<slug> if missing, launch it
        return {"result": out | sm64_swap.use(ctx, meta, game, inp)}
    from . import gta_stories_models as lcs
    if gid in lcs.GAME_IDS and inp.slot == "player":              # GTA LCS (PS2): every Toni outfit -> lcs_<slug>
        return {"result": out | lcs.use(ctx, meta, game, inp)}
    from . import gta3_swap
    if gid in gta3_swap.GAME_IDS and inp.slot == "player":         # GTA III (PS2): Claude -> gta3_<slug> (disc image)
        return {"result": out | gta3_swap.use(ctx, meta, game, inp)}
    from . import gta_vc_swap
    if gid in gta_vc_swap.GAME_IDS and (inp.slot in ("player", "peds:all", "all") or inp.slot.startswith("ped:")):
        # GTA Vice City (classic PC port): Tommy / one ped / every ped -> gtavc_<slug>[_<slot>] (rebuilt gta3.img);
        # a Definitive Edition install gets the overlay fallback + gap report from inside use()
        return {"result": out | gta_vc_swap.use(ctx, meta, game, inp)}
    from . import re6_tool
    if gid in re6_tool.GAME_IDS and (inp.slot in ("player", "enemies") or inp.slot.startswith("enemy:")):
        # RE6 (X360, Xenia): player = Leon's every costume -> re6_<slug>; enemies / enemy:<family> -> zombies, J'avo
        return {"result": out | re6_tool.use(ctx, meta, game, inp)}
    from . import metal_arms
    if gid in metal_arms.GAME_IDS and inp.slot in ("player", "npc", "enemy", "enemies"):   # Metal Arms GC: Glitch / a bot
        return {"result": out | metal_arms.use(ctx, meta, game, inp)}
    from . import sa2_chars
    if gid in sa2_chars.GAME_IDS and inp.slot == "player":    # Sonic Adventure 2 (DC): Sonic -> sa2_<slug> (GD-ROM copy)
        return {"result": out | sa2_chars.use(ctx, meta, game, inp)}
    from . import jgr_swap
    if gid in jgr_swap.GAME_IDS:            # JGR: player (Beat unless active_id) | character:<name> | id:N | NN
        return {"result": out | jgr_swap.use(ctx, meta, game, inp)}
    from . import pso_player
    if gid in pso_player.GAME_IDS and (inp.slot == "player" or pso_player.is_enemy_slot(inp.slot)):
        # PSO Ver.2 (DC): the operator's class (HUcast) -> pso_<slug>; enemy:<name> | enemies -> pso_<slug>_as_<name>
        # (gbox.pso_enemy: the character on the enemy's node tree and motions)
        return {"result": out | pso_player.use(ctx, meta, game, inp)}
    from . import crazy_taxi_swap
    if gid in crazy_taxi_swap.GAME_IDS and crazy_taxi_swap.is_slot(inp.slot):
        # Crazy Taxi GC: player | driver:<name> | drivers | pedestrian(s) | passenger(s) -> ct_<slug>[_<slot>]
        return {"result": out | crazy_taxi_swap.use(ctx, meta, game, inp)}
    from . import aki_wrestling
    if gid in aki_wrestling.GAME_IDS:                         # AKI wrestling (No Mercy): slot = a wrestler | player 1
        return {"result": out | aki_wrestling.use(ctx, meta, game, inp)}
    from . import yukes_sd
    if gid in yukes_sd.GAME_IDS or gid in yukes_sd.SD1_IDS:   # Yuke's SmackDown! 2 (PS1): slot = a wrestler (The Rock)
        return {"result": out | yukes_sd.use(ctx, meta, game, inp)}
    from . import defjam_writer
    if gid in defjam_writer.GAME_IDS:                         # Def Jam Vendetta (PS2): slot = a wrestler | player (heroes)
        return {"result": out | defjam_writer.use(ctx, meta, game, inp)}
    from . import clayfighter_swap
    if gid in clayfighter_swap.GAME_IDS and (inp.slot == "player" or inp.slot.startswith("fighter:")):
        # Clay Fighter SC (N64): one fighter's sprite frames re-drawn from a sprites entry -> cfsc_<slug>_as_<fighter>
        return {"result": out | clayfighter_swap.use(ctx, meta, game, inp)}
    from . import pe_swap
    if gid in pe_swap.GAME_IDS and inp.slot == "player":         # Parasite Eve (PS1): Aya, all 5 outfits -> pe_<slug>
        return {"result": out | pe_swap.use(ctx, meta, game, inp)}
    from . import pe2_swap
    if gid in pe2_swap.GAME_IDS and inp.slot == "player":        # Parasite Eve II (PS1): Aya, every outfit -> pe2_<slug>
        return {"result": out | pe2_swap.use(ctx, meta, game, inp)}
    from . import ff7_swap
    if gid in ff7_swap.GAME_IDS and inp.slot == "player":        # Final Fantasy VII (PS1): Cloud, field + battle -> ff7_<slug>
        return {"result": out | ff7_swap.use(ctx, meta, game, inp)}
    from . import mgs_vr_swap
    if gid in mgs_vr_swap.GAME_IDS and inp.slot == "player":
        return {"result": out | mgs_vr_swap.use(ctx, meta, game, inp)}
    from . import mgs1_swap
    if gid in mgs1_swap.GAME_IDS and inp.slot == "player" and meta["slug"] == "hucast":
        return {"result": out | mgs1_swap.use(ctx, meta, game, inp)}
    from . import filemods
    here = {m["name"] for m in filemods.list_mods(ctx.config, gid)}
    built = [t for t in meta.get("targets", {}).get(gid, []) if t.get("mod") and t.get("slot", "player") == inp.slot
             and not t.get("needs_rebuild")]
    if built and not inp.rebuild:
        t = next((t for t in built if t["mod"] in here), None)
        node = HOST_OS if t else (built[0].get("nodes") or [HOST_OS])[0]
        t = t or built[0]
        if t["mod"] in here or node != HOST_OS:
            l = _launch(ctx, gid, t["mod"], node) if inp.launch else None
            return {"result": out | {"status": "launched" if l else "ready", "mod": t["mod"], "slot": t.get("slot"),
                                     "launch": l, "notes": t.get("notes", "")}}
    if (gid in RE4GC or gid in RE4WII) and inp.slot == "player":
        b = build_re4(ctx, meta, game, ctx.progress)
        _api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
             json={"game_id": gid, "slot": "player", "mod": b["mod"], "nodes": [HOST_OS],
                   "notes": "replaces Leon (story + Mercenaries); Mercenaries: re_mods mercenaries_unlock, then Game Reset"})
        l = _launch(ctx, gid, b["mod"], HOST_OS) if inp.launch else None
        return {"result": out | {"status": "built+launched" if l else "built", "mod": b["mod"], "build": b, "launch": l,
                                 "notes": "untested build: check the model in game (Mercenaries: re_mods mercenaries_unlock)"}}
    if gid in RE4GC:
        need = {"target": f"RE4 {inp.slot}", "have": "player swaps are built automatically; enemy swaps need "
                "gbox/re4gc_enemies.Builder (Melee rigs) run by hand", "steps": ["re4gc_enemies.combine for the Ganado files"]}
    else:
        need = needs_for(game)
    from . import char_coverage                               # no writer: overlay now (if the game runs) + a gap report
    return {"result": out | char_coverage.no_writer(ctx, _api, meta, game, need, inp)}
