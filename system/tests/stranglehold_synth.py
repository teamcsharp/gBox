"""Synthetic Stranglehold (PS3 UE3 v375 / Midway) packages for the reader and writer tests: a chunked .xxx with one
SkeletalMesh (18-bone HumanIK-named skeleton, one LOD of SPU segments) and its body diffuse Texture2D (DXT5).
No game data: every byte is built here."""
import struct
import zlib

import numpy as np

from gbox import stranglehold_inventory as I
from gbox import stranglehold_models as M
from gbox import stranglehold_swap as W

# name, parent, local position (mesh space: -Y up, +X = the character's left, +Z front; centimetres)
BONES = [("reference", -1, (0, 0, 0)), ("hips", 0, (0, -100, 0)), ("Spine", 1, (0, -15, 0)), ("spine2", 2, (0, -25, 0)),
         ("neck", 3, (0, -20, 0)), ("Head", 4, (0, -12, 0)),
         ("LeftShoulder", 3, (8, -15, 0)), ("LeftArm", 6, (12, 0, 0)), ("LeftForeArm", 7, (28, 0, 0)), ("LeftHand", 8, (25, 0, 0)),
         ("RightShoulder", 3, (-8, -15, 0)), ("RightArm", 10, (-12, 0, 0)), ("RightForeArm", 11, (-28, 0, 0)), ("RightHand", 12, (-25, 0, 0)),
         ("LeftUpLeg", 1, (10, 5, 0)), ("LeftLeg", 14, (0, 45, 0)), ("LeftFoot", 15, (0, 45, 0)),
         ("RightUpLeg", 1, (-10, 5, 0)), ("RightLeg", 17, (0, 45, 0)), ("RightFoot", 18, (0, 45, 0))]
MESH = "synthClass01_lod00_skmesh"
TEX = "synthClass01_all_diffuse"


def world_positions() -> np.ndarray:
    out = []
    for name, par, p in BONES:
        out.append(np.array(p, float) + (out[par] if par >= 0 else 0))
    return np.array(out)


def box(c, h=(3.0, 3.0, 3.0)):
    """8 corners + 12 triangles of an axis box around c (mesh space)."""
    s = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], float) * h + c
    t = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6],
                  [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]])
    return s, t


def figure():
    """A box per bone -> (P mesh space, F, bone per vertex, uv)."""
    W_ = world_positions()
    P, F, B = [], [], []
    for j in range(1, len(BONES)):
        s, t = box(W_[j])
        F.append(t + len(P) * 0 + sum(len(x) for x in P))
        P.append(s)
        B += [j] * 8
    P = np.concatenate(P)
    uv = (P[:, [0, 1]] - P[:, [0, 1]].min(0)) / np.ptp(P[:, [0, 1]], 0)
    return P, np.concatenate(F), np.array(B), uv


def first_use(F):
    order, remap = [], {}
    for v in F.reshape(-1):
        if int(v) not in remap:
            remap[int(v)] = len(order)
            order.append(int(v))
    return np.array(order), np.vectorize(remap.get)(F)


def lod_blob(P, F, B, uv, split=2):
    """One FStaticLODModel: `split` SPU segments of the figure."""
    segs, nverts = [], 0
    for part in np.array_split(np.arange(len(F)), split):
        order, local = first_use(F[part])
        segs.append(W.segment_bytes(P[order], np.zeros((len(order), 9), np.uint8), uv[order], np.zeros((len(order), 2)),
                                    B[order], local))
        nverts += len(order)
    used = sorted(set(B.tolist()))
    out = struct.pack(">i", 1) + struct.pack(">HHIH", 0, 0, 0, len(F)) + struct.pack(">i", 0)
    out += struct.pack(">i", len(used)) + struct.pack(f">{len(used)}H", *used) + struct.pack(">i", 0)
    out += struct.pack(">i", 1) + struct.pack(">iii", 0, 0, 0) + struct.pack(">i", len(used)) + \
        struct.pack(f">{len(used)}H", *used) + struct.pack(">iii", nverts, 0, 4)
    out += struct.pack(">iii", 0x67006E, nverts, 0) + struct.pack(">ii", 1, len(segs)) + b"".join(segs)
    out += struct.pack(">i", len(BONES)) + bytes(range(len(BONES)))
    return out


class Names:
    def __init__(self):
        self.names = []

    def __call__(self, s):
        if s not in self.names:
            self.names.append(s)
        return self.names.index(s)


def mesh_export(nm: Names) -> bytes:
    b = struct.pack(">i", 0) + struct.pack(">ii", nm("None"), 0)              # net index, no tagged properties
    b += struct.pack(">7f", 0, -90, 0, 80, 90, 20, 120)
    b += struct.pack(">i", 0)                                                # Materials: none (atlas fallback)
    b += struct.pack(">3f", 0, 0, 0) + struct.pack(">3i", 0, 0, 0)
    b += struct.pack(">i", len(BONES))
    for name, par, p in BONES:
        b += struct.pack(">iii", nm(name), 0, 0) + struct.pack(">4f", 0, 0, 0, 1) + struct.pack(">3f", *p)
        b += struct.pack(">ii", sum(1 for _n, pp, _p in BONES if pp == BONES.index((name, par, p))), max(par, 0))
    b += struct.pack(">iii", 5, 0, 1)                                        # depth, Midway 0, one LOD
    P, F, B, uv = figure()
    b += lod_blob(P, F, B, uv)
    b += struct.pack(">i", 0) * 4                                            # tail (name map ...)
    return b


