"""PlatinumGames WMB model reader (Bayonetta 2 Switch, ``WMB\\0`` little-endian).

Proven fields (owned Bayonetta 2 pl0000/pl0010 .wmb, cross-checked on both):
  0x0c u32 vertex count      0x18 u32 vertex array offset (32-byte stride)
  0x1c u32 vertex ex-data offset (== 0x18 + 32*count, ex stride 16)
  0x30 u32 bone count        0x34 hierarchy (i16 parent, -1 root)
  0x38 relative positions    0x3c absolute positions   (3*f32 each)
Mesh/batch tables (proved on pl0000/pl0010, indices land inside each batch's vertex
range and triangle edges stay short):
  0x50 u32 mesh count, 0x54 u32 offset of per-mesh u32 offsets, 0x58 mesh base
  (mesh record = base + offset[i]); mesh +0x20 name[32]; mesh +0x80 u32 table of
  batch offsets relative to mesh+0x80 (table length = first entry / 4).
  Batch (at mesh+0x80+off): +0x00 u32 group, +0x0c vertex_start, +0x10 vertex_end,
  +0x14 prim type (4 = triangle list), +0x18 index data offset (rel. to batch),
  +0x1c u32 index count (u16 indices, RELATIVE to vertex_start; parse_meshes adds it), +0x40 u32 bone-set count + u8 bone ids.
  Vertex ex-data is 4 B/vertex (0x1c .. bone table), not 16.
Vertex (32 B): pos f32x3 | uv f16x2 | normal 4B packed | tangent 4B packed |
bone idx u8x4 | bone weight u8x4.  Header 0x5c is the total triangle count (23620 on pl0000). Packed normal/tangent
decode, material tables (0x70..0x7c) and 0x44/0x48 group table are NOT yet proved.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

VERTEX_STRIDE = 32
EX_STRIDE = 4


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


@dataclass
class WmbBatch:
    group: int
    vertex_start: int
    vertex_end: int
    prim: int
    indices: list
    bone_set: list
    material: int = 0   # u16 at batch+6 (proved: 0..12 == the 13 material records)


@dataclass
class WmbMesh:
    name: str
    batches: list


def parse_meshes(buf: bytes) -> list:
    """Parse mesh -> batch -> u16 index lists. Raises ValueError on bad tables."""
    nm, otab, base = struct.unpack_from("<I", buf, 0x50)[0], struct.unpack_from("<I", buf, 0x54)[0], \
        struct.unpack_from("<I", buf, 0x58)[0]
    nv = struct.unpack_from("<I", buf, 0x0c)[0]
    meshes = []
    for i in range(nm):
        moff = base + struct.unpack_from("<I", buf, otab + 4 * i)[0]
        name = buf[moff + 0x20:moff + 0x40].split(b"\0")[0].decode("ascii", "replace")
        first = struct.unpack_from("<I", buf, moff + 0x80)[0]
        if first % 4 or first == 0 or first > 0x80:
            raise ValueError("bad batch table in mesh %d" % i)
        offs = [o for o in struct.unpack_from("<%dI" % (first // 4), buf, moff + 0x80) if o]
        batches = []
        for bo in offs:
            b0 = moff + 0x80 + bo
            grp, = struct.unpack_from("<I", buf, b0)
            vs, ve, prim, ioff, ni = struct.unpack_from("<5I", buf, b0 + 0x0c)
            if ni % 3 or ve > nv or vs > ve:
                raise ValueError("bad batch header in mesh %d" % i)
            idx = [vs + i for i in struct.unpack_from("<%dH" % ni, buf, b0 + ioff)]
            if idx and max(idx) >= ve:
                raise ValueError("index out of range in mesh %d" % i)
            nb, = struct.unpack_from("<I", buf, b0 + 0x40)
            bs = list(buf[b0 + 0x44:b0 + 0x44 + nb])
            mat, = struct.unpack_from("<H", buf, b0 + 6)
            batches.append(WmbBatch(grp, vs, ve, prim, idx, bs, mat))
        meshes.append(WmbMesh(name, batches))
    return meshes


@dataclass
class WmbMaterial:
    index: int
    texture_ids: list   # u32 hashes found in the record, in order (first = base colour, HYPOTHESIS)
    size: int


def parse_materials(buf: bytes, wta_ids=()) -> list:
    """Material records: 0x44 u32 count, 0x48 u32 offset table, 0x4c u32 record base; record = u32 index, then u32 texture hashes (ids from the .wta id table or the
    global shared hashes listed at header 0x74 as (type,id) pairs), then float params.
    Record sizes (104/180/44/196) come from consecutive offsets; the last ends at 0x7c."""
    n, otab, base = struct.unpack_from("<III", buf, 0x44)
    tail = struct.unpack_from("<I", buf, 0x7c)[0]
    known = set(wta_ids)
    tpos = struct.unpack_from("<I", buf, 0x74)[0]
    # (slot-type, id) pairs at 0x74; ids shared with materials even when absent from the wta
    while tpos + 8 <= len(buf):
        typ, hid = struct.unpack_from("<II", buf, tpos)
        if typ > 100 or hid < 0x1000:
            break
        known.add(hid)
        tpos += 8
    offs = list(struct.unpack_from("<%dI" % n, buf, otab))
    out = []
    for i, o in enumerate(offs):
        end = offs[i + 1] if i + 1 < n else tail
        words = struct.unpack_from("<%dI" % ((end - o) // 4), buf, base + o)
        ids = []
        for x in words[1:]:
            if x in known:
                ids.append(x)
            elif ids:
                break
        out.append(WmbMaterial(words[0], ids, end - o))
    return out


def export_obj(w: Wmb, meshes: list) -> str:
    """Wavefront OBJ (positions + uv, one object per mesh) for editing/inspection."""
    out = []
    for v in w.vertices:
        out.append("v %.6f %.6f %.6f" % v.pos)
    for v in w.vertices:
        out.append("vt %.5f %.5f" % (v.uv[0], 1.0 - v.uv[1]))
    for m in meshes:
        out.append("o " + m.name)
        for b in m.batches:
            ix = b.indices
            for t in range(0, len(ix) - 2, 3):
                a, c, d = ix[t] + 1, ix[t + 1] + 1, ix[t + 2] + 1
                out.append("f %d/%d %d/%d %d/%d" % (a, a, c, c, d, d))
    return "\n".join(out) + "\n"
