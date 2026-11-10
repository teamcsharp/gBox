"""NW4R BRRES ``MDL0`` (model) reader, v8-v11, big-endian.

Verified on Metroid: Other M (R3OJ01) FST file '0' ``samus_normal`` (v11).
Decodes: header/section table, properties (vertex/face/bone counts, extents),
bone tree (SRT + parent links), vertex arrays (position/normal/uv), and the
material / object / texture-link name lists.  Display-list (face) decoding is a
later stage; object entries only expose their raw offsets.
"""
from __future__ import annotations

import struct

SECTIONS = ("defs", "bones", "verts", "norms", "colors", "uvs", "furvecs",
            "furlayers", "materials", "shaders", "objects", "textures",
            "palettes", "userdata")
_CT = {0: ("B", 1), 1: ("b", 1), 2: ("H", 2), 3: ("h", 2), 4: ("f", 4)}


class Mdl0Error(ValueError):
    pass


def _u32(b, o):
    return struct.unpack_from(">I", b, o)[0]


def _s32(b, o):
    return struct.unpack_from(">i", b, o)[0]


def _cstr(b, o):
    n = _u32(b, o - 4)
    if n > 512 or o + n > len(b):
        raise Mdl0Error("bad string")
    return b[o:o + n].decode("latin1")


def _group(b: bytes, base: int):
    """Resource dict group -> [(name, absolute data offset)] (index 0 is root)."""
    if base < 0 or base + 8 > len(b):
        raise Mdl0Error("group out of range")
    _sz, n = struct.unpack_from(">II", b, base)
    if n > 8192:
        raise Mdl0Error("implausible group size")
    out = []
    for i in range(1, n + 1):
        o = base + 8 + 16 * i
        _i, _f, _l, _r, no, do = struct.unpack_from(">HHHHII", b, o)
        out.append((_cstr(b, base + no), base + do))
    return out


def _vec(b, o, n):
    return struct.unpack_from(">%df" % n, b, o)


def parse_bone(b, o, name):
    (ln, mo, so, idx, node, flags, bb, ref) = struct.unpack_from(">8I", b, o)
    scale, rot, trans = _vec(b, o + 0x20, 3), _vec(b, o + 0x2C, 3), _vec(b, o + 0x38, 3)
    vmin, vmax = _vec(b, o + 0x44, 3), _vec(b, o + 0x50, 3)
    par, child, nxt, prv, p2 = struct.unpack_from(">5i", b, o + 0x5C)
    return {"name": name, "index": idx, "node_id": node, "flags": flags,
            "scale": scale, "rot_deg": rot, "trans": trans, "min": vmin, "max": vmax,
            "parent_off": par, "bind": _vec(b, o + 0x70, 12), "off": o}


def parse_vertex_array(b, o, name, kind):
    ln, mo, do, so, idx, comp, typ = struct.unpack_from(">7I", b, o)
    div, stride, cnt = struct.unpack_from(">BBH", b, o + 0x1C)
    nf = 3 if kind in ("pos", "norm") else 2
    if kind == "pos":
        nf = 3 if comp else 2
    if kind == "uv":
        nf = 2 if comp else 1
    if typ not in _CT:
        raise Mdl0Error("bad component type %d" % typ)
    fmt, sz = _CT[typ]
    start = o + do
    if start + cnt * stride > len(b):
        raise Mdl0Error("vertex data out of range")
    if stride != nf * sz and kind != "norm":
        raise Mdl0Error("stride %d != %d*%d" % (stride, nf, sz))
    nf_dec = min(nf, stride // sz)
    pts = []
    sc = 1.0 / (1 << div) if typ != 4 else 1.0
    for i in range(cnt):
        v = struct.unpack_from(">%d%s" % (nf_dec, fmt), b, start + i * stride)
        pts.append(tuple(x * sc for x in v))
    return {"name": name, "index": idx, "type": typ, "divisor": div, "stride": stride,
            "count": cnt, "components": nf_dec, "data_off": start, "values": pts}


def parse_mdl0(b: bytes, o: int = 0) -> dict:
    if b[o:o + 4] != b"MDL0":
        raise Mdl0Error("not MDL0")
    size, ver = struct.unpack_from(">II", b, o + 4)
    if ver not in (8, 9, 10, 11):
        raise Mdl0Error("unsupported MDL0 version %d" % ver)
    n_off = 14 if ver == 11 else 12
    offs = struct.unpack_from(">%di" % n_off, b, o + 0x10)
    names = SECTIONS[:n_off]
    name = _cstr(b, o + _s32(b, o + 0x10 + 4 * n_off))
    po = o + 0x10 + 4 * n_off + 4
    (hl, _mo, scaling, texmtx, nverts, nfaces, _orig, nnodes) = struct.unpack_from(">IiIIIIII", b, po)
    mdl = {"name": name, "version": ver, "size": size, "offset": o,
           "scaling_rule": scaling, "num_vertices": nverts, "num_faces": nfaces,
           "num_bones": nnodes, "min": _vec(b, po + 0x28, 3), "max": _vec(b, po + 0x34, 3),
           "sections": {}}
    for nm, off in zip(names, offs):
        if off:
            mdl["sections"][nm] = [(n, d) for n, d in _group(b, o + off)]
    mdl["bones"] = [parse_bone(b, d, n) for n, d in mdl["sections"].get("bones", [])]
    # parent resolution by absolute offset
    by_off = {bn["off"]: bn["name"] for bn in mdl["bones"]}
    for bn in mdl["bones"]:
        bn["parent"] = by_off.get(bn["off"] + bn["parent_off"]) if bn["parent_off"] else None
    for key, kind in (("verts", "pos"), ("norms", "norm"), ("uvs", "uv")):
        mdl[key] = [parse_vertex_array(b, d, n, kind) for n, d in mdl["sections"].get(key, [])]
    mdl["materials"] = [n for n, _ in mdl["sections"].get("materials", [])]
    mdl["objects"] = [{"name": n, "off": d} for n, d in mdl["sections"].get("objects", [])]
    mdl["textures"] = [n for n, _ in mdl["sections"].get("textures", [])]
    return mdl
