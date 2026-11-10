"""Perfect Dark (N64) model display-list reader -> triangle meshes / OBJ.

Builds on gbox.pd_model (modeldef/node probe). Command layout is the Rare
F3DEX variant used by n64decomp/perfect_dark (include/PR/gbi.h):

* 0x04 G_VTX   : n=((w0>>20)&15)+1, v0=(w0>>16)&15, length=w0&0xffff,
                 w1 = 0x04000000 | byte offset into the node's vertex array
                 (segment 4; base = DL rodata ``vertices_offset``).
* Vtx is 12 bytes: s16 x,y,z, u16 colour-offset, s16 s,t (S10.5).
* 0xb1 G_TRI4  : (hypothesis validated by edge-length test) w0 low 16 bits hold
                 4 nibbles, w1 holds 4 bytes; triangle i (MSB first) =
                 (nibble_i, hi(byte_i), lo(byte_i)); all-zero triangles are padding.
* 0xbf G_TRI1  : w1 bytes = 2*index (standard F3DEX).
* 0x06 G_DL    : call/branch (segment 5 pointers ignored here, reported).
* 0xb8 G_ENDDL ends the list.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from typing import Iterable

from . import pd_model

VTX_SIZE = 12
G_VTX, G_DL, G_TRI1, G_ENDDL, G_TRI4 = 0x04, 0x06, 0xBF, 0xB8, 0xB1


@dataclass
class Mesh:
    node_offset: int
    which: str  # 'opa' or 'xlu'
    vertices: list[tuple[int, int, int]] = field(default_factory=list)
    uvs: list[tuple[float, float]] = field(default_factory=list)
    colour_offsets: list[int] = field(default_factory=list)
    triangles: list[tuple[int, int, int]] = field(default_factory=list)
    skipped: int = 0  # triangles referencing unloaded buffer slots
    commands: dict[int, int] = field(default_factory=dict)


def _read_vtx(data: bytes, off: int):
    x, y, z, col, s, t = struct.unpack_from(">hhhHhh", data, off)
    return (x, y, z), col, (s / 32.0, t / 32.0)


def decode_dl(data: bytes, dl_offset: int, vtx_base: int, numvertices: int,
              node_offset: int = 0, which: str = "opa", max_cmds: int = 4096) -> Mesh:
    """Decode one display list into a Mesh (vertices deduplicated by array index)."""
    mesh = Mesh(node_offset, which)
    buf: dict[int, int] = {}  # F3DEX buffer slot -> mesh vertex index
    arr_map: dict[int, int] = {}  # vertex-array index -> mesh vertex index
    pos = dl_offset
    for _ in range(max_cmds):
        if pos + 8 > len(data):
            raise ValueError("display list runs past end of blob")
        w0, w1 = struct.unpack_from(">II", data, pos)
        pos += 8
        op = w0 >> 24
        mesh.commands[op] = mesh.commands.get(op, 0) + 1
        if op == G_ENDDL:
            break
        if op == G_VTX:
            n = ((w0 >> 20) & 0xF) + 1
            v0 = (w0 >> 16) & 0xF
            if (w0 & 0xFFFF) != n * VTX_SIZE:
                raise ValueError(f"G_VTX length {w0 & 0xffff} != {n}*12 at {pos-8:#x}")
            if w1 >> 24 != 4:
                raise ValueError(f"G_VTX non-segment-4 address {w1:#x}")
            first = (w1 & 0xFFFFFF) // VTX_SIZE
            if first + n > numvertices:
                raise ValueError("G_VTX beyond node vertex array")
            for k in range(n):
                ai = first + k
                if ai not in arr_map:
                    p, c, uv = _read_vtx(data, vtx_base + ai * VTX_SIZE)
                    arr_map[ai] = len(mesh.vertices)
                    mesh.vertices.append(p)
                    mesh.colour_offsets.append(c)
                    mesh.uvs.append(uv)
                buf[v0 + k] = arr_map[ai]
        elif op == G_TRI4:
            nibs = [(w0 >> 12) & 0xF, (w0 >> 8) & 0xF, (w0 >> 4) & 0xF, w0 & 0xF]
            for i in range(4):
                b = (w1 >> (24 - 8 * i)) & 0xFF
                tri = (nibs[i], b >> 4, b & 0xF)
                if tri == (0, 0, 0):
                    continue
                _add(mesh, buf, tri)
        elif op == G_TRI1:
            tri = ((w1 >> 16 & 0xFF) // 2, (w1 >> 8 & 0xFF) // 2, (w1 & 0xFF) // 2)
            _add(mesh, buf, tri)
    else:
        raise ValueError("display list has no G_ENDDL within command limit")
    return mesh


def _add(mesh: Mesh, buf: dict[int, int], tri):
    if all(i in buf for i in tri):
        mesh.triangles.append((buf[tri[0]], buf[tri[1]], buf[tri[2]]))
    else:
        mesh.skipped += 1


def decode_model(data: bytes, model: pd_model.ModelDef | None = None) -> list[Mesh]:
    """Decode every DL node (opa, then xlu if present) of a decompressed chr blob."""
    model = model or pd_model.parse(data)
    meshes = []
    for n in model.nodes:
        if n.type_name != "DL":
            continue
        r = n.rodata
        for key, which in (("opagdl_offset", "opa"), ("xlugdl_offset", "xlu")):
            if r.get(key):
                meshes.append(decode_dl(data, r[key], r["vertices_offset"],
                                        r["numvertices"], n.file_offset, which))
    return meshes


def bind_offsets(model: pd_model.ModelDef) -> dict[int, tuple[float, float, float]]:
    """Accumulated POSITION translations along the parent chain per node
    (HYPOTHESIS for a bind pose: translation only, no rotation/mtx palette)."""
    by_off = {n.file_offset: n for n in model.nodes}
    out: dict[int, tuple[float, float, float]] = {}
    for n in model.nodes:
        x = y = z = 0.0
        cur, guard = n, 0
        while cur is not None and guard < 256:
            if cur.type_name == "POSITION":
                p = cur.rodata["pos"]
                x += p["x"]; y += p["y"]; z += p["z"]
            cur = by_off.get(cur.parent_offset) if cur.parent_offset else None
            guard += 1
        out[n.file_offset] = (x, y, z)
    return out


def edge_stats(mesh: Mesh) -> dict:
    """Mean/max triangle edge length (model units): large values flag a wrong index decode."""
    es = []
    for a, b, c in mesh.triangles:
        for u, v in ((a, b), (b, c), (c, a)):
            es.append(math.dist(mesh.vertices[u], mesh.vertices[v]))
    return {"edges": len(es), "mean": sum(es) / len(es) if es else 0.0, "max": max(es, default=0.0)}


def to_obj(meshes: Iterable[Mesh], offsets: dict[int, tuple[float, float, float]] | None = None,
           scale: float = 1.0) -> str:
    lines = ["# gbox pd_mesh export (model units * scale); translation-only bind offsets are a hypothesis"]
    base = 1
    for i, m in enumerate(meshes):
        ox, oy, oz = (offsets or {}).get(m.node_offset, (0.0, 0.0, 0.0))
        lines.append(f"o dl{i}_{m.node_offset:#x}_{m.which}")
        for (x, y, z), (s, t) in zip(m.vertices, m.uvs):
            lines.append(f"v {(x+ox)*scale:.5f} {(y+oy)*scale:.5f} {(z+oz)*scale:.5f}")
        for s, t in m.uvs:
            lines.append(f"vt {s:.4f} {t:.4f}")
        for a, b, c in m.triangles:
            lines.append(f"f {a+base}/{a+base} {b+base}/{b+base} {c+base}/{c+base}")
        base += len(m.vertices)
    return "\n".join(lines) + "\n"
