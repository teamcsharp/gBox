"""Enter the Matrix (PS2 SLUS-20454) character models: ``actors\\*.dcn`` "DC patch models" -> rigged, textured GLB.

Layout recovered from the owned disc and the model loader in SLUS_204.54 (``0x167da0``, allocation tags
``DCPatchModel`` / ``DCjointoffsets`` / ``DCjointpositions`` / ``DC2CharTexture`` / ``DC2CharMaterial`` /
``DCModelConfigs`` / ``DCModelConfigData``); every one of the 275 ``.dcn`` files the model table names parses to its last byte.
All little endian; ``qw`` = 16 bytes.

    0x00 u32 skeleton checksum      the animation set's skeleton must match ("DC2 Model checksum error"); 0x002e5ea3
                                    in every human (and weapon) model: one shared 89-joint skeleton
    0x04 char name[16]   0x14 f32, 0x18 f32 (1.0)   0x1c u32 joints   0x24 u32 materials (0x48 records)
    0x2c u32 textures (0x40 records)   0x34 u32 configs   0x40 u32 meshes   (0x20/0x28/0x30/0x38/0x3c/0x44: runtime)
    0x48 u32 mesh pointer slots[meshes]          (runtime; garbage in the file)
         f32 joint_offsets[joints][3]            offset from the parent joint, in the parent's rest frame
         f32 joint_positions[joints][3]          rest (bind) position, model space
    meshes: 0x50 header {char name[20] (stale exporter buffer), u32 -1, u32 render flags (64 opaque ...),
         u32 0x78001045, u32 index, u32 count[4], i32 joint_group, u32 n_group_joints, u32 bytes[4], u32 runtime}
         + i32 group_joints[(n + 3) & ~3] + four blocks (present when count[k]):
         A  bicubic Bezier quad patches   4 header qw {f32 u, f32 v, u32 slot (qw0) / size in qw (qw1), 0}
            (corner UVs of control points 0, 12, 15, 3) + 16 control points, row-major 4 x 4
         B  cubic Bezier triangle patches 3 header qw (corner UVs of control points 0, 3, 6; slot in qw0, size in
            qw1) + 10 control points: corners 0 / 3 / 6, edge points 1 2 / 4 5 / 7 8 in loop order, centre 9
         C  triangles: header qw {u32 slot, u32 size (10), u32 vertices (3), 0}, per vertex a UV qw {u, v, 0, 0}
         D  never used on this disc (refused)
         control point / vertex: qw {x, y, z, u32 joint * 4}, qw {nx, ny, nz, u32 extra}, extra x qw
         {u32 joint * 4, f32 w, u32 joint * 4, f32 w} (characters: 0 or 1 = two-joint skinning; 2 in three vehicles)
    textures: 0x40 headers {char name[32] (.tga), u32 w, u32 h, u32 -, u32 pixel bytes, u32 -, u32 palette bytes,
         u32 -, u32 -} then per texture pixels (linear, 4-bit low nibble first or 8-bit) + palette (RGBA8888, alpha
         0..255 linear; the loader halves alpha and CSM1-swizzles 256-colour palettes itself); no palette = direct
         colour (16-bit A1B5G5R5 in Cop_LP, 32-bit by size)
    materials: 0x48 {char name[32], i32 texture, i32 -, i32 environment texture, f32 flag (-1 = reflective mask),
         f32 x5, f32}
    configs: 0x14 {ptr, u32 mesh count, ptr, ptr, ptr} x n, then per config i32 meshes[count] + i32 slot_to_material
         [materials] (-1 = hidden). Config 0 is the full model, later ones LODs / variants.

Model space is left handed (+Y up, the character faces -Z, its right hand is at -X) in centimetres; the GLB is
mirrored to glTF's convention (z negated: facing +Z, left = +X) and scaled to metres. Patches are tessellated
(Bernstein basis, 3 x 3 quads / 9 triangles per patch by default); skin weights are the patch basis applied to the
control points' weights, cut to the 4 strongest joints.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

import numpy as np

from . import etm_inventory as inv

HEADER, SUB_HDR, TEX_HDR, MAT_SIZE, CFG_SIZE = 0x48, 0x50, 0x40, 0x48, 0x14
QUAD_UV_CP = (0, 12, 15, 3)                   # header UV k belongs to control point QUAD_UV_CP[k]
TRI_CORNERS = (0, 3, 6)
GLTF_SCALE = 0.01                             # centimetres -> metres
TESS = 3
MAX_COUNT = 1 << 16

# the shared skeleton (checksum 0x002e5ea3): parent order is breadth first; names from the rest positions
JOINT_NAMES = {0: "pelvis", 1: "l_thigh", 2: "spine", 3: "r_thigh", 4: "l_thigh_twist", 5: "r_thigh_twist",
               6: "spine1", 7: "chest", 8: "l_knee", 9: "r_knee", 10: "l_ankle", 11: "l_clavicle", 12: "neck",
               13: "r_ankle", 14: "r_clavicle", 15: "head", 16: "l_toe", 17: "l_shoulder", 18: "r_toe",
               19: "r_shoulder", 20: "l_upperarm_twist", 21: "r_upperarm_twist", 22: "l_elbow", 23: "r_elbow",
               24: "l_forearm_twist", 25: "r_forearm_twist", 26: "l_wrist", 27: "r_wrist", 28: "r_hand", 29: "l_hand"}
SHARED_PARENTS = ([-1, 0, 0, 0, 1, 3, 2, 6, 4, 5, 8, 7, 7, 9, 7, 12, 10, 11, 13, 14, 17, 19, 20, 21, 22, 23, 24, 25,
                   27, 26] + [28] * 5 + list(range(30, 40)) + [29] * 5 + list(range(45, 55)) + [15] * 29)
ROLE_JOINTS = {"hip": 0, "chest": 7, "neck": 12, "head": 15, "l_clav": 11, "r_clav": 14, "l_upper": 17, "l_fore": 22,
               "l_hand": 26, "r_upper": 19, "r_fore": 23, "r_hand": 27, "l_thigh": 1, "l_shin": 8, "l_foot": 10,
               "r_thigh": 3, "r_shin": 9, "r_foot": 13}


class FormatError(ValueError):
    pass


def joint_name(i: int) -> str:
    if i in JOINT_NAMES:
        return JOINT_NAMES[i]
    if 30 <= i < 45:
        return f"r_finger{i - 30:02d}"
    if 45 <= i < 60:
        return f"l_finger{i - 45:02d}"
    return f"face{i - 60:02d}" if 60 <= i < 89 else f"joint{i:02d}"


def _u32(b, o):
    if o < 0 or o + 4 > len(b):
        raise FormatError(f"read past the end at 0x{o:x}")
    return struct.unpack_from("<I", b, o)[0]


def _cstr(b: bytes) -> str:
    return b.split(b"\0")[0].decode("latin-1")


# ---------------------------------------------------------------- parsing
def _vertices(b: bytes, r: int, n: int, uvs: bool, nj: int) -> tuple[dict, int]:
    P = np.zeros((n, 3), np.float32)
    Nn = np.zeros((n, 3), np.float32)
    UV = np.zeros((n, 2), np.float32)
    J = np.zeros((n, 4), np.int32)
    W = np.zeros((n, 4), np.float32)
    for v in range(n):
        if uvs:
            if r + 16 > len(b):
                raise FormatError(f"vertex UV at 0x{r:x} past the end")
            UV[v] = struct.unpack_from("<2f", b, r)
            r += 16
        if r + 32 > len(b):
            raise FormatError(f"vertex at 0x{r:x} past the end")
        x, y, z, bone = struct.unpack_from("<3fI", b, r)
        nx, ny, nz, extra = struct.unpack_from("<3fI", b, r + 16)
        r += 32
        if bone % 4 or bone // 4 >= nj:
            raise FormatError(f"vertex at 0x{r - 32:x}: joint slot {bone} outside the {nj}-joint skeleton")
        if extra > 2:
            raise FormatError(f"vertex at 0x{r - 32:x}: {extra} weight quadwords (0..2 seen)")
        P[v], Nn[v] = (x, y, z), (nx, ny, nz)
        if r + 16 * extra > len(b):
            raise FormatError(f"vertex weights at 0x{r:x} past the end")
        J[v, 0], W[v, 0] = bone // 4, 1.0
        for k in range(extra):
            b0, w0, b1, w1 = struct.unpack_from("<IfIf", b, r)
            r += 16
            if b0 % 4 or b1 % 4 or b0 // 4 >= nj or b1 // 4 >= nj:
                raise FormatError(f"vertex weights at 0x{r - 16:x}: joint slot outside the skeleton")
            J[v, 2 * k:2 * k + 2], W[v, 2 * k:2 * k + 2] = (b0 // 4, b1 // 4), (w0, w1)
    return {"pos": P, "nrm": Nn, "uv": UV, "joints": J, "weights": W}, r


def parse_dcn(b: bytes) -> dict:
    """One .dcn file -> header, skeleton, meshes (patches / triangles), textures, materials, configs. Every count,
    size and offset is bounds-checked and the walk must end exactly at the end of the file."""
    if len(b) < HEADER:
        raise FormatError("shorter than the 0x48-byte header")
    checksum = _u32(b, 0)
    name = _cstr(b[4:0x14])
    f14, f18 = struct.unpack_from("<2f", b, 0x14)
    nj, nmat, ntex, ncfg, nmesh = (_u32(b, o) for o in (0x1C, 0x24, 0x2C, 0x34, 0x40))
    for what, n in (("joints", nj), ("materials", nmat), ("textures", ntex), ("configs", ncfg), ("meshes", nmesh)):
        if n > MAX_COUNT:
            raise FormatError(f"implausible {what} count {n}")
    p = HEADER + 4 * nmesh
    if p + 24 * nj > len(b):
        raise FormatError("joint arrays past the end")
    J1 = np.frombuffer(b, np.float32, 3 * nj, p).reshape(nj, 3).copy()
    J2 = np.frombuffer(b, np.float32, 3 * nj, p + 12 * nj).reshape(nj, 3).copy()
    p += 24 * nj
    meshes = []
    for s in range(nmesh):
        if p + SUB_HDR > len(b):
            raise FormatError(f"mesh {s} header past the end")
        w = struct.unpack_from("<20I", b, p)
        counts, sizes = w[9:13], w[15:19]
        group, ngj = struct.unpack_from("<i", b, p + 0x34)[0], w[14]
        if ngj > 256:
            raise FormatError(f"mesh {s}: {ngj} group joints")
        pad = ((ngj + 3) & ~3) if ngj else 0
        gj = list(struct.unpack_from(f"<{ngj}i", b, p + SUB_HDR)) if ngj else []
        q = p + SUB_HDR + 4 * pad
        mesh = {"index": s, "offset": p, "name": _cstr(b[p:p + 0x14]), "words": list(w), "flags": w[6],
                "group": group, "group_joints": gj, "counts": list(counts), "patches": []}
        for k in range(4):
            if not counts[k]:
                continue
            if k == 3:
                raise FormatError(f"mesh {s}: block D (never seen on this disc) is present")
            end = q + sizes[k]
            if end > len(b):
                raise FormatError(f"mesh {s} block {'ABC'[k]} past the end")
            n = 0
            while q < end:
                if k == 2:
                    slot, size, nv, _z = struct.unpack_from("<4I", b, q)
                    if nv != 3 or size < 1:
                        raise FormatError(f"mesh {s}: triangle packet at 0x{q:x} has {nv} vertices")
                    vx, r = _vertices(b, q + 16, 3, True, nj)
                    pk = {"kind": "tri3", "slot": slot, **vx}
                else:
                    nh, ncp = (4, 16) if k == 0 else (3, 10)
                    hdr = [struct.unpack_from("<2f2I", b, q + 16 * i) for i in range(nh)]
                    slot, size = hdr[0][2], hdr[1][2]
                    vx, r = _vertices(b, q + 16 * nh, ncp, False, nj)
                    pk = {"kind": "quad" if k == 0 else "tri", "slot": slot,
                          "corner_uv": np.array([h[:2] for h in hdr], np.float32), **vx}
                if size < 1 or r != q + 16 * size:
                    raise FormatError(f"mesh {s}: packet at 0x{q:x} declares {size} qw, its vertices take "
                                      f"{(r - q) // 16}")
                mesh["patches"].append(pk)
                q = r
                n += 1
            if q != end:
                raise FormatError(f"mesh {s} block {'ABC'[k]} overruns its {sizes[k]} bytes")
            if n != counts[k]:
                raise FormatError(f"mesh {s} block {'ABC'[k]}: {n} packets, header says {counts[k]}")
        meshes.append(mesh)
        p = q
    tex = []
    if p + TEX_HDR * ntex > len(b):
        raise FormatError("texture headers past the end")
    q = p + TEX_HDR * ntex
    for i in range(ntex):
        h = b[p + TEX_HDR * i:p + TEX_HDR * (i + 1)]
        tw, th, _x, dsz, _p, psz = struct.unpack_from("<6I", h, 0x20)
        bpp = {(64, tw * th // 2): 4, (1024, tw * th): 8, (0, tw * th * 2): 16, (0, tw * th * 4): 32}.get((psz, dsz))
        if not (tw and th and tw <= 1024 and th <= 1024) or bpp is None:
            raise FormatError(f"texture {i} ({_cstr(h[:0x20])}): {tw}x{th}, {dsz} pixel / {psz} palette bytes")
        if q + dsz + psz > len(b):
            raise FormatError(f"texture {i} data past the end")
        tex.append({"name": _cstr(h[:0x20]), "w": tw, "h": th, "bpp": bpp, "header": h,
                    "pixels": b[q:q + dsz], "palette": b[q + dsz:q + dsz + psz], "offset": q})
        q += dsz + psz
    p = q
    if p + MAT_SIZE * nmat + CFG_SIZE * ncfg > len(b):
        raise FormatError("materials / configs past the end")
    mats = []
    for i in range(nmat):
        r = b[p:p + MAT_SIZE]
        t = struct.unpack_from("<3i", r, 0x20)
        for x in t:
            if x >= ntex:
                raise FormatError(f"material {i} uses texture {x} of {ntex}")
        mats.append({"name": _cstr(r[:0x20]), "textures": list(t), "params": list(struct.unpack_from("<7f", r, 0x2C)),
                     "raw": r})
        p += MAT_SIZE
    cfg_hdr = [struct.unpack_from("<5I", b, p + CFG_SIZE * i) for i in range(ncfg)]
    p += CFG_SIZE * ncfg
    configs = []
    for c in cfg_hdr:
        n = c[1]
        if n > nmesh or p + 4 * (n + nmat) > len(b):
            raise FormatError(f"config lists past the end ({n} meshes)")
        ms = list(struct.unpack_from(f"<{n}i", b, p))
        p += 4 * n
        sm = list(struct.unpack_from(f"<{nmat}i", b, p))
        p += 4 * nmat
        if any(not 0 <= x < nmesh for x in ms) or any(x >= nmat for x in sm):
            raise FormatError("config refers to a mesh / material that doesn't exist")
        configs.append({"meshes": ms, "slot_material": sm})
    if p != len(b):
        raise FormatError(f"{len(b) - p} unexplained bytes after the configs")
    return {"checksum": checksum, "name": name, "scale": (f14, f18), "joint_offsets": J1, "joint_positions": J2,
            "parents": parents(J1, J2), "meshes": meshes, "textures": tex, "materials": mats, "configs": configs,
            "size": len(b)}


def _fits(J1: np.ndarray, J2: np.ndarray, par: list[int]) -> bool:
    for i, p in enumerate(par):
        L = float(np.linalg.norm(J1[i]))
        if p >= 0 and abs(float(np.linalg.norm(J2[i] - J2[p])) - L) > 2e-3 + 1e-4 * L:
            return False
    return True


def parents(J1: np.ndarray, J2: np.ndarray) -> list[int]:
    """The joint tree. The shared 89-joint skeleton's tree (SHARED_PARENTS) when the file's offsets fit it (every
    human and most props: joints stacked on one point make the distances ambiguous, so it is not re-derived);
    otherwise each joint's parent is the latest earlier joint whose distance equals the joint's offset length."""
    if len(J2) == len(SHARED_PARENTS) and _fits(J1, J2, SHARED_PARENTS):
        return list(SHARED_PARENTS)
    out = [-1] if len(J2) else []
    for i in range(1, len(J2)):
        L = float(np.linalg.norm(J1[i]))
        d = np.abs(np.linalg.norm(J2[:i] - J2[i], axis=1) - L)
        cand = np.where(d < 2e-3 + 1e-4 * L)[0]
        if not len(cand):
            raise FormatError(f"joint {i}: no earlier joint at its offset length {L:.3f}")
        out.append(int(cand[-1]))
    return out


# ---------------------------------------------------------------- textures
def decode_texture(t: dict) -> np.ndarray:
    if t["bpp"] == 32:
        return np.frombuffer(t["pixels"], np.uint8).reshape(t["h"], t["w"], 4).copy()
    if t["bpp"] == 16:                                    # PSMCT16: A1 B5 G5 R5, R in the low bits
        v = np.frombuffer(t["pixels"], "<u2").reshape(t["h"], t["w"]).astype(np.uint32)
        out = np.stack([(v & 31) << 3, ((v >> 5) & 31) << 3, ((v >> 10) & 31) << 3, np.full_like(v, 255)], -1)
        out[..., :3] |= out[..., :3] >> 5
        return out.astype(np.uint8)
    pal = np.frombuffer(t["palette"], np.uint8).reshape(-1, 4)
    d = np.frombuffer(t["pixels"], np.uint8)
    idx = d if t["bpp"] == 8 else np.stack([d & 15, d >> 4], 1).reshape(-1)
    return pal[idx[:t["w"] * t["h"]]].reshape(t["h"], t["w"], 4).copy()


# ---------------------------------------------------------------- tessellation
def _bern3(t: np.ndarray) -> np.ndarray:
    s = 1 - t
    return np.stack([s ** 3, 3 * s * s * t, 3 * s * t * t, t ** 3], -1)


def _tri_grid(n: int):
    pts = [(i, j, n - i - j) for i in range(n, -1, -1) for j in range(n - i, -1, -1)]
    idx = {p: k for k, p in enumerate(pts)}
    tris = []
    for i in range(n):
        for j in range(n - i):
            k = n - i - j
            tris.append((idx[(i, j, k)], idx[(i + 1, j, k - 1)], idx[(i, j + 1, k - 1)]))
            if k >= 2:
                tris.append((idx[(i + 1, j, k - 1)], idx[(i + 1, j + 1, k - 2)], idx[(i, j + 1, k - 1)]))
    bc = np.array(pts, float) / n
    return bc, np.array(tris, int)


def _tri_basis(bc: np.ndarray) -> np.ndarray:
    u, v, w = bc[:, 0], bc[:, 1], bc[:, 2]
    # control point order: c0 (u), e, e, c1 (v), e, e, c2 (w), e, e, centre
    return np.stack([u ** 3, 3 * u * u * v, 3 * u * v * v, v ** 3, 3 * v * v * w, 3 * v * w * w, w ** 3,
                     3 * w * w * u, 3 * w * u * u, 6 * u * v * w], -1)


def _dense_weights(pk: dict, nj: int) -> np.ndarray:
    n = len(pk["pos"])
    D = np.zeros((n, nj), np.float32)
    np.add.at(D, (np.arange(n)[:, None].repeat(pk["joints"].shape[1], 1), pk["joints"]), pk["weights"])
    return D


def tessellate(pk: dict, nj: int, n: int = TESS) -> dict:
    """One patch / triangle -> {pos, nrm, uv, w (dense joint weights), tris} in model space."""
    if pk["kind"] == "tri3":
        return {"pos": pk["pos"].astype(float), "nrm": pk["nrm"].astype(float), "uv": pk["uv"].astype(float),
                "w": _dense_weights(pk, nj).astype(float), "tris": np.array([[0, 1, 2]])}
    D = _dense_weights(pk, nj).astype(float)
    if pk["kind"] == "quad":
        t = np.linspace(0, 1, n + 1)
        B = _bern3(t)
        M = np.einsum("ai,bj->abij", B, B).reshape((n + 1) ** 2, 16)
        s_, t_ = np.meshgrid(t, t, indexing="ij")
        s_, t_ = s_.reshape(-1), t_.reshape(-1)
        c = pk["corner_uv"]                               # header order: cp0, cp12, cp15, cp3
        uv = (((1 - s_) * (1 - t_))[:, None] * c[0] + (s_ * (1 - t_))[:, None] * c[1] + (s_ * t_)[:, None] * c[2]
              + ((1 - s_) * t_)[:, None] * c[3])
        tris = []
        for a in range(n):
            for b_ in range(n):
                v0 = a * (n + 1) + b_
                tris += [(v0, v0 + n + 1, v0 + n + 2), (v0, v0 + n + 2, v0 + 1)]
        tris = np.array(tris, int)
    else:
        bc, tris = _tri_grid(n)
        M = _tri_basis(bc)
        c = pk["corner_uv"]
        uv = bc[:, :1] * c[0] + bc[:, 1:2] * c[1] + bc[:, 2:3] * c[2]
    P = M @ pk["pos"].astype(float)
    Nn = M @ pk["nrm"].astype(float)
    Nn /= np.maximum(np.linalg.norm(Nn, axis=1, keepdims=True), 1e-9)
    return {"pos": P, "nrm": Nn, "uv": uv, "w": M @ D, "tris": tris}


def top4(W: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    k = min(4, W.shape[1])
    J = np.argsort(-W, axis=1)[:, :k]
    w = np.take_along_axis(W, J, 1)
    w = np.where(w > 1e-4, w, 0)
    w /= np.maximum(w.sum(1, keepdims=True), 1e-9)
    return J.astype(np.uint16), w.astype(np.float32)


def to_gltf(p: np.ndarray) -> np.ndarray:
    """Model space (left handed, facing -Z, cm) -> glTF (right handed, facing +Z, m)."""
    q = np.asarray(p, float) * GLTF_SCALE
    q[..., 2] *= -1
    return q


def assemble(m: dict, config: int = 0, n: int = TESS) -> dict:
    """The model's chosen config as glTF-ready primitives (one per material), the skeleton and the checks."""
    nj = len(m["joint_positions"])
    cfg = m["configs"][config] if m["configs"] else {"meshes": list(range(len(m["meshes"]))),
                                                      "slot_material": list(range(len(m["materials"])))}
    groups: dict[int, list] = {}
    counts = {"quad": 0, "tri": 0, "tri3": 0}
    hidden = 0
    for si in cfg["meshes"]:
        for pk in m["meshes"][si]["patches"]:
            counts[pk["kind"]] += 1
            mat = cfg["slot_material"][pk["slot"]] if pk["slot"] < len(cfg["slot_material"]) else -1
            if mat < 0:
                hidden += 1
                continue
            groups.setdefault(mat, []).append(tessellate(pk, nj, n))
    prims, flipped, total = [], 0, 0
    for mat, parts in sorted(groups.items()):
        P = np.concatenate([g["pos"] for g in parts])
        Nn = np.concatenate([g["nrm"] for g in parts])
        UV = np.concatenate([g["uv"] for g in parts])
        W = np.concatenate([g["w"] for g in parts])
        off = np.cumsum([0] + [len(g["pos"]) for g in parts])[:-1]
        T = np.concatenate([g["tris"] + o for g, o in zip(parts, off)])
        Pg, Ng = to_gltf(P), Nn.copy()
        Ng[:, 2] *= -1
        key = np.concatenate([np.round(Pg * 1e4), np.round(UV * 1e4), np.round(Ng * 1e2),
                              np.round(W * 1e3)], 1)
        _u, first, inv_ = np.unique(key, axis=0, return_index=True, return_inverse=True)
        inv_ = inv_.reshape(-1)
        Pg, Ng, UV, W, T = Pg[first], Ng[first], UV[first], W[first], inv_[T]
        T = T[(T[:, 0] != T[:, 1]) & (T[:, 1] != T[:, 2]) & (T[:, 0] != T[:, 2])]
        fn = np.cross(Pg[T[:, 1]] - Pg[T[:, 0]], Pg[T[:, 2]] - Pg[T[:, 0]])
        vn = Ng[T].sum(1)
        flip = (fn * vn).sum(1) < 0
        T[flip] = T[flip][:, ::-1]
        flipped += int(flip.sum())
        total += len(T)
        J, Wt = top4(W)
        prims.append({"material": mat, "pos": Pg, "nrm": Ng, "uv": UV, "joints": J, "weights": Wt, "tris": T})
    allp = np.concatenate([p["pos"] for p in prims]) if prims else np.zeros((0, 3))
    return {"prims": prims, "counts": counts, "hidden_patches": hidden, "triangles": total,
            "flipped": flipped, "height_m": float(np.ptp(allp[:, 1])) if len(allp) else 0.0,
            "joints": [{"name": joint_name(i), "parent": m["parents"][i], "world": to_gltf(m["joint_positions"][i])}
                       for i in range(nj)]}


