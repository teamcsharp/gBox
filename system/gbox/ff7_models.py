"""Final Fantasy VII (PlayStation) character models -> rigged glTF, read straight from the operator's disc image.

Formats (Qhimm wiki: "FF7/Battle model format (PSX)", "FF7/Battle/Battle Animation (PC)", "FF7/LZS format"):

  ENEMY6/<NAME>.LZS  party battle models (CLOUD, HICLOUD = the high-poly Cloud of the final duel, TIFA, BARRETT...).
  LZS                u32 compressed size, then LZSS: flag byte (LSB first, 1 = literal), reference = 2 bytes
                     (offset = b0 | (b1 & 0xF0) << 4 into a 4 KiB ring buffer that starts at 0xFEE, length = (b1&15)+3).
  decompressed       u32 section count + u32 offsets. Section 0 = skeleton + meshes, 1 = model settings / scripts,
                     2.. = animations, then a TIM (4bpp, CLUT rows), then the weapon models (party models only).
  skeleton           u32 bone count, root bone (8 zero bytes), then per bone {u16 parent, s16 length, u32 mesh offset
                     from the section start (0 = joint, no mesh)}. Bone i (1-based, root = 0) hangs off its parent's END:
                     M_i = M_parent * T(0, 0, length_parent) * Ry * Rx * Rz (the FF7 rotation order).
  mesh               u32 vertex pool bytes, vertices {s16 x, y, z, pad}, then four {u16 count, u16 texpage} groups:
                     textured triangles (16 B: 4 u16 vertex BYTE offsets, uv0, u16 clut, uv1, uv2), textured quads
                     (20 B: +uv3, pad), Gouraud triangles (20 B: indices + 3 RGBx), Gouraud quads (24 B: + 4 RGBx).
                     PSX quads are Z-ordered (ABC + BDC). Clut word = (y << 6) | (x >> 4) in VRAM; the TIM's CLUT rows.
  animation (PSX)    no 12-byte frame header: u16 frames, u16 size, u8 key, then a big-endian bit stream: frame 0 =
                     3 x s16 root offset + (bones+1) x 3 rotations of (12-key) bits (<< key); later frames are deltas
                     (offsets 1+7 or 1+16 bits, rotations by the "1 bit + 3 bit type" scheme). 4096 = 360 degrees.
  weapon section     u32 0, then a single bone {u16 0, s16 length, u32 mesh offset} and a mesh (Gouraud only).

Output glTF: joints j00 (root) .. jNN (FF7 bone order), one rigid mesh weighted 100% per bone, textured polygons on the
TIM (one material per CLUT), Gouraud polygons baked into a colour atlas (one 4x4 texel cell per triangle / quad with the
vertex colours painted bilinearly, so the per-vertex shading survives engines without vertex colours), an optional
weapon mesh parented to a bone, and the chosen animation as a glTF animation. Units: FF7 battle units (Cloud ~ 1700).
"""
from __future__ import annotations

import base64
import io
import json
import math
import struct
from pathlib import Path

import numpy as np

# ENEMY6/CLOUD.LZS bone names (Lazy Bastard's breakdown on the Qhimm wiki; HICLOUD shares the skeleton)
CLOUD_BONES = {0: "root", 1: "pelvis", 2: "torso", 3: "head", 4: "l_shoulder_j", 5: "l_clavicle_j", 6: "l_upperarm",
               7: "l_forearm", 8: "l_hand", 9: "r_shoulder_j", 10: "r_clavicle_j", 11: "r_upperarm", 12: "r_forearm",
               13: "r_hand", 14: "l_hip_j", 15: "l_thigh", 16: "l_shin", 17: "l_heel", 18: "l_toe", 19: "r_hip_j",
               20: "r_thigh", 21: "r_shin", 22: "r_heel", 23: "r_toe"}


