"""Def Jam: Vendetta PS2 (SLUS_206.39 v1.00): native wrestler reader -> rigged, textured GLBs with body roles.

Formats (worked out on the owned disc; container/identity in gbox/defjam_inventory.py, details and evidence in
docs/defjam_pipeline.md):

* Model slot (BODY 1, BODY2 2, FACE 3, L HAND 4, R HAND 5 of a WRS container): u32 geometry offset, u32 geometry size,
  u32 node count, u32 0, then node records of 0x190 bytes from +0x10: {i32 first child, i32 next sibling,
  i32 palette slot (-1 = no vertices), u32 0, f32[16] matrix A, f32[16] LOCAL bind matrix (row vectors,
  translation in row 3), 0x100 bytes}. Forward kinematics of the local matrices gives the T-pose: BODY's 42 nodes
  put the pelvis at y 10.56, the head end at y 20.71, the hands at x +-9.87 and the feet at y 0 (game units, y-up,
  facing +Z, the wrestler's left = +X). The parent tree is the same in all 58 containers.
* Geometry: a VIF stream; one UNPACK V4-32 without FLG first writes 159 qwords at VU address 0x39 (a GIF tag
  template and a zeroed matrix palette: 8 qwords per palette slot from qword 64), then batches of UNPACK V4-32 with
  FLG separated by FLUSH/MSCALF. Batch: header qword {n_single, n_weighted, n_strips, 0x8000 | n_loose}, n_single
  x {ST (u32 matrix address in w), N, P}, n_weighted x {ST, N, P, (u32 matrix a, f32 weight a, u32 matrix b,
  f32 weight b)}, then u32 strips {length, length x VU qword address (double-buffer base 0/0x100/0x200/0x300 +
  qword offset of the vertex's ST)}, then n_loose triangles of 3 addresses. Matrix address = 64 + 8 * palette
  slot; the node whose record holds that slot is the joint. decode_batches/encode_model rebuild all 290 model
  slots on the disc byte for byte.
  BODY/BODY2 positions are model space (bind pose). FACE and the hands are in the space of their own root node,
  which the game attaches to BODY node 7 (head) and nodes 13 / 19 (left / right wrist): placed there they close
  the neck and wrist seams (checked on all 58).
* Texture (WRS slot 18): u32 0x80, u32 packet size, 0x70 bytes, then a GS packet: GIF A+D {BITBLTBUF, TRXPOS,
  TRXREG, TRXDIR} + IMAGE for the texels (256 x 256 PSMCT32 = one 512 x 512 PSMT8 texture uploaded as CT32), then
  the same for a 16 x 16 PSMCT32 CLUT (CSM1 order, alpha 0x80 = opaque). UV = (S, 1 + T) over that 512 x 512 page.

  python -m gbox.defjam_models <iso> <out_dir> [data.bin index ...]
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path

import numpy as np

from . import defjam_inventory as inv
from .defjam_inventory import FormatError
from .side_dirs import side_dir

NODE_SIZE = 0x190
NODE_BASE = 0x10
MAX_NODES = 256
MATRIX_BASE, MATRIX_STRIDE = 64, 8
PARTS = {1: "body", 2: "body2", 3: "face", 4: "left_hand", 5: "right_hand", 6: "alpha1", 7: "alpha2"}
# where FACE / hands attach on BODY (node index in the BODY tree) and the BODY node of each collection role
ATTACH = {3: 7, 4: 13, 5: 19}
ROLE_NODES = {"hip": 2, "chest": 5, "neck": 6, "head": 7,
              "l_clav": 10, "l_upper": 11, "l_fore": 12, "l_hand": 13,
              "r_clav": 16, "r_upper": 17, "r_fore": 18, "r_hand": 19,
              "l_thigh": 25, "l_shin": 26, "l_foot": 29, "r_thigh": 35, "r_shin": 36, "r_foot": 39}
BODY_NODES = 42
UNPACK = {0x0: (1, 32), 0x1: (1, 16), 0x2: (1, 8), 0x4: (2, 32), 0x5: (2, 16), 0x6: (2, 8), 0x8: (3, 32),
          0x9: (3, 16), 0xA: (3, 8), 0xC: (4, 32), 0xD: (4, 16), 0xE: (4, 8), 0xF: (4, 5)}
MIN_WINDING = 0.85
SEAM, MIN_SEAM_VERTICES = 0.05, 6
GLTF_SCALE = 1.0 / 11.7         # game units -> metres: the 6'1" (1.85 m) wrestler's 21.7-unit T-pose ~ 1.85 m


# --- model slot ------------------------------------------------------------------------------------------------
def parse_nodes(blk: bytes) -> dict:
    """Node records -> {parent, palette, local (row-vector 4x4), world (T-pose)}; strict on indices and cycles."""
    if len(blk) < 0x20:
        raise FormatError("model slot shorter than its header")
    geo, gsz, nn = struct.unpack_from("<3I", blk, 0)
    if not 1 <= nn <= MAX_NODES:
        raise FormatError(f"implausible node count {nn}")
    if geo != (0x20 + nn * NODE_SIZE + 0x7F) & ~0x7F or geo + gsz > len(blk):
        raise FormatError(f"geometry 0x{geo:x}+0x{gsz:x} does not follow {nn} node records in 0x{len(blk):x} bytes")
    child, sib, pal, local = [], [], [], []
    for k in range(nn):
        o = NODE_BASE + k * NODE_SIZE
        c, s, p, _ = struct.unpack_from("<iiiI", blk, o)
        for v, what in ((c, "child"), (s, "sibling")):
            if not -1 <= v < nn:
                raise FormatError(f"node {k} {what} {v} outside 0..{nn - 1}")
        child.append(c)
        sib.append(s)
        pal.append(p)
        m = np.array(struct.unpack_from("<16f", blk, o + 0x50), np.float64).reshape(4, 4)
        if not np.isfinite(m).all() or abs(m[3, 3] - 1) > 1e-3 or np.abs(m[:3, 3]).max() > 1e-3:
            raise FormatError(f"node {k} local matrix is not affine")
        local.append(m)
    parent, seen, stack = [-1] * nn, set(), [(0, -1)]
    while stack:
        k, p = stack.pop()
        while k >= 0:
            if k in seen:
                raise FormatError(f"node {k} is reached twice (cycle)")
            seen.add(k)
            parent[k] = p
            if child[k] >= 0:
                stack.append((child[k], k))
            k = sib[k]
    if len(seen) != nn:
        raise FormatError(f"{nn - len(seen)} nodes are not reachable from node 0")
    world: list[np.ndarray] = [np.eye(4)] * nn
    order = sorted(range(nn), key=lambda k: _depth(parent, k))
    for k in order:
        world[k] = local[k] @ (world[parent[k]] if parent[k] >= 0 else np.eye(4))
    used = [p for p in pal if p >= 0]
    if len(set(used)) != len(used) or (used and max(used) >= nn):
        raise FormatError("palette slots repeat or exceed the node count")
    return {"count": nn, "geometry": (geo, gsz), "parent": parent, "palette": pal, "local": local, "world": world,
            "pal2node": {p: k for k, p in enumerate(pal) if p >= 0}}


def _depth(parent, k):
    d = 0
    while parent[k] >= 0 and d <= MAX_NODES:
        k, d = parent[k], d + 1
    return d


def _batch(data: bytes, n: int, acc: dict, pal2node: dict):
    if len(data) < n * 16:
        raise FormatError("batch shorter than its UNPACK count")
    ns, nw, nst, flags = struct.unpack_from("<4I", data, 0)
    need = 1 + 3 * ns + 4 * nw
    if not flags & 0x8000 or need > n or nst > 4096:
        raise FormatError(f"bad batch header ({ns}, {nw}, {nst}, 0x{flags:x}) for {n} qwords")
    q = np.frombuffer(data, "<f4", count=n * 4).reshape(n, 4)
    qi = np.frombuffer(data, "<u4", count=n * 4).reshape(n, 4)

    def joint(addr: int) -> int:
        slot, rem = divmod(int(addr) - MATRIX_BASE, MATRIX_STRIDE)
        if rem or slot not in pal2node:
            raise FormatError(f"matrix address {addr} is not a palette slot of this model")
        return pal2node[slot]
    offs = {}
    for j in range(ns + nw):
        k = 1 + 3 * j if j < ns else 1 + 3 * ns + 4 * (j - ns)
        offs[k] = len(acc["P"])
        acc["T"].append(q[k, :2])
        acc["N"].append(q[k + 1, :3])
        acc["P"].append(q[k + 2, :3])
        if j < ns:
            acc["J"].append((joint(qi[k, 3]), 0))
            acc["W"].append((1.0, 0.0))
        else:
            wa, wb = float(q[k + 3, 1]), float(q[k + 3, 3])
            if not (0 <= wa <= 1.001 and 0 <= wb <= 1.001 and abs(wa + wb - 1) < 0.02):
                raise FormatError(f"weights {wa}, {wb} do not sum to 1")
            acc["J"].append((joint(qi[k + 3, 0]), joint(qi[k + 3, 2])))
            acc["W"].append((wa, wb))
    words, pos, strips = qi[need:].reshape(-1), 0, []
    for _ in range(nst):
        if pos >= len(words):
            raise FormatError("strip list runs past the batch")
        ln = int(words[pos])
        pos += 1
        if ln < 3 or pos + ln > len(words):
            raise FormatError(f"bad strip length {ln}")
        strips.append([int(x) for x in words[pos:pos + ln]])
        pos += ln
    nlist = flags & 0x7FFF                                   # then n loose triangles, 3 addresses each
    if pos + 3 * nlist > len(words):
        raise FormatError(f"{nlist} loose triangles run past the batch")
    loose = [[int(x) for x in words[pos + 3 * t:pos + 3 * t + 3]] for t in range(nlist)]
    addrs = {a for s in strips + loose for a in s}
    base = next((bb for bb in (0, 0x100, 0x200, 0x300) if all(a - bb in offs for a in addrs)), None)
    if base is None:
        raise FormatError("strip addresses do not map onto the batch's vertices")
    for s in strips + loose:
        for i in range(len(s) - 2):
            a, b_, c = (offs[x - base] for x in s[i:i + 3])
            if i & 1:
                a, b_ = b_, a
            if a != b_ and b_ != c and a != c:
                acc["tris"].append((a, b_, c))
    acc["weighted"] += nw
    acc["loose"] += nlist
    acc["single"] += ns


def parse_model(blk: bytes) -> dict:
    """One model slot -> skeleton + skinned vertices (joint = node index of this slot's tree) + triangles."""
    sk = parse_nodes(blk)
    geo, gsz = sk["geometry"]
    acc = {"P": [], "N": [], "T": [], "J": [], "W": [], "tris": [], "weighted": 0, "single": 0, "loose": 0}
    o, end, batches = geo, geo + gsz, 0
    while o + 4 <= end:
        w = struct.unpack_from("<I", blk, o)[0]
        o += 4
        cmd, num, imm = (w >> 24) & 0x7F, (w >> 16) & 0xFF, w & 0xFFFF
        if cmd & 0x60 == 0x60:
            if cmd & 0xF not in UNPACK:
                raise FormatError(f"unknown UNPACK format 0x{cmd:x} at 0x{o - 4:x}")
            vn, vl = UNPACK[cmd & 0xF]
            n = num or 256
            nbytes = (vl * vn * n + 31) // 32 * 4
            if o + nbytes > end:
                raise FormatError(f"UNPACK at 0x{o - 4:x} runs past the geometry")
            if cmd & 0x6F == 0x6C and imm & 0x8000:
                _batch(blk[o:o + nbytes], n, acc, sk["pal2node"])
                batches += 1
            o += nbytes
        elif cmd in (0x30, 0x31):
            o += 16
        elif cmd == 0x20:
            o += 4
        elif cmd in (0x50, 0x51):
            o += (imm or 0x10000) * 16
        elif cmd == 0x4A:
            o += (num or 256) * 8
        elif cmd not in (0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x10, 0x11, 0x13, 0x14, 0x15, 0x17):
            raise FormatError(f"unknown VIF command 0x{cmd:02x} at 0x{o - 4:x}")
    if not batches:
        raise FormatError("no vertex batches in the model slot")
    return {**sk, "positions": np.array(acc["P"], np.float64).reshape(-1, 3),
            "normals": np.array(acc["N"], np.float64).reshape(-1, 3),
            "uvs": np.array(acc["T"], np.float64).reshape(-1, 2),
            "joints": np.array(acc["J"], np.int64).reshape(-1, 2), "weights": np.array(acc["W"], np.float64).reshape(-1, 2),
            "tris": np.array(acc["tris"], np.int64).reshape(-1, 3), "batches": batches,
            "weighted": acc["weighted"], "single": acc["single"], "loose": acc["loose"]}


ALPHA_VERTEX = 0x48


def parse_alpha(blk: bytes) -> dict:
    """ALPHA1/ALPHA2 slot (blended layers: hair cards, see-through cloth): {u32 node count, u32 vertices,
    u32 triangles, u32 0}, 0x10 bytes, node records (0x190 each from +0x20: {child, sibling, 0, 0, A, local}),
    vertices of 0x48 bytes {f32 position[3], f32 normal[3], f32 s, t, i32 node a, i32 node b, f32 weight a,
    f32 weight b, 0...}, then u32 triangle indices. Node indices are this slot's own tree: ALPHA2 carries the FACE
    tree (11 nodes, positions in FACE space), ALPHA1 the BODY spine (10 nodes: BODY 0..8 and 41, model space)."""
    if len(blk) < 0x20:
        raise FormatError("alpha slot shorter than its header")
    nn, nv, nt, _ = struct.unpack_from("<4I", blk, 0)
    if not 1 <= nn <= 64:
        raise FormatError(f"alpha layer node count {nn}")
    vo = 0x20 + nn * NODE_SIZE
    if not (nv and nt) or nv > 4096 or nt > 8192 or vo + nv * ALPHA_VERTEX + 12 * nt > len(blk):
        raise FormatError(f"alpha layer {nv} vertices / {nt} triangles do not fit 0x{len(blk):x} bytes")
    local = [np.array(struct.unpack_from("<16f", blk, 0x20 + k * NODE_SIZE + 0x50), np.float64).reshape(4, 4)
             for k in range(nn)]
    raw = np.frombuffer(blk, np.uint8, nv * ALPHA_VERTEX, vo).reshape(nv, ALPHA_VERTEX)
    f = raw[:, :0x20].copy().view("<f4").reshape(nv, 8).astype(np.float64)
    ji = raw[:, 0x20:0x28].copy().view("<i4").reshape(nv, 2).astype(np.int64)
    wt = raw[:, 0x28:0x30].copy().view("<f4").reshape(nv, 2).astype(np.float64)
    if (ji[:, 0] < 0).any() or (ji >= nn).any() or not np.isfinite(f).all():
        raise FormatError("alpha vertex joints outside the layer's tree")
    one = ji[:, 1] < 0
    ji[one, 1], wt[one, 1] = 0, 0.0
    if (np.abs(wt.sum(1) - 1) > 0.02).any():
        raise FormatError("alpha vertex weights do not sum to 1")
    tris = np.frombuffer(blk, "<u4", 3 * nt, vo + nv * ALPHA_VERTEX).reshape(nt, 3).astype(np.int64)
    if tris.max() >= nv:
        raise FormatError("alpha triangle index past the vertex list")
    return {"count": nn, "local": local, "positions": f[:, :3], "normals": f[:, 3:6], "uvs": f[:, 6:8], "joints": ji,
            "weights": wt, "tris": tris, "vertex_offset": vo}


def alpha_tree(al: dict, face: dict | None, body: dict):
    """Which tree an alpha layer rides: ("face", node map) when its locals are FACE's, ("body", {k: k, 9: 41}) when
    they are BODY's spine; None when neither matches."""
    def same(k, ref):
        return np.allclose(al["local"][k][3, :3], ref[3, :3], atol=1e-3)
    if face is not None and al["count"] == face["count"] and all(same(k, face["local"][k]) for k in range(min(9, al["count"]))):
        return "face", {k: k for k in range(al["count"])}
    if al["count"] == 10 and all(same(k, body["local"][k]) for k in range(9)):
        return "body", {**{k: k for k in range(9)}, 9: 41}
    return None


def winding(P: np.ndarray, N: np.ndarray, t: np.ndarray) -> float:
    """Share of triangles whose right-hand face normal agrees with the stored vertex normals (0.5 = noise)."""
    if not len(t):
        return 0.0
    fn = np.cross(P[t[:, 1]] - P[t[:, 0]], P[t[:, 2]] - P[t[:, 0]])
    d = (fn * (N[t[:, 0]] + N[t[:, 1]] + N[t[:, 2]])).sum(1)
    ok = np.abs(d) > 1e-12
    return float((d[ok] > 0).mean()) if ok.any() else 0.0


# --- GS texture packet -------------------------------------------------------------------------------------------
_BLOCK = np.array([[0, 1, 4, 5, 16, 17, 20, 21], [2, 3, 6, 7, 18, 19, 22, 23], [8, 9, 12, 13, 24, 25, 28, 29],
                   [10, 11, 14, 15, 26, 27, 30, 31]])
_COL32 = np.array([[0, 1, 4, 5, 8, 9, 12, 13], [2, 3, 6, 7, 10, 11, 14, 15], [16, 17, 20, 21, 24, 25, 28, 29],
                   [18, 19, 22, 23, 26, 27, 30, 31], [32, 33, 36, 37, 40, 41, 44, 45], [34, 35, 38, 39, 42, 43, 46, 47],
                   [48, 49, 52, 53, 56, 57, 60, 61], [50, 51, 54, 55, 58, 59, 62, 63]])
_COL8 = np.array([
    [0, 4, 16, 20, 32, 36, 48, 52, 2, 6, 18, 22, 34, 38, 50, 54], [8, 12, 24, 28, 40, 44, 56, 60, 10, 14, 26, 30, 42, 46, 58, 62],
    [33, 37, 49, 53, 1, 5, 17, 21, 35, 39, 51, 55, 3, 7, 19, 23], [41, 45, 57, 61, 9, 13, 25, 29, 43, 47, 59, 63, 11, 15, 27, 31],
    [96, 100, 112, 116, 64, 68, 80, 84, 98, 102, 114, 118, 66, 70, 82, 86],
    [104, 108, 120, 124, 72, 76, 88, 92, 106, 110, 122, 126, 74, 78, 90, 94],
    [65, 69, 81, 85, 97, 101, 113, 117, 67, 71, 83, 87, 99, 103, 115, 119],
    [73, 77, 89, 93, 105, 109, 121, 125, 75, 79, 91, 95, 107, 111, 123, 127],
    [128, 132, 144, 148, 160, 164, 176, 180, 130, 134, 146, 150, 162, 166, 178, 182],
    [136, 140, 152, 156, 168, 172, 184, 188, 138, 142, 154, 158, 170, 174, 186, 190],
    [161, 165, 177, 181, 129, 133, 145, 149, 163, 167, 179, 183, 131, 135, 147, 151],
    [169, 173, 185, 189, 137, 141, 153, 157, 171, 175, 187, 191, 139, 143, 155, 159],
    [224, 228, 240, 244, 192, 196, 208, 212, 226, 230, 242, 246, 194, 198, 210, 214],
    [232, 236, 248, 252, 200, 204, 216, 220, 234, 238, 250, 254, 202, 206, 218, 222],
    [193, 197, 209, 213, 225, 229, 241, 245, 195, 199, 211, 215, 227, 231, 243, 247],
    [201, 205, 217, 221, 233, 237, 249, 253, 203, 207, 219, 223, 235, 239, 251, 255]])


def _addr32(w: int, h: int, bw: int) -> np.ndarray:
    y, x = np.mgrid[0:h, 0:w]
    return ((y // 32) * bw + x // 64) * 8192 + _BLOCK[(y % 32) // 8, (x % 64) // 8] * 256 + _COL32[y % 8, x % 8] * 4


def _addr8(w: int, h: int, bw: int) -> np.ndarray:
    y, x = np.mgrid[0:h, 0:w]
    return ((y // 64) * (bw // 2) + x // 128) * 8192 + _BLOCK[(y % 64) // 16, (x % 128) // 16] * 256 + _COL8[y % 16, x % 16]


def ct32_as_t8(data: bytes, w32: int, h32: int) -> np.ndarray:
    """Texels uploaded as a w32 x h32 PSMCT32 rectangle (buffer width w32) and sampled as PSMT8: (2*h32, 2*w32)
    indices. Emulates the GS local-memory swizzle of both formats (page/block/column tables)."""
    if w32 % 64 or h32 % 32 or len(data) < w32 * h32 * 4:
        raise FormatError(f"CT32 upload {w32}x{h32} is not whole pages or is truncated")
    mem = np.zeros(w32 * h32 * 4, np.uint8)
    a = _addr32(w32, h32, w32 // 64).reshape(-1)
    src = np.frombuffer(data, np.uint8, w32 * h32 * 4).reshape(-1, 4)
    for k in range(4):
        mem[a + k] = src[:, k]
    return mem[_addr8(2 * w32, 2 * h32, 2 * w32 // 64)]


def _gif_transfers(pkt: bytes) -> list[dict]:
    """GIF A+D register writes followed by IMAGE data -> [{bitbltbuf, trxreg, data}] (bounded walk)."""
    out, o, regs = [], 0, {}
    while o + 16 <= len(pkt) and len(out) < 16:
        lo, hi = struct.unpack_from("<QQ", pkt, o)
        nloop, eop, flg, nreg = lo & 0x7FFF, (lo >> 15) & 1, (lo >> 58) & 3, (lo >> 60) & 15
        o += 16
        nreg = nreg or 16
        if flg == 0 and all((hi >> (4 * r)) & 0xF == 0xE for r in range(nreg)):     # PACKED, every register A+D
            for _ in range(nloop * nreg):
                if o + 16 > len(pkt):
                    raise FormatError("A+D data runs past the texture packet")
                val, reg = struct.unpack_from("<QQ", pkt, o)
                regs[reg & 0xFF] = val
                o += 16
        elif flg == 2:                                             # IMAGE
            n = nloop * 16
            if o + n > len(pkt):
                raise FormatError("IMAGE data runs past the texture packet")
            bb, tr = regs.get(0x50), regs.get(0x52)
            if bb is None or tr is None:
                raise FormatError("IMAGE transfer without BITBLTBUF/TRXREG")
            out.append({"at": o, "dbp": (bb >> 32) & 0x3FFF, "dbw": (bb >> 48) & 0x3F, "dpsm": (bb >> 56) & 0x3F,
                        "w": tr & 0xFFF, "h": (tr >> 32) & 0xFFF, "data": pkt[o:o + n]})
            o += n
        elif nloop == 0 and not eop:
            continue
        else:
            break
        if eop and flg == 2 and len(out) >= 2:
            break
    return out


def parse_texture(slot: bytes) -> dict:
    """WRS slot 18 -> {width, height, rgba (H, W, 4) uint8}."""
    if len(slot) < 0x90 or struct.unpack_from("<I", slot, 0)[0] != 0x80:
        raise FormatError("texture slot does not start with the 0x80 packet header")
    size = struct.unpack_from("<I", slot, 4)[0]
    pkt = slot[0x80:0x80 + size]
    xfers = _gif_transfers(pkt)
    if len(xfers) < 2:
        raise FormatError(f"texture packet has {len(xfers)} image transfers (need texels + CLUT)")
    tex, clut = xfers[0], xfers[1]
    if clut["dpsm"] != 0 or (clut["w"], clut["h"]) != (16, 16):
        raise FormatError(f"CLUT {clut['w']}x{clut['h']} psm {clut['dpsm']} is not a 256-colour CT32 CLUT")
    if tex["dpsm"] == 0:
        idx = ct32_as_t8(tex["data"], tex["w"], tex["h"])
    elif tex["dpsm"] == 0x13:
        if len(tex["data"]) < tex["w"] * tex["h"]:
            raise FormatError("PSMT8 texels truncated")
        idx = np.frombuffer(tex["data"], np.uint8, tex["w"] * tex["h"]).reshape(tex["h"], tex["w"])
    else:
        raise FormatError(f"texel upload psm 0x{tex['dpsm']:x} is not decoded")
    raw = np.frombuffer(clut["data"], np.uint8, 1024).reshape(256, 4)
    perm = [(i & ~0x18) | ((i & 8) << 1) | ((i & 0x10) >> 1) for i in range(256)]     # CSM1 order
    pal = raw[perm].copy()
    pal[:, 3] = np.minimum(255, pal[:, 3].astype(np.int32) * 2).astype(np.uint8)        # GS alpha 0x80 = 1.0
    return {"width": idx.shape[1], "height": idx.shape[0], "rgba": np.ascontiguousarray(pal[idx]),
            "texels_psm": tex["dpsm"], "transfers": [(x["w"], x["h"], x["dpsm"]) for x in xfers]}


def png_bytes(rgba: np.ndarray) -> bytes:
    h, w = rgba.shape[:2]
    raw = b"".join(b"\0" + rgba[y].tobytes() for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# --- assembly: one skeleton, placed parts ------------------------------------------------------------------------
def joint_name(part: int, k: int) -> str:
    return f"{PARTS[part] if part != 2 else 'body'}_{k:02d}"


def assemble(b: bytes, body_slot: int = 1) -> dict:
    """WRS container -> {joints [{name, parent, local, world}], prims [...], roles, report}. FACE / hands join the
    BODY tree under their attach nodes; their vertices are moved into model space by the attach node's T-pose."""
    w = inv.parse_wrs(b)
    if body_slot not in w["slots"]:
        raise FormatError(f"container has no slot {body_slot}")
    models, report = {}, []
    for part in (body_slot, 3, 4, 5):
        if part not in w["slots"]:
            continue
        s = w["slots"][part]
        blk = b[s["start"]:s["end"]]
        rec = {"slot": part, "part": PARTS[part], "bytes": len(blk), "sha256": hashlib.sha256(blk).hexdigest()}
        try:
            models[part] = parse_model(blk)
        except FormatError as e:
            if part == body_slot:
                raise
            report.append({**rec, "verified": False, "error": str(e)})
            continue
        report.append(rec)
    body = models[body_slot]
    if body["count"] != BODY_NODES:
        raise FormatError(f"BODY has {body['count']} nodes, the reader knows the {BODY_NODES}-node tree")
    joints, base = [], {}
    for part, m in models.items():
        base[part] = len(joints)
        attach = None if part == body_slot else ATTACH[part]
        A = np.eye(4) if attach is None else body["world"][attach]
        for k in range(m["count"]):
            p = m["parent"][k]
            parent = base[part] + p if p >= 0 else (-1 if attach is None else base[body_slot] + attach)
            joints.append({"name": joint_name(part, k), "parent": parent, "local": m["local"][k],
                           "world": m["world"][k] @ A})
    prims = []
    for rec in report:
        part = rec["slot"]
        if part not in models:
            continue
        m = models[part]
        attach = None if part == body_slot else ATTACH[part]
        A = np.eye(4) if attach is None else body["world"][attach]
        P = np.c_[m["positions"], np.ones(len(m["positions"]))] @ A
        N = m["normals"] @ A[:3, :3]
        N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)
        wv = winding(P[:, :3], N, m["tris"])
        nl = float(np.linalg.norm(m["normals"], axis=1).mean()) if len(m["normals"]) else 0.0
        rec.update(nodes=m["count"], batches=m["batches"], vertices=len(P), single=m["single"], weighted=m["weighted"],
                   triangles=len(m["tris"]), winding=round(max(wv, 1 - wv), 4), flipped=wv < 0.5,
                   normal_length=round(nl, 3), bbox=[P[:, :3].min(0).round(3).tolist(), P[:, :3].max(0).round(3).tolist()],
                   attach=None if attach is None else joint_name(body_slot, attach))
        rec["verified"] = bool(rec["triangles"] and rec["winding"] >= MIN_WINDING and abs(nl - 1) < 0.05)
        tris = m["tris"][:, ::-1] if wv < 0.5 else m["tris"]
        prims.append({"name": PARTS[part], "pos": P[:, :3], "nrm": N, "uv": np.c_[m["uvs"][:, 0], 1.0 + m["uvs"][:, 1]],
                      "joints": m["joints"] + base[part], "weights": m["weights"], "tris": tris})
    # seams: an attached part placed right shares its neck / wrist ring with BODY (8+ hand and 15+ face vertices
    # within SEAM of a BODY vertex on all 58 containers); a part on the wrong node shares none
    bodyP = prims[0]["pos"]
    model_prims = list(prims)
    for part in (6, 7):                                      # ALPHA1/ALPHA2: blended layers on the BODY / FACE tree
        if part not in w["slots"]:
            continue
        s = w["slots"][part]
        rec = {"slot": part, "part": PARTS[part], "bytes": s["end"] - s["start"]}
        try:
            al = parse_alpha(b[s["start"]:s["end"]])
            tree = alpha_tree(al, models.get(3), body)
            if tree is None:
                raise FormatError(f"alpha layer's {al['count']}-node tree is neither FACE's nor BODY's spine")
        except FormatError as e:
            report.append({**rec, "verified": False, "error": str(e)})
            continue
        on, nmap = tree
        A = body["world"][ATTACH[3]] if on == "face" else np.eye(4)
        P = np.c_[al["positions"], np.ones(len(al["positions"]))] @ A
        N = al["normals"] @ A[:3, :3]
        N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)
        wv = winding(P[:, :3], N, al["tris"])
        lift = base[3] if on == "face" else base[body_slot]
        J = np.vectorize(nmap.get)(al["joints"]) + lift
        rec.update(tree=on, vertices=len(P), triangles=len(al["tris"]), winding=round(max(wv, 1 - wv), 4),
                   attach=joint_name(body_slot, ATTACH[3]) if on == "face" else None,
                   bbox=[P[:, :3].min(0).round(3).tolist(), P[:, :3].max(0).round(3).tolist()])
        rec["verified"] = rec["winding"] >= MIN_WINDING and bool(P[:, 1].min() > 0)
        report.append(rec)
        prims.append({"name": rec["part"], "pos": P[:, :3], "nrm": N, "alpha": True, "joints": J,
                      "uv": np.c_[al["uvs"][:, 0], 1.0 + al["uvs"][:, 1]], "weights": al["weights"],
                      "tris": al["tris"][:, ::-1] if wv < 0.5 else al["tris"]})
    for rec, pr in zip([r for r in report if r["slot"] in models], model_prims):
        if rec["slot"] == body_slot:
            continue
        d = np.sqrt(((pr["pos"][:, None, :] - bodyP[None, :, :]) ** 2).sum(-1)).min(1)
        rec["seam_vertices"] = int((d < SEAM).sum())
        rec["placed"] = rec["seam_vertices"] >= MIN_SEAM_VERTICES
    roles = {r: joint_name(body_slot, n) for r, n in ROLE_NODES.items() if body["palette"][n] >= 0 or r == "hip"}
    return {"joints": joints, "prims": prims, "roles": roles, "report": report, "slots": w["slots"],
            "height": round(float(body["world"][8][3, 1]), 3)}


# --- skinned GLB -------------------------------------------------------------------------------------------------
def _trs(m_row: np.ndarray):
    M = m_row.T
    t = M[:3, 3]
    R = M[:3, :3]
    s = np.linalg.norm(R, axis=0)
    R = R / np.where(s == 0, 1, s)
    if np.linalg.det(R) < 0:
        s[0], R[:, 0] = -s[0], -R[:, 0]
    tr = np.trace(R)
    if tr > 0:
        k = np.sqrt(tr + 1.0) * 2
        q = [(R[2, 1] - R[1, 2]) / k, (R[0, 2] - R[2, 0]) / k, (R[1, 0] - R[0, 1]) / k, 0.25 * k]
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        k = np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        q = [0.25 * k, (R[0, 1] + R[1, 0]) / k, (R[0, 2] + R[2, 0]) / k, (R[2, 1] - R[1, 2]) / k]
    elif R[1, 1] > R[2, 2]:
        k = np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        q = [(R[0, 1] + R[1, 0]) / k, 0.25 * k, (R[1, 2] + R[2, 1]) / k, (R[0, 2] - R[2, 0]) / k]
    else:
        k = np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        q = [(R[0, 2] + R[2, 0]) / k, (R[1, 2] + R[2, 1]) / k, 0.25 * k, (R[1, 0] - R[0, 1]) / k]
    q = np.array(q)
    return t, q / np.linalg.norm(q), s


def write_glb(path: Path, a: dict, name: str, image: np.ndarray | None = None, scale: float = GLTF_SCALE,
              extras: dict | None = None) -> Path:
    """Assembled wrestler -> one skinned GLB (joint nodes with TRS = the game's local matrices, inverse binds from
    the T-pose, up to two weights per vertex, one material on the 512 x 512 texture page)."""
    bin_, views, accs = bytearray(), [], []

    def view(data: bytes, target=None):
        while len(bin_) % 4:
            bin_.append(0)
        views.append({"buffer": 0, "byteOffset": len(bin_), "byteLength": len(data), **({"target": target} if target else {})})
        bin_.extend(data)
        return len(views) - 1

    def acc(arr: np.ndarray, typ: str, ctype=5126, target=34962, minmax=False):
        arr = np.ascontiguousarray(arr)
        x = {"bufferView": view(arr.tobytes(), target), "componentType": ctype, "count": len(arr), "type": typ}
        if minmax:
            x["min"], x["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accs.append(x)
        return len(accs) - 1

    J = a["joints"]
    nodes = []
    for j in J:
        t, q, s = _trs(j["local"])
        nd = {"name": j["name"], "translation": [float(v * scale) for v in t], "rotation": [float(v) for v in q]}
        if np.abs(s - 1).max() > 1e-4:
            nd["scale"] = [float(v) for v in s]
        nodes.append(nd)
    for i, j in enumerate(J):
        if j["parent"] >= 0:
            nodes[j["parent"]].setdefault("children", []).append(i)
    roots = [i for i, j in enumerate(J) if j["parent"] < 0]
    ibm = []
    for j in J:
        W = j["world"].copy()
        W[3, :3] *= scale
        ibm.append(np.linalg.inv(W).astype(np.float32).reshape(16))     # inv(row-major W) == column-major inv(W^T)
    mat = {"name": f"{name}_skin", "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 0.9},
           "doubleSided": False}
    images, textures, samplers = [], [], []
    if image is not None:
        images.append({"bufferView": view(png_bytes(image)), "mimeType": "image/png", "name": f"{name}_tex"})
        textures.append({"source": 0, "sampler": 0})
        samplers.append({"magFilter": 9729, "minFilter": 9729, "wrapS": 10497, "wrapT": 10497})
        mat["pbrMetallicRoughness"]["baseColorTexture"] = {"index": 0}
        if int(image[..., 3].min()) < 250:
            mat.update(alphaMode="MASK", alphaCutoff=0.5)
    mats = [mat]
    if any(p.get("alpha") for p in a["prims"]):              # the ALPHA layers: blended, both sides (hair cards)
        mats.append({**json.loads(json.dumps(mat)), "name": f"{name}_alpha", "alphaMode": "BLEND", "doubleSided": True})
        mats[1].pop("alphaCutoff", None)
    prims = []
    for p in a["prims"]:
        jj = np.zeros((len(p["pos"]), 4), np.uint16)
        ww = np.zeros((len(p["pos"]), 4), np.float32)
        jj[:, :2] = p["joints"]
        ww[:, :2] = p["weights"]
        ww /= np.maximum(ww.sum(1, keepdims=True), 1e-9)
        attrs = {"POSITION": acc((p["pos"] * scale).astype(np.float32), "VEC3", minmax=True),
                 "NORMAL": acc(p["nrm"].astype(np.float32), "VEC3"),
                 "TEXCOORD_0": acc(p["uv"].astype(np.float32), "VEC2"),
                 "JOINTS_0": acc(jj, "VEC4", 5123), "WEIGHTS_0": acc(ww, "VEC4")}
        prims.append({"attributes": attrs, "indices": acc(p["tris"].reshape(-1).astype(np.uint32), "SCALAR", 5125, 34963),
                      "material": 1 if p.get("alpha") else 0})
    skin = {"name": f"{name}_rig", "joints": list(range(len(J))), "skeleton": roots[0],
            "inverseBindMatrices": acc(np.array(ibm, np.float32), "MAT4", target=None)}
    nodes.append({"name": name, "mesh": 0, "skin": 0})
    gl = {"asset": {"version": "2.0", "generator": "gbox.defjam_models", **({"extras": extras} if extras else {})},
          "scene": 0, "scenes": [{"name": name, "nodes": roots + [len(nodes) - 1]}], "nodes": nodes,
          "meshes": [{"name": name, "primitives": prims}], "skins": [skin], "materials": mats,
          "accessors": accs, "bufferViews": views, "buffers": [{"byteLength": len(bin_)}]}
    if images:
        gl.update(images=images, textures=textures, samplers=samplers)
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


def extract_wrs(b: bytes, out: Path, name: str, body_slot: int = 1, extras: dict | None = None) -> dict:
    """One WRS container -> rigged textured GLB + per-part checks."""
    a = assemble(b, body_slot)
    image, tex_err = None, None
    if 18 in a["slots"]:
        s = a["slots"][18]
        try:
            image = parse_texture(b[s["start"]:s["end"]])["rgba"]
        except FormatError as e:
            tex_err = str(e)
    else:
        tex_err = "no texture slot"
    glb = write_glb(out, a, name, image, extras={"source": f"Def Jam Vendetta PS2 {inv.SERIAL} v{inv.VERSION}",
                                                 "units": f"metres (game units x {GLTF_SCALE:.6f})", **(extras or {})})
    parts = a["report"]
    ok = all(r.get("verified") for r in parts) and all(r.get("placed", True) for r in parts) and image is not None
    return {"model": name, "glb": str(glb), "verified": bool(ok), "parts": parts, "roles": a["roles"],
            "joints": len(a["joints"]), "height": a["height"], "texture_error": tex_err,
            "triangles": sum(r.get("triangles", 0) for r in parts)}


# --- geometry codec (round trip; the writer's encoder) -------------------------------------------------------------
STATIC_GIF = bytes.fromhex("0000000000400e3112040000000000000080000000c00d911224411204000000"
                           "00000000040000200700000000000000")     # same 3 qwords in all 290 model slots on the disc
STATIC_AT = 0x39
MAX_BATCH_QW = 256


def decode_batches(blk: bytes) -> dict:
    """Model slot -> {nodes (raw records), batches [{verts [{st, n, p, mtx | w}], strips, loose}]}: every field the
    encoder needs to rebuild the slot byte for byte (addresses stay VU qword addresses)."""
    nn = struct.unpack_from("<3I", blk, 0)[2]
    parse_nodes(blk)                                         # validates the tree/geometry header
    geo, gsz = struct.unpack_from("<2I", blk, 0)
    batches, statics, o, end = [], [], geo, geo + gsz
    while o + 4 <= end:
        w = struct.unpack_from("<I", blk, o)[0]
        o += 4
        cmd, num, imm = (w >> 24) & 0x7F, (w >> 16) & 0xFF, w & 0xFFFF
        if cmd & 0x60 != 0x60:
            continue
        n = num or 256
        if cmd != 0x6C or o + n * 16 > end:
            raise FormatError(f"UNPACK 0x{cmd:x} at 0x{o - 4:x} is not a V4-32 inside the geometry")
        d = blk[o:o + n * 16]
        o += n * 16
        if not imm & 0x8000:
            statics.append((imm & 0x3FF, n))
            continue
        q = np.frombuffer(d, "<f4").reshape(n, 4)
        qi = np.frombuffer(d, "<u4").reshape(n, 4)
        ns, nw, nst, flags = (int(x) for x in qi[0])
        verts, k = [], 1
        for j in range(ns + nw):
            v = {"st": q[k, :3].tolist(), "n": q[k + 1].tolist(), "p": q[k + 2].tolist()}
            if j < ns:
                v["mtx"] = int(qi[k, 3])
                k += 3
            else:
                v["w"] = (int(qi[k + 3, 0]), float(q[k + 3, 1]), int(qi[k + 3, 2]), float(q[k + 3, 3]))
                v["stw"] = float(q[k, 3])
                k += 4
            verts.append(v)
        words, pos, strips = qi[k:].reshape(-1), 0, []
        for _ in range(nst):
            ln = int(words[pos])
            strips.append([int(x) for x in words[pos + 1:pos + 1 + ln]])
            pos += 1 + ln
        loose = [[int(x) for x in words[pos + 3 * t:pos + 3 * t + 3]] for t in range(flags & 0x7FFF)]
        batches.append({"verts": verts, "strips": strips, "loose": loose, "flg": flags & 0x8000})
    if statics != [(STATIC_AT, 7 + MATRIX_STRIDE * len([1 for p in parse_nodes(blk)["palette"] if p >= 0]))]:
        raise FormatError(f"static VU upload {statics} is not the GIF template + matrix palette")
    return {"nodes": blk[0x10:0x10 + nn * NODE_SIZE], "count": nn, "batches": batches}


def encode_batch(b: dict) -> bytes:
    """Batch -> UNPACK V4-32 payload (header, vertices, strips, loose triangles; padded to a qword)."""
    verts = b["verts"]
    ns = sum("mtx" in v for v in verts)
    if any("mtx" in v for v in verts[ns:]):
        raise FormatError("rigid vertices must come before weighted ones")
    out = [struct.pack("<4I", ns, len(verts) - ns, len(b["strips"]), b.get("flg", 0x8000) | len(b["loose"]))]
    for v in verts:
        if "mtx" in v:
            out.append(struct.pack("<3fI", *v["st"], v["mtx"]))
        else:
            out.append(struct.pack("<4f", *v["st"], v.get("stw", 1.0)))
        out += [struct.pack("<4f", *v["n"]), struct.pack("<4f", *v["p"])]
        if "w" in v:
            out.append(struct.pack("<IfIf", *v["w"]))
    words = [x for s in b["strips"] for x in [len(s), *s]] + [x for t in b["loose"] for x in t]
    words += [0] * (-len(words) % 4)
    data = b"".join(out) + struct.pack(f"<{len(words)}I", *words)
    if len(data) // 16 > MAX_BATCH_QW:
        raise FormatError(f"batch of {len(data) // 16} qwords exceeds the VU buffer ({MAX_BATCH_QW})")
    return data


def encode_model(nodes: bytes, count: int, batches: list[dict], npal: int) -> bytes:
    """Node records + batches -> a model slot laid out like the game's (VIF: BASE/OFFSET, static upload, MSCALF 0,
    then UNPACK/FLUSH/MSCALF 0xb/NOP per batch, a trailing FLUSH; slot padded to 0x80)."""
    static = STATIC_GIF + bytes(16 * (7 + MATRIX_STRIDE * npal) - len(STATIC_GIF))
    n_static = len(static) // 16
    vif = struct.pack("<3I", 0x03000100, 0x02000100, 0) + struct.pack("<I", 0x6C000000 | (n_static << 16) | STATIC_AT)
    vif += static + struct.pack("<3I", 0x11000000, 0x15000000, 0)
    for k, b in enumerate(batches):
        d = encode_batch(b)
        n = len(d) // 16
        vif += struct.pack("<I", 0x6C008000 | ((n & 0xFF) << 16)) + d
        vif += struct.pack("<2I", 0x11000000, 0x1500000B) + (struct.pack("<I", 0) if k < len(batches) - 1 else
                                                             struct.pack("<2I", 0x11000000, 0))
    geo = (0x20 + count * NODE_SIZE + 0x7F) & ~0x7F
    head = struct.pack("<3I", geo, len(vif), count).ljust(0x10, b"\0")
    blk = (head + nodes).ljust(geo, b"\0") + vif
    return blk + bytes(-len(blk) % 0x80)


# --- roster, collection hook, CLI ----------------------------------------------------------------------------------
NAMES = {198: "BRIGGS", 199: "BRIGGS", 200: "BRIGGS", 201: "TANK", 202: "TANK", 203: "TANK", 204: "PROOF",
         205: "PROOF", 206: "PROOF", 207: "SPIDER", 208: "SPIDER", 209: "SPIDER", 210: "CRUZ", 211: "STEEL",
         212: "DRAKE", 213: "DAN G", 214: "ARII", 215: "MASA", 216: "PEEWEE", 217: "PEEWEE", 218: "RUFFNECK",
         219: "RUFFNECK", 220: "CHUKKLEZ", 221: "ICEBERG", 222: "NYNE", 223: "SKETCH", 224: "SKETCH", 225: "MOSES",
         226: "POCKETS", 227: "SNOWMAN", 228: "HOUSE", 229: "HEADACHE", 230: "ZAHEER", 231: "RAZOR", 232: "RAZOR",
         233: "D-MOB", 234: "D-MOB", 235: "METHOD MAN", 236: "REDMAN", 237: "NORE", 238: "LUDACRIS", 239: "DMX",
         240: "KEITH MURRAY", 241: "WC", 242: "CAPONE", 243: "GHOSTFACE KILLAH", 244: "SCARFACE",
         245: "FUNKMASTER FLEX", 246: "JOE BUDDEN", 247: "MANNY", 248: "MANNY", 249: "OMAR", 250: "DEEBO", 251: "DEJA",
         252: "T'AI MONIQUE", 253: "OPAL", 254: "PENNY", 255: "CARLA"}      # SLUS_206.39 wrestler table (ELF 0x17F100)


def _title(n: str) -> str:
    return " ".join(w if w in ("DMX", "WC", "NORE", "G") else "-".join(x.capitalize() for x in w.split("-"))
                    for w in n.split(" "))


def roster() -> list[dict]:
    """The 58 WRS fighter buffers of SLUS_206.39 v1.00 (data.bin 198..255), named from the ELF's wrestler table."""
    out, seen = [], {}
    count = {n: sum(1 for v in NAMES.values() if v == n) for n in set(NAMES.values())}
    for i in range(inv.WRS_FIRST, inv.WRS_FIRST + inv.WRS_COUNT):
        n = NAMES[i]
        seen[n] = seen.get(n, 0) + 1
        nice = _title(n)
        label = nice if count[n] == 1 else f"{nice} (costume {seen[n]})"
        slug = "djv_ps2_" + "".join(c if c.isalnum() else "_" for c in n.lower()).strip("_")
        slug = slug if count[n] == 1 else f"{slug}_{seen[n]}"
        out.append({"key": f"wrs{i:03d}", "slug": slug, "data_index": i, "kind": "character",
                    "name": f"{label} (Def Jam Vendetta PS2)",
                    "aliases": [f"wrs{i:03d}", nice, n, f"Def Jam Vendetta {nice}"] + ([] if count[n] == 1 else [f"{nice} {seen[n]}"])})
    return out


def extract_index(disc: inv.Iso, index: int, out: Path, body_slot: int = 1) -> dict:
    ents = inv.entries(disc)
    if not 0 <= index < len(ents) or ents[index]["kind"] != "fighter":
        raise FormatError(f"data.bin entry {index} is not a WRS fighter container")
    e = ents[index]
    b = inv.read_entry(disc, e)
    r = extract_wrs(b, out, out.stem, body_slot, {"data_index": index, "data_sector": e["sector"],
                                                   "wrestler": NAMES.get(index)})
    r.update(data_index=index, sector=e["sector"], wrestler=NAMES.get(index),
             container_sha256=hashlib.sha256(b[:inv.parse_wrs(b)["size"]]).hexdigest())
    return r


def _source_iso(ctx, game: dict) -> Path:
    from . import characters as C
    try:
        p = C._rom(ctx, game)                                # the catalog source on this node (the .iso itself)
    except Exception:                                        # noqa: BLE001 - any resolver failure falls through
        p = None
    if p and Path(p).suffix.lower() == ".iso" and Path(p).exists():
        return Path(p)
    for p in [game.get("path"), *(game.get("source_paths") or []), (game.get("launch") or {}).get("path")]:
        if p and str(p).lower().endswith(".iso") and Path(str(p)).exists():
            return Path(str(p))
    gid = game.get("game_id") or game.get("id")
    for cache in (Path(getattr(getattr(ctx, "config", None), "cache", "") or side_dir("gbox-cache")) / str(gid) / "source.iso",
                  side_dir("gbox-cache") / str(gid) / "source.iso"):
        if cache.exists():
            return cache
    raise FormatError(f"no unpacked ISO for {gid}: stage it at ~/gBox_alt/gbox-cache/{gid}/source.iso")


def extract_run(ctx, game: dict, e: dict, work: Path) -> dict:
    """characters.DEDICATED hook: one WRS buffer -> verified rigged, textured GLB with body roles."""
    disc = inv.Iso(_source_iso(ctx, game))
    ident = inv.identify(disc)
    if not ident["exact_build"]:
        raise FormatError(f"{ident['serial']} v{ident['version']}: the reader is verified on {inv.SERIAL} v{inv.VERSION} only")
    r = extract_index(disc, int(e.get("data_index") or e["key"][3:]), Path(work) / f"{e['slug']}.glb")
    if not r["verified"]:
        bad = [p["part"] for p in r["parts"] if not (p.get("verified") and p.get("placed", True))]
        raise FormatError(f"{e['key']}: parts failed verification: {bad or r['texture_error']}")
    return {"files": [Path(r["glb"])], "roles": r["roles"], "tool": "gbox.defjam_models",
            "source_files": [f"{inv.DATA_NAME}#{r['data_index']} (WRS, sha256 {r['container_sha256'][:16]})"],
            "notes": (f"Native {inv.SERIAL} v{inv.VERSION} WRS model: BODY + FACE + both hands on one {r['joints']}-joint "
                      f"skeleton (T-pose bind, up to 2 weights per vertex), {r['triangles']} triangles, the fighter's "
                      "512x512 texture page.")}


def extract_all(iso, out_dir: Path, indices=None) -> dict:
    disc = inv.Iso(iso)
    out_dir = Path(out_dir)
    ros = {r["data_index"]: r for r in roster()}
    results = []
    for i in indices or range(inv.WRS_FIRST, inv.WRS_FIRST + inv.WRS_COUNT):
        try:
            results.append(extract_index(disc, i, out_dir / f"{ros[i]['slug']}.glb"))
        except (FormatError, KeyError) as e:
            results.append({"data_index": i, "verified": False, "error": str(e)})
    man = {"identity": inv.identify(disc), "verified": sum(bool(r["verified"]) for r in results),
           "total": len(results), "models": results}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(json.dumps(man, indent=1, default=str))
    return man


if __name__ == "__main__":
    m = extract_all(sys.argv[1], Path(sys.argv[2]), [int(x) for x in sys.argv[3:]] or None)
    print(json.dumps({k: m[k] for k in ("identity", "verified", "total")}, indent=1))
    for r in m["models"]:
        print(r.get("data_index"), r.get("wrestler"), r.get("verified"), r.get("error") or
              [(p["part"], p.get("triangles"), p.get("winding"), p.get("seam_gap")) for p in r["parts"]])
