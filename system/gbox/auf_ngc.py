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
                if i >= n_src:
                    raise ValueError("BOA literal past the end of the stream")
                out.append(src[i])
                i += 1
                continue
            if i + 1 >= n_src:
                raise ValueError("BOA back-reference past the end of the stream")
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
    if len(table) < 0x10:
        raise ValueError("restable shorter than its 0x10-byte header")
    count = struct.unpack_from(">I", table, 0)[0]
    if 0x10 + count * 16 > len(table):
        raise ValueError("restable: %d records overrun the table" % count)
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

    def payload(self, cid: str) -> bytes:
        """Decompressed payload of a chunk (cached)."""
        cache = self.__dict__.setdefault("_payloads", {})
        if cid not in cache:
            cache[cid] = read_chunk(self.data, self.chunk(cid))
        return cache[cid]

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


def to_glb(m: dict, path, name: str = "model", basis=None, names=None):
    """Rigged GLB (glTF Y-up: x, z, -y) with the rest-pose skeleton as joints. ``basis`` (a 3x3 rotation) replaces
    that frame change, e.g. auf_swap.A2R for the library frame (left +X, up +Y, facing +Z); ``names`` the joint names
    (default ``bone<i>_<hash>``)."""
    import numpy as np
    from pathlib import Path
    from .gta_rw import write_skinned_glb
    C = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], float) if basis is None else np.asarray(basis, float)
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
    names = list(names) if names else ["bone%02d_%08x" % (i, b["hash"]) for i, b in enumerate(bones)]
    parents = [b["parent"] if b["parent"] >= 0 else -1 for b in bones]
    return write_skinned_glb(Path(path), P, N, UV, J, tris, names, parents, world, name=name, weights=W)



# ---------------------------------------------------------------------------
# Textures and shaders (reader stage, textures).
#
# restxtrs chunk (RSRC_InitStaticTextures 0x80016A7C -> TexMgr_LoadStaticTextures
# 0x80185EA8): f32 version (must equal the build constant, 1.2), u32 count,
# u32 offset of a u32 texture-ID array, u32 offset of 0x44-byte records; all
# offsets are relative to the chunk payload (TexMgr_InitTexture 0x80185CFC
# relocates +0x10 and +0x1C).  TexMgr_InitGXTex 0x80186094 builds two GXTexObjs
# per record: GXInitTexObj(image, w=u16 +4, h=u16 +6, fmt, wrapS +8, wrapT +0xC,
# mipmap u8 +0x3A) for (fmt +0, data +0x10) and, when +0x1C != 0, (fmt +0x18,
# data +0x1C); GXInitTexObjLOD(min +0x28, mag +0x2C, maxLOD f32 +0x30, bias +0x34).
# +0x14 / +0x20 are the byte sizes of the two images (full mip chains).
#
# shaders chunk (SHDR_Init 0x80188AA8 / SHDR_FixupShaderTable 0x801886C4):
# +4 shader array offset, +8 count; shader = 16 bytes {u32 id, u8 group count,
# .., +0xC group array offset}; group = 0x14 bytes {u32 pass array offset,
# u16 pass count, ..}; pass = 0x14 bytes {u32 flags, u32 texture id, ..}.
# SHDR_FixupIndices 0x801885C0 turns pass +4 into a TexMgr index via
# TexMgr_GetIndexForTextureID (0xCCDDCCDD = no texture; flags & 0x4000 = an
# animated list at pass +0x10).  SHDR_GetTextureForPassNum 0x801870CC returns
# pass +4, so pass 0 of group 0 is a geom section's base texture.
# ---------------------------------------------------------------------------

GX_I4, GX_I8, GX_IA4, GX_IA8, GX_RGB565, GX_RGB5A3, GX_RGBA8 = 0, 1, 2, 3, 4, 5, 6
GX_CI4, GX_CI8, GX_CI14, GX_CMPR = 8, 9, 10, 14
GX_BLOCK = {GX_I4: (8, 8, 4), GX_I8: (8, 4, 8), GX_IA4: (8, 4, 8), GX_IA8: (4, 4, 16),
            GX_RGB565: (4, 4, 16), GX_RGB5A3: (4, 4, 16), GX_RGBA8: (4, 4, 32),
            GX_CI4: (8, 8, 4), GX_CI8: (8, 4, 8), GX_CI14: (4, 4, 16), GX_CMPR: (8, 8, 4)}
