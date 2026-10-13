"""007: Agent Under Fire (GameCube, GW7E69) level package (.ngc) and model (.gcm) probe.

Every layout below was read from the owned disc's ``/base.elf/Bond.elf``
(sha256 1a9c0d19fb7bab09c2fd6ef56bd8158e88e507f72ba982d0ca292bc8145e716f), which
keeps its symbol table, so the functions are named and the offsets reproducible:

``maps/*.ngc`` -- ``RSRC_Load`` 0x80016AFC
    A sequence of 32-byte aligned chunks. ``GetChunkHeader`` 0x80010B6C aligns the
    file position to 32 and reads a 0x20-byte big-endian header::

        +0x00 char id[8]   two u32 words, each byte-reversed (``ChunkIDToStr`` 0x80010858)
        +0x08 u32 size     uncompressed payload size (``SkipChunkData`` 0x80010A54 seeks it)
        +0x0C f32 version
        +0x10 u32 compressed
        +0x14 u32 pad (0xCDCDCDCD)
        +0x18 u32 disk_size  bytes stored after the header (``ReadChunkData`` 0x80010A7C)
        +0x1C u32 mem_size   expanded buffer size (size rounded up to 32)

    Compressed payloads use ``BOA_ExpandInplace`` 0x8001094C: an LZ77 variant with
    an LSB-first flag byte per 8 tokens; a set bit is a literal byte, a clear bit a
    2-byte back-reference ``b0, b1``: ``length = (b0 & 15) + 2`` (length nibble 0 is a
    no-op), ``distance = (b0 >> 4) | (b1 << 4)``.  Known chunk ids and their
    consumers in RSRC_Load: ``restable`` (FS_UseResourceTable 0x801AEF64),
    ``restxtrs`` (RSRC_InitStaticTextures), ``dyntxtrs`` (RSRC_InitDynTextures),
    ``shaders`` (SHDR_Init), ``bspfile`` (BSP_Init), ``sndbank`` /
    ``snd_alb`` (AL_LoadSampleBankMem / AL_LoadPatchBankMem), ``shockprf``.

``restable`` -- ``FS_UseResourceTable`` 0x801AEF64
    The level's file system: u32 count, then from +0x10 ``count`` records of
    ``{u32 name_off, u32 data_off, u32 size, u32 hash}`` relative to the table.
    It holds the character models (``models/actors/**.gcm``), animations (``.gca``),
    entity definitions (``.men``) and scripts.

``.gcm`` -- ``NGCObject3D::FixupModelData`` 0x8017AA9C,
``C_Object3D::FixupModelData`` 0x80183968, ``FixupHeaderOff`` 0x80183AF4,
``NGCObject3D::FixupNGCModelData`` 0x8017AB18
    Blocks start with a header whose byte 7 is the extra header length; the
    block body starts at ``block + 8 + byte7``.  ``(u32[0] >> 20) & 0x4FF == 0x484``
    marks an object.  Body offsets +0x74..+0x94 are block offsets relative to the
    file; body+0x80 is the NGC geometry block.  Its body holds 13 ``{u32 off, u32
    count}`` pairs (offsets relative to that body) at +0x34..+0x94; the element sizes
    below are the ones that tile every character model exactly (see ``tile_check``).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from dataclasses import asdict, dataclass

BOND_ELF_SHA256 = "1a9c0d19fb7bab09c2fd6ef56bd8158e88e507f72ba982d0ca292bc8145e716f"
SOURCE_GCZ_SHA256 = "00a0ebbd99cf3934b626dbc0d5bfa0de53e91a1f717fbb1814cb6c93d393faac"

# Bond.elf functions (RAM addresses as linked; ET_EXEC, symbol table kept).
EVIDENCE = {
    "RSRC_Load": 0x80016AFC,
    "GetChunkHeader": 0x80010B6C,
    "ReadChunkData": 0x80010A7C,
    "SkipChunkData": 0x80010A54,
    "ChunkIDToStr": 0x80010858,
    "BOA_ExpandInplace": 0x8001094C,
    "FS_UseResourceTable": 0x801AEF64,
    "NGCObject3D::FixupModelData": 0x8017AA9C,
    "NGCObject3D::FixupNGCModelData": 0x8017AB18,
    "C_Object3D::FixupModelData": 0x80183968,
    "C_Object3D::FixupHeaderOff": 0x80183AF4,
    "C_Q3Object3D::CreateObjectFrom": 0x80178B4C,
    "ME_LoadTIKIfile": 0x80173C24,
    "ME_LoadModel": 0x801748B4,
    "NGCObject3D::BuildMatrixList": 0x8017A674,
    "C_Q3Object3D::AnimateSkeleton": 0x80177958,
}

CHUNK_HEADER = 0x20
OBJECT_MAGIC = 0x484

# NGC geometry body: (field offset of the pointer, name, element size).
# The u32 count follows each pointer.  Order and names come from
# FixupNGCModelData's RecoverPointer<T> calls.
NGC_ARRAYS = (
    (0x34, "vtx_pos", 6),        # NGC_EntVtxPos_s: s16 x,y,z
    (0x3C, "vtx_normal", 3),     # NGC_EntVtxNormal_s: s8 x,y,z
    (0x44, "vtx_st", 4),         # NGC_EntVtxST_s: s16 s,t
    (0x4C, "ent_vtx", 6),        # NGC_EntVtx_s: u16 pos, normal, st indices
    (0x54, "u16_list", 2),       # RecoverPointer<unsigned short>
    (0x5C, "u8_list", 1),        # RecoverPointer<unsigned char>
    (0x64, "tri_strip", 8),      # NGC_EntTriStrip_s
    (0x6C, "mtx_map", 2),        # NGC_EntMtxMap_s
    (0x74, "geom_group", 8),     # NGC_EntGeomGroup_s
    (0x7C, "geom_section", 16),  # NGC_EntGeomSection_s (+4 = shader id -> SHDR_LookupID)
    (0x84, "morph_delta", None),
    (0x8C, "morph_vtx", None),
    (0x94, "morph_group", 12),   # NGC_MorphGroup_s (+4 -> MorphVtx)
)


def chunk_id(raw: bytes) -> str:
    """Decode an 8-byte chunk id exactly like ChunkIDToStr (two byte-reversed words)."""
    w0, w1 = struct.unpack(">II", raw[:8])
    return (struct.pack("<I", w1) + struct.pack("<I", w0)).split(b"\0", 1)[0].decode("latin-1")


def encode_chunk_id(name: str) -> bytes:
    b = name.encode("latin-1").ljust(8, b"\0")[:8]
    w1 = struct.unpack("<I", b[:4])[0]
    w0 = struct.unpack("<I", b[4:])[0]
    return struct.pack(">II", w0, w1)


def boa_expand(src: bytes, size: int, pos: int = 0) -> tuple[bytes, int]:
    """BOA_ExpandInplace. Returns (expanded bytes, input bytes consumed)."""
    out = bytearray()
    i = pos
    n_src = len(src)
    while len(out) < size:
        if i >= n_src:
            raise ValueError("BOA stream truncated at %d/%d output bytes" % (len(out), size))
        flags = src[i]
        i += 1
        for bit in range(8):
            if len(out) >= size:
                break
            if flags >> bit & 1:
                out.append(src[i])
                i += 1
                continue
            b0, b1 = src[i], src[i + 1]
            i += 2
            n = b0 & 15
            if not n:
                continue
            dist = (b0 >> 4) | (b1 << 4)
            start = len(out) - dist
            if dist == 0 or start < 0:
                raise ValueError("BOA back-reference before start (dist %d at %d)" % (dist, len(out)))
            for k in range(n + 2):
                out.append(out[start + k])
    return bytes(out[:size]), i - pos


def boa_store(data: bytes) -> bytes:
    """Encode ``data`` as an all-literal BOA stream (valid input for boa_expand)."""
    out = bytearray()
    for i in range(0, len(data), 8):
        block = data[i:i + 8]
        out.append(0xFF)
        out += block
    return bytes(out)


@dataclass
class Chunk:
    id: str
    offset: int
    size: int
    version: float
    compressed: int
    disk_size: int
    mem_size: int

    @property
    def data_offset(self) -> int:
        return self.offset + CHUNK_HEADER

    @property
    def end(self) -> int:
        return (self.data_offset + self.disk_size + 31) & ~31


def iter_chunks(data: bytes):
    pos = 0
    while pos + CHUNK_HEADER <= len(data):
        h = data[pos:pos + CHUNK_HEADER]
        size, ver, comp, _pad, disk, mem = struct.unpack(">IfIIII", h[8:])
        c = Chunk(chunk_id(h), pos, size, ver, comp, disk, mem)
        if c.data_offset + disk > len(data):
            raise ValueError("chunk %r at %#x overruns the file" % (c.id, pos))
        yield c
        pos = c.end


def read_chunk(data: bytes, c: Chunk) -> bytes:
    raw = data[c.data_offset:c.data_offset + c.disk_size]
    if not c.compressed:
        return raw[:c.size]
    out, _used = boa_expand(raw, c.mem_size)
    return out


@dataclass
class Resource:
    name: str
    offset: int
    size: int
    hash: int


def parse_restable(table: bytes) -> list[Resource]:
    count = struct.unpack_from(">I", table, 0)[0]
    out = []
    for i in range(count):
        no, do, sz, hv = struct.unpack_from(">4I", table, 0x10 + i * 16)
        end = table.index(b"\0", no)
        if do + sz > len(table):
            raise ValueError("resource %d overruns the table" % i)
        out.append(Resource(table[no:end].decode("latin-1"), do, sz, hv))
    return out


class NgcPackage:
    def __init__(self, data: bytes):
        self.data = data
        self.chunks = list(iter_chunks(data))
        self._table = None

    def chunk(self, cid: str) -> Chunk:
        for c in self.chunks:
            if c.id == cid:
                return c
        raise KeyError(cid)

    @property
    def table(self) -> bytes:
        if self._table is None:
            self._table = read_chunk(self.data, self.chunk("restable"))
        return self._table

    def resources(self) -> list[Resource]:
        return parse_restable(self.table)

    def read(self, name: str) -> bytes:
        for r in self.resources():
            if r.name.lower() == name.lower():
                return self.table[r.offset:r.offset + r.size]
        raise KeyError(name)


def _body(data: bytes, block: int) -> int:
    return block + 8 + data[block + 7]


def gcm_info(gcm: bytes) -> dict:
    """Header + NGC geometry array table of one .gcm object."""
    word0 = struct.unpack_from(">I", gcm, 0)[0]
    if (word0 >> 20) & 0x4FF != OBJECT_MAGIC:
        raise ValueError("not an NGCObject3D model (magic %#x)" % ((word0 >> 20) & 0x4FF))
    hdr = _body(gcm, 0)
    flags = struct.unpack_from(">I", gcm, hdr + 8)[0]
    file_size = struct.unpack_from(">I", gcm, hdr + 0x0C)[0]
    blocks = {}
    for off in (0x74, 0x78, 0x7C, 0x80, 0x84, 0x88, 0x8C, 0x90, 0x94):
        blocks[off] = struct.unpack_from(">I", gcm, hdr + off)[0]
    ngc_block = blocks[0x80]
    if not ngc_block:
        raise ValueError("no NGC geometry block")
    body = _body(gcm, ngc_block)
    arrays = []
    for field, name, esize in NGC_ARRAYS:
        off, count = struct.unpack_from(">II", gcm, body + field)
        arrays.append({"name": name, "field": field, "offset": off, "count": count,
                       "elem_size": esize, "file_offset": body + off if off else 0})
    return {"flags": flags, "file_size": file_size, "packed": bool(flags & 0x8000),
            "blocks": {"%#x" % k: v for k, v in blocks.items()},
            "ngc_block": ngc_block, "ngc_body": body, "arrays": arrays}


def tile_check(info: dict) -> list[str]:
    """Check the arrays are contiguous: each ends (with <=3 bytes of 4-byte padding)
    where the next present one starts.  Returns problems (empty = consistent)."""
    present = [a for a in info["arrays"] if a["offset"] and a["count"]]
    problems = []
    for a, b in zip(present, present[1:]):
        if a["elem_size"] is None:
            continue
        end = a["offset"] + a["count"] * a["elem_size"]
        gap = b["offset"] - end
        if not 0 <= gap <= 3:
            problems.append("%s ends at %#x but %s starts at %#x" % (a["name"], end, b["name"], b["offset"]))
    return problems


def positions(gcm: bytes, info: dict | None = None) -> list[tuple[int, int, int]]:
    """Raw s16 vertex positions (fixed point; the scale is a reader-stage item)."""
    info = info or gcm_info(gcm)
    a = info["arrays"][0]
    return [struct.unpack_from(">hhh", gcm, a["file_offset"] + 6 * i) for i in range(a["count"])]


# ---------------------------------------------------------------------------
# Reader: skeleton, matrix palette and skinned mesh (reader stage, #1362).
#
# Render path, pinned from Bond.elf:
#   R_InitEntVtxDesc 0x80179FB8 loads GXVtxDescList 0x80261630 (POS/NRM/TEX0 all
#   GX_INDEX16) and GXVtxAttrFmtList 0x80261650: POS xyz s16 frac 0, NRM s8,
#   TEX0 st s16 frac 11 (st / 2048).
#   R_DrawGeomSection 0x80179C44(section, object): section = {u32 model, u32
#   shader, u16 group_start, u16 group_count, u32}; each geom_group = {u16
#   mtx_map_start, u16 mtx_map_count, u16 strip_start, u16 strip_count}; each
#   mtx_map = {u8 palette index, u8 GX PNMTX slot} -> GXLoadPosMtxImm(palette
#   [i]+0x30, slot) (slots persist across groups, like the GX state); each
#   tri_strip = {u16 u16_list start, u16 vertex count, u16 u8_list start, u8,
#   u8 slot}: GXBegin(GX_TRIANGLESTRIP); slot 0xFF = per-vertex PNMTXIDX from
#   the u8 list, otherwise GXSetCurrentMtx(slot).  Each vertex is ent_vtx[u16]
#   = {u16 pos, u16 normal, u16 st}.
#   BuildMatrixList 0x8017A674: palette[i] = objToWorld * MtxFromQuat(pose[a].q
#   or slerp(pose[b].q, pose[a].q, w), pose[a].pos) for the header's +0x54 count
#   of {s16 a, s16 b (-2 = none), f32 w} records (header block +0x7C).
#   BuildViewMatrixList 0x8017A5A4: final = view * palette[i] * (model+0x80),
#   i.e. the 3x4 matrix at the start of the NGC geometry body dequantises the
#   s16 positions.
#   Skeleton: header +0x50 u16 bone count, block +0x74 = {s32 parent, u32 name
#   hash} per bone, block +0x78 = {f32 pos[3], pad, f32 quat xyzw} rest pose,
#   parent relative.  The chained pose reproduces the header bounding box
#   (+0x20 centre, +0x30 half extents) exactly, see ``bbox_error``.
# ---------------------------------------------------------------------------
UV_SCALE = 1.0 / 2048.0      # TEX0 frac 11
NRM_SCALE = 1.0 / 64.0       # GX s8 normals


def _hdr(gcm: bytes) -> int:
    return _body(gcm, 0)


def _block_body(gcm: bytes, field: int) -> int:
    b = struct.unpack_from(">I", gcm, _hdr(gcm) + field)[0]
    return _body(gcm, b) if b else 0


def _qmat(q):
    x, y, z, w = q
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def _mm(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _mv(a, v):
    return [a[i][0] * v[0] + a[i][1] * v[1] + a[i][2] * v[2] for i in range(3)]


def _slerp(q1, q2, t):
    """veQuatSLERP after veQuatGetSmallestArc (q2 sign-flipped to q1's hemisphere)."""
    d = sum(a * b for a, b in zip(q1, q2))
    if d < 0:
        q2, d = [-c for c in q2], -d
    if d > 0.9995:
        r = [a + (b - a) * t for a, b in zip(q1, q2)]
    else:
        import math
        th = math.acos(min(1.0, d))
        s = math.sin(th)
        k1, k2 = math.sin((1 - t) * th) / s, math.sin(t * th) / s
        r = [k1 * a + k2 * b for a, b in zip(q1, q2)]
    n = sum(c * c for c in r) ** 0.5 or 1.0
    return [c / n for c in r]


def skeleton(gcm: bytes) -> list[dict]:
    """Bones with parent, name hash, local rest pose and chained model-space transform."""
    h = _hdr(gcm)
    n = struct.unpack_from(">H", gcm, h + 0x50)[0]
    bt, bp = _block_body(gcm, 0x74), _block_body(gcm, 0x78)
    if not n or not bt or not bp:
        return []
    out = []
    for i in range(n):
        parent, hv = struct.unpack_from(">iI", gcm, bt + 8 * i)
        v = struct.unpack_from(">8f", gcm, bp + 32 * i)
        pos, quat = list(v[:3]), list(v[4:8])
        r = _qmat(quat)
        if 0 <= parent < i:
            pr, pt = out[parent]["rot"], out[parent]["world_pos"]
            rot, wpos = _mm(pr, r), [a + b for a, b in zip(_mv(pr, pos), pt)]
        elif parent < 0 or parent == i or i == 0:
            rot, wpos = r, pos
        else:
            raise ValueError("bone %d parent %d is not earlier in the table" % (i, parent))
        out.append({"index": i, "parent": parent if parent != i else -1, "hash": hv,
                    "pos": pos, "quat": quat, "rot": rot, "world_pos": wpos})
    for b in out:     # model-space quaternion (for the palette slerp)
        b["world_quat"] = _mat_quat(b["rot"])
    return out


def _mat_quat(m):
    t = m[0][0] + m[1][1] + m[2][2]
    if t > 0:
        s = (t + 1.0) ** 0.5 * 2
        return [(m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s, 0.25 * s]
    i = max(range(3), key=lambda k: m[k][k])
    j, k = (i + 1) % 3, (i + 2) % 3
    s = (1.0 + m[i][i] - m[j][j] - m[k][k]) ** 0.5 * 2
    q = [0.0] * 4
    q[i] = 0.25 * s
    q[j] = (m[j][i] + m[i][j]) / s
    q[k] = (m[k][i] + m[i][k]) / s
    q[3] = (m[k][j] - m[j][k]) / s
    return q


def matrix_records(gcm: bytes) -> list[tuple[int, int, float]]:
    h = _hdr(gcm)
    n = struct.unpack_from(">H", gcm, h + 0x54)[0]
    mr = _block_body(gcm, 0x7C)
    return [struct.unpack_from(">hhf", gcm, mr + 8 * i) for i in range(n)] if mr else []


def matrix_palette(gcm: bytes, bones: list[dict] | None = None) -> list[tuple[list, list]]:
    """BuildMatrixList in the rest pose: (rotation 3x3, translation) per palette entry."""
    bones = skeleton(gcm) if bones is None else bones
    out = []
    for a, b, w in matrix_records(gcm):
        if b == -2:
            q = bones[a]["world_quat"]
        else:
            q = _slerp(bones[b]["world_quat"], bones[a]["world_quat"], w)
        out.append((_qmat(q), bones[a]["world_pos"]))
    return out


def dequant(gcm: bytes, info: dict | None = None) -> tuple[float, ...]:
    info = info or gcm_info(gcm)
    return struct.unpack_from(">12f", gcm, info["ngc_body"])


def _array(gcm, info, idx, fmt):
    a = info["arrays"][idx]
    size = struct.calcsize(fmt)
    return [struct.unpack_from(fmt, gcm, a["file_offset"] + size * i) for i in range(a["count"])]


def mesh(gcm: bytes) -> dict:
    """Decode a .gcm into a rest-pose skinned triangle mesh (model space, Z up).

    Vertices are unique (ent_vtx, palette entry) pairs; ``joints``/``weights`` give
    the bone blend of each vertex's palette record (a: w, b: 1 - w)."""
    info = gcm_info(gcm)
    bones = skeleton(gcm)
    recs = matrix_records(gcm)
    pal = matrix_palette(gcm, bones) if recs else [([[1, 0, 0], [0, 1, 0], [0, 0, 1]], [0, 0, 0])]
    D = dequant(gcm, info)
    pos = _array(gcm, info, 0, ">hhh")
    nrm = _array(gcm, info, 1, ">bbb")
    st = _array(gcm, info, 2, ">hh")
    ev = _array(gcm, info, 3, ">HHH")
    u16 = [x[0] for x in _array(gcm, info, 4, ">H")]
    a8 = info["arrays"][5]
    u8 = gcm[a8["file_offset"]:a8["file_offset"] + a8["count"]] if a8["count"] else b""
    strips = _array(gcm, info, 6, ">HHHBB")
    mmap = _array(gcm, info, 7, ">BB")
    groups = _array(gcm, info, 8, ">HHHH")
    sections = _array(gcm, info, 9, ">IIHHI")
    rot_d = [[D[4 * r + c] for c in range(3)] for r in range(3)]
    out_p, out_n, out_uv, out_j, out_w, faces = [], [], [], [], [], []
    vmap = {}
    slot = {0: 0} if not recs else {}

    def vertex(e, m):
        key = (e, m)
        if key in vmap:
            return vmap[key]
        pi, ni, ti = ev[e]
        p = pos[pi]
        local = [D[4 * r] * p[0] + D[4 * r + 1] * p[1] + D[4 * r + 2] * p[2] + D[4 * r + 3] for r in range(3)]
        R, T = pal[m]
        out_p.append([a + b for a, b in zip(_mv(R, local), T)])
        nv = _mv(R, _mv(rot_d, [c * NRM_SCALE for c in nrm[ni]])) if ni < len(nrm) else [0, 0, 1]
        ln = sum(c * c for c in nv) ** 0.5 or 1.0
        out_n.append([c / ln for c in nv])
        s, t = st[ti] if ti < len(st) else (0, 0)
        out_uv.append([s * UV_SCALE, t * UV_SCALE])
        if recs:
            a, b, w = recs[m]
            out_j.append([a, b if b >= 0 else a])
            out_w.append([w, 1.0 - w] if b >= 0 else [1.0, 0.0])
        else:
            out_j.append([0, 0])
            out_w.append([1.0, 0.0])
        vmap[key] = len(out_p) - 1
        return vmap[key]

    for si, (_model, shader, gs, gc, _x) in enumerate(sections):
        for ms, mc, ss, sc in groups[gs:gs + gc]:
            for k in range(mc):
                pi, sid = mmap[ms + k]
                if pi >= len(pal):
                    raise ValueError("mtx_map palette index %d >= %d" % (pi, len(pal)))
                slot[sid] = pi
            for li, cnt, u8o, _f, cur in strips[ss:ss + sc]:
                vs = []
                for k in range(cnt):
                    sid = u8[u8o + k] if cur == 0xFF else cur
                    if sid not in slot:
                        raise ValueError("strip uses unloaded matrix slot %d" % sid)
                    vs.append(vertex(u16[li + k], slot[sid]))
                for k in range(cnt - 2):
                    a, b, c = vs[k], vs[k + 1], vs[k + 2]
                    if not k & 1:     # GX front faces are clockwise: emit CCW
                        a, b = b, a
                    if a != b and b != c and a != c:
                        faces.append((a, b, c, si))
    return {"positions": out_p, "normals": out_n, "uvs": out_uv, "joints": out_j, "weights": out_w,
            "faces": faces, "shaders": [s[1] for s in sections], "bones": bones}


def bbox_error(gcm: bytes, m: dict | None = None) -> tuple[float, str]:
    """Compare the decoded rest-pose bounds with the header bounding box (+0x20
    centre, +0x30 half extents).  The exporter wrote that box in one of three
    frames, all of which pin the decoded x/y exactly: ``exact`` (the decoded pose),
    ``origin`` (per axis unioned with the model origin, used by heads) or
    ``root`` (z measured with the root bone at 0) or both (``root+origin``).  Returns (max error, frame)."""
    m = m or mesh(gcm)
    h = _hdr(gcm)
    c = struct.unpack_from(">3f", gcm, h + 0x20)
    e = struct.unpack_from(">3f", gcm, h + 0x30)
    used = sorted({i for f in m["faces"] for i in f[:3]})
    if not used:
        return float("inf"), "empty"
    lo = [min(m["positions"][i][ax] for i in used) for ax in range(3)]
    hi = [max(m["positions"][i][ax] for i in used) for ax in range(3)]
    hlo = [c[ax] - e[ax] for ax in range(3)]
    hhi = [c[ax] + e[ax] for ax in range(3)]
    rz = m["bones"][0]["world_pos"][2] if m["bones"] else 0.0
    frames = {
        "exact": (lo, hi),
        "origin": ([min(v, 0.0) for v in lo], [max(v, 0.0) for v in hi]),
        "root": (lo[:2] + [lo[2] - rz], hi[:2] + [hi[2] - rz]),
    }
    rlo, rhi = frames["root"]
    frames["root+origin"] = ([min(v, 0.0) for v in rlo], [max(v, 0.0) for v in rhi])
    best = (float("inf"), "none")
    for name, (a, b) in frames.items():
        err = max(max(abs(a[i] - hlo[i]), abs(b[i] - hhi[i])) for i in range(3))
        best = min(best, (err, name))
    return best


def winding_agreement(m: dict) -> float:
    """Fraction of faces whose geometric normal agrees with the decoded vertex normals."""
    ok = tot = 0
    P, N = m["positions"], m["normals"]
    for a, b, c, _s in m["faces"]:
        u = [P[b][i] - P[a][i] for i in range(3)]
        v = [P[c][i] - P[a][i] for i in range(3)]
        g = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
        n = [N[a][i] + N[b][i] + N[c][i] for i in range(3)]
        tot += 1
        ok += sum(x * y for x, y in zip(g, n)) > 0
    return ok / tot if tot else 0.0


def to_obj(m: dict, path, name: str = "model") -> str:
    """Write an editable Wavefront OBJ (Z-up model space, one group per geom section)."""
    lines = ["# 007 Agent Under Fire GC .gcm via gbox.auf_ngc", "o %s" % name]
    lines += ["v %.5f %.5f %.5f" % tuple(p) for p in m["positions"]]
    lines += ["vt %.5f %.5f" % (u, 1.0 - v) for u, v in m["uvs"]]
    lines += ["vn %.4f %.4f %.4f" % tuple(n) for n in m["normals"]]
    cur = None
    for a, b, c, s in sorted(m["faces"], key=lambda f: f[3]):
        if s != cur:
            cur = s
            lines += ["g section%d" % s, "usemtl shader_%08x" % m["shaders"][s]]
        lines.append("f %d/%d/%d %d/%d/%d %d/%d/%d" % ((a + 1,) * 3 + (b + 1,) * 3 + (c + 1,) * 3))
    text = "\n".join(lines) + "\n"
    with open(path, "w") as fh:
        fh.write(text)
    return hashlib.sha256(text.encode()).hexdigest()


def to_glb(m: dict, path, name: str = "model"):
    """Rigged GLB (glTF Y-up: x, z, -y) with the rest-pose skeleton as joints."""
    import numpy as np
    from pathlib import Path
    from .gta_rw import write_skinned_glb
    C = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], float)
    P = np.asarray(m["positions"], float) @ C.T
    N = np.asarray(m["normals"], float) @ C.T
    UV = np.asarray(m["uvs"], float)
    J = np.zeros((len(P), 4))
    W = np.zeros((len(P), 4))
    J[:, :2] = m["joints"]
    W[:, :2] = m["weights"]
    tris = np.asarray([f[:3] for f in m["faces"]], np.uint32)
    bones = m["bones"] or [{"hash": 0, "parent": -1, "rot": np.eye(3).tolist(), "world_pos": [0, 0, 0]}]
    world = []
    for b in bones:
        M = np.eye(4)
        M[:3, :3] = C @ np.asarray(b["rot"]) @ C.T
        M[:3, 3] = C @ np.asarray(b["world_pos"])
        world.append(M)
    names = ["bone%02d_%08x" % (i, b["hash"]) for i, b in enumerate(bones)]
    parents = [b["parent"] if b["parent"] >= 0 else -1 for b in bones]
    return write_skinned_glb(Path(path), P, N, UV, J, tris, names, parents, world, name=name, weights=W)