def lzs(d: bytes) -> bytes:
    n = struct.unpack_from("<I", d)[0]
    src = d[4:4 + n]
    out = bytearray()
    ring = bytearray(4096)
    r = 0xFEE
    i = 0
    while i < len(src):
        f = src[i]
        i += 1
        for b in range(8):
            if i >= len(src):
                break
            if f >> b & 1:
                c = src[i]
                i += 1
                out.append(c)
                ring[r] = c
                r = (r + 1) & 0xFFF
            else:
                o = src[i] | ((src[i + 1] & 0xF0) << 4)
                ln = (src[i + 1] & 0xF) + 3
                i += 2
                for k in range(ln):
                    c = ring[(o + k) & 0xFFF]
                    out.append(c)
                    ring[r] = c
                    r = (r + 1) & 0xFFF
    return bytes(out)


# ---------------------------------------------------------------- model

def read_mesh(u: bytes, q: int) -> dict:
    vs = struct.unpack_from("<I", u, q)[0]
    q += 4
    verts = np.frombuffer(u, "<i2", vs // 2, q).reshape(-1, 4)[:, :3].astype(float)
    q += vs
    m = {"verts": verts, "tt": [], "tq": [], "ct": [], "cq": []}
    for key, size in (("tt", 16), ("tq", 20), ("ct", 20), ("cq", 24)):
        c, page = struct.unpack_from("<HH", u, q)
        q += 4
        m[key + "_page"] = page
        for k in range(c):
            p = u[q + size * k:q + size * (k + 1)]
            idx = [x // 8 for x in struct.unpack_from("<4H", p)]
            if key == "tt":
                m["tt"].append((idx[:3], [(p[8], p[9]), (p[12], p[13]), (p[14], p[15])], struct.unpack_from("<H", p, 10)[0]))
            elif key == "tq":
                m["tq"].append((idx, [(p[8], p[9]), (p[12], p[13]), (p[14], p[15]), (p[16], p[17])],
                                struct.unpack_from("<H", p, 10)[0]))
            elif key == "ct":
                m["ct"].append((idx[:3], [tuple(p[8 + 4 * j:11 + 4 * j]) for j in range(3)]))
            else:
                m["cq"].append((idx, [tuple(p[8 + 4 * j:11 + 4 * j]) for j in range(4)]))
        q += c * size
    m["end"] = q
    return m


def read_tim(u: bytes, t: int) -> dict:
    magic, flags = struct.unpack_from("<II", u, t)
    assert magic == 0x10, "not a TIM"
    bpp = {0: 4, 1: 8, 2: 16, 3: 24}[flags & 3]
    q = t + 8
    clut = None
    if flags & 8:
        bl, cx, cy, cw, ch = struct.unpack_from("<I4H", u, q)
        raw = np.frombuffer(u, "<u2", cw * ch, q + 12).reshape(ch, cw)
        clut = {"x": cx, "y": cy, "rows": raw}
        q += bl
    bl, ix, iy, iw, ih = struct.unpack_from("<I4H", u, q)
    pix = np.frombuffer(u, np.uint8, iw * 2 * ih, q + 12).reshape(ih, iw * 2)
    if bpp == 4:
        idx = np.zeros((ih, iw * 4), np.uint8)
        idx[:, 0::2] = pix & 15
        idx[:, 1::2] = pix >> 4
    elif bpp == 8:
        idx = pix
    else:
        raise NotImplementedError("direct-colour TIM")
    return {"bpp": bpp, "x": ix, "y": iy, "idx": idx, "clut": clut}


def _c15(v: np.ndarray, stp_black_transparent: bool = True) -> np.ndarray:
    r, g, b = (v & 31), (v >> 5) & 31, (v >> 10) & 31
    a = np.where((v == 0) & stp_black_transparent, 0, 255)
    return np.stack([r * 255 // 31, g * 255 // 31, b * 255 // 31, a], -1).astype(np.uint8)


def tim_rgba(tim: dict, row: int) -> np.ndarray:
    pal = _c15(tim["clut"]["rows"][row].astype(np.int64))
    return pal[tim["idx"]]


def read_battle_model(lzs_bytes: bytes) -> dict:
    u = lzs(lzs_bytes)
    ns = struct.unpack_from("<I", u)[0]
    offs = list(struct.unpack_from(f"<{ns}I", u, 4))
    base = offs[0]
    nb = struct.unpack_from("<I", u, base)[0]
    bones = []
    for i in range(nb + 1):
        p, ln, o = struct.unpack_from("<HhI", u, base + 4 + 8 * i)
        bones.append({"parent": p if i else None, "length": ln, "mesh": read_mesh(u, base + o) if o else None})
    # sections after the animations: the TIM (magic 0x10, flags 8/9) and the weapons
    tim_i = next(i for i in range(2, ns) if struct.unpack_from("<II", u, offs[i]) in ((0x10, 8), (0x10, 9)))
    anims = offs[2:tim_i]
    weapons = []
    for i in range(tim_i + 1, ns):
        o = offs[i]
        _z, _p, wl, wo = struct.unpack_from("<IHhI", u, o)
        weapons.append({"length": wl, "mesh": read_mesh(u, o + wo)})
    return {"raw": u, "sections": offs, "bones": bones, "anims": anims, "tim": read_tim(u, offs[tim_i]),
            "weapons": weapons}


# ---------------------------------------------------------------- animation

class _Bits:
    def __init__(self, d: bytes):
        self.d, self.p = d, 0

    def get(self, n: int, signed: bool = True) -> int:
        v = 0
        for _ in range(n):
            byte = self.d[self.p >> 3] if (self.p >> 3) < len(self.d) else 0
            v = (v << 1) | ((byte >> (7 - (self.p & 7))) & 1)
            self.p += 1
        if signed and n and v & (1 << (n - 1)):
            v -= 1 << n
        return v

    def offset(self) -> int:                               # 1 + 7 or 1 + 16 bits
        return self.get(7) if not self.get(1, False) else self.get(16)

    def delta(self, key: int) -> int:
        if not self.get(1, False):
            return 0
        t = self.get(3, False)
        if t == 0:
            return -1 << key
        if t == 7:
            return self.get(12 - key) << key
        v = self.get(t)
        v = v - (1 << (t - 1)) if v < 0 else v + (1 << (t - 1))
        return v << key


def read_animation(u: bytes, off: int, nbones: int) -> list[dict]:
    """PSX battle animation -> frames [{"pos": (x, y, z), "rot": [(rx, ry, rz) degrees] * (nbones + 1)}]."""
    frames, size, key = struct.unpack_from("<HHB", u, off)
    if size < 11:
        return []
    b = _Bits(u[off + 5:off + 5 + size])
    out = []
    pos = [0, 0, 0]
    rot = [[0, 0, 0] for _ in range(nbones + 1)]
    for f in range(frames):
        if f == 0:
            pos = [b.get(16) for _ in range(3)]
            rot = [[b.get(12 - key) << key for _ in range(3)] for _ in range(nbones + 1)]
        else:
            if b.p // 8 >= size - 1:
                break
            pos = [pos[k] + b.offset() for k in range(3)]
            for r in rot:
                for k in range(3):
                    r[k] += b.delta(key)
        out.append({"pos": tuple(pos), "rot": [tuple((v % 4096) * 360.0 / 4096 for v in r) for r in rot],
                    "bits": b.p})
    return out


def _rot(rx, ry, rz) -> np.ndarray:
    x, y, z = map(math.radians, (rx, ry, rz))
    Rx = np.array([[1, 0, 0], [0, math.cos(x), -math.sin(x)], [0, math.sin(x), math.cos(x)]])
    Ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    Rz = np.array([[math.cos(z), -math.sin(z), 0], [math.sin(z), math.cos(z), 0], [0, 0, 1]])
    return Ry @ Rx @ Rz


def pose(bones: list[dict], frame: dict | None) -> list[np.ndarray]:
    """World matrix (column-vector 4x4) at the START of each bone for one animation frame (None = all zero)."""
    W = []
    for i, bn in enumerate(bones):
        L = np.eye(4)
        if frame:
            L[:3, :3] = _rot(*frame["rot"][i])
        if bn["parent"] is None:
            if frame:
                L[:3, 3] = frame["pos"]
            W.append(L)
            continue
        P = W[bn["parent"]].copy()
        T = np.eye(4)
        T[2, 3] = bones[bn["parent"]]["length"]
        W.append(P @ T @ L)
    return W


# ---------------------------------------------------------------- glTF

def _png(img: np.ndarray) -> str:
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(img, "RGBA").save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


class _Atlas:
    """Gouraud polygons -> 4x4 texel cells (corners at texel centres, colours painted bilinearly)."""
    CELL = 4

    def __init__(self, size: int = 128):
        self.size = size
        self.per = size // self.CELL
        self.pages: list[np.ndarray] = []
        self.n = 0

    def add(self, cols: list[tuple]) -> tuple[int, list[tuple[float, float]]]:
        k = self.n % (self.per * self.per)
        if k == 0:
            self.pages.append(np.zeros((self.size, self.size, 4), np.uint8))
        self.n += 1
        page = len(self.pages) - 1
        cx, cy = (k % self.per) * self.CELL, (k // self.per) * self.CELL
        c = [np.array(x, float) for x in cols]
        if len(c) == 3:                                    # tri: A=(0,0) B=(1,0) C=(0,1), D = B + C - A
            c.append(np.clip(c[1] + c[2] - c[0], 0, 255))
        img = self.pages[page]
        n = self.CELL - 1
        for j in range(self.CELL):
            for i in range(self.CELL):
                s, t = i / n, j / n
                v = c[0] * (1 - s) * (1 - t) + c[1] * s * (1 - t) + c[2] * (1 - s) * t + c[3] * s * t
                img[cy + j, cx + i, :3] = np.clip(v, 0, 255)
                img[cy + j, cx + i, 3] = 255
        uv = [((cx + 0.5 + s * n) / self.size, (cy + 0.5 + t * n) / self.size) for s, t in ((0, 0), (1, 0), (0, 1), (1, 1))]
        return page, uv


def to_gltf(model: dict, path: Path, anim: int = 0, rest_frame: int = 0, names: dict | None = None,
            weapon: int | None = None, weapon_bone: int = 13, weapon_xform: list | None = None,
            scale: float = 1.0, animate: bool = True, fill_transparent: bool = True, world: list | None = None) -> dict:
    """Rigid-per-bone glTF. Bind pose = frame `rest_frame` of animation `anim` (or `world`: the bones' world matrices,
    e.g. a field model's pose). Y is flipped (FF7 / PSX is Y-down) so the glTF is +Y up; FF7 +Z (bone axis) stays +Z."""
    u, bones, tim = model["raw"], model["bones"], model["tim"]
    names = names or {}
    nb = len(bones) - 1
    frames = read_animation(u, model["anims"][anim], nb) if anim is not None else []
    W = world if world is not None else pose(bones, frames[rest_frame] if frames else None)
    flip = np.diag([1.0, -1.0, -1.0, 1.0])              # PSX (x right, y down, z fwd) -> glTF (x, y up, z back): 180 deg about X
    Wg = [flip @ w for w in W]
    atlas = _Atlas(128)
    prims: dict[tuple, dict] = {}                          # (kind, page/clut) -> {P, UV, J}
    pageorg = (tim["x"] * 16 // tim["bpp"]) if tim else 0

    def emit(key, pts, uvs, j):
        g = prims.setdefault(key, {"P": [], "UV": [], "J": []})
        g["P"] += pts
        g["UV"] += uvs
        g["J"] += [j] * len(pts)

    meshes = [(i, bn["mesh"], Wg[i]) for i, bn in enumerate(bones) if bn["mesh"]]
    if weapon is not None and model["weapons"]:
        wm = model["weapons"][weapon]["mesh"]
        X = np.array(weapon_xform, float).reshape(4, 4) if weapon_xform is not None else np.eye(4)
        T = np.eye(4)
        T[2, 3] = bones[weapon_bone]["length"]
        meshes.append((weapon_bone, wm, flip @ W[weapon_bone] @ T @ X))
    fill = []                                             # skin colour around the textured face polygons
    for j, m, M in meshes:
        tv = {i for poly in m["tt"] + m["tq"] for i in poly[0]}
        fill += [c for idx, cols in m["ct"] + m["cq"] for i, c in zip(idx, cols) if i in tv]
    fill = np.median(np.array(fill, float), 0).astype(np.uint8) if fill else np.array([200, 160, 130], np.uint8)
    for j, m, M in meshes:
        V = (np.c_[m["verts"], np.ones(len(m["verts"]))] @ M.T)[:, :3] * scale
        for idx, uv, clut in m["tt"] + [(q[0], q[1], q[2]) for q in m["tq"]]:
            row = ((clut >> 6) - tim["clut"]["y"]) if tim and tim["clut"] else 0
            tw = tim["idx"].shape[1]
            th = tim["idx"].shape[0]
            # texpage x origin: the polygon's page (stored in the group header); uv is page-relative
            page_tex = ((m["tt_page"] if len(idx) == 3 else m["tq_page"]) & 15) * 64 * 16 // tim["bpp"]
            ox = page_tex - pageorg
            tuv = [((a + ox + 0.5) / tw, (b + 0.5) / th) for a, b in uv]
            order = [(0, 1, 2)] if len(idx) == 3 else [(0, 1, 2), (1, 3, 2)]
            for tri in order:
                emit(("tex", row), [V[idx[k]] for k in tri], [tuv[k] for k in tri], j)
        for idx, cols in m["ct"] + m["cq"]:
            page, cuv = atlas.add(cols)
            order = [(0, 1, 2)] if len(idx) == 3 else [(0, 1, 2), (1, 3, 2)]
            for tri in order:
                emit(("col", page), [V[idx[k]] for k in tri], [cuv[k] for k in tri], j)
    blob = bytearray()
    views, accs = [], []

    def add(arr, comp, typ, target=None, minmax=False):
        nonlocal blob
        blob += bytes((-len(blob)) % 4)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": arr.nbytes, **({"target": target} if target else {})})
        blob += arr.tobytes()
        a = {"bufferView": len(views) - 1, "componentType": comp, "count": len(arr), "type": typ}
        if minmax:
            a["min"], a["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accs.append(a)
        return len(accs) - 1
    images, textures, mats, gprims = [], [], [], []
    img_of = {}
    for key, g in prims.items():
        if key not in img_of:
            if key[0] == "tex":                           # PSX colour 0 = see-through: bake the skin under it
                img = tim_rgba(tim, key[1]).copy()
                if fill_transparent:
                    img[img[..., 3] == 0] = np.r_[fill, 255]
            else:
                img = atlas.pages[key[1]]
            images.append({"uri": _png(img)})
            textures.append({"source": len(images) - 1, "sampler": 0})
            img_of[key] = len(textures) - 1
        mats.append({"name": f"{key[0]}{key[1]}", "pbrMetallicRoughness": {"baseColorTexture": {"index": img_of[key]},
                     "metallicFactor": 0, "roughnessFactor": 0.9}, "doubleSided": True,
                     **({"alphaMode": "MASK", "alphaCutoff": 0.5} if key[0] == "tex" and not fill_transparent else {})})
        P = np.array(g["P"], np.float32)
        # PSX winding is clockwise with Y down; after the Y/Z flip triangles stay front-facing CCW -> keep order
        tri = P.reshape(-1, 3, 3)
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
        N = np.repeat(n, 3, 0).astype(np.float32)
        J = np.zeros((len(P), 4), np.uint16)
        J[:, 0] = g["J"]
        Wt = np.zeros((len(P), 4), np.float32)
        Wt[:, 0] = 1
        gprims.append({"attributes": {"POSITION": add(P, 5126, "VEC3", 34962, True), "NORMAL": add(N, 5126, "VEC3", 34962),
                                      "TEXCOORD_0": add(np.array(g["UV"], np.float32), 5126, "VEC2", 34962),
                                      "JOINTS_0": add(J, 5123, "VEC4", 34962), "WEIGHTS_0": add(Wt, 5126, "VEC4", 34962)},
                       "material": len(mats) - 1})
    nodes = []
    for i, bn in enumerate(bones):
        if bn["parent"] is None:
            L = Wg[i]
        else:
            L = np.linalg.inv(Wg[bn["parent"]]) @ Wg[i]
        L = L.copy()
        L[:3, 3] *= scale
        nodes.append({"name": names.get(i, f"j{i:02d}"), "matrix": L.T.reshape(16).tolist()})
    for i, bn in enumerate(bones):
        if bn["parent"] is not None:
            nodes[bn["parent"]].setdefault("children", []).append(i)
    ibm = np.zeros((len(bones), 16), np.float32)
    for i in range(len(bones)):
        w = Wg[i].copy()
        w[:3, 3] *= scale
        ibm[i] = np.linalg.inv(w).T.reshape(16)
    nodes.append({"name": "ff7_model", "mesh": 0, "skin": 0})
    gl = {"asset": {"version": "2.0", "generator": "gbox ff7_models"}, "scene": 0,
          "scenes": [{"nodes": [0, len(nodes) - 1]}], "nodes": nodes,
          "meshes": [{"name": "ff7_model", "primitives": gprims}],
          "skins": [{"joints": list(range(len(bones))), "inverseBindMatrices": add(ibm, 5126, "MAT4"), "skeleton": 0}],
          "materials": mats, "images": images, "textures": textures,
          "samplers": [{"magFilter": 9728, "minFilter": 9728, "wrapS": 33071, "wrapT": 33071}],
          "accessors": accs, "bufferViews": views}
    if animate and len(frames) > 1:                       # glTF animation (rotations; root translation)
        fps = 30.0
        times = np.arange(len(frames), dtype=np.float32) / fps
        tin = add(times.reshape(-1, 1), 5126, "SCALAR")
        accs[tin]["min"], accs[tin]["max"] = [float(times[0])], [float(times[-1])]
        chans, samps = [], []
        for i, bn in enumerate(bones):
            q = []
            for fr in frames:
                Wf = pose(bones, fr)
                Lf = (flip @ Wf[i]) if bn["parent"] is None else np.linalg.inv(flip @ Wf[bn["parent"]]) @ (flip @ Wf[i])
                q.append(_quat(Lf[:3, :3]))
            samps.append({"input": tin, "output": add(np.array(q, np.float32), 5126, "VEC4"), "interpolation": "LINEAR"})
            chans.append({"sampler": len(samps) - 1, "target": {"node": i, "path": "rotation"}})
        tr = np.array([(flip @ pose(bones, fr)[0])[:3, 3] * scale for fr in frames], np.float32)
        samps.append({"input": tin, "output": add(tr, 5126, "VEC3"), "interpolation": "LINEAR"})
        chans.append({"sampler": len(samps) - 1, "target": {"node": 0, "path": "translation"}})
        gl["animations"] = [{"name": f"anim{anim:02d}", "channels": chans, "samplers": samps}]
    gl["buffers"] = [{"byteLength": len(blob), "uri": "data:application/octet-stream;base64," + base64.b64encode(bytes(blob)).decode()}]
    Path(path).write_text(json.dumps(gl))
    return {"bones": len(bones), "tris": sum(len(g["P"]) // 3 for g in prims.values()), "materials": len(mats),
            "atlas_pages": len(atlas.pages), "frames": len(frames)}


def _quat(R: np.ndarray) -> list:
    t = np.trace(R)
    if t > 0:
        s = math.sqrt(t + 1) * 2
        return [(R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s, 0.25 * s]
    i = int(np.argmax(np.diag(R)))
    j, k = (i + 1) % 3, (i + 2) % 3
    s = math.sqrt(1 + R[i, i] - R[j, j] - R[k, k]) * 2
    q = [0.0] * 4
    q[i] = 0.25 * s
    q[j] = (R[j, i] + R[i, j]) / s
    q[k] = (R[k, i] + R[i, k]) / s
    q[3] = (R[k, j] - R[j, k]) / s
    return q


def from_disc(path: str | Path, name: str = "ENEMY6/CLOUD.LZS") -> dict:
    from gbox.psxdisc import PSXDisc
    return read_battle_model(PSXDisc(str(path)).read(name))


# ---------------------------------------------------------------- field models (PSX FIELD/*.BCX)
#
# Reverse-engineered from FIELD/CLOUD.BCX (LZS, same codec as the battle files). Decompressed:
#   u32 size, u32 header offset H.  H: u16 0xFF01, u8 bones, u8 parts, u8 animations, 17 x 0, u16 scale (512),
#   u16 parts offset, u16 animations offset (both relative to the skeleton), u32 skeleton offset | 0x80000000.
#   bone (4 B)      s16 length, u8 parent (255 = none), u8 has mesh.  Bone i sits at its parent's origin + (0, 0, length)
#                   in the parent's frame (own length, like Parasite Eve), then rotates: M_i = M_p T(0,0,len_i) Ry Rx Rz.
#   part (32 B)     u8 1, u8 bone, u8 vertices, u8 texcoords, u8 counts x 8 (quad col+tex, tri col+tex, quad mono+tex,
#                   tri mono+tex, tri mono, quad mono, tri col, quad col), u8 flags, u8 controls, u16 poly offset,
#                   u16 texcoord offset, u16 flags offset, u16 control offset, u16 GPU buffer bytes (G3 28, G4 36,
#                   GT3 40, GT4 52 per poly), u32 vertex block offset | 0x80000000, u32 0.
#   vertex block    u32 0, vertices (s16 x, y, z, 0), then (poly offset, from the block) polygons in count order:
#                   col+tex quad 24 B (4 x u8 vertex, 4 x RGBn, 4 x u8 texcoord), col+tex tri 20 B, col tri 16 B
#                   (3 x u8 vertex + pad, 3 x RGBn), col quad 20 B. n = the vertex's lighting normal index (per vertex).
#   animation (16)  u16 frames, u8 channels, u8 per-frame translation tracks, u8 static translations, u8 per-frame
#                   rotation tracks, u16 x 3 offsets (per-frame translations s16, static translations s16, per-frame
#                   rotations u8) from the data, u32 data | 0x80000000.  data: u32, then per channel (= bone) 8 B:
#                   u8 flags (bit 0..2 rotation x/y/z per frame, bit 4..6 translation x/y/z per frame), rx, ry, rz
#                   (static value or track index; rotations in 1/256 turn), tx, ty, tz (track / static index, 255 =
#                   none), pad.
FIELD_BCX = {"CLOUD": "Cloud Strife (field)", "TIFA": "Tifa Lockhart (field)", "EARITH": "Aerith Gainsborough (field)",
             "RED": "Red XIII (field)", "CID": "Cid Highwind (field)", "YUFI": "Yuffie Kisaragi (field)",
             "KETCY": "Cait Sith (field)", "VINCENT": "Vincent Valentine (field)", "BALLET": "Barret Wallace (field)"}
FIELD_POLYS = (("qct", 24, 4, True), ("tct", 20, 3, True), ("qmt", 0, 4, True), ("tmt", 0, 3, True),
               ("tm", 0, 3, False), ("qm", 0, 4, False), ("tc", 16, 3, False), ("qc", 20, 4, False))
FIELD_PACKET = {"qct": 52, "tct": 40, "tc": 28, "qc": 36}


def read_field_model(bcx: bytes, compressed: bool = True) -> dict:
    u = lzs(bcx) if compressed else bytes(bcx)
    h = struct.unpack_from("<I", u, 4)[0]
    nb, npart, nanim = u[h + 2], u[h + 3], u[h + 4]
    scale, op, oa = struct.unpack_from("<HHH", u, h + 0x16)
    osk = struct.unpack_from("<I", u, h + 0x1C)[0] & 0x7FFFFFFF
    bones = []
    for i in range(nb):
        ln, par, mesh = struct.unpack_from("<hBB", u, osk + 4 * i)
        bones.append({"length": ln, "parent": None if par == 255 else par, "has_mesh": mesh})
    parts = []
    for p in range(npart):
        q = osk + op + 32 * p
        f = struct.unpack_from("<12B2B5H2I", u, q)
        cnt = dict(zip([k for k, *_ in FIELD_POLYS], f[4:12]))
        ovx = f[19] & 0x7FFFFFFF
        part = {"raw": u[q:q + 32], "bone": f[1], "nv": f[2], "ntc": f[3], "counts": cnt, "flags": f[12],
                "controls": f[13], "opoly": f[14], "otc": f[15], "ofl": f[16], "octl": f[17], "buffer": f[18], "ovx": ovx}
        part["verts"] = np.frombuffer(u, "<i2", 4 * f[2], ovx + 4).reshape(-1, 4)[:, :3].astype(float)
        polys, o = [], ovx + f[14]
        for key, size, n, tex in FIELD_POLYS:
            for _ in range(cnt[key]):
                if not size:
                    raise NotImplementedError(f"field polygon type {key} (no sample yet)")
                polys.append({"kind": key, "idx": list(u[o:o + n]),
                              "cols": [tuple(u[o + 4 + 4 * j:o + 7 + 4 * j]) for j in range(n)],
                              "nrm": [u[o + 7 + 4 * j] for j in range(n)],
                              "tc": list(u[o + 4 + 4 * n:o + 4 + 4 * n + n]) if tex else None})
                o += size
        part["polys"] = polys
        parts.append(part)
    anims = [field_anim(u, osk + oa + 16 * k) for k in range(nanim)]
    return {"raw": u, "header": h, "skeleton": osk, "parts_off": op, "anims_off": oa, "scale": scale, "bones": bones,
            "parts": parts, "anims": anims}


def field_anim(u: bytes, off: int) -> list[dict]:
    """-> frames [{"pos": root (x, y, z), "rot": [(rx, ry, rz) in 4096 units] per bone}]."""
    nf, nch, _nft, _nst, _nfr, oft, ost, ofr, data = struct.unpack_from("<HBBBBHHHI", u, off)
    data &= 0x7FFFFFFF
    ch = [u[data + 4 + 8 * c:data + 12 + 8 * c] for c in range(nch)]
    out = []
    for f in range(nf):
        rot, pos = [], [0, 0, 0]
        for c, e in enumerate(ch):
            fl = e[0]
            rot.append(tuple((u[data + ofr + e[1 + a] * nf + f] if fl >> a & 1 else e[1 + a]) * 16 for a in range(3)))
            for a in range(3):
                i = e[4 + a]
                if i == 255:
                    continue
                pos[a] = (struct.unpack_from("<h", u, data + oft + 2 * (i * nf + f))[0] if fl >> (4 + a) & 1
                          else struct.unpack_from("<h", u, data + ost + 2 * i)[0])
        out.append({"pos": tuple(pos), "rot": rot})
    return out


def field_pose(bones: list[dict], frame: dict | None) -> list[np.ndarray]:
    """World matrices (column vectors) of the field skeleton for one frame (None = zero rotations)."""
    W = []
    for i, b in enumerate(bones):
        L = np.eye(4)
        if frame:
            L[:3, :3] = _rot(*(v * 360 / 4096 for v in frame["rot"][i]))
        T = np.eye(4)
        T[2, 3] = b["length"]
        if b["parent"] is None:
            if frame:
                T[:3, 3] += frame["pos"]
            W.append(T @ L)
        else:
            W.append(W[b["parent"]] @ T @ L)
    return W


def field_to_battle_dict(fm: dict) -> dict:
    """The field model in read_battle_model()'s shape (bones with meshes, colour polygons only), for to_gltf."""
    bones = [{"parent": b["parent"], "length": 0, "mesh": None} for b in fm["bones"]]
    for p in fm["parts"]:
        m = {"verts": p["verts"], "tt": [], "tq": [], "ct": [], "cq": [], "tt_page": 0, "tq_page": 0}
        for pl in p["polys"]:
            (m["cq"] if len(pl["idx"]) == 4 else m["ct"]).append((pl["idx"], pl["cols"]))
        bones[p["bone"]]["mesh"] = m
    return {"raw": fm["raw"], "bones": bones, "anims": [], "tim": None, "weapons": []}


def field_to_gltf(fm: dict, path: Path, anim: int = 0, frame: int = 0, scale: float = 1.0) -> dict:
    """Rigid glTF of a field model, bind pose = frame `frame` of animation `anim` (no glTF animation)."""
    W = field_pose(fm["bones"], fm["anims"][anim][frame] if fm["anims"] else None)
    return to_gltf(field_to_battle_dict(fm), path, anim=None, names={i: f"j{i:02d}" for i in range(len(fm["bones"]))},
                   scale=scale, animate=False, world=W)


def field_from_disc(path: str | Path, name: str = "CLOUD") -> dict:
    from gbox.psxdisc import PSXDisc
    return read_field_model(PSXDisc(str(path)).read(f"FIELD/{name}.BCX"))