def roles(m: dict) -> dict[str, str]:
    """{role: joint name} for the shared human skeleton, checked against the rest pose (left joints at +X in glTF
    space, the chain order down each limb); {} for other skeletons."""
    if m["checksum"] != inv.SKELETON_CHECKSUM or len(m["joint_positions"]) != 89:
        return {}
    G = to_gltf(m["joint_positions"])
    par = m["parents"]
    ok = all(G[ROLE_JOINTS[f"l_{r}"]][0] > 0 > G[ROLE_JOINTS[f"r_{r}"]][0]
             for r in ("upper", "fore", "hand", "thigh", "shin", "foot"))
    ok &= G[ROLE_JOINTS["head"]][1] > G[ROLE_JOINTS["neck"]][1] > G[ROLE_JOINTS["chest"]][1] > G[0][1]
    ok &= G[ROLE_JOINTS["l_foot"]][1] < G[ROLE_JOINTS["l_shin"]][1] < G[ROLE_JOINTS["l_thigh"]][1]

    def anc(j, a):
        while j >= 0:
            if j == a:
                return True
            j = par[j]
        return False
    ok &= all(anc(ROLE_JOINTS[f"{s}_hand"], ROLE_JOINTS[f"{s}_upper"]) and
              anc(ROLE_JOINTS[f"{s}_foot"], ROLE_JOINTS[f"{s}_thigh"]) for s in "lr")
    return {r: joint_name(j) for r, j in ROLE_JOINTS.items()} if ok else {}


