"""Parasite Eve II (PS1): Aya's field model -> rigged GLB with body roles (#559 reader; characters.DEDICATED "pe2").

Model format (decoded from SLUS_010.42: instance builder 0x80041700, relocator 0x800409D0, bone renderer 0x80010848,
primitive handlers 0x80010F08 / 0x800110A0 / 0x800112DC / 0x800113E8 / 0x80011530). The model is LZ data that a type-0
chunk unpacks to a fixed RAM address, so every pointer is absolute:

  header (36 bytes): u32 0 (the relocator sets 1 once primitive codes became handler pointers), u32 ?, u32 ?,
      u32 bones, u32 per-bone vertex counts*, u32 vertices*, u32 normals*, u32 bones*, u32 primitive stream*
  bones: 0x24 bytes each: s16 R[9] (4.12, identity at rest), s16 pad, s32 T[3] (offset from the parent, PSX axes:
      +Y down), s16 parent, s16 pad
  vertices: s16 x, y, z, pad, bone-local, contiguous per bone in bone order (counts table)
  normals: s16 x, y, z, pad (4.12)
  primitive stream: groups [u32 code, u32 0 (handler slot), u32 count << 16 | words per item] + items; 0xFFFFFFFE
      ends a bone's groups, 0xFFFFFFFF ends the stream. The groups after the last bone are seams.
      0x38 (6 words) lit textured triangle: u16 v0 v1 v2 (byte offset / 8 = vertex), n0 n1 n2, uv0, clut, uv1, tpage,
           uv2, pad
      0x78 (7 words) lit textured quad: v0..v3, n0..n3, uv0, clut, uv1, tpage, uv2, uv3
      0xC8 (2 words) seam vertex: u16 vertex offset, normal offset, screen slot, colour slot (fills the per-vertex
           screen table under this bone's matrix)
      0x39 / 0x79 (5 words) seam triangle / quad on that table: u16 s0 s1 s2 [s3] (offset / 4 = vertex), uv0, clut,
           uv1, tpage, uv2 [uv3]
  Textures: 8-bit pages (tpage 0xB6 / 0xB7 = VRAM x 384 / 448, y 256) with CLUT rows 245/246, from the same file's
  type-1 and type-2 chunks (gbox.pe2_inventory.decode_image / decode_clut).

  python -m gbox.pe2_models <disc.chd | extracted dir> <out dir> [--outfit N ...]
"""
from __future__ import annotations

import argparse
import io
import json
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import pe2_inventory as I

C = np.diag([-1.0, -1.0, 1.0])                  # PSX (y down) -> glTF (y up); Aya faces PSX +Z -> glTF front +Z
SCALE = 1 / 1000                                  # PE2 units are millimetres (Aya ~1.7 m)
PRIM_WORDS = {0x38: 6, 0x78: 7, 0xC8: 2, 0x39: 5, 0x79: 5}
END_BONE = struct.pack("<I", 0xFFFFFFFE)
END_STREAM = struct.pack("<I", 0xFFFFFFFF)


@dataclass
class Prim:
    verts: list[int]
    uvs: list[tuple[int, int]]
    clut: int
    tpage: int
    bone: int
    seam: bool = False
    normals: list[int] = field(default_factory=list)
    code: int = 0x38


@dataclass
class Model:
    base: int
    header: int                    # offset of the header in the blob
    nbones: int
    rot: np.ndarray                # (B, 3, 3)
    trans: np.ndarray              # (B, 3) offset from the parent (PSX units / axes)
    parent: list[int]
    counts: list[int]
    verts: np.ndarray              # (V, 3) bone-local
    vbone: np.ndarray              # (V,)
    normals: np.ndarray            # (N, 3)
    prims: list[Prim]
    seams: list[tuple[int, int, int, int, int]]   # 0xC8 entries: (bone, vertex, normal, xy slot, rgb slot)
    layout: dict                   # blob offsets of each table (for the writer)
    unknown_codes: dict[int, int]

    def world(self) -> np.ndarray:
        """Rest-pose joint positions (PSX axes): the bones' translations accumulated (rotations are identity)."""
        W = np.zeros((self.nbones, 3))
        for b in range(self.nbones):
            p = self.parent[b]
            W[b] = self.trans[b] + (W[p] if 0 <= p < b else 0)
        return W

    def rest_vertices(self) -> np.ndarray:
        return self.verts + self.world()[self.vbone]


