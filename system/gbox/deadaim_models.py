"""Resident Evil - Dead Aim (PS2) character texture ('miz') and shape ('fsc') headers.

Evidence (owned USA CHD, SLUS_206.69, request #1904).  Little-endian.

miz ('wZIM', 0xC0-byte header + GS upload packets, pixels at 0x240):
  0x00 'wZIM', 0x2c u16 width, u16 height, 0x4c u32 palette bytes (0x400 -> 8bpp,
  0x40 -> 4bpp).  Pixels (w*h*bpp/8 bytes) start at 0x240 and are followed
  directly by the palette (RGBA8888 entries, alpha 0..0x80); file size equals
  0x240 + pixel bytes + palette bytes (+ optional pad).  8bpp pixels are
  row-linear (smoothness metric 55.6 raw vs 101 after PSMT8 unswizzle).
  Palette index order is not yet confirmed (CSM1 swap gives 61.4 vs 55.6 raw).

fsc ('CSFg', one per mesh part in allshp.bin): 0x0f ASCII kind tag (e.g. 'CARM',
  'CBRU'), name string after it; five u32 at 0x38 section table:
  [data_start(0x4c), s1, s2, s3, end] with end == file size.  Vertex/strip
  encoding of the sections is NOT decoded yet.
"""
from __future__ import annotations

import struct
from typing import Dict, Tuple

MIZ_MAGIC = b"wZIM"
FSC_MAGIC = b"CSFg"
MIZ_PIXELS = 0x240


def parse_miz(data: bytes) -> Dict:
    if data[:4] != MIZ_MAGIC:
        raise ValueError("not a miz texture")
    w, h = struct.unpack_from("<HH", data, 0x2C)
    pal_bytes = struct.unpack_from("<I", data, 0x4C)[0]
    bpp = {0x400: 8, 0x40: 4}.get(pal_bytes)
    if bpp is None:
        raise ValueError("unsupported palette size 0x%x" % pal_bytes)
    npix = w * h * bpp // 8
    need = MIZ_PIXELS + npix + pal_bytes
    if len(data) < need:
        raise ValueError("truncated miz: %d < %d" % (len(data), need))
    return {"width": w, "height": h, "bpp": bpp, "pixels": data[MIZ_PIXELS:MIZ_PIXELS + npix],
            "palette": data[MIZ_PIXELS + npix:need], "pad": len(data) - need}