NO_TEXTURE = 0xCCDDCCDD


def gx_image_size(fmt: int, w: int, h: int) -> int:
    bw, bh, bpp = GX_BLOCK[fmt]
    return ((w + bw - 1) // bw) * ((h + bh - 1) // bh) * bw * bh * bpp // 8


def gx_chain_size(fmt: int, w: int, h: int, levels: int) -> int:
    return sum(gx_image_size(fmt, max(1, w >> i), max(1, h >> i)) for i in range(levels))


def _rgb565(c):
    return ((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31


def decode_gx(fmt: int, w: int, h: int, data: bytes) -> bytes:
    """Decode mip level 0 of a GX texture to RGBA8 rows (top row first).

    Implements the formats this disc uses (CMPR, RGBA8, I8 - every record on all
    38 maps) plus I4/IA8/RGB565/RGB5A3."""
    bw, bh, _bpp = GX_BLOCK[fmt]
    out = bytearray(w * h * 4)
    need = gx_image_size(fmt, w, h)
    if len(data) < need:
        raise ValueError("GX fmt %d %dx%d needs %d bytes, have %d" % (fmt, w, h, need, len(data)))

    def put(x, y, px):
        if x < w and y < h:
            o = (y * w + x) * 4
            out[o:o + 4] = bytes(px)

    pos = 0
    for by in range(0, h, bh):
        for bx in range(0, w, bw):
            if fmt == GX_CMPR:
                for sb in range(4):
                    c0, c1, bits = struct.unpack_from(">HHI", data, pos)
                    pos += 8
                    p0, p1 = _rgb565(c0), _rgb565(c1)
                    if c0 > c1:
                        pal = [p0 + (255,), p1 + (255,),
                               tuple((2 * a + b) // 3 for a, b in zip(p0, p1)) + (255,),
                               tuple((a + 2 * b) // 3 for a, b in zip(p0, p1)) + (255,)]
                    else:
                        pal = [p0 + (255,), p1 + (255,),
                               tuple((a + b) // 2 for a, b in zip(p0, p1)) + (255,), (0, 0, 0, 0)]
                    ox, oy = bx + (sb & 1) * 4, by + (sb >> 1) * 4
                    for i in range(16):
                        put(ox + (i & 3), oy + (i >> 2), pal[(bits >> (30 - 2 * i)) & 3])
            elif fmt == GX_RGBA8:
                for i in range(16):
                    a, r = data[pos + 2 * i], data[pos + 2 * i + 1]
                    g, b = data[pos + 32 + 2 * i], data[pos + 33 + 2 * i]
                    put(bx + (i & 3), by + (i >> 2), (r, g, b, a))
                pos += 64
            elif fmt == GX_I8:
                for i in range(32):
                    v = data[pos + i]
                    put(bx + (i & 7), by + (i >> 3), (v, v, v, 255))
                pos += 32
            elif fmt == GX_I4:
                for i in range(64):
                    v = (data[pos + i // 2] >> (4 if not i & 1 else 0)) & 15
                    put(bx + (i & 7), by + (i >> 3), (v * 17,) * 3 + (255,))
                pos += 32
            elif fmt == GX_IA8:
                for i in range(16):
                    a, v = data[pos + 2 * i], data[pos + 2 * i + 1]
                    put(bx + (i & 3), by + (i >> 2), (v, v, v, a))
                pos += 32
            elif fmt in (GX_RGB565, GX_RGB5A3):
                for i in range(16):
                    c = struct.unpack_from(">H", data, pos + 2 * i)[0]
                    if fmt == GX_RGB565:
                        px = _rgb565(c) + (255,)
                    elif c & 0x8000:
                        px = (((c >> 10) & 31) * 255 // 31, ((c >> 5) & 31) * 255 // 31, (c & 31) * 255 // 31, 255)
                    else:
                        px = (((c >> 8) & 15) * 17, ((c >> 4) & 15) * 17, (c & 15) * 17, ((c >> 12) & 7) * 255 // 7)
                    put(bx + (i & 3), by + (i >> 2), px)
                pos += 32
            else:
                raise ValueError("GX texture format %d not supported" % fmt)
    return bytes(out)


@dataclass
class Texture:
    id: int
    index: int
    fmt: int
    width: int
    height: int
    wrap_s: int
    wrap_t: int
    offset: int
    size: int
    fmt2: int
    offset2: int
    size2: int
    mipmap: int
    max_lod: float

    @property
    def levels(self) -> int:
        return int(self.max_lod) + 1 if self.mipmap else 1


def textures(pkg: "NgcPackage") -> dict:
    """{texture id: Texture} from the level's restxtrs chunk (payload kept on pkg)."""
    p = pkg.payload("restxtrs")
    _ver, n, ido, reco = struct.unpack_from(">fIII", p, 0)
    out = {}
    for i in range(n):
        r = reco + i * 0x44
        f, w, h, ws, wt, off, sz, f2, off2, sz2 = struct.unpack_from(">IHHIIIIIII", p, r)
        maxlod = struct.unpack_from(">f", p, r + 0x30)[0]
        tid = struct.unpack_from(">I", p, ido + 4 * i)[0]
        out[tid] = Texture(tid, i, f, w, h, ws, wt, off, sz, f2, off2, sz2, p[r + 0x3A], maxlod)
    return out


def texture_check(pkg: "NgcPackage") -> list[str]:
    """Every image must be exactly its GX mip chain and lie inside the chunk."""
    p = pkg.payload("restxtrs")
    bad = []
    for t in textures(pkg).values():
        planes = [(t.fmt, t.offset, t.size)]
        if t.offset2:
            planes.append((t.fmt2, t.offset2, t.size2))
        for f, o, s in planes:
            if f not in GX_BLOCK:
                bad.append("%08x: format %d" % (t.id, f))
            elif gx_chain_size(f, t.width, t.height, t.levels) != s:
                bad.append("%08x: size %d != chain %d" % (t.id, s, gx_chain_size(f, t.width, t.height, t.levels)))
            elif o + s > len(p):
                bad.append("%08x: overruns restxtrs" % t.id)
    return bad


def texture_rgba(pkg: "NgcPackage", t: Texture, plane: int = 0) -> bytes:
    p = pkg.payload("restxtrs")
    f, o = (t.fmt, t.offset) if plane == 0 else (t.fmt2, t.offset2)
    return decode_gx(f, t.width, t.height, p[o:o + gx_image_size(f, t.width, t.height)])


def shaders(pkg: "NgcPackage") -> dict:
    """{shader id: [[(flags, texture id), ...] per group]} from the shaders chunk."""
    s = pkg.payload("shaders")
    so, sc = struct.unpack_from(">II", s, 4)
    out = {}
    for i in range(sc):
        sid, ng = struct.unpack_from(">IB", s, so + 16 * i)
        gptr = struct.unpack_from(">I", s, so + 16 * i + 12)[0]
        groups = []
        for j in range(ng):
            pp, npass = struct.unpack_from(">IH", s, gptr + 0x14 * j)
            groups.append([struct.unpack_from(">II", s, pp + 0x14 * k) for k in range(npass)])
        out[sid] = groups
    return out


def section_textures(pkg: "NgcPackage", m: dict, shd: dict | None = None, tex: dict | None = None) -> list:
    """Base Texture (pass 0 of group 0) of each geom section, or None."""
    shd = shaders(pkg) if shd is None else shd
    tex = textures(pkg) if tex is None else tex
    out = []
    for h in m["shaders"]:
        groups = shd.get(h) or []
        tid = groups[0][0][1] if groups and groups[0] else NO_TEXTURE
        out.append(tex.get(tid))
    return out


def png_bytes(rgba: bytes, w: int, h: int) -> bytes:
    import zlib
    raw = b"".join(b"\0" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def glb_add_materials(path, m: dict, images: list) -> None:
    """Split a single-primitive GLB from ``to_glb`` into one primitive per geom
    section, each with its own material and embedded PNG (``images[s]`` is
    (png bytes, wrap_s, wrap_t) or None)."""
    import numpy as np
    from pathlib import Path
    data = Path(path).read_bytes()
    jl = struct.unpack_from("<I", data, 12)[0]
    gl = json.loads(data[20:20 + jl])
    blob = bytearray(data[20 + jl + 8:])
    wrap = {0: 33071, 1: 10497, 2: 33648}

    def view(b):
        while len(blob) % 4:
            blob.append(0)
        gl["bufferViews"].append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(b)})
        blob.extend(b)
        return len(gl["bufferViews"]) - 1

    prim0 = gl["meshes"][0]["primitives"][0]
    prims, mats = [], []
    gl.setdefault("images", []); gl.setdefault("textures", []); gl.setdefault("samplers", [])
    for s in range(len(m["shaders"])):
        tri = np.asarray([f[:3] for f in m["faces"] if f[3] == s], np.uint32).reshape(-1)
        if not len(tri):
            continue
        gl["accessors"].append({"bufferView": view(tri.tobytes()), "componentType": 5125,
                                "count": len(tri), "type": "SCALAR"})
        mat = {"name": "shader_%08x" % m["shaders"][s], "doubleSided": False,
               "pbrMetallicRoughness": {"metallicFactor": 0, "roughnessFactor": 1}}
        if images[s] is not None:
            png, ws, wt = images[s][:3]
            gl["images"].append({"bufferView": view(png), "mimeType": "image/png"})
            gl["samplers"].append({"magFilter": 9729, "minFilter": 9987,
                                   "wrapS": wrap.get(ws, 10497), "wrapT": wrap.get(wt, 10497)})
            gl["textures"].append({"source": len(gl["images"]) - 1, "sampler": len(gl["samplers"]) - 1})
            mat["pbrMetallicRoughness"]["baseColorTexture"] = {"index": len(gl["textures"]) - 1}
            if len(images[s]) > 3 and images[s][3]:
                mat["alphaMode"] = "MASK"
        mats.append(mat)
        prims.append({"attributes": prim0["attributes"], "indices": len(gl["accessors"]) - 1,
                      "material": len(mats) - 1})
    gl["meshes"][0]["primitives"] = prims
    gl["materials"] = mats
    for k in ("images", "textures", "samplers"):
        if not gl[k]:
            del gl[k]
    while len(blob) % 4:
        blob.append(0)
    gl["buffers"] = [{"byteLength": len(blob)}]
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    Path(path).write_bytes(struct.pack("<III", 0x46546C67, 2, 28 + len(js) + len(blob))
                           + struct.pack("<II", len(js), 0x4E4F534A) + js
                           + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob))


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
        tex_meta, images = [], []
        for s, t in enumerate(section_textures(pkg, m)):
            if t is None:
                images.append(None)
                tex_meta.append(None)
                continue
            rgba = texture_rgba(pkg, t)
            png = png_bytes(rgba, t.width, t.height)
            fn = "%s_tex%08x.png" % (stem, t.id)
            with open(os.path.join(a.export[1], fn), "wb") as fh:
                fh.write(png)
            cut = any(rgba[i] < 128 for i in range(3, len(rgba), 4))
            images.append((png, t.wrap_s, t.wrap_t, cut))
            row = {"section": s, "texture": "%08x" % t.id, "format": t.fmt, "size": [t.width, t.height],
                   "wrap": [t.wrap_s, t.wrap_t], "levels": t.levels, "png": fn,
                   "png_sha256": hashlib.sha256(png).hexdigest()}
            if t.offset2:
                # second GXTexObj of the record (TexMgr_InitGXTex); kept as-is
                png2 = png_bytes(texture_rgba(pkg, t, 1), t.width, t.height)
                fn2 = "%s_tex%08x_plane1.png" % (stem, t.id)
                with open(os.path.join(a.export[1], fn2), "wb") as fh:
                    fh.write(png2)
                row.update(plane1_format=t.fmt2, plane1_png=fn2)
            tex_meta.append(row)
        glb_add_materials(glb, m, images)
        err, frame = bbox_error(g, m)
        meta = {"source": a.export[0], "gcm_sha256": hashlib.sha256(g).hexdigest(), "obj_sha256": obj,
                "glb_sha256": hashlib.sha256(open(glb, "rb").read()).hexdigest(),
                "vertices": len(m["positions"]), "triangles": len(m["faces"]),
                "bbox_error": err, "bbox_frame": frame, "winding": winding_agreement(m),
                "shaders": ["%08x" % x for x in m["shaders"]], "textures": tex_meta,
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