def _ptr(blob: bytes, base: int, v: int, size: int = 1) -> int | None:
    o = v - base
    return o if 0 <= o and o + size <= len(blob) else None


def find_headers(blob: bytes, base: int) -> list[int]:
    """Offsets of model headers in an LZ-unpacked blob: five in-blob pointers in table order and a sane bone count."""
    out = []
    for o in range(0, len(blob) - 36, 4):
        z, _a, _b, nb, pc, pv, pn, pb, pp = struct.unpack_from("<9I", blob, o)
        if z not in (0, 1) or not 1 <= nb <= 64:
            continue
        offs = [_ptr(blob, base, x) for x in (pc, pv, pn, pb, pp)]
        if None in offs:
            continue
        oc, ov, on, ob, op = offs
        if not (ob < oc <= ov < on < op <= o) or oc - ob != nb * 0x24 or ov - oc != nb * 4:
            continue
        out.append(o)
    return out


def parse_model(blob: bytes, base: int, header: int | None = None) -> Model:
    if header is None:
        hs = find_headers(blob, base)
        if not hs:
            raise ValueError("no PE2 model header in this blob")
        nb = {h: struct.unpack_from("<I", blob, h + 12)[0] for h in hs}
        header = max(hs, key=lambda h: (nb[h], h))           # the body; 1-bone headers are hand/prop parts
    if header + 36 > len(blob):
        raise ValueError("header past the blob")
    z, _a, _b, nb, pc, pv, pn, pb, pp = struct.unpack_from("<9I", blob, header)
    oc, ov, on, ob, op = (_ptr(blob, base, x) for x in (pc, pv, pn, pb, pp))
    if None in (oc, ov, on, ob, op):
        raise ValueError("model header points outside the blob")
    if z:
        raise ValueError("model already relocated (primitive codes replaced by handler pointers)")
    rot = np.zeros((nb, 3, 3))
    trans = np.zeros((nb, 3))
    parent = []
    for b in range(nb):
        o = ob + b * 0x24
        rot[b] = np.array(struct.unpack_from("<9h", blob, o), float).reshape(3, 3) / 4096.0
        trans[b] = struct.unpack_from("<3i", blob, o + 0x14)
        p = struct.unpack_from("<h", blob, o + 0x20)[0]
        parent.append(-1 if b == 0 or p == b else p)
        if not -1 <= parent[-1] < b:
            raise ValueError(f"bone {b}: parent {p} isn't an earlier bone")
    counts = list(struct.unpack_from(f"<{nb}I", blob, oc))
    nv = sum(counts)
    if ov + nv * 8 > on:
        raise ValueError("vertex table overlaps the normals")
    verts = np.array(struct.unpack_from(f"<{nv * 4}h", blob, ov), float).reshape(-1, 4)[:, :3]
    vbone = np.repeat(np.arange(nb), counts)
    nn = (op - on) // 8
    normals = np.array(struct.unpack_from(f"<{nn * 4}h", blob, on), float).reshape(-1, 4)[:, :3] / 4096.0
    prims, seams, unknown = [], [], {}
    o, bone = op, 0
    while True:
        if o + 4 > header:
            raise ValueError("primitive stream runs into the header")
        code = struct.unpack_from("<I", blob, o)[0]
        if code == 0xFFFFFFFF:
            end = o + 4
            break
        if code == 0xFFFFFFFE:
            bone += 1
            o += 4
            continue
        slot, cs = struct.unpack_from("<2I", blob, o + 4)
        cnt, words = cs >> 16, cs & 0xFFFF
        if slot or not 1 <= words <= 32 or o + 12 + cnt * words * 4 > header:
            raise ValueError(f"bad primitive group at {o:#x}")
        items = o + 12
        if code in PRIM_WORDS and PRIM_WORDS[code] == words:
            for k in range(cnt):
                h = struct.unpack_from(f"<{words * 2}H", blob, items + k * words * 4)
                b = min(bone, nb - 1)
                if code == 0x38:
                    prims.append(Prim([x // 8 for x in h[0:3]], [_uv(h[6]), _uv(h[8]), _uv(h[10])], h[7], h[9], b,
                                      normals=[x // 8 for x in h[3:6]], code=code))
                elif code == 0x78:
                    prims.append(Prim([x // 8 for x in h[0:4]], [_uv(h[8]), _uv(h[10]), _uv(h[12]), _uv(h[13])], h[9],
                                      h[11], b, normals=[x // 8 for x in h[4:8]], code=code))
                elif code == 0xC8:
                    seams.append((b, h[0] // 8, h[1] // 8, h[2], h[3]))
                elif code == 0x39:
                    prims.append(Prim([x // 4 for x in h[0:3]], [_uv(h[4]), _uv(h[6]), _uv(h[8])], h[5], h[7], b,
                                      seam=True, code=code))
                elif code == 0x79:
                    prims.append(Prim([x // 4 for x in h[0:4]], [_uv(h[4]), _uv(h[6]), _uv(h[8]), _uv(h[9])], h[5],
                                      h[7], b, seam=True, code=code))
        else:
            unknown[code] = unknown.get(code, 0) + cnt
        o = items + cnt * words * 4
    for p in prims:
        if any(not 0 <= v < nv for v in p.verts):
            raise ValueError(f"primitive references vertex outside 0..{nv - 1}")
    slots = {xy: (v, n) for _b, v, n, xy, _rgb in seams}
    for p, base_ in zip((p for p in prims if p.seam), seam_bases(prims)):
        p.normals = [slots.get(base_ + 8 + 12 * k, (p.verts[k], 0))[1] for k in range(len(p.verts))]
    layout = {"counts": oc, "verts": ov, "normals": on, "bones": ob, "prims": op, "prims_end": end, "header": header}
    return Model(base, header, nb, rot, trans, parent, counts, verts, vbone, normals, prims, seams, layout, unknown)


def _uv(h: int) -> tuple[int, int]:
    return h & 0xFF, h >> 8


def seam_bases(prims: list[Prim]) -> list[int]:
    """Packet offset of each seam primitive in the seam buffer (GT3 0x28 / GT4 0x34 bytes, stream order); the 0xC8
    entries write corner k's colour at base + 4 + 12k and screen XY at base + 8 + 12k."""
    out, o = [], 0
    for p in prims:
        if p.seam:
            out.append(o)
            o += 0x28 if len(p.verts) == 3 else 0x34
    return out


def packet_bytes(prims: list[Prim]) -> tuple[int, int]:
    """(all packet bytes, seam packet bytes) = header words +4 / +8."""
    allb = sum(0x28 if len(p.verts) == 3 else 0x34 for p in prims)
    return allb, sum(0x28 if len(p.verts) == 3 else 0x34 for p in prims if p.seam)


def serialize_tables(m: Model, start_ram: int) -> tuple[bytes, dict]:
    """bones, counts, vertices, normals, primitive stream laid out from RAM `start_ram` (the original order) ->
    (bytes, {counts, verts, normals, bones, prims: RAM pointers, pk_all, pk_seam}). Vertices must be grouped by bone
    (m.vbone non-decreasing); seam corners get 0xC8 entries in their vertex's bone, ordered by (vertex, slot)."""
    nb, nv = m.nbones, len(m.verts)
    if list(m.vbone) != sorted(m.vbone) or len(m.counts) != nb or sum(m.counts) != nv:
        raise ValueError("vertices must be contiguous per bone")
    out = bytearray()
    ptr = {"bones": start_ram}
    for b in range(nb):
        r = np.clip(np.round(m.rot[b] * 4096), -32768, 32767).astype(int).reshape(-1)
        t = np.round(m.trans[b]).astype(int)
        out += struct.pack("<9hh3ihh", *r, 0, *t, max(m.parent[b], 0), 0)
    ptr["counts"] = start_ram + len(out)
    out += struct.pack(f"<{nb}I", *m.counts)
    ptr["verts"] = start_ram + len(out)
    vv = np.clip(np.round(m.verts), -32768, 32767).astype(int)
    out += b"".join(struct.pack("<4h", *v, 0) for v in vv)
    ptr["normals"] = start_ram + len(out)
    nn = np.clip(np.round(m.normals * 4096), -32768, 32767).astype(int)
    out += b"".join(struct.pack("<4h", *n, 0) for n in nn)
    ptr["prims"] = start_ram + len(out)
    c8: dict[int, list] = {}
    for p, base in zip((p for p in m.prims if p.seam), seam_bases(m.prims)):
        for k, v in enumerate(p.verts):
            n = p.normals[k] if k < len(p.normals) else 0
            c8.setdefault(int(m.vbone[v]), []).append((v, base + 8 + 12 * k, n, base + 4 + 12 * k))

    def group(code, items, words):
        if not items:
            return b""
        return struct.pack("<3I", code, 0, len(items) << 16 | words) + b"".join(items)

    def uvw(uv):
        return uv[0] | uv[1] << 8
    for b in range(nb):
        mine = [p for p in m.prims if p.bone == b and not p.seam]
        tri = [struct.pack("<12H", *(8 * v for v in p.verts), *(8 * n for n in p.normals), uvw(p.uvs[0]), p.clut,
                           uvw(p.uvs[1]), p.tpage, uvw(p.uvs[2]), 0) for p in mine if len(p.verts) == 3]
        quad = [struct.pack("<14H", *(8 * v for v in p.verts), *(8 * n for n in p.normals), uvw(p.uvs[0]), p.clut,
                            uvw(p.uvs[1]), p.tpage, uvw(p.uvs[2]), uvw(p.uvs[3])) for p in mine if len(p.verts) == 4]
        sm = [struct.pack("<4H", 8 * v, 8 * n, xy, rgb) for v, xy, n, rgb in sorted(c8.get(b, []))]
        out += group(0x38, tri, 6) + group(0x78, quad, 7) + group(0xC8, sm, 2) + END_BONE
    s3 = [struct.pack("<10H", *(4 * v for v in p.verts), 0, uvw(p.uvs[0]), p.clut, uvw(p.uvs[1]), p.tpage,
                      uvw(p.uvs[2]), 0) for p in m.prims if p.seam and len(p.verts) == 3]
    s4 = [struct.pack("<10H", *(4 * v for v in p.verts), uvw(p.uvs[0]), p.clut, uvw(p.uvs[1]), p.tpage,
                      uvw(p.uvs[2]), uvw(p.uvs[3])) for p in m.prims if p.seam and len(p.verts) == 4]
    seams = [p for p in m.prims if p.seam]
    if seams and seams != [p for p in seams if len(p.verts) == 3] + [p for p in seams if len(p.verts) == 4]:
        raise ValueError("seam triangles must come before seam quads (packet order)")
    out += group(0x39, s3, 5) + group(0x79, s4, 5) + END_BONE + END_STREAM
    ptr["pk_all"], ptr["pk_seam"] = packet_bytes(m.prims)
    return bytes(out), ptr


def header_bytes(ptr: dict, nbones: int) -> bytes:
    return struct.pack("<9I", 0, ptr["pk_all"], ptr["pk_seam"], nbones, ptr["counts"], ptr["verts"], ptr["normals"],
                       ptr["bones"], ptr["prims"])


# ------------------------------------------------------------------------------------------------ VRAM

class VRAM:
    def __init__(self):
        self.mem = np.zeros((512, 1024), np.uint16)

    def put(self, x: int, y: int, w: int, h: int, data: bytes):
        a = np.frombuffer(data[:w * h * 2], np.uint16).reshape(h, w)
        self.mem[y:y + h, x:x + w] = a[:max(0, min(h, 512 - y)), :max(0, min(w, 1024 - x))]

    def load_file(self, cdf: bytes, chunks: list[I.Chunk]):
        for c in chunks:
            if c.type == 1:
                for blk in I.decode_image(I.payload(cdf, c)):
                    self.put(blk["x"], blk["y"] & 0x1FF, 64, 256, blk["data"])
            elif c.type == 2:
                cl = I.decode_clut(I.payload(cdf, c))
                self.put(cl["x"], cl["y"], cl["w"], cl["h"], cl["data"])

    @staticmethod
    def rgba(px: np.ndarray, opaque_black: bool = False) -> np.ndarray:
        r = (px & 31) * 255 // 31
        g = ((px >> 5) & 31) * 255 // 31
        b = ((px >> 10) & 31) * 255 // 31
        a = np.where((px == 0) & (not opaque_black), 0, 255)
        return np.stack([r, g, b, a], -1).astype(np.uint8)

    def page(self, tpage: int, clut: int) -> np.ndarray:
        """256x256 RGBA of a texture page through a CLUT (PSX tpage/clut words)."""
        tx, ty, mode = (tpage & 0xF) * 64, ((tpage >> 4) & 1) * 256, (tpage >> 7) & 3
        cx, cy = (clut & 0x3F) * 16, (clut >> 6) & 0x1FF
        if mode == 1:                                                 # 8-bit
            words = np.zeros((256, 128), np.uint16)
            w = min(128, 1024 - tx)
            words[:, :w] = self.mem[ty:ty + 256, tx:tx + w]
            idx = np.stack([words & 0xFF, words >> 8], -1).reshape(256, 256)
            pal = self.mem[cy, cx:cx + 256]
        elif mode == 0:                                               # 4-bit
            words = np.zeros((256, 64), np.uint16)
            w = min(64, 1024 - tx)
            words[:, :w] = self.mem[ty:ty + 256, tx:tx + w]
            idx = np.stack([(words >> (4 * k)) & 15 for k in range(4)], -1).reshape(256, 256)
            pal = self.mem[cy, cx:cx + 16]
        else:
            words = np.zeros((256, 256), np.uint16)
            w = min(256, 1024 - tx)
            words[:, :w] = self.mem[ty:ty + 256, tx:tx + w]
            return self.rgba(words)
        pal = np.concatenate([pal, np.zeros(max(0, int(idx.max()) + 1 - len(pal)), np.uint16)])
        return self.rgba(pal[idx])


# ------------------------------------------------------------------------------------------------ roles

def infer_roles(m: Model) -> dict[str, int]:
    """Body roles from the hierarchy (hip -> spine -> chest with two 4-bone arms + head; two 3-bone legs on the hip);
    left/right from geometry (the side the character's left hand is on when facing where the face points)."""
    kids = {b: [c for c in range(m.nbones) if m.parent[c] == b] for b in range(m.nbones)}

    def chain(b):
        out = [b]
        while len(kids[out[-1]]) == 1:
            out.append(kids[out[-1]][0])
        return out

    def size(b):
        return 1 + sum(size(c) for c in kids[b])
    root = 0
    hip = max(kids[root], key=size) if kids[root] else root
    legs = [c for c in kids[hip] if len(chain(c)) == 3 and not kids[chain(c)[-1]]]
    spine = [c for c in kids[hip] if c not in legs]
    if len(legs) != 2 or len(spine) != 1:
        raise ValueError("unexpected hip layout")
    chest = spine[0]
    while len(kids[chest]) == 1:
        chest = kids[chest][0]
    arms = [c for c in kids[chest] if len(chain(c)) == 4]
    heads = [c for c in kids[chest] if c not in arms]
    if len(arms) != 2 or len(heads) != 1:
        raise ValueError("unexpected chest layout")
    head = chain(heads[0])[-1]
    W = m.world() @ C.T
    pv = m.rest_vertices() @ C.T
    hv = pv[m.vbone == head]
    front = (hv.mean(0) - W[head]) if len(hv) else np.array([0, 0, 1.0])
    front[1] = 0
    if np.linalg.norm(front) < 1e-6:
        front = np.array([0, 0, 1.0])
    k = int(np.argmax(np.abs(front)))
    front = np.eye(3)[k] * np.sign(front[k])
    left = np.cross(np.array([0, 1.0, 0]), front)
    a, b = (chain(x) for x in arms)
    if W[a[1]] @ left < W[b[1]] @ left:
        a, b = b, a
    la, lb = (chain(x) for x in legs)
    if W[la[0]] @ left < W[lb[0]] @ left:
        la, lb = lb, la
    roles = {"hip": hip, "chest": chest, "head": head}
    if heads[0] != head:
        roles["neck"] = heads[0]
    for s, ch in (("l", a), ("r", b)):
        roles.update({f"{s}_clav": ch[0], f"{s}_upper": ch[1], f"{s}_fore": ch[2], f"{s}_hand": ch[3]})
    for s, ch in (("l", la), ("r", lb)):
        roles.update({f"{s}_thigh": ch[0], f"{s}_shin": ch[1], f"{s}_foot": ch[2]})
    return roles


# ------------------------------------------------------------------------------------------------ GLB

def _png(rgba: np.ndarray) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, "PNG", optimize=True)
    return buf.getvalue()


def to_glb(m: Model, vram: VRAM | None, path: Path, name: str = "aya", scale: float = SCALE) -> dict:
    """Skinned GLB: joints j00.. (rest = the file's bind pose), every vertex rigid on its bone, one atlas slot per
    (tpage, clut) pair used, feet on y = 0."""
    W = m.world()
    pv = (m.rest_vertices() @ C.T) * scale
    lift = -float(pv[:, 1].min())
    keys = []
    for p in m.prims:
        if (p.tpage, p.clut) not in keys:
            keys.append((p.tpage, p.clut))
    nk = max(1, len(keys))
    atlas = np.concatenate([vram.page(t, c) for t, c in keys], 0) if vram is not None and keys else None
    vn = np.zeros_like(pv)
    for p in m.prims:
        if p.normals:
            for v, n in zip(p.verts, p.normals):
                if 0 <= n < len(m.normals):
                    vn[v] += C @ (m.rot[m.vbone[v]] @ m.normals[n])
    P, N, UV, J = [], [], [], []
    for p in m.prims:
        slot = keys.index((p.tpage, p.clut))
        tris = [(0, 1, 2), (1, 3, 2)] if len(p.verts) == 4 else [(0, 1, 2)]
        for tri in tris:
            for c in (tri[0], tri[2], tri[1]):                 # PSX clockwise -> glTF counter-clockwise
                v = p.verts[c]
                P.append(pv[v])
                N.append(vn[v])
                u, w = p.uvs[c]
                UV.append(((u + 0.5) / 256.0, (slot * 256 + w + 0.5) / (256.0 * nk)))
                J.append(int(m.vbone[v]))
    P = np.array(P, np.float32).reshape(-1, 3)
    N = np.array(N, np.float32).reshape(-1, 3)
    for s in range(0, len(P), 3):                                 # vertices without a lit normal: face normal
        for k in range(3):
            if np.linalg.norm(N[s + k]) < 1e-6:
                fn = np.cross(P[s + 1] - P[s], P[s + 2] - P[s])
                N[s + k] = fn if np.linalg.norm(fn) > 0 else (0, 1, 0)
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)
    UV = np.array(UV, np.float32).reshape(-1, 2)
    J4 = np.zeros((len(P), 4), np.uint16)
    J4[:, 0] = J
    W4 = np.zeros((len(P), 4), np.float32)
    W4[:, 0] = 1
    blob, views, accs = bytearray(), [], []

    def add(arr, comp, typ, target=None, minmax=False):
        nonlocal blob
        blob += bytes((-len(blob)) % 4)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": arr.nbytes, **({"target": target} if target else {})})
        blob += arr.tobytes()
        a = {"bufferView": len(views) - 1, "componentType": comp, "count": int(arr.shape[0]), "type": typ}
        if minmax:
            a["min"], a["max"] = [float(x) for x in arr.min(0)], [float(x) for x in arr.max(0)]
        accs.append(a)
        return len(accs) - 1
    attrs = {"POSITION": add(P, 5126, "VEC3", 34962, True), "NORMAL": add(N.astype(np.float32), 5126, "VEC3", 34962),
             "TEXCOORD_0": add(UV, 5126, "VEC2", 34962), "JOINTS_0": add(J4, 5123, "VEC4", 34962),
             "WEIGHTS_0": add(W4, 5126, "VEC4", 34962)}
    mat = {"name": f"{name}_tex", "pbrMetallicRoughness": {"metallicFactor": 0, "roughnessFactor": 1,
           **({"baseColorTexture": {"index": 0}} if atlas is not None else {})},
           "alphaMode": "MASK", "alphaCutoff": 0.5, "doubleSided": True}
    prim = {"attributes": attrs, "indices": add(np.arange(len(P), dtype=np.uint32), 5125, "SCALAR", 34963), "material": 0}
    Wg = (W @ C.T) * scale
    nodes = [{"name": name, "translation": [0, lift, 0], "children": [1]}, {"name": f"{name}_mesh", "mesh": 0, "skin": 0}]
    for b in range(m.nbones):
        p = m.parent[b]
        t = Wg[b] - (Wg[p] if p >= 0 else 0)
        nodes.append({"name": f"j{b:02d}", "translation": [float(x) for x in t]})
    for b in range(m.nbones):
        ch = [2 + c for c in range(m.nbones) if m.parent[c] == b]
        if ch:
            nodes[2 + b]["children"] = ch
    roots = [2 + b for b in range(m.nbones) if m.parent[b] < 0]
    nodes[0]["children"] += roots
    ibm = []
    for b in range(m.nbones):
        mm = np.eye(4)
        mm[:3, 3] = Wg[b]
        ibm.append(np.linalg.inv(mm).T.reshape(-1))
    skin = {"joints": [2 + b for b in range(m.nbones)], "skeleton": roots[0],
            "inverseBindMatrices": add(np.array(ibm, np.float32), 5126, "MAT4")}
    gl = {"asset": {"version": "2.0", "generator": "gBox pe2_models.py"}, "scene": 0, "scenes": [{"nodes": [0]}],
          "nodes": nodes, "meshes": [{"name": f"{name}_mesh", "primitives": [prim]}], "skins": [skin],
          "materials": [mat], "accessors": accs, "bufferViews": views, "buffers": [{"byteLength": 0}]}
    if atlas is not None:
        png = _png(atlas)
        blob += bytes((-len(blob)) % 4)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(png)})
        blob += png
        gl["images"] = [{"bufferView": len(views) - 1, "mimeType": "image/png", "name": f"{name}_atlas"}]
        gl["textures"] = [{"source": 0, "sampler": 0}]
        gl["samplers"] = [{"magFilter": 9728, "minFilter": 9728, "wrapS": 33071, "wrapT": 33071}]
    blob += bytes((-len(blob)) % 4)
    gl["buffers"][0]["byteLength"] = len(blob)
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * ((-len(js)) % 4)
    out = struct.pack("<III", 0x46546C67, 2, 28 + len(js) + len(blob))
    out += struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob)
    Path(path).write_bytes(out)
    return {"path": str(path), "bones": m.nbones, "verts": int(len(m.verts)), "prims": len(m.prims),
            "seam_prims": sum(p.seam for p in m.prims), "atlas_slots": len(keys),
            "height_m": float(np.ptp(pv[:, 1])), "unknown_codes": {hex(k): v for k, v in m.unknown_codes.items()}}


# ------------------------------------------------------------------------------------------------ Aya

def load_file_model(disc: I.PE2Disc, fid: int) -> tuple[Model, VRAM, dict]:
    cdf = disc.cdf
    ch = disc.chunks(fid)
    lz = [c for c in ch if c.type == 0]
    if not lz:
        raise ValueError(f"file {fid}: no LZ RAM chunk")
    blob, _ = I.lz_decode(I.payload(cdf, lz[-1]))
    m = parse_model(blob, lz[-1].addr)
    vram = VRAM()
    vram.load_file(cdf, ch)
    return m, vram, {"file": fid, "chunk": lz[-1], "blob": blob}


def export_aya(disc: I.PE2Disc, outfit: int, out: Path) -> dict:
    fid = disc.outfit_files()[outfit]
    m, vram, info = load_file_model(disc, fid)
    rep = to_glb(m, vram, out, name=f"aya_{I.AYA_OUTFIT_NAMES.get(outfit, outfit)}")
    rep["roles"] = {k: f"j{v:02d}" for k, v in infer_roles(m).items()}
    rep["file"] = fid
    return rep


# characters.DEDICATED hooks ------------------------------------------------------------------------

def roster() -> list[dict]:
    out = []
    for o, n in I.AYA_OUTFIT_NAMES.items():
        label = n.replace("_", " ")
        out.append({"key": o, "slug": "pe2_aya" if o == I.DEFAULT_OUTFIT else f"pe2_aya_{n}", "name": f"Aya Brea (PE2, {label})",
                    "kind": "character", "aliases": [f"PE2 Aya {label}"] + (["PE2 Aya", "Aya (Parasite Eve II)"] if o == I.DEFAULT_OUTFIT else [])})
    return out


def extract_run(ctx, game, e, work):
    from .characters import _rom
    disc = I.PE2Disc(_rom(ctx, game))
    out = Path(work) / f"pe2_aya_{I.AYA_OUTFIT_NAMES[e['key']]}.glb"
    rep = export_aya(disc, e["key"], out)
    return {"files": [out], "tool": "gbox.pe2_models (export_aya)", "roles": rep["roles"],
            "source_files": ["STAGE0.CDF file %d (LZ model + 8-bit texture + CLUT)" % rep["file"], "SLUS_010.42"],
            "notes": f"PE2 field model, {rep['bones']} bones, {rep['prims']} primitives (rest pose = the file's bind "
                     "pose); body roles from the hierarchy, left/right from the face direction."}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m gbox.pe2_models")
    ap.add_argument("disc")
    ap.add_argument("out")
    ap.add_argument("--outfit", type=int, action="append")
    a = ap.parse_args(argv)
    disc = I.PE2Disc(a.disc)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    for o in a.outfit or sorted(I.AYA_OUTFIT_NAMES):
        rep = export_aya(disc, o, Path(a.out) / f"pe2_aya_{I.AYA_OUTFIT_NAMES[o]}.glb")
        print(json.dumps(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
