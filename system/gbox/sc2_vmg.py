"""Soul Calibur II (GameCube) model files: Namco "VMG." models with their "VGT." texture sets (docs/soulcalibur2_gc.md).

Layout (big-endian, offsets from the start of the VMG; the loader 0x801237f0 adds the base to every pointer):

  +0x00 "VMG."  +0x04 u8 version 3  +0x05 u8 0x10 (pointer block at +0x18)  +0x06 u8 13 pointers  +0x07 relocated
  +0x08 u16 1   +0x0a u16 nodes (0x150 each)  +0x0c/+0x0e/+0x10 u16 meshes in the three draw lists (opaque, second,
  sorted-translucent)  +0x12 u16 bones (0x40 each)  +0x14 u16 materials (0x50 each)  +0x16 u16 skin groups (0x24)
  +0x18 VGT texture set  +0x1c materials  +0x20 texture stages (0x24)  +0x24 nodes  +0x28 colour block
  +0x2c/+0x30/+0x34 mesh lists (0x38 each)  +0x38 skin groups  +0x3c optional  +0x40 bones  +0x44 bone names
  +0x48 tail block

  bone (0x40)   f32 quat[4], f32 translation[3] (+ 1.0), f32 euler[3] in turns (R = Rz Ry Rx), name ptr (+0x2c),
                f32 scale[3], u8 0, u8 parent (0xff root), u8 index, u8 kind. Bind world = G . chain + root offset,
                G = 90 degrees about Y (the engine's skeleton frame: +X along the bone; model space: +Y up).
  mesh (0x38)   u8 flags (2 = depth-sorted), 3 x {u8 stride, u8 GX comp type, u8 frac} for position, normal, uv,
                4 x u8 index type (GX_INDEX8 2 / INDEX16 3) for position, normal, colour, uv; u16 display list size
                / 32; node, material, positions, positions (2nd buffer), normals, normals (2nd), colours, uvs,
                display list, extra (pointers).
                Skinned meshes (node 0, identity) index the shared world-space vertex buffers the CPU skinning
                writes every frame (float xyzw, stride 16); rigid meshes (byte-index format) carry their own
                arrays in the space of their node (node kind 2 = rides bone node[1]).
  skin group    u32 counts of 1-, 2-, 3-influence vertices, u32 (unused), skin records, positions, positions 2,
  (0x24)        normals, normals 2. A skin record (16 bytes) = s16 x, y, z (bone space, x weight, 1/8192),
                s16 weight (8192 = 1), s16 normal x, y, z (x weight, 1/16384), u8 count delta, u8 bone. After the
                three fixed groups come vertices with 4+ influences (the count grows by the delta of each vertex's
                last record), ended by a record whose weight is -1 (skinning loop 0x801269d4).
  material(0x50) u32 layers, u32 flags, texture record ptr[2], -, stage ptr[2], -, colours (f32)
  VGT.          u8 version 4, u32 textures, u32 palettes, table ptrs; texture record 0x44 = palette record ptr +
                two GXTexObj (the 1P and the 2P colour); palette record 0x18 = two GXTlutObj.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

MAGIC = b"VMG."
VGT_MAGIC = b"VGT."
Q_POS = 8192.0
Q_NRM = 16384.0
G = np.array([[0, 0, 1.0], [0, 1, 0], [-1, 0, 0]])      # skeleton frame -> model frame (90 degrees about +Y)


def _rx(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _ry(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _rz(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _quat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


@dataclass
class Bone:
    index: int
    name: str
    parent: int
    quat: tuple
    trans: tuple
    euler: tuple
    scale: tuple
    kind: int
    offset: int


@dataclass
class Mesh:
    table: int
    index: int
    offset: int
    flags: int
    fmt: tuple            # ((stride, comp, frac) x 3: pos, nrm, uv)
    idx: tuple            # index types: pos, nrm, clr, uv
    dl_size: int
    node: int
    material: int
    pos: int
    pos2: int
    nrm: int
    nrm2: int
    clr: int
    uv: int
    dl: int
    extra: int

    @property
    def skinned(self) -> bool:
        return self.fmt[0][0] == 16 and self.fmt[0][1] == 4


@dataclass
class Vmg:
    data: bytes
    counts: dict
    ptrs: dict
    bones: list = field(default_factory=list)
    meshes: list = field(default_factory=list)
    materials: list = field(default_factory=list)
    nodes: list = field(default_factory=list)
    skin: list = field(default_factory=list)

    def u32(self, o):
        return struct.unpack_from(">I", self.data, o)[0]


PTR_NAMES = ["vgt", "materials", "stages", "nodes", "colours", "list0", "list1", "list2", "skin", "opt", "bones",
             "names", "tail"]


def parse(data: bytes) -> Vmg:
    if data[:4] != MAGIC:
        raise ValueError(f"not a VMG model (magic {data[:4]!r})")
    if data[4] != 3:
        raise ValueError(f"VMG version {data[4]} (the game reads 3)")
    c = struct.unpack_from(">8H", data, 8)
    counts = {"one": c[0], "nodes": c[1], "list0": c[2], "list1": c[3], "list2": c[4], "bones": c[5],
              "materials": c[6], "skin": c[7]}
    base, n = data[5] + 8, data[6]
    ptrs = dict(zip(PTR_NAMES, struct.unpack_from(f">{n}I", data, base)))
    v = Vmg(data, counts, ptrs)
    bo = ptrs["bones"]
    for i in range(counts["bones"]):
        r = bo + 0x40 * i
        f = struct.unpack_from(">11f", data, r)
        npx = struct.unpack_from(">I", data, r + 0x2c)[0]
        name = data[npx:data.index(b"\0", npx)].decode("latin-1") if npx else ""
        sc = struct.unpack_from(">3f", data, r + 0x30)
        par = data[r + 0x3d]
        v.bones.append(Bone(i, name, -1 if par == 0xFF else par, f[0:4], f[4:7], f[8:11], sc, data[r + 0x3f], r))
    for t in range(3):
        lo = ptrs[f"list{t}"]
        for i in range(counts[f"list{t}"]):
            r = lo + 0x38 * i
            b = data[r:r + 14]
            fmt = ((b[1], b[2], b[3]), (b[4], b[5], b[6]), (b[7], b[8], b[9]))
            q = struct.unpack_from(">H10I", data, r + 14)
            v.meshes.append(Mesh(t, i, r, b[0], fmt, tuple(b[10:14]), q[0] * 32, *q[1:]))
    mo = ptrs["materials"]
    for i in range(counts["materials"]):
        r = mo + 0x50 * i
        layers, flags, t0, t1, _x, s0, s1, _y = struct.unpack_from(">8I", data, r)
        v.materials.append({"offset": r, "layers": layers, "flags": flags, "tex": [t0, t1], "stages": [s0, s1],
                            "colours": struct.unpack_from(">12f", data, r + 0x20)})
    no = ptrs["nodes"]
    for i in range(counts["nodes"]):
        r = no + 0x150 * i
        m = np.array(struct.unpack_from(">16f", data, r + 0x10)).reshape(4, 4)
        v.nodes.append({"offset": r, "kind": data[r], "bone": data[r + 1], "matrix": m})
    so = ptrs["skin"]
    for i in range(counts["skin"]):
        r = so + 0x24 * i
        q = struct.unpack_from(">9I", data, r)
        v.skin.append({"offset": r, "counts": q[0:4], "records": q[4], "pos": q[5], "pos2": q[6], "nrm": q[7],
                       "nrm2": q[8]})
    return v


# ------------------------------------------------------------------------------------------------ skeleton

def local_matrix(b: Bone) -> np.ndarray:
    a = np.asarray(b.euler, float) * 2 * np.pi
    m = np.eye(4)
    q = np.asarray(b.quat, float)
    qn = float(np.linalg.norm(q)) if np.isfinite(q).all() else 0.0
    # body / finger bones carry a unit quaternion (identity on every model read); the swing / helper bones
    # (kind 11 ...) keep other parameters in those 16 bytes
    rq = _quat(q / qn) if abs(qn - 1.0) < 1e-3 else np.eye(3)
    m[:3, :3] = _rz(a[2]) @ _ry(a[1]) @ _rx(a[0]) @ rq
    m[:3, 3] = b.trans
    return m


def bind_world(v: Vmg, root: np.ndarray | None = None) -> np.ndarray:
    """(bones, 4, 4) bind-pose world matrices in model space (metres, +Y up). root: the model-space position of the
    skeleton's roots (the skin's own bind pose; skin_root() measures it)."""
    root = np.zeros(3) if root is None else np.asarray(root, float)
    W = np.zeros((len(v.bones), 4, 4))
    gm = np.eye(4)
    gm[:3, :3] = G
    for b in v.bones:
        L = local_matrix(b)
        if b.parent < 0 or b.parent >= b.index:
            W[b.index] = gm @ L
            W[b.index][:3, 3] += root
        else:
            W[b.index] = W[b.parent] @ L
    return W


# ------------------------------------------------------------------------------------------------ skin

def skin_records(v: Vmg, g: dict, variable: bool = True) -> list[list[tuple[int, float, np.ndarray, np.ndarray]]]:
    """Per output vertex: [(bone, weight, bone-space position (pre-weighted, /8192), pre-weighted normal)]."""
    d = v.data
    o = g["records"]
    out = []

    def rec(o):
        x, y, z, w, nx, ny, nz = struct.unpack_from(">7h", d, o)
        return (d[o + 15], w / Q_POS, np.array([x, y, z], float) / Q_POS, np.array([nx, ny, nz], float) / Q_NRM,
                d[o + 14], w)
    for k, n in enumerate(g["counts"][:3]):
        for _ in range(n):
            out.append([rec(o + 16 * j)[:4] for j in range(k + 1)])
            o += 16 * (k + 1)
    n = 4
    guard = 0
    while variable and o + 16 * n <= len(d) and struct.unpack_from(">h", d, o + 6)[0] != -1 and guard < 100000:
        rs = [rec(o + 16 * j) for j in range(n)]
        out.append([r[:4] for r in rs])
        o += 16 * n
        n += rs[-1][4]
        guard += 1
    return out


def skin_root(v: Vmg) -> np.ndarray:
    """The model-space offset of the skeleton roots in the skin's bind pose: single-influence vertices are
    bone-space positions; their stored world positions minus the root-less bone transform give it."""
    if not v.skin:
        return np.zeros(3)
    g = v.skin[0]
    W = bind_world(v)
    P = np.frombuffer(v.data, ">f4", g["counts"][0] * 4, g["pos"]).reshape(-1, 4)[:, :3].astype(float)
    recs = skin_records(v, {**g, "counts": (g["counts"][0], 0, 0, 0)}, variable=False)
    if not recs:
        return np.zeros(3)
    diffs = [P[i] - (W[r[0][0]][:3, :3] @ r[0][2] + W[r[0][0]][:3, 3]) for i, r in enumerate(recs)
             if r[0][0] < len(W)]
    return np.median(np.array(diffs), 0) if diffs else np.zeros(3)


# ------------------------------------------------------------------------------------------------ display lists

_COMP = {0: (">u1", 1), 1: (">i1", 1), 2: (">u2", 2), 3: (">i2", 2), 4: (">f4", 4)}


def read_array(d: bytes, off: int, fmt: tuple, ncomp: int, count: int) -> np.ndarray:
    stride, comp, frac = fmt
    dt, size = _COMP[comp]
    out = np.zeros((count, ncomp))
    for i in range(count):
        out[i] = np.frombuffer(d, dt, ncomp, off + stride * i)
    return out / (1 << frac) if comp != 4 else out


def display_list(d: bytes, off: int, size: int, idx: tuple) -> list[tuple[int, list[tuple]]]:
    """GX primitives: [(opcode, [(pos, nrm, clr, uv) per vertex])]; index types 2 = u8, 3 = u16, 0 = none."""
    width = [1 if t == 2 else 2 if t == 3 else 0 for t in idx]
    vsz = sum(width)
    o, end, out = off, off + size, []
    while o < end:
        op = d[o]
        if op == 0:
            break
        if op & 0xF8 not in (0x80, 0x90, 0x98, 0xA0, 0xA8, 0xB0, 0xB8):
            break
        n = struct.unpack_from(">H", d, o + 1)[0]
        o += 3
        verts = []
        for _ in range(n):
            vv, p = [], o
            for w in width:
                vv.append(d[p] if w == 1 else struct.unpack_from(">H", d, p)[0] if w == 2 else -1)
                p += w
            verts.append(tuple(vv))
            o += vsz
        out.append((op & 0xF8, verts))
    return out


def triangles(prims: list[tuple[int, list]]) -> list[tuple]:
    """GX primitives -> triangle corner tuples (front faces as the game winds them)."""
    tris = []
    for op, vs in prims:
        if op == 0x90:
            tris += [(vs[i], vs[i + 1], vs[i + 2]) for i in range(0, len(vs) - 2, 3)]
        elif op == 0x98:
            for i in range(len(vs) - 2):
                tris.append((vs[i], vs[i + 1], vs[i + 2]) if i % 2 == 0 else (vs[i + 1], vs[i], vs[i + 2]))
        elif op == 0xA0:
            tris += [(vs[0], vs[i], vs[i + 1]) for i in range(1, len(vs) - 1)]
    return tris


# ------------------------------------------------------------------------------------------------ textures

def vgt_textures(d: bytes, base: int) -> list[dict]:
    """The VGT set at `base`: [{offset (record), fmt, w, h, data, data2 (2P), tlut, tlut_fmt, n, tlut2}]."""
    if d[base:base + 4] != VGT_MAGIC:
        return []
    n, npal, to, po = struct.unpack_from(">4I", d, base + 8)
    out = []
    for i in range(n):
        r = base + to + 0x44 * i
        pal, = struct.unpack_from(">I", d, r)
        img0, data0 = struct.unpack_from(">II", d, r + 0x0c)
        flags = struct.unpack_from(">H", d, r + 0x14)[0]
        img1, data1 = struct.unpack_from(">II", d, r + 0x2c)
        w, h, fmt = (img0 & 0x3FF) + 1, ((img0 >> 10) & 0x3FF) + 1, (img0 >> 20) & 0xF
        t = {"index": i, "record": r, "fmt": fmt, "w": w, "h": h, "data": base + data0, "flags": flags,
             "data2": base + data1 if flags & 2 and data1 else None, "tlut": None}
        if pal:
            p = base + pal
            tf, toff, tn = struct.unpack_from(">IIH", d, p)
            t2f, t2off, t2n = struct.unpack_from(">IIH", d, p + 0x0c)
            t.update(tlut=base + toff, tlut_fmt=(tf >> 10) & 3, tlut_n=tn or 256,
                     tlut2=base + t2off if t2off else None, tlut_record=p)
        out.append(t)
    return out


def texture_rgba(d: bytes, t: dict, second: bool = False) -> np.ndarray:
    from .melee_models import decode_texture, tex_size
    off = t["data2"] if second and t.get("data2") else t["data"]
    raw = d[off:off + tex_size(t["fmt"], t["w"], t["h"])]
    tl = None
    if t.get("tlut") is not None:
        to = t["tlut2"] if second and t.get("tlut2") else t["tlut"]
        tl = d[to:to + 2 * t["tlut_n"]]
    return decode_texture(raw, t["fmt"], t["w"], t["h"], tl, t.get("tlut_fmt", 0), t.get("tlut_n", 256))


def texture_of(v: Vmg, material: int) -> dict | None:
    """The colour texture record a material samples first."""
    if not (0 <= material < len(v.materials)) and material not in [m["offset"] for m in v.materials]:
        return None
    m = next((m for m in v.materials if m["offset"] == material), None) if material >= len(v.materials) else \
        v.materials[material]
    if m is None or not m["tex"][0]:
        return None
    base = v.ptrs["vgt"]
    for t in vgt_textures(v.data, base):
        if t["record"] == m["tex"][0]:
            return t
    return None


# ------------------------------------------------------------------------------------------------ decode

def decode(v: Vmg, second_colour: bool = False, lists=(0, 1, 2)) -> tuple[list[dict], np.ndarray, list[str]]:
    """-> (prims, bind world (bones, 4, 4), bone names). Prims: {pos (n,3), nrm, uv, tris, J (n,4), W (n,4),
    image (RGBA | None), mesh (table, index), material}. Positions in metres, model space (+Y up), bind pose."""
    d = v.data
    root = skin_root(v)
    W = bind_world(v, root)
    skinv = []
    if v.skin:
        g = v.skin[0]
        skinv = skin_records(v, g)
        nv = len(skinv)
        SP = np.frombuffer(d, ">f4", nv * 4, g["pos"]).reshape(-1, 4)[:, :3].astype(float)
        SN = np.frombuffer(d, ">f4", nv * 4, g["nrm"]).reshape(-1, 4)[:, :3].astype(float)
        SJ = np.zeros((nv, 4), np.int64)
        SW = np.zeros((nv, 4))
        for i, rs in enumerate(skinv):
            rs = sorted(rs, key=lambda r: -r[1])[:4]
            tot = sum(max(r[1], 0) for r in rs) or 1.0
            for k, r in enumerate(rs):
                SJ[i, k], SW[i, k] = r[0], max(r[1], 0) / tot
    texcache: dict = {}
    prims = []
    for m in v.meshes:
        if m.table not in lists or m.dl_size == 0:
            continue
        tris = triangles(display_list(d, m.dl, m.dl_size, m.idx))
        if not tris:
            continue
        corners = [c for t in tris for c in t]
        n = len(corners)
        pos_i = np.array([c[0] for c in corners])
        nrm_i = np.array([c[1] for c in corners])
        uv_i = np.array([c[3] for c in corners])
        UV = read_array(d, m.uv, m.fmt[2], 2, int(uv_i.max()) + 1) if m.uv and uv_i.max() >= 0 else None
        if m.skinned and len(skinv):
            P, N = SP[pos_i], SN[nrm_i]
            J, Wt = SJ[pos_i], SW[pos_i]
        else:
            Pl = read_array(d, m.pos, m.fmt[0], 3, int(pos_i.max()) + 1)[pos_i]
            Nl = read_array(d, m.nrm, m.fmt[1], 3, int(nrm_i.max()) + 1)[nrm_i] if m.nrm else np.tile([0, 1.0, 0], (n, 1))
            node = next((nd for nd in v.nodes if nd["offset"] == m.node), None)
            if node is not None and node["kind"] == 2 and node["bone"] < len(W):
                M = W[node["bone"]]
                bone = node["bone"]
            else:
                M = node["matrix"].T if node is not None else np.eye(4)
                bone = 0
            P = Pl @ M[:3, :3].T + M[:3, 3]
            N = Nl @ M[:3, :3].T
            J = np.zeros((n, 4), np.int64)
            J[:, 0] = bone
            Wt = np.zeros((n, 4))
            Wt[:, 0] = 1
        N = N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)
        mat = next((k for k, mt in enumerate(v.materials) if mt["offset"] == m.material), -1)
        if mat not in texcache:
            t = texture_of(v, mat) if mat >= 0 else None
            try:
                texcache[mat] = texture_rgba(d, t, second_colour) if t else None
            except (KeyError, ValueError, IndexError):
                texcache[mat] = None
        prims.append({"pos": P, "nrm": N, "uv": UV[uv_i] if UV is not None else np.zeros((n, 2)),
                      "tris": np.arange(n).reshape(-1, 3), "J": J, "W": Wt, "image": texcache[mat],
                      "mesh": (m.table, m.index), "material": mat, "skinned": m.skinned})
    return prims, W, [b.name or f"bone{b.index:03d}" for b in v.bones]


def stats(v: Vmg) -> dict:
    tris = 0
    for m in v.meshes:
        tris += len(triangles(display_list(v.data, m.dl, m.dl_size, m.idx))) if m.dl_size else 0
    return {"bones": len(v.bones), "meshes": len(v.meshes), "materials": len(v.materials), "triangles": tris,
            "bytes": len(v.data), "textures": len(vgt_textures(v.data, v.ptrs["vgt"]))}
