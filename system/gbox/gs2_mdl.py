"""Resident Evil Survivor 2 - Code: Veronica (PS2 Europe) MDL model format probe (analysis stage).

Verified against all 94 MDL entries on the owned build (87 SYSTEM.AFS + 7 TSUIKA.AFS,
SLES_506.50 v1.02 PAL, disc.iso sha256 a810796c...). This is a format probe, not a full
reader: it pins the Capcom wrapper header and proves the model body is a Sega Ninja (NJ)
chunk stream — the same stream ``gbox.ninja`` decodes for the Dreamcast titles — so the
reader stage can reuse that code instead of writing a new decoder.

Findings (each reproducible via ``probe`` / the walkers):

* Magic is ``b"MDL"`` at offset 4 + a 1-byte marker at offset 7:
    0xbc  SYSTEM.AFS main models (all 87)
    0xac  TSUIKA.AFS models (6 of 7; entry 1 uses 0xbc)
    0xad  nested sub-model sections inside a multi-part model
  offset 8: ``u16`` == 0x0010 (constant), offset 10: ``u16`` type in 1..7.
  offset 0: ``u32`` section offset whose meaning depends on ``type``:
    type 1 / 3 -> offset of the embedded TIM2 texture ("TIM2" magic found there);
    type 2     -> boundary just past the first sub-model's chunk stream.
* Every MDL embeds a TIM2 texture; multi-part (type 2/5) models nest further MDL sections.
* The geometry body is Ninja chunk data: material (0x10-0x1f), tiny/texture-id (0x08-0x09),
  vertex (0x20-0x32), strip (0x40-0x4b) and 0xff end markers, little-endian. Verified by
  walking the type-2 "Shell_1" polygon list (0x44 -> 3 strips, 20 tris, 0xff at 0xfc) and
  its vertex lists (10 chunks, 402 vertices; VN 0x29 = position 3f + normal 3f, 24 bytes).

Roster (from ``mdl_name``): the four 21-MDL groups repeat the same cast + weapon set, so the
MDL slots map to characters/items, not to a flat index: Shell_1 (enemy), cl02 (Claire),
ch03 (Chris), STU_05 (Steve), plus weapons/items BR_93R, ZIPPO, PYTHON, Ingram, bowgun,
SPAS12, AK47S, M79, knife, MR7, PF3.

Loader-location data (owned SLES_506.50 ELF, reproducible string offsets): the archive name
table hardcodes SYSTEM.AFS@0x2ef718, MRY.AFS@0x2ef728, TSUIKA.AFS@0x2ef7a0, TIM2@0x2ef7c8,
and a second "MDL"@0x30e2d2 cluster. Resolving which functions xref these is the Ghidra
MIPS R5900LE project step (next).
"""
from __future__ import annotations

import math
import struct

MDL_PREFIX = b"MDL"
MARKER_SYSTEM = 0xBC
MARKER_TSUIKA = 0xAC
MARKER_NESTED = 0xAD
END = 0xFF

# Ninja SDK chunk families (see gbox.formats.ninja_chunk): material 16-31, vertex 32-50,
# tiny 8-9, strip 64-75, end 255.
_VERTEX_STRIDES = {12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 64}


def mdl_header(data: bytes) -> dict | None:
    """Capcom MDL wrapper header. Returns None when offset 4 is not the ``MDL`` magic."""
    if len(data) < 12 or data[4:7] != MDL_PREFIX:
        return None
    u32v = struct.unpack_from("<I", data, 0)[0]
    marker = data[7]
    const, typ = struct.unpack_from("<HH", data, 8)
    return {"u32": u32v, "marker": marker, "const": const, "type": typ}


def mdl_name(data: bytes) -> str | None:
    """Best-effort null-terminated ASCII name from the header's 8-byte name slots."""
    if mdl_header(data) is None:
        return None
    for off in (0x28, 0x2C, 0x34, 0x3B):
        if off + 8 > len(data):
            continue
        chunk = data[off:off + 8]
        if not chunk or chunk[0] not in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_":
            continue
        name = chunk.split(b"\x00", 1)[0]
        if name and all(32 <= c < 127 for c in name):
            return name.decode("ascii", "replace")
    return None


def embedded_tim2(data: bytes) -> int | None:
    """Offset of the embedded TIM2 texture, if any."""
    o = data.find(b"TIM2")
    return o if o >= 0 else None


def nested_mdl(data: bytes) -> list[int]:
    """Offsets of nested ``MDL`` sub-model sections beyond the outer header."""
    out, s = [], 8
    while True:
        j = data.find(b"MDL", s)
        if j < 0:
            break
        out.append(j)
        s = j + 3
    return out


