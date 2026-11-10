"""FLVE (big-endian FLVER 0x2000x) mesh reader for Armored Core V: tables, positions, triangles, OBJ.

Layout (verified on owned-ISO samples; absolute offsets into the FLVE blob):
header 0x80 | dummies*0x40 | materials*0x20 | bones*0x80 | meshes*0x30 |
facesets*0x20 | vertex_buffers*0x20 | layouts*0x10 | textures*0x20 | layout members*0x14.
mesh: +0x00 dynamic, +0x04 material, +0x10 default_bone, +0x14 bone_count, +0x1C bone_idx_off,
      +0x20 faceset_count, +0x24 faceset_idx_off, +0x28 vb_count, +0x2C vb_idx_off (u32 index arrays).
faceset: +0x04 tristrip u8, +0x08 index_count, +0x0C index_offset, +0x10 index_bytes (rel. data_offset).
vertex buffer: +0x04 layout_idx, +0x08 vertex_size, +0x0C vertex_count, +0x18 buffer_len, +0x1C buffer_off.
layout: +0x00 member_count, +0x0C member_offset; member: +0x04 offset, +0x08 type, +0x0C semantic.
Only float3 (type 2) POSITION (semantic 0) is decoded; other attributes are not.
"""
from __future__ import annotations

import math
import struct

from gbox.acv_flve import parse_flve_header

SEM_POSITION = 0
TYPE_FLOAT3 = 2


def _u32s(buf, off, n):
    if off < 0 or off + 4 * n > len(buf):
        raise ValueError("table out of range")
    return struct.unpack_from(">%dI" % n, buf, off)


def strip_to_tris(idx, restart):
    tris, a, b, flip = [], None, None, False
    run = []
    for i in idx:
        if i == restart:
            run = []
            continue
        run.append(i)
        if len(run) >= 3:
            x, y, z = run[-3:]
            if x != y and y != z and x != z:
                tris.append((x, z, y) if len(run) % 2 == 0 else (x, y, z))
    return tris


def parse_flve_mesh(buf: bytes, include_lods: bool = False) -> dict:
    hd = parse_flve_header(buf)
    nd, nm, nb, nme = (hd["dummy_count"], hd["material_count"], hd["bone_count"], hd["mesh_count"])
    off = 0x80 + nd * 0x40 + nm * 0x20 + nb * 0x80
    mesh_off = off
    off += nme * 0x30
    # total faceset count = sum over meshes
    meshes = []
    nfs = nvb = 0
    for i in range(nme):
        m = _u32s(buf, mesh_off + i * 0x30, 12)
        meshes.append(m)
        nfs += m[8]
        nvb += m[10]
    if nfs > 4096 or nvb > 4096:
        raise ValueError("implausible faceset/vb counts")
    fs_off = off
    vb_off = fs_off + nfs * 0x20
    lay_off = vb_off + nvb * 0x20
    if hd["vertex_buffer_count"] != nvb:
        raise ValueError("vertex buffer count mismatch")
    data = hd["data_offset"]
    fsets = []
    for i in range(nfs):
        f = _u32s(buf, fs_off + i * 0x20, 8)
        cnt, ioff, ilen = f[2], f[3], f[4]
        strip = (f[1] >> 24) & 0xFF
        a = data + ioff
        if a + cnt * 2 > len(buf) or cnt > 1 << 22:
            raise ValueError("faceset index range")
        idx = struct.unpack_from(">%dH" % cnt, buf, a)
        fsets.append({"flags": f[0], "tristrip": strip, "index_count": cnt, "indices": idx})
    vbs = []
    for i in range(nvb):
        v = _u32s(buf, vb_off + i * 0x20, 8)
        lay, vsize, vcount, blen, boff = v[1], v[2], v[3], v[6], v[7]
        vbs.append({"layout": lay, "vertex_size": vsize, "vertex_count": vcount,
                    "buffer_len": blen, "buffer_off": boff})
        if vsize * vcount != blen or data + boff + blen > len(buf):
            raise ValueError("vertex buffer range")
    nlay = max((v["layout"] for v in vbs), default=-1) + 1
    layouts = []
    for i in range(nlay):
        cnt, _, _, moff = _u32s(buf, lay_off + i * 0x10, 4)
        if cnt > 64:
            raise ValueError("implausible member count")
        mem = []
        for j in range(cnt):
            w = _u32s(buf, moff + j * 0x14, 5)
            mem.append({"offset": w[1], "type": w[2], "semantic": w[3], "index": w[4]})
        layouts.append(mem)
    out_meshes, fi, vi = [], 0, 0
    bb0, bb1 = hd["bbox_min"], hd["bbox_max"]
    for m in meshes:
        fs_idx = _u32s(buf, m[9], m[8])
        vb_idx = _u32s(buf, m[11], m[10])
        verts = []
        vb = vbs[vb_idx[0]]
        pos = [x for x in layouts[vb["layout"]] if x["semantic"] == SEM_POSITION and x["type"] == TYPE_FLOAT3]
        if not pos:
            raise ValueError("no float3 position member")
        po = pos[0]["offset"]
        base = data + vb["buffer_off"]
        for k in range(vb["vertex_count"]):
            verts.append(struct.unpack_from(">3f", buf, base + k * vb["vertex_size"] + po))
        tris = []
        for fi_ in fs_idx:
            fsd = fsets[fi_]
            if fsd["flags"] != 0 and not include_lods:
                continue
            if fsd["tristrip"]:
                tris += strip_to_tris(fsd["indices"], 0xFFFF)
            else:
                ix = fsd["indices"]
                tris += [tuple(ix[j:j + 3]) for j in range(0, len(ix) - 2, 3)]
        tris = [t for t in tris if max(t) < len(verts)]
        for p in verts:
            if not all(math.isfinite(c) for c in p):
                raise ValueError("non-finite position")
        out_meshes.append({"material": m[1], "vertices": verts, "triangles": tris})
    return {"header": hd, "meshes": out_meshes, "layouts": layouts}


def to_obj(model: dict, name: str = "acv") -> str:
    lines, base = ["# ACV FLVE export (positions + triangles only)", "o " + name], 1
    for mi, m in enumerate(model["meshes"]):
        lines.append("g mesh%d" % mi)
        lines += ["v %.6f %.6f %.6f" % v for v in m["vertices"]]
        lines += ["f %d %d %d" % tuple(i + base for i in t) for t in m["triangles"]]
        base += len(m["vertices"])
    return "\n".join(lines) + "\n"
