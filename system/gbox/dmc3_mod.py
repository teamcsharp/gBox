"""Devil May Cry 3 SE (PS2, SLUS_213.61) ``MOD `` model geometry probe.

Layout established on the owned disc (GDATA.AFS entry 0 ``pl000.pac``, PAC
children 1 and 12) and cross-checked with the boot ELF, see
``gbox/dmc3_slus.py``: ``0x1a9870`` classifies a model by its magic
(``MOD `` -> 0x10000000) and ``0x199070`` copies header bytes 0x10/0x11/0x13
and word 0x14 into the model instance.  All offsets are relative to the MOD
start and every attribute array starts on a 16-byte boundary.

Header (0x30 bytes)
  0x00 ``MOD ``  0x04 f32 version (1.01)  0x10 u8 objects  0x11 u8 bones
  0x12 u8, 0x13 u8, 0x14 u32 (217 on pl000)  0x1c u32 skeleton offset
Object record (0x30 bytes each, from 0x30)
  +0 u8 meshes  +1 u8 flags (0x80)  +2 u16 vertices (sum over its meshes)
  +4 u32 mesh-table offset  +8 u32 (1 or 0x00100001)  +0x20 f32[4] sphere x,y,z,r
Mesh record (0x30 bytes each, at the object's mesh-table offset)
  +0 u16 vertices  +2 u16 texture slot  +0xc u32 positions (f32 x,y,z)
  +0x10 normals (f32 x,y,z)  +0x14 uvs (s16 u,v; 4096 = 1.0)
  +0x18 bone refs (4 x u8 per vertex)  +0x1c strip/weight word (u16 per vertex)
Word bit 0x8000 is the PS2 GS no-kick (ADC) bit: vertex ``i`` closes triangle
``(i-2, i-1, i)`` only when it is clear; winding alternates.  Bits 0-14 are three
5-bit skin weights that sum to 31 on every pl000 body/coat vertex; bone-ref
byte 0 is 0 and bytes 1-3 are multiples of 4 (VU1 matrix slots, mapping to
skeleton bones is reader-stage work).
Skeleton: four u32 offsets relative to the skeleton start (parents, bone order,
flags, 0x20-byte transforms), parents are u8 with 0xff for the root.
"""
from __future__ import annotations

import math
import struct

HEADER = 0x30
REC = 0x30
NO_KICK = 0x8000
UV_ONE = 4096.0


def _off(b: bytes, o: int, n: int, what: str) -> int:
    if o % 16 or o + n > len(b) or o < HEADER:
        raise ValueError(f"{what} at {o:#x} (+{n:#x}) is unaligned or outside the {len(b):#x}-byte model")
    return o


def strip_triangles(flags, base: int = 0) -> list[tuple[int, int, int]]:
    """Triangles of one PS2 strip run using the GS no-kick (ADC) bit."""
    tris = []
    for i in range(2, len(flags)):
        if flags[i] & NO_KICK:
            continue
        a, b, c = base + i - 2, base + i - 1, base + i
        tris.append((a, b, c) if i % 2 == 0 else (b, a, c))
    return tris