def miz_to_rgba(tex: Dict) -> bytes:
    pal = tex["palette"]
    cols = [bytes((pal[i * 4], pal[i * 4 + 1], pal[i * 4 + 2], min(255, pal[i * 4 + 3] * 2)))
            for i in range(len(pal) // 4)]
    out = bytearray()
    px = tex["pixels"]
    for i in range(tex["width"] * tex["height"]):
        idx = px[i] if tex["bpp"] == 8 else (px[i >> 1] >> (4 * (i & 1))) & 15
        out += cols[idx]
    return bytes(out)


def parse_fsc_header(data: bytes) -> Dict:
    if data[:4] != FSC_MAGIC:
        raise ValueError("not an fsc shape")
    tag = data[0x0F:0x13].split(b"\0")[0].decode("latin1")
    name = data[0x14:0x34].split(b"\0")[0].decode("latin1")
    sec = struct.unpack_from("<5I", data, 0x38)
    return {"kind": tag, "name": name, "sections": sec, "size_matches": sec[4] == len(data)}


def _fsc_group_ok(data: bytes, p: int, end: int) -> bool:
    while p + 16 < end and data[p:p + 4] == b"\0\0\0\0":
        p += 4
    n = struct.unpack_from("<I", data, p)[0]
    return 0 < n <= 0x4000 and p + 16 + 16 * n <= end and data[p + 8:p + 16] == b"\0" * 8


def _fsc_vertex_groups(data: bytes, start: int, end: int):
    """Walk the vertex section: u32 ngroups, then groups of
    [u32 n][4 bone-id bytes][8 zero bytes][n*int16[3] positions][...planar
    normals/colours, 16*n bytes total incl. positions]. Zero u32 padding
    words may precede any group header.
    """
    ngroups = struct.unpack_from("<I", data, start)[0]
    p = start + 4
    verts, groups = [], []
    for _ in range(ngroups):
        n = struct.unpack_from("<I", data, p)[0]
        while n == 0 and p + 4 < end:  # zero padding words precede a group
            p += 4
            n = struct.unpack_from("<I", data, p)[0]
        if n > 0x4000 or p + 16 + 16 * n > end:
            raise ValueError("bad vertex group @%#x" % p)
        ids = data[p + 4:p + 8]
        d0 = p + 16
        verts.extend(struct.unpack_from("<3h", data, d0 + 6 * i) for i in range(n))
        groups.append({"offset": p, "count": n, "bones": list(ids)})
        p = d0 + 16 * n
        if len(groups) < ngroups:
            # next header: first 16-aligned address after the arrays whose
            # n/ids/zero layout is plausible (arrays carry odd tail padding)
            q = (p + 15) & ~15
            while q + 16 < end and not (data[q:q + 4] != b"\0\0\0\0" and _fsc_group_ok(data, q, end)):
                q += 16
            p = q
    return verts, groups


def parse_fsc_mesh(data: bytes) -> Dict:
    """Decode an fsc (CSFg) shape into strips, int16 positions and int16 UVs.

    Evidence (owned USA build, pc01a/pc02a zones): section table @0x38 =
    [index, vertex, vertex(dup), uv, end].
      index sec: u32 a, u32 0x200, u32 total_refs, u16 n_strips, u16 1, u16 x,
        u16 x, 12*0xFF, then n_strips x [u16 count, count x (u16 vertex,
        u16 uv_byte_offset)]  (triangle strips).
      vertex sec @sec[1]: 24-byte header (u32 1, u32 count@4, ...), then
        count x int16[3] positions, followed by further planar arrays
        (normals/colour; not decoded here).
      uv sec @sec[3]: u32 count, then count x int16[2]; uv = value/1024
        (scale unconfirmed, values observed < 1024).
    """
    h = parse_fsc_header(data)
    s = h["sections"]
    ioff = s[0]
    total, nstrips = struct.unpack_from("<IH", data, ioff + 8)
    pos = ioff + 32
    strips = []
    for _ in range(nstrips):
        (n,) = struct.unpack_from("<H", data, pos)
        pos += 2
        strips.append(list(struct.unpack_from("<%dH" % (2 * n), data, pos)))
        pos += 4 * n
    strips = [[(r[i], r[i + 1] // 4) for i in range(0, len(r), 2)] for r in strips]
    verts, groups = _fsc_vertex_groups(data, s[1], s[3])
    ucount = struct.unpack_from("<I", data, s[3])[0]
    uvs = [struct.unpack_from("<2h", data, s[3] + 4 + 4 * i) for i in range(ucount)]
    return {"header": h, "strips": strips, "verts": verts, "groups": groups, "uvs": uvs,
            "index_end": pos, "index_total": total}


def fsc_to_obj(mesh: Dict, scale: float = 1.0 / 256.0) -> str:
    out = []
    for x, y, z in mesh["verts"]:
        out.append("v %f %f %f" % (x * scale, y * scale, z * scale))
    for u, v in mesh["uvs"]:
        out.append("vt %f %f" % (u / 1024.0, 1.0 - v / 1024.0))
    for st in mesh["strips"]:
        for i in range(len(st) - 2):
            tri = (st[i], st[i + 1], st[i + 2]) if i % 2 == 0 else (st[i + 1], st[i], st[i + 2])
            if len({t[0] for t in tri}) < 3:
                continue
            out.append("f " + " ".join("%d/%d" % (a + 1, b + 1) for a, b in tri))
    return "\n".join(out) + "\n"
