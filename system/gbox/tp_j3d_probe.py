"""Twilight Princess (GZ2E01) J3D BMD3 reader probe: skeleton (JNT1+INF1), VTX1 positions, chunk census.

Read-only and bounded by the model size. Layout per zeldaret/tww J3DModelLoader / JSystem docs:
  header 0x20 'J3D2'+'bmd3'|'bdl4' | size | nchunks; chunk = tag | size (BE).
  INF1: +0x08 u16 flags, +0x0C u32 packet count, +0x10 u32 vertex count, +0x14 u32 hierarchy offset
        hierarchy = (u16 type, u16 index): 0x10 joint, 0x11 material, 0x12 shape, 1 open, 2 close, 0 end.
  JNT1: +0x08 u16 count, +0x0C entries (0x40 B each), +0x10 remap, +0x14 name table (u16 n, pad, {hash,off}[n]).
  VTX1: +0x08 attr-format list offset, +0x0C..+0x3C 13 array offsets; format = (attr, cnt, type, frac)*16 B, attr 0xFF ends.
Verified-by-owned-build only for the sampled Link body (Kmdl.arc bmwr/al.bmd); unproved fields stay hypotheses.
"""
from __future__ import annotations

import struct

TAGS = (b"INF1", b"VTX1", b"EVP1", b"DRW1", b"JNT1", b"SHP1", b"MAT3", b"MDL3", b"TEX1")


class J3DProbeError(ValueError):
    pass


def chunk_table(raw: bytes) -> dict:
    if len(raw) < 0x20 or raw[:4] != b"J3D2" or raw[4:8] not in (b"bmd3", b"bdl4", b"bmd2"):
        raise J3DProbeError("not a J3D2 bmd/bdl model")
    size, n = struct.unpack_from(">II", raw, 8)
    if size != len(raw) or not 0 < n <= 32:
        raise J3DProbeError("J3D size/chunk count mismatch")
    out, off = {}, 0x20
    for _ in range(n):
        if off + 8 > size:
            raise J3DProbeError("truncated chunk header")
        tag, csz = raw[off:off + 4], struct.unpack_from(">I", raw, off + 4)[0]
        if csz < 8 or csz > size - off or tag not in TAGS or tag in out:
            raise J3DProbeError("bad chunk %r" % tag)
        out[tag] = (off, csz)
        off += csz
    return out


def _u16(b, o):
    if o < 0 or o + 2 > len(b):
        raise J3DProbeError("read out of range")
    return struct.unpack_from(">H", b, o)[0]


def hierarchy(raw: bytes, chunks: dict | None = None) -> list[tuple[int, int]]:
    """INF1 scene graph as flat [(type,index)] up to the terminating 0 node (bounded)."""
    off, sz = (chunks or chunk_table(raw))[b"INF1"]
    c = raw[off:off + sz]
    start = struct.unpack_from(">I", c, 0x14)[0]
    out = []
    for p in range(start, sz - 3, 4):
        t, i = struct.unpack_from(">HH", c, p)
        if t == 0:
            return out
        if t not in (1, 2, 0x10, 0x11, 0x12):
            raise J3DProbeError("unknown INF1 node type %#x" % t)
        out.append((t, i))
    raise J3DProbeError("INF1 hierarchy not terminated")