# ---------------------------------------------------------------- glTF
def write_glb(path: Path, m: dict, a: dict, name: str, extras: dict | None = None) -> Path:
    from .defjam_models import png_bytes
    bin_, views, accs = bytearray(), [], []

    def view(data: bytes, target=None):
        while len(bin_) % 4:
            bin_.append(0)
        views.append({"buffer": 0, "byteOffset": len(bin_), "byteLength": len(data), **({"target": target} if target else {})})
        bin_.extend(data)
        return len(views) - 1

    def acc(arr, typ, ctype=5126, target=34962, minmax=False):
        arr = np.ascontiguousarray(arr)
        x = {"bufferView": view(arr.tobytes(), target), "componentType": ctype, "count": len(arr), "type": typ}
        if minmax:
            x["min"], x["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accs.append(x)
        return len(accs) - 1

    J = a["joints"]
    nodes = []
    for i, j in enumerate(J):
        t = j["world"] - (J[j["parent"]]["world"] if j["parent"] >= 0 else 0)
        nodes.append({"name": j["name"], "translation": [float(v) for v in t]})
    for i, j in enumerate(J):
        if j["parent"] >= 0:
            nodes[j["parent"]].setdefault("children", []).append(i)
    roots = [i for i, j in enumerate(J) if j["parent"] < 0]
    ibm = []
    for j in J:
        M = np.eye(4, dtype=np.float32)
        M[3, :3] = -j["world"]                              # column-major translate(-world)
        ibm.append(M.reshape(16))
    images, textures, materials, tex_of = [], [], [], {}
    for p in a["prims"]:
        mat = m["materials"][p["material"]]
        base, _x, env = mat["textures"]
        ti = base if base >= 0 else env
        mj = {"name": mat["name"] or f"material{p['material']}",
              "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 0.85}}
        if ti >= 0:
            if ti not in tex_of:
                rgba = decode_texture(m["textures"][ti])
                images.append({"bufferView": view(png_bytes(rgba)), "mimeType": "image/png",
                               "name": m["textures"][ti]["name"]})
                textures.append({"source": len(images) - 1, "sampler": 0})
                tex_of[ti] = (len(textures) - 1, rgba)
            k, rgba = tex_of[ti]
            mj["pbrMetallicRoughness"]["baseColorTexture"] = {"index": k}
            if mat["params"][0] >= 0 and base >= 0 and float((rgba[..., 3] < 64).mean()) > 0.02:
                mj.update(alphaMode="MASK", alphaCutoff=0.5, doubleSided=True)
        else:
            mj["pbrMetallicRoughness"]["baseColorFactor"] = [0.6, 0.6, 0.6, 1.0]
        materials.append(mj)
    prims = []
    for k, p in enumerate(a["prims"]):
        attrs = {"POSITION": acc(p["pos"].astype(np.float32), "VEC3", minmax=True),
                 "NORMAL": acc(p["nrm"].astype(np.float32), "VEC3"),
                 "TEXCOORD_0": acc(p["uv"].astype(np.float32), "VEC2"),
                 "JOINTS_0": acc(p["joints"], "VEC4", 5123), "WEIGHTS_0": acc(p["weights"], "VEC4")}
        prims.append({"attributes": attrs, "material": k,
                      "indices": acc(p["tris"].reshape(-1).astype(np.uint32), "SCALAR", 5125, 34963)})
    skin = {"name": f"{name}_rig", "joints": list(range(len(J))), "skeleton": roots[0],
            "inverseBindMatrices": acc(np.array(ibm, np.float32), "MAT4", target=None)}
    nodes.append({"name": name, "mesh": 0, "skin": 0})
    gl = {"asset": {"version": "2.0", "generator": "gbox.etm_models", **({"extras": extras} if extras else {})},
          "scene": 0, "scenes": [{"name": name, "nodes": roots + [len(nodes) - 1]}], "nodes": nodes,
          "meshes": [{"name": name, "primitives": prims}], "skins": [skin], "materials": materials,
          "accessors": accs, "bufferViews": views, "buffers": [{"byteLength": len(bin_)}]}
    if images:
        gl.update(images=images, textures=textures,
                  samplers=[{"magFilter": 9729, "minFilter": 9729, "wrapS": 10497, "wrapT": 10497}])
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    while len(bin_) % 4:
        bin_.append(0)
    out = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bin_))
    out += struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(bin_), 0x004E4942) + bytes(bin_)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out)
    return path


