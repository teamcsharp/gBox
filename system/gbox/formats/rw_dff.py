"""Minimal RenderWare DFF (clump) chunk probe for PS2 NFL Blitz 2003 (BERTHA.ZIP).

Chunk header: type u32, size u32, version u32 (little endian). Probe only: walks the
chunk tree and reports clump/frame/geometry/atomic counts and per-geometry
vertex/triangle counts. It is not a mesh exporter.
"""
from __future__ import annotations
import struct
from typing import Dict, List

CLUMP, STRUCT, FRAMELIST, GEOMETRY, GEOMLIST, ATOMIC = 0x10, 0x01, 0x0E, 0x0F, 0x1A, 0x14
MATLIST, MATERIAL, TEXTURE, EXTENSION = 0x08, 0x07, 0x06, 0x03
CONTAINERS = {CLUMP, FRAMELIST, GEOMETRY, GEOMLIST, ATOMIC, MATLIST, MATERIAL, TEXTURE}


def walk(data: bytes, off: int = 0, end: int = None, depth: int = 0) -> List[dict]:
    end = len(data) if end is None else end
    out = []
    while off + 12 <= end:
        t, size, ver = struct.unpack_from("<III", data, off)
        body = off + 12
        if body + size > end:
            break
        node = {"type": t, "size": size, "version": ver, "offset": off, "depth": depth}
        if t in CONTAINERS:
            node["children"] = walk(data, body, body + size, depth + 1)
        out.append(node)
        off = body + size
    return out


def _find(nodes, t):
    for n in nodes:
        if n["type"] == t:
            yield n
        yield from _find(n.get("children", []), t)


def probe(data: bytes) -> Dict:
    tree = walk(data)
    if not tree or tree[0]["type"] != CLUMP:
        raise ValueError("not a RenderWare clump")
    clump = tree[0]
    st = clump["children"][0]
    if st["type"] != STRUCT:
        raise ValueError("clump lacks struct")
    n_atomic = struct.unpack_from("<I", data, st["offset"] + 12)[0]
    frames = 0
    for fl in _find([clump], FRAMELIST):
        frames = struct.unpack_from("<I", data, fl["children"][0]["offset"] + 12)[0]
    geoms = []
    for g in _find([clump], GEOMETRY):
        s = g["children"][0]
        flags, ntri, nvert, nmorph = struct.unpack_from("<IIII", data, s["offset"] + 12)
        geoms.append({"flags": flags, "triangles": ntri, "vertices": nvert, "morph_targets": nmorph})
    return {
        "clump_size": clump["size"], "library_stamp": clump["version"],
        "declared_atomics": n_atomic, "atomic_chunks": sum(1 for _ in _find([clump], ATOMIC)),
        "frames": frames, "geometries": geoms,
        "trailing_bytes": len(data) - (clump["offset"] + 12 + clump["size"]),
    }