def joints(raw: bytes, chunks: dict | None = None) -> list[dict]:
    """JNT1 joints with names and the parent index derived from the INF1 scene graph."""
    chunks = chunks or chunk_table(raw)
    off, sz = chunks[b"JNT1"]
    c = raw[off:off + sz]
    n = _u16(c, 8)
    eo, ro, no = struct.unpack_from(">III", c, 0x0C)
    if eo + n * 0x40 > sz:
        raise J3DProbeError("JNT1 entries out of range")
    remap = [_u16(c, ro + 2 * i) for i in range(n)]
    cnt = _u16(c, no)
    names = []
    for i in range(cnt):
        so = _u16(c, no + 4 + i * 4 + 2) + no
        e = c.find(b"\0", so)
        if e < 0:
            raise J3DProbeError("unterminated joint name")
        names.append(c[so:e].decode("latin-1"))
    out = []
    for i in range(n):
        e = eo + i * 0x40
        mt, inh = struct.unpack_from(">HB", c, e)
        sc = struct.unpack_from(">3f", c, e + 4)
        rot = struct.unpack_from(">3h", c, e + 0x10)
        tr = struct.unpack_from(">3f", c, e + 0x18)
        radius = struct.unpack_from(">f", c, e + 0x24)[0]
        bb = struct.unpack_from(">6f", c, e + 0x28)
        out.append({"index": i, "name": names[remap[i]] if remap[i] < len(names) else "", "matrix_type": mt,
                    "scale": sc, "rot_s16": rot, "trans": tr, "radius": radius, "bbox": bb, "parent": -1})
    stack, last = [], None
    for t, i in hierarchy(raw, chunks):
        if t == 0x10:
            if i >= n:
                raise J3DProbeError("joint index out of range")
            out[i]["parent"] = stack[-1] if stack else -1
            last = i
        elif t == 1:
            stack.append(last if last is not None else -1)
        elif t == 2:
            if not stack:
                raise J3DProbeError("unbalanced INF1 close")
            stack.pop()
    return out


def vtx_positions(raw: bytes, chunks: dict | None = None, limit: int = 1 << 20) -> list[tuple]:
    """Decode the VTX1 position array (s16 w/ fraction shift or f32); returns [(x,y,z)]."""
    off, sz = (chunks or chunk_table(raw))[b"VTX1"]
    c = raw[off:off + sz]
    fmt_off = struct.unpack_from(">I", c, 8)[0]
    arrs = struct.unpack_from(">13I", c, 0x0C)
    p, fmt = fmt_off, None
    while p + 16 <= sz:
        attr, cnt, ctype, frac = struct.unpack_from(">IIIB", c, p)
        if attr == 0xFF:
            break
        if attr == 9:
            fmt = (cnt, ctype, frac)
        p += 16
    if fmt is None or arrs[0] == 0:
        raise J3DProbeError("no position array")
    cnt, ctype, frac = fmt
    if ctype not in (3, 4) or cnt not in (0, 1):
        raise J3DProbeError("unsupported position format %r" % (fmt,))
    comps = 3 if cnt else 2
    esz = (2 if ctype == 3 else 4) * comps
    nxt = min([a for a in arrs[1:] if a > arrs[0]] + [sz])
    count = min((nxt - arrs[0]) // esz, limit)
    # INF1 +0x10 is the model vertex count; the remainder of the array is 32-byte alignment padding.
    ioff, _isz = (chunks or chunk_table(raw))[b"INF1"]
    inf_verts = struct.unpack_from(">I", raw, ioff + 0x10)[0]
    if 0 < inf_verts <= count:
        count = inf_verts
    ch = ">%d%s" % (comps, "h" if ctype == 3 else "f")
    scale = 1.0 / (1 << frac) if ctype == 3 else 1.0
    pts = []
    for i in range(count):
        v = struct.unpack_from(ch, c, arrs[0] + i * esz)
        v = tuple(x * scale for x in v) + ((0.0,) if comps == 2 else ())
        pts.append(v)
    return pts


def summarize(raw: bytes) -> dict:
    ch = chunk_table(raw)
    js = joints(raw, ch)
    pts = vtx_positions(raw, ch)
    lo = [min(p[k] for p in pts) for k in range(3)]
    hi = [max(p[k] for p in pts) for k in range(3)]
    roots = [j["index"] for j in js if j["parent"] < 0]
    return {"kind": raw[4:8].decode(), "size": len(raw), "chunks": {t.decode(): v for t, v in ch.items()},
            "joint_count": len(js), "roots": roots, "joint_names": [j["name"] for j in js],
            "position_count": len(pts), "pos_min": lo, "pos_max": hi}