def parse_mod(b: bytes) -> dict:
    """Header, objects, meshes (vertex arrays + triangles) and skeleton."""
    if b[:4] != b"MOD " or len(b) < HEADER:
        raise ValueError("not a DMC3 MOD model")
    version = struct.unpack_from("<f", b, 4)[0]
    nobj, nbone, h12, h13, h14 = struct.unpack_from("<BBBBI", b, 0x10)
    skel_off = struct.unpack_from("<I", b, 0x1C)[0]
    objects = []
    for k in range(nobj):
        r = HEADER + REC * k
        nmesh, oflags, ovc, mtab, ou8 = struct.unpack_from("<BBHII", b, r)
        sphere = struct.unpack_from("<4f", b, r + 0x20)
        meshes = []
        for j in range(nmesh):
            m = _off(b, mtab, REC * nmesh, "mesh table") + REC * j
            vc, tex = struct.unpack_from("<HH", b, m)
            po, no, uo, bo, fo = struct.unpack_from("<5I", b, m + 0xC)
            pos = struct.unpack_from(f"<{3 * vc}f", b, _off(b, po, 12 * vc, "positions"))
            nrm = struct.unpack_from(f"<{3 * vc}f", b, _off(b, no, 12 * vc, "normals"))
            uv = struct.unpack_from(f"<{2 * vc}h", b, _off(b, uo, 4 * vc, "uvs"))
            bones = b[_off(b, bo, 4 * vc, "bone refs"):bo + 4 * vc]
            flags = struct.unpack_from(f"<{vc}H", b, _off(b, fo, 2 * vc, "strip flags"))
            meshes.append({
                "vertices": vc, "texture": tex,
                "offsets": {"positions": po, "normals": no, "uvs": uo, "bones": bo, "flags": fo},
                "positions": [pos[3 * i:3 * i + 3] for i in range(vc)],
                "normals": [nrm[3 * i:3 * i + 3] for i in range(vc)],
                "uvs": [(uv[2 * i] / UV_ONE, uv[2 * i + 1] / UV_ONE) for i in range(vc)],
                "bone_refs": [tuple(bones[4 * i:4 * i + 4]) for i in range(vc)],
                "flags": list(flags),
                "weights": [tuple(((f >> s) & 31) / 31 for s in (0, 5, 10)) for f in flags],
                "triangles": strip_triangles(flags),
            })
        if sum(m["vertices"] for m in meshes) != ovc:
            raise ValueError(f"object {k}: mesh vertices do not add up to {ovc}")
        objects.append({"meshes": meshes, "vertices": ovc, "flags": oflags, "u8": ou8,
                        "mesh_table": mtab, "sphere": sphere})
    return {"version": round(version, 3), "objects": objects, "bones": nbone,
            "header": {"u12": h12, "u13": h13, "u14": h14, "skeleton_offset": skel_off},
            "skeleton": parse_skeleton(b, skel_off, nbone) if skel_off else None}


def parse_skeleton(b: bytes, off: int, nbone: int) -> dict:
    """Parent indices, bone order, flag bytes and 0x20-byte transform rows."""
    parents_o, order_o, flags_o, xf_o = struct.unpack_from("<4I", b, off)
    if off + xf_o + 0x20 * nbone > len(b):
        raise ValueError("skeleton transforms run past the model")
    parents = list(b[off + parents_o:off + parents_o + nbone])
    xf = [struct.unpack_from("<8f", b, off + xf_o + 0x20 * i) for i in range(nbone)]
    return {"offset": off, "parents": parents,
            "order": list(b[off + order_o:off + order_o + nbone]),
            "flags": list(b[off + flags_o:off + flags_o + nbone]),
            "transforms": xf, "ends_at": off + xf_o + 0x20 * nbone}


def mod_stats(model: dict) -> dict:
    """Totals plus the geometry sanity checks the reader stage relies on."""
    v = t = outside = 0
    worst_normal = 0.0
    for o in model["objects"]:
        cx, cy, cz, r = o["sphere"]
        for m in o["meshes"]:
            v += m["vertices"]
            t += len(m["triangles"])
            for x, y, z in m["positions"]:
                outside += math.dist((x, y, z), (cx, cy, cz)) > r * 1.001 + 1e-3
            for n in m["normals"]:
                worst_normal = max(worst_normal, abs(math.hypot(*n) - 1.0))
    return {"objects": len(model["objects"]), "meshes": sum(len(o["meshes"]) for o in model["objects"]),
            "vertices": v, "triangles": t, "outside_sphere": outside,
            "worst_normal_error": round(worst_normal, 6), "bones": model["bones"]}


def to_obj(model: dict, name: str = "mod") -> str:
    """Wavefront OBJ text (one group per object/mesh) for an editable preview."""
    out, base = [f"# DMC3 MOD {name}"], 1
    for k, o in enumerate(model["objects"]):
        for j, m in enumerate(o["meshes"]):
            out.append(f"g {name}_o{k}_m{j}_t{m['texture']}")
            out += ["v %.6f %.6f %.6f" % p for p in m["positions"]]
            out += ["vt %.6f %.6f" % (u, 1.0 - w) for u, w in m["uvs"]]
            out += ["vn %.6f %.6f %.6f" % n for n in m["normals"]]
            out += ["f %d/%d/%d %d/%d/%d %d/%d/%d" % tuple(x + base for i in tri for x in (i, i, i))
                    for tri in m["triangles"]]
            base += m["vertices"]
    return "\n".join(out) + "\n"
