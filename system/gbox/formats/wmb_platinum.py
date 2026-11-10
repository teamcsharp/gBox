"""PlatinumGames WMB model reader (Bayonetta 2 Switch, ``WMB\\0`` little-endian).

Proven fields (owned Bayonetta 2 pl0000/pl0010 .wmb, cross-checked on both):
  0x0c u32 vertex count      0x18 u32 vertex array offset (32-byte stride)
  0x1c u32 vertex ex-data offset (== 0x18 + 32*count, ex stride 16)
  0x30 u32 bone count        0x34 hierarchy (i16 parent, -1 root)
  0x38 relative positions    0x3c absolute positions   (3*f32 each)
Vertex (32 B): pos f32x3 | uv f16x2 | normal 4B packed | tangent 4B packed |
bone idx u8x4 | bone weight u8x4.  Packed normal/tangent decode, batch/index
tables (0x44..0x7c) and material tables are NOT yet proved (hypotheses only).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

VERTEX_STRIDE = 32
EX_STRIDE = 16


@dataclass
class WmbVertex:
    pos: tuple
    uv: tuple
    normal_raw: int
    tangent_raw: int
    bone_idx: tuple
    bone_w: tuple


@dataclass
class Wmb:
    flags: int
    vertex_count: int
    vertex_off: int
    ex_off: int
    parents: list
    rel_pos: list
    abs_pos: list
    vertices: list


def parse_wmb(buf: bytes, with_vertices: bool = True) -> Wmb:
    if buf[:4] != b"WMB\0":
        raise ValueError("not WMB")
    flags, nv = struct.unpack_from("<II", buf, 8)
    ov, oe = struct.unpack_from("<II", buf, 0x18)
    nb, oh, orp, oab = struct.unpack_from("<4I", buf, 0x30)
    if oe != ov + VERTEX_STRIDE * nv and oe < ov + VERTEX_STRIDE * nv:
        raise ValueError("vertex array overlaps ex data")
    if ov + VERTEX_STRIDE * nv > len(buf) or oh + 2 * nb > len(buf):
        raise ValueError("table out of range")
    parents = list(struct.unpack_from("<%dh" % nb, buf, oh))
    if any(p < -1 or p >= nb for p in parents):
        raise ValueError("bad bone parent")
    rel = [struct.unpack_from("<3f", buf, orp + 12 * i) for i in range(nb)]
    ab = [struct.unpack_from("<3f", buf, oab + 12 * i) for i in range(nb)]
    verts = []
    if with_vertices:
        for i in range(nv):
            o = ov + VERTEX_STRIDE * i
            p = struct.unpack_from("<3f", buf, o)
            uv = struct.unpack_from("<2e", buf, o + 12)
            n, t = struct.unpack_from("<II", buf, o + 16)
            verts.append(WmbVertex(p, uv, n, t, tuple(buf[o + 24:o + 28]), tuple(buf[o + 28:o + 32])))
    return Wmb(flags, nv, ov, oe, parents, rel, ab, verts)


def skeleton_error(w: Wmb) -> float:
    """Max |abs - (parent_abs + rel)| over bones; ~0 proves the tables."""
    err = 0.0
    for i, p in enumerate(w.parents):
        base = w.abs_pos[p] if p >= 0 else (0.0, 0.0, 0.0)
        for k in range(3):
            err = max(err, abs(w.abs_pos[i][k] - base[k] - w.rel_pos[i][k]))
    return err