def characters(pkg: NgcPackage) -> list[dict]:
    out = []
    for r in pkg.resources():
        if not (r.name.startswith("models/actors/") and r.name.endswith(".gcm")):
            continue
        g = pkg.table[r.offset:r.offset + r.size]
        row = {"name": r.name, "size": r.size, "sha256": hashlib.sha256(g).hexdigest()}
        try:
            info = gcm_info(g)
            row.update(vtx_pos=info["arrays"][0]["count"], ent_vtx=info["arrays"][3]["count"],
                       tri_strips=info["arrays"][6]["count"], sections=info["arrays"][9]["count"],
                       mtx_map=info["arrays"][7]["count"], tile_problems=tile_check(info))
        except (ValueError, struct.error) as e:
            row["error"] = str(e)
        out.append(row)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="AUF GC .ngc level package / .gcm model probe")
    ap.add_argument("ngc")
    ap.add_argument("--gcm", help="dump one model's header/array table")
    ap.add_argument("--extract", help="write the named resource to this path", nargs=2,
                    metavar=("NAME", "OUT"))
    ap.add_argument("--export", nargs=2, metavar=("GCM", "OUT_DIR"),
                    help="decode one .gcm to OBJ + rigged GLB + skeleton JSON")
    a = ap.parse_args(argv)
    pkg = NgcPackage(open(a.ngc, "rb").read())
    if a.extract:
        open(a.extract[1], "wb").write(pkg.read(a.extract[0]))
        return 0
    if a.export:
        import os
        g = pkg.read(a.export[0])
        stem = os.path.splitext(os.path.basename(a.export[0]))[0]
        os.makedirs(a.export[1], exist_ok=True)
        m = mesh(g)
        base = os.path.join(a.export[1], stem)
        obj = to_obj(m, base + ".obj", stem)
        glb = str(to_glb(m, base + ".glb", stem))
        err, frame = bbox_error(g, m)
        meta = {"source": a.export[0], "gcm_sha256": hashlib.sha256(g).hexdigest(), "obj_sha256": obj,
                "glb_sha256": hashlib.sha256(open(glb, "rb").read()).hexdigest(),
                "vertices": len(m["positions"]), "triangles": len(m["faces"]),
                "bbox_error": err, "bbox_frame": frame, "winding": winding_agreement(m),
                "shaders": ["%08x" % x for x in m["shaders"]],
                "bones": [{"parent": b["parent"], "hash": "%08x" % b["hash"], "pos": b["pos"],
                           "quat": b["quat"]} for b in m["bones"]]}
        with open(base + ".json", "w") as fh:
            json.dump(meta, fh, indent=1)
        print(json.dumps({k: v for k, v in meta.items() if k != "bones"}, indent=1))
        return 0
    if a.gcm:
        info = gcm_info(pkg.read(a.gcm))
        info["tile_problems"] = tile_check(info)
        print(json.dumps(info, indent=1))
        return 0
    res = pkg.resources()
    print(json.dumps({"chunks": [asdict(c) for c in pkg.chunks], "resources": len(res),
                      "characters": characters(pkg)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