def walk_ninja_polys(data: bytes, start: int) -> dict:
    """Walk a Ninja polygon-list chunk stream (mirrors gbox.ninja.NJ._polys).

    Returns {end, texture_id, strips, triangles}. Stops at a 0xff end marker or the first
    unknown chunk, and raises on data overrun, so a bogus start offset fails loudly.
    """
    o, tex, nstrip, ntris = start, 0, 0, 0
    n = len(data)
    while o < n:
        typ, flg = struct.unpack_from("<BB", data, o)
        if typ == END:
            return {"end": o + 4 if flg == 0 else o + 2, "texture_id": tex,
                    "strips": nstrip, "triangles": ntris}
        if typ in (0, 4, 5) or 1 <= typ <= 7:
            o += 2
        elif typ in (8, 9):                                  # tiny: texture id
            tex = struct.unpack_from("<H", data, o + 2)[0] & 0x1FFF
            o += 4
        elif 0x10 <= typ <= 0x3A:                            # material / volume
            o += 4 + struct.unpack_from("<H", data, o + 2)[0] * 2
        elif 0x40 <= typ <= 0x4B:                            # strip
            size, hdr = struct.unpack_from("<HH", data, o + 2)
            nstrips, user = hdr & 0x3FFF, hdr >> 14
            uvs = typ in (0x41, 0x42, 0x44, 0x45, 0x47, 0x48, 0x4A, 0x4B)
            extra = 3 if typ in (0x43, 0x44, 0x45) else (2 if typ in (0x46, 0x47, 0x48) else 0)
            p = o + 6
            for _ in range(nstrips):
                cnt = struct.unpack_from("<h", data, p)[0]
                p += 2
                flip, cnt = cnt < 0, abs(cnt)
                for k in range(cnt):
                    p += 2
                    if uvs:
                        p += 4
                    p += extra * 2 + (user * 2 if k >= 2 else 0)
                ntris += max(0, cnt - 2)
            nstrip += nstrips
            o += 4 + size * 2
        else:
            return {"end": o, "texture_id": tex, "strips": nstrip, "triangles": ntris}
        if o > n:
            raise ValueError(f"polygon list overran data at {o:#x}")
    raise ValueError("polygon list never terminated")


def walk_ninja_verts(data: bytes, start: int) -> dict:
    """Walk a Ninja vertex-list chunk stream (mirrors gbox.ninja.NJ._vertices).

    Returns {end, vertices, types}. Vertex chunk: u32 head = typ | flg<<8 | size<<16
    (size in u32 words), u32 count<<16 | base, then ``count`` vertices of ``stride`` floats.
    """
    o, total = start, 0
    types: set[int] = set()
    n = len(data)
    while o + 4 <= n:
        head = struct.unpack_from("<I", data, o)[0]
        typ, size = head & 0xFF, head >> 16
        if typ == END:
            return {"end": o + 4, "vertices": total, "types": sorted(types)}
        if not (0x20 <= typ <= 0x32) or size == 0 or o + 4 + size * 4 > n:
            raise ValueError(f"not a vertex chunk at {o:#x} (typ {typ:#x})")
        bc = struct.unpack_from("<I", data, o + 4)[0]
        base, count = bc & 0xFFFF, bc >> 16
        if count == 0 or (size * 4 - 4) % count:
            raise ValueError(f"bad vertex chunk at {o:#x} (size {size} count {count})")
        stride = (size * 4 - 4) // count
        if stride not in _VERTEX_STRIDES:
            raise ValueError(f"unexpected vertex stride {stride} at {o:#x}")
        total += count
        types.add(typ)
        o += 4 + size * 4
    raise ValueError("vertex list never terminated")


def ninja_vertex_census(data: bytes) -> list[dict]:
    """Heuristic census: scan the whole entry for validated vertex chunks.

    A candidate is accepted only when size/count are consistent, the derived stride is a
    known Ninja vertex size, and every position/normal float is finite — so texture bytes
    and names don't yield false positives. Reliable on the large character models; small
    weapon/item models legitimately report few or no chunks when their layout differs.
    """
    chunks, n = [], len(data)
    o = 0
    while o + 8 <= n:
        head = struct.unpack_from("<I", data, o)[0]
        typ, size = head & 0xFF, head >> 16
        if 0x20 <= typ <= 0x32 and size > 0 and o + 4 + size * 4 <= n:
            bc = struct.unpack_from("<I", data, o + 4)[0]
            base, count = bc & 0xFFFF, bc >> 16
            if 0 < count <= 0xFFFF and (size * 4 - 4) % count == 0:
                stride = (size * 4 - 4) // count
                if stride in _VERTEX_STRIDES and _finite_floats(data, o + 8, count, stride):
                    chunks.append({"off": o, "type": typ, "words": size, "base": base,
                                   "count": count, "stride": stride})
                    o += 4 + size * 4
                    continue
        o += 4
    return chunks


def _finite_floats(data: bytes, p: int, count: int, stride: int) -> bool:
    nf = min(stride // 4, 8)
    for _ in range(count):
        for k in range(nf):
            if not math.isfinite(struct.unpack_from("<f", data, p + k * 4)[0]):
                return False
        p += stride
    return True


def probe(data: bytes) -> dict | None:
    """Combined probe: wrapper header + embedded TIM2 + nested MDL + vertex census."""
    h = mdl_header(data)
    if h is None:
        return None
    vcs = ninja_vertex_census(data)
    h["name"] = mdl_name(data)
    h["embedded_tim2"] = embedded_tim2(data)
    h["nested_mdl"] = nested_mdl(data)
    h["vertex_chunks"] = len(vcs)
    h["vertices"] = sum(c["count"] for c in vcs)
    h["vertex_types"] = sorted({c["type"] for c in vcs})
    return h
