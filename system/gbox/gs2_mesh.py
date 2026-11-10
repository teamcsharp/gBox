"""RE Survivor 2 (PS2) MDL mesh reader -> glTF 2.0 (.glb).

Evidence-backed layout (owned disc, SYSTEM.AFS entry 20 'cl02', MDL type 1):
  vertex chunk  : u32 head (type 0x33 | size_words<<16), u16 base, u16 count;
                  payload ends at head+4+size*4; the last count*32 bytes are
                  count x [pos(3f) w=1.0f][nrm(3f) w=1.0f] (stride 32, 16B
                  records, normals unit length); bytes before are padding.
  end marker    : 0xff 00 00 00 after the vertex list
  polygon list  : standard Ninja chunk stream (material 0x13, tiny 0x08,
                  strip 0x42 with u16 idx + u16x2 uv) handled by
                  gbox.gs2_mdl.walk_ninja_polys.
Hypotheses (not proven): node/skeleton transforms are not applied; parts are
exported in local space.
"""
from __future__ import annotations

import json
import struct

from .gs2_mdl import walk_ninja_polys  # validated in tests/test_gs2_mdl.py

VERT_TYPES = range(0x20, 0x3B)
_END_VERT = b"\xff\x00\x00\x00"


def parse_vertex_chunk(d: bytes, o: int):
    """Return (positions, normals, end_offset) for a type-0x33 chunk or None."""
    if o + 8 > len(d):
        return None
    head, = struct.unpack_from("<I", d, o)
    typ, size = head & 0xFF, head >> 16
    if typ != 0x33 or size < 3:
        return None
    base, count = struct.unpack_from("<HH", d, o + 4)
    end = o + 4 + size * 4
    start = end - count * 32
    if count == 0 or start < o + 8 or end > len(d):
        return None
    pos, nrm = [], []
    for i in range(count):
        px, py, pz = struct.unpack_from("<3f", d, start + 32 * i)
        nx, ny, nz = struct.unpack_from("<3f", d, start + 32 * i + 16)
        pos.append((px, py, pz))
        nrm.append((nx, ny, nz))
    return {"base": base, "pos": pos, "nrm": nrm}, end


def strips_to_tris(d: bytes, o: int, end: int):
    """Decode polygon-list strips between o and end -> (tris, uvs-by-vertex).

    Returns list of (idx_a, idx_b, idx_c) and dict idx->(u,v) (1/1023 scale).
    """
    tris, uv = [], {}
    while o + 4 <= end:
        typ, size = d[o], struct.unpack_from("<H", d, o + 2)[0]
        if typ == 0xFF:
            break
        if 0x40 <= typ <= 0x4F and size >= 1:
            nstrip = struct.unpack_from("<H", d, o + 4)[0] & 0x3FFF
            p = o + 6
            for _ in range(nstrip):
                n = struct.unpack_from("<h", d, p)[0]
                p += 2
                cw = n < 0
                n = abs(n)
                ids = []
                for k in range(n):
                    idx, u, v = struct.unpack_from("<Hhh", d, p)
                    p += 6
                    ids.append(idx)
                    uv[idx] = (u / 1023.0, v / 1023.0)
                for k in range(2, n):
                    a, b, c = ids[k - 2], ids[k - 1], ids[k]
                    if a == b or b == c or a == c:
                        cw = not cw
                        continue
                    tris.append((a, c, b) if (k & 1) == (0 if cw else 1) else (a, b, c))
            o += 4 + size * 2
            continue
        o += 4 if typ < 0x10 else 4 + size * 2  # tiny chunks carry no size
    return tris, uv


def extract_parts(d: bytes, start: int = 0x84):
    """Sequentially read [vertex chunk, end, polygon list] parts."""
    parts, o = [], start
    while True:
        vc = parse_vertex_chunk(d, o)
        if not vc:
            break
        v, o = vc
        if d[o:o + 4] != _END_VERT:
            break
        o += 4
        r = walk_ninja_polys(d, o)
        tris, uv = strips_to_tris(d, o, r["end"])
        parts.append({**v, "tris": tris, "uv": uv, "texture_id": r.get("texture_id")})
        o = r["end"]
    return parts


def to_glb(parts) -> bytes:
    """Pack parts into a single-buffer glTF 2.0 binary (positions, normals, uv0, indices)."""
    buf = bytearray()
    views, accs, prims = [], [], []

    def add(data: bytes, target):
        while len(buf) % 4:
            buf.append(0)
        views.append({"buffer": 0, "byteOffset": len(buf), "byteLength": len(data), "target": target})
        buf.extend(data)
        return len(views) - 1

    for p in parts:
        n = len(p["pos"])
        if not p["tris"] or not n:
            continue
        flat = [c for v in p["pos"] for c in v]
        xs, ys, zs = flat[0::3], flat[1::3], flat[2::3]
        a_pos = len(accs)
        accs.append({"bufferView": add(struct.pack(f"<{n*3}f", *flat), 34962), "componentType": 5126, "count": n,
                     "type": "VEC3", "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]})
        nf = [c for v in p["nrm"] for c in v]
        a_nrm = len(accs)
        accs.append({"bufferView": add(struct.pack(f"<{n*3}f", *nf), 34962), "componentType": 5126, "count": n, "type": "VEC3"})
        uvf = []
        for i in range(n):
            u, v = p["uv"].get(i, (0.0, 0.0))
            uvf += [u, v]
        a_uv = len(accs)
        accs.append({"bufferView": add(struct.pack(f"<{n*2}f", *uvf), 34962), "componentType": 5126, "count": n, "type": "VEC2"})
        idx = [i for t in p["tris"] if max(t) < n for i in t]
        a_ix = len(accs)
        accs.append({"bufferView": add(struct.pack(f"<{len(idx)}H", *idx), 34963), "componentType": 5123,
                     "count": len(idx), "type": "SCALAR"})
        prims.append({"attributes": {"POSITION": a_pos, "NORMAL": a_nrm, "TEXCOORD_0": a_uv}, "indices": a_ix})
    gltf = {"asset": {"version": "2.0", "generator": "gbox.gs2_mesh"}, "scene": 0, "scenes": [{"nodes": [0]}],
            "nodes": [{"mesh": 0}], "meshes": [{"primitives": prims}], "buffers": [{"byteLength": len(buf)}],
            "bufferViews": views, "accessors": accs}
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    while len(buf) % 4:
        buf.append(0)
    total = 12 + 8 + len(js) + 8 + len(buf)
    return (struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(js), b"JSON") + js
            + struct.pack("<I4s", len(buf), b"BIN\x00") + bytes(buf))