def texture_export(nm: Names, rgba: np.ndarray) -> bytes:
    h, w = rgba.shape[:2]

    def tag(name, typ, size, val):
        return struct.pack(">iiiiii", nm(name), 0, nm(typ), 0, size, 0) + val
    b = struct.pack(">i", 0)
    b += tag("SizeX", "IntProperty", 4, struct.pack(">i", w)) + tag("SizeY", "IntProperty", 4, struct.pack(">i", h))
    b += tag("Format", "ByteProperty", 1, b"\x07") + struct.pack(">ii", nm("None"), 0)
    data = W.dxt_encode(rgba, 5)
    b += b"\0" * 16 + struct.pack(">i", 1) + struct.pack(">iiii", 0, len(data), len(data), 0) + data + struct.pack(">ii", w, h)
    return b


def package() -> bytes:
    """Chunked package: summary + chunk table, chunk 1 = name/import/export tables, chunk 2 = the two exports."""
    nm = Names()
    for s in ("None", "Core", "Engine", "Class", "SkeletalMesh", "Texture2D", MESH, TEX):
        nm(s)
    img = np.zeros((64, 64, 4), np.uint8)
    img[..., 0] = 200
    img[..., 3] = 255
    mesh = mesh_export(nm)
    tex = texture_export(nm, img)
    nt = b"".join(struct.pack(">i", len(n) + 1) + n.encode() + b"\x00" + b"\x00" * 8 for n in nm.names)
    imp = (struct.pack(">iiiiiii", nm("Core"), 0, nm("Class"), 0, 0, nm("SkeletalMesh"), 0) +
           struct.pack(">iiiiiii", nm("Core"), 0, nm("Class"), 0, 0, nm("Texture2D"), 0))
    pre = struct.pack(">II", I.TAG, 0x00190177) + struct.pack(">I", 0) + struct.pack(">i", 5) + b"None\x00"
    summary_size = len(pre) + 32 + 16 + 4 + 12 + 16
    no = summary_size
    io = no + len(nt)
    eo = io + len(imp)
    ex_len = 2 * (24 + 8 + 8 + 12 + 16)
    dep = eo + ex_len
    data_off = dep + 16
    mesh_off, tex_off = data_off, data_off + len(mesh)

    def export(cls, name_idx, size, off):
        return (struct.pack(">iiiiii", cls, 0, 0, name_idx, 0, 0) + b"\x00" * 8 + struct.pack(">ii", size, off)
                + struct.pack(">iii", 0, 0, 0) + b"\x00" * 16)
    ex = export(-1, nm(MESH), len(mesh), mesh_off) + export(-2, nm(TEX), len(tex), tex_off)
    tables = nt + imp + ex + b"\0" * 16
    body = mesh + tex
    c1, c2 = W.compress_chunk(tables), W.compress_chunk(body)
    head_len = summary_size + 32
    head = (pre + struct.pack(">8I", 0x02880009, len(nm.names), no, 2, eo, 2, io, dep) + b"\x11" * 16
            + struct.pack(">I", 1) + struct.pack(">III", 2, len(nm.names), 0)
            + struct.pack(">IIII", 2605, 32, 1, 2))
    assert len(head) == summary_size
    head += struct.pack(">IIII", summary_size, len(tables), head_len, len(c1))
    head += struct.pack(">IIII", data_off, len(body), head_len + len(c1), len(c2))
    return head + c1 + c2


def donor_glb(path, tint=(30, 160, 60, 255)):
    """A small skinned GLB (the synthetic figure, re-scaled a little, in glTF metres) with roles -> (path, roles)."""
    P, F, B, uv = figure()
    pos = M.to_gltf_points(P * 0.9)
    tris = F[:, [0, 2, 1]]
    Wm = M.to_gltf_matrices(np.stack([np.block([[np.eye(3), (wp * 0.9)[:, None]], [np.zeros((1, 3)), np.ones((1, 1))]])
                                      for wp in world_positions()]))
    joints = np.c_[B, np.zeros((len(B), 3), int)]
    weights = np.c_[np.ones(len(B)), np.zeros((len(B), 3))]
    img = np.zeros((16, 16, 4), np.uint8)
    img[:] = tint
    prim = {"pos": pos, "nrm": M.smooth_normals(pos, tris), "uv": uv, "joints": joints, "weights": weights,
            "tris": tris, "image": 0}
    names = [b[0] for b in BONES]
    M.write_glb(path, [prim], names, [b[1] for b in BONES], Wm, [img], "donor")
    return path, M.roles_of([{"name": n} for n in names])


def raw_chunk(data: bytes) -> bytes:
    comp = zlib.compress(data)
    return struct.pack(">IIII", I.TAG, 0x10000, len(comp), len(data)) + struct.pack(">II", len(comp), len(data)) + comp