def extract_bytes(b: bytes, out: Path, name: str, extras: dict | None = None, n: int = TESS) -> dict:
    m = parse_dcn(b)
    a = assemble(m, 0, n)
    rl = roles(m)
    glb = write_glb(out, m, a, name, {"source": f"Enter the Matrix PS2 {inv.SERIAL}", "model": m["name"],
                                      "units": "metres (game centimetres x 0.01, z mirrored)", **(extras or {})})
    ok = bool(a["triangles"]) and m["checksum"] == inv.SKELETON_CHECKSUM and bool(rl) and 0.5 < a["height_m"] < 3.0
    return {"model": m["name"], "glb": str(glb), "verified": ok, "roles": rl, "triangles": a["triangles"],
            "patches": a["counts"], "hidden_patches": a["hidden_patches"], "joints": len(a["joints"]),
            "height_m": round(a["height_m"], 3), "textures": len(m["textures"]), "materials": len(m["materials"]),
            "configs": len(m["configs"]), "checksum": hex(m["checksum"]), "sha256": hashlib.sha256(b).hexdigest()}


# ---------------------------------------------------------------- roster
# (model file, slug, display name, extra aliases): every human .dcn an actor of class hero / npc / story npc uses,
# without the seated driving variants and the debug export (Niobe_Costume01_eka)
CAST = [
    ("Niobe_Costume01", "etm_niobe", "Niobe", ["Niobe 1", "ETM Niobe"]),
    ("Niobe_Costume02", "etm_niobe_2", "Niobe (costume 2)", ["Niobe 2"]),
    ("Niobe_Costume03", "etm_niobe_3", "Niobe (costume 3)", ["Niobe 3"]),
    ("Niobe_Costume04", "etm_niobe_4", "Niobe (costume 4)", ["Niobe 4"]),
    ("Niobe_Costume05", "etm_niobe_5", "Niobe (costume 5)", ["Niobe 5"]),
    ("Niobe_1_phase", "etm_niobe_phase", "Niobe (phasing)", []),
    ("Ghost_Costume01", "etm_ghost", "Ghost", ["Ghost 1", "ETM Ghost"]),
    ("Ghost_Costume02", "etm_ghost_2", "Ghost (costume 2)", ["Ghost 2"]),
    ("Ghost_Costume03", "etm_ghost_3", "Ghost (costume 3)", ["Ghost 3"]),
    ("Ghost_Costume04", "etm_ghost_4", "Ghost (costume 4)", ["Ghost 4"]),
    ("Ghost_Costume05", "etm_ghost_5", "Ghost (costume 5)", ["Ghost 5"]),
    ("Ghost_Gi", "etm_ghost_gi", "Ghost (gi)", []),
    ("Ghost_phasing", "etm_ghost_phase", "Ghost (phasing)", []),
    ("AgentSmith", "etm_agent_smith", "Agent Smith", ["Smith"]),
    ("AgentJackson", "etm_agent_jackson", "Agent Jackson", ["Jackson"]),
    ("agentjohnson", "etm_agent_johnson", "Agent Johnson", ["Johnson"]),
    ("AgentThompson", "etm_agent_thompson", "Agent Thompson", ["Thompson"]),
    ("Agents_3", "etm_agents_3", "Agents (three)", []),
    ("Trinity_zen", "etm_trinity", "Trinity", ["Trinity Zen"]),
    ("Morpheus_coat", "etm_morpheus", "Morpheus", ["Morpheus coat"]),
    ("Morpheus", "etm_morpheus_lp", "Morpheus (low poly)", []),
    ("Neo", "etm_neo", "Neo", []),
    ("Seraph", "etm_seraph", "Seraph", []),
    ("Keymaker", "etm_keymaker", "Keymaker", ["The Keymaker"]),
    ("merovingian", "etm_merovingian", "Merovingian", ["The Merovingian"]),
    ("Twin01", "etm_twin", "Twin", ["Twins", "The Twins"]),
    ("Vlad", "etm_vlad", "Vlad", []),
    ("cujo", "etm_cujo", "Cujo", []),
    ("abel", "etm_abel", "Abel", []),
    ("Cain", "etm_cain", "Cain", []),
    ("Bane", "etm_bane", "Bane", []),
    ("axel", "etm_axel", "Axel", []),
    ("Ballard", "etm_ballard", "Ballard", ["Commander Ballard"]),
    ("Binary", "etm_binary", "Binary", []),
    ("Malachi", "etm_malachi", "Malachi", []),
    ("Corrupt", "etm_corrupt", "Corrupt", []),
    ("vector", "etm_vector", "Vector", []),
    ("wurm", "etm_wurm", "Wurm", []),
    ("Captain_Soren", "etm_soren", "Captain Soren", ["Soren"]),
    ("captain_ice", "etm_ice", "Captain Ice", ["Ice"]),
    ("Sparks", "etm_sparks", "Sparks", []),
    ("Swat", "etm_swat", "SWAT officer", ["SWAT", "Swat"]),
    ("Swat_armored", "etm_swat_armored", "SWAT (armored)", []),
    ("Swat_sniper", "etm_swat_sniper", "SWAT sniper", []),
    ("Swat_pilot", "etm_swat_pilot", "SWAT pilot", []),
    ("Swat_sewer", "etm_swat_sewer", "SWAT (sewer)", []),
    ("Swat_thermal", "etm_swat_thermal", "SWAT (thermal)", []),
    ("Swat_xbox", "etm_swat_alt", "SWAT (alternate)", []),
    ("Cop", "etm_cop", "Police officer", ["Cop", "Police"]),
    ("Cop_LP", "etm_cop_lp", "Police officer (low poly)", []),
    ("security_guard", "etm_security_guard", "Security guard", []),
    ("Bloodsucker_1", "etm_vampire", "Vampire", ["Bloodsucker"]),
    ("Bloodsucker_fem", "etm_vampire_f", "Vampire (female)", []),
    ("prisoner_1", "etm_prisoner", "Prisoner", []),
    ("janitor", "etm_janitor", "Janitor", []),
    ("sewing_woman", "etm_sewing_woman", "Sewing woman", []),
    ("postal_worker", "etm_postal_worker", "Postal worker", []),
    ("postal_sorter", "etm_postal_sorter", "Postal sorter", []),
    ("postal_operator", "etm_postal_operator", "Postal operator", []),
    ("aport_mechanic", "etm_mechanic", "Airport mechanic", []),
    ("pplant_repairman", "etm_repairman", "Power plant repairman", []),
    ("PPlant_welder", "etm_welder", "Power plant welder", []),
    ("shopkeeper", "etm_shopkeeper", "Shopkeeper", []),
    ("Civ_male01", "etm_civilian_m1", "Civilian (man 1)", []),
    ("Civ_male02", "etm_civilian_m2", "Civilian (man 2)", []),
    ("Civ_Female01", "etm_civilian_f1", "Civilian (woman 1)", []),
    ("Civ_Female02", "etm_civilian_f2", "Civilian (woman 2)", []),
    ("firebird_man", "etm_firebird_man", "Firebird driver", []),
    ("agentcar_man", "etm_agentcar_man", "Agent car driver", []),
]


