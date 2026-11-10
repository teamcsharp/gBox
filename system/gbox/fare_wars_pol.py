"""Crazy Taxi: Fare Wars (PSP, USA, ULUS10273) POL*.BIN model files (request #2453).

Not the Dreamcast NAOMI layout of gbox.crazy_taxi2 (its ``walk`` rejects every PSP file); the PSP port stores
PSP-GE-ready vertex data.  Layout (little-endian), proven on the owned CT2/POLPP* driver models:

* header, 16 bytes: u32 slots, u32 meshes, u32 strips, u32 vertex_data_offset (file offset);
* slot table, ``slots`` x 32 bytes at 0x10: u16 first_mesh, u16 mesh_count, u32 0, f32 min xyz, f32 max xyz
  (an empty slot is 0, 0, 0 with min = +FLT_MAX and max = -FLT_MAX, so slots stay aligned with the DC part list);
* mesh table, ``meshes`` x 44 bytes: u32 first_strip, u32 strip_count, u32 texture index (0xFFFFFFFF = none),
  u32 ARGB, u32 tag, f32 min xyz, f32 max xyz;
* strip table, ``strips`` x 16 bytes: u32 flags, u16 GE primitive (3 list, 4 strip, 5 fan), u16 GE vertex type
  (0x0121 = u8 uv, s8 normal, s16 position), u32 vertex count, u32 byte offset from vertex_data_offset;
* vertex data: GE vertices (vtype 0x121: 12 B = u8 u,v; s8 nx,ny,nz,pad; s16 x,y,z; vtype 0x123: f32 u,v first, 20 B).  The s16 position is a fraction of 32767 of
  one uniform scale per mesh: pos = centre + s16 / 32767 * max(half-extent), centre/half from the mesh min/max.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

FLT_MAX = 3.4028234663852886e+38
VT_POS16_NRM8_UV8 = 0x0121
PRIM_LIST, PRIM_STRIP, PRIM_FAN = 3, 4, 5
KNOWN_VTYPES = (0x0121, 0x0123)   # both seen in the owned build; others are rejected, not guessed


def ge_layout(vtype: int):
    """PSP GE layout for s16 position / s8 normal / u8 or f32 uv -> (stride, uv_off, nrm_off, pos_off, uv_kind)."""
    tt, nt, vt = vtype & 3, (vtype >> 5) & 3, (vtype >> 7) & 3
    if (tt, nt, vt) not in ((1, 1, 2), (3, 1, 2)) or vtype & ~0x1A3:
        raise ValueError(f"unsupported GE vertex type {vtype:#x}")
    off = 2 if tt == 1 else 8
    nrm_off = off
    off = (off + 3 + 1) & ~1
    pos_off = off
    off += 6
    align = 4 if tt == 3 else 2
    return (off + align - 1) // align * align, 0, nrm_off, pos_off, ("u8" if tt == 1 else "f32")


@dataclass
class Slot:
    index: int
    first_mesh: int
    mesh_count: int
    bmin: tuple
    bmax: tuple

    @property
    def empty(self) -> bool:
        return self.mesh_count == 0


@dataclass
class Mesh:
    first_strip: int
    strip_count: int
    texture: int          # -1 = untextured
    argb: int
    tag: int
    bmin: tuple
    bmax: tuple


@dataclass
class Strip:
    flags: int
    prim: int
    vtype: int
    count: int
    offset: int


@dataclass
class Pol:
    slots: list = field(default_factory=list)
    meshes: list = field(default_factory=list)
    strips: list = field(default_factory=list)
    vertex_offset: int = 0
    size: int = 0
    vertex_end: int = 0


def parse_pol(b: bytes) -> Pol:
    if len(b) < 16:
        raise ValueError("file shorter than the 16-byte header")
    ns, nm, nst, vo = struct.unpack_from("<4I", b, 0)
    mesh_at = 16 + 32 * ns
    strip_at = mesh_at + 44 * nm
    if strip_at + 16 * nst != vo or vo > len(b):
        raise ValueError(f"tables end at {strip_at + 16 * nst:#x}, header says vertex data at {vo:#x}")
    p = Pol(vertex_offset=vo, size=len(b))
    for i in range(ns):
        f = struct.unpack_from("<HHI6f", b, 16 + 32 * i)
        p.slots.append(Slot(i, f[0], f[1], f[3:6], f[6:9]))
    for i in range(nm):
        w = struct.unpack_from("<5I6f", b, mesh_at + 44 * i)
        tex = -1 if w[2] == 0xFFFFFFFF else w[2]
        p.meshes.append(Mesh(w[0], w[1], tex, w[3], w[4], w[5:8], w[8:11]))
    for i in range(nst):
        fl, prim, vt, cnt, off = struct.unpack_from("<IHHII", b, strip_at + 16 * i)
        p.strips.append(Strip(fl, prim, vt, cnt, off))
    # structural invariants (not assumptions): meshes are contiguous in slot order, strips in mesh order
    expect = 0
    for s in p.slots:
        if s.mesh_count:
            if s.first_mesh != expect:
                raise ValueError(f"slot {s.index} starts at mesh {s.first_mesh}, expected {expect}")
            expect += s.mesh_count
    if expect != nm:
        raise ValueError(f"slots cover {expect} meshes, header says {nm}")
    expect = 0
    for i, m in enumerate(p.meshes):
        if m.first_strip != expect:
            raise ValueError(f"mesh {i} starts at strip {m.first_strip}, expected {expect}")
        expect += m.strip_count
    if expect != nst:
        raise ValueError(f"meshes cover {expect} strips, header says {nst}")
    off = 0
    for i, s in enumerate(p.strips):
        if s.vtype not in KNOWN_VTYPES:
            raise ValueError(f"strip {i} vertex type {s.vtype:#x} is not a known layout")
        if s.offset < off:
            raise ValueError(f"strip {i} vertex offset {s.offset} overlaps earlier data ({off})")
        off = s.offset + ge_layout(s.vtype)[0] * s.count
    if vo + off > len(b):
        raise ValueError(f"vertex data ends at {vo + off:#x}, file is {len(b):#x} bytes")
    p.vertex_end = vo + off
    return p


def mesh_vertices(b: bytes, p: Pol, mesh_index: int):
    """Raw decoded vertices of one mesh: (positions f32 Nx3, normals f32 Nx3, uv f32 Nx2 (u8/128), strip sizes)."""
    import numpy as np
    m = p.meshes[mesh_index]
    pos, nrm, uv, sizes = [], [], [], []
    for s in p.strips[m.first_strip:m.first_strip + m.strip_count]:
        base = p.vertex_offset + s.offset
        stride, uo, no, po, kind = ge_layout(s.vtype)
        for v in range(s.count):
            at = base + stride * v
            if kind == "u8":
                u, w = struct.unpack_from("<2B", b, at + uo)
                u, w = u / 128.0, w / 128.0
            else:
                u, w = struct.unpack_from("<2f", b, at + uo)
            nx, ny, nz = struct.unpack_from("<3b", b, at + no)
            uv.append((u, w))
            nrm.append((nx / 127.0, ny / 127.0, nz / 127.0))
            pos.append(struct.unpack_from("<3h", b, at + po))
        sizes.append(s.count)
    pos = np.array(pos, dtype=np.float64) / 32767.0
    lo, hi = np.array(m.bmin), np.array(m.bmax)
    centre, half = (lo + hi) / 2.0, (hi - lo) / 2.0
    return (centre + pos * half.max()).astype(np.float32), np.array(nrm, np.float32), np.array(uv, np.float32), sizes


def strip_triangles(prim: int, n: int):
    if prim == PRIM_LIST:
        return [(i, i + 1, i + 2) for i in range(0, n - 2, 3)]
    if prim == PRIM_STRIP:
        return [((i, i + 1, i + 2) if i % 2 == 0 else (i + 1, i, i + 2)) for i in range(n - 2)]
    if prim == PRIM_FAN:
        return [(0, i, i + 1) for i in range(1, n - 1)]
    raise ValueError(f"unsupported GE primitive {prim}")