def model_path(stem: str) -> str:
    return f"actors\\{stem}.dcn"


def roster() -> list[dict]:
    return [{"key": stem, "slug": slug, "name": f"{name} (Enter the Matrix)", "model": model_path(stem),
             "aliases": [stem, name, f"Enter the Matrix {name}", f"ETM {name}", *extra], "kind": "character"}
            for stem, slug, name, extra in CAST]


def source_disc(ctx, game: dict) -> Path:
    from . import characters as C
    p = C._rom(ctx, game)
    if p.suffix.lower() not in (".chd", ".iso"):
        raise FormatError(f"{p.name}: the Enter the Matrix reader reads the PS2 disc (CHD or ISO)")
    return p


def open_archive(path):
    from .shiny_dfu import Dfu
    disc = inv.open_disc(path)
    ident = inv.identify(disc)
    if not ident["exact_build"]:
        raise FormatError(f"{ident['boot']} ({ident['elf_sha256']}): the reader is verified on {inv.SERIAL} "
                          f"(ELF sha256 {inv.ELF_SHA256[:16]}) only")
    return disc, Dfu(disc, "etm"), ident


def extract_run(ctx, game: dict, e: dict, work: Path) -> dict:
    """characters.DEDICATED hook: one ETM model -> rigged, textured GLB with body roles."""
    _disc, dfu, _ident = open_archive(source_disc(ctx, game))
    path = e.get("model") or model_path(e["key"])
    ent = dfu.entry(path)
    if ent is None:
        raise FormatError(f"{path} is not in WAD1.DFU")
    r = extract_bytes(dfu.read(ent), Path(work) / f"{e['slug']}.glb", e["slug"], {"file": path})
    if not r["verified"]:
        raise FormatError(f"{path}: failed verification ({r['triangles']} triangles, checksum {r['checksum']}, "
                          f"body roles {'found' if r['roles'] else 'missing'})")
    return {"files": [Path(r["glb"])], "roles": r["roles"], "tool": "gbox.etm_models",
            "source_files": [f"WAD1.DFU:{path} (sha256 {r['sha256'][:16]})"],
            "notes": (f"Native {inv.SERIAL} DC patch model: {r['patches']['quad']} quad + {r['patches']['tri']} "
                      f"triangle Bezier patches and {r['patches']['tri3']} triangles (config 0), tessellated to "
                      f"{r['triangles']} triangles on the shared 89-joint skeleton ({r['height_m']} m tall), "
                      f"{r['textures']} PS2 CLUT textures.")}


def extract_all(path, out_dir: Path, stems=None) -> dict:
    _disc, dfu, ident = open_archive(path)
    out_dir = Path(out_dir)
    rows = []
    for e in roster():
        if stems and e["key"] not in stems:
            continue
        try:
            rows.append({"key": e["key"], **extract_bytes(dfu.read(e["model"]), out_dir / f"{e['slug']}.glb", e["slug"])})
        except (FormatError, KeyError) as x:
            rows.append({"key": e["key"], "verified": False, "error": str(x)})
    man = {"identity": ident, "verified": sum(bool(r.get("verified")) for r in rows), "total": len(rows), "models": rows}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(json.dumps(man, indent=1, default=str))
    return man


if __name__ == "__main__":
    man = extract_all(sys.argv[1], Path(sys.argv[2]), sys.argv[3:] or None)
    print(json.dumps({k: man[k] for k in ("verified", "total")}))
    for r in man["models"]:
        print(r["key"], r.get("verified"), r.get("error") or (r["triangles"], r["height_m"], r["patches"]))
