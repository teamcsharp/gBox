"""Forsaken 64 (N64) decoded-RNC1 model container + F3DEX1 display-list walker.

Container (big-endian), verified on the owned USA ROM:
  u32 dl_off      byte offset of the display list inside the block
  u32 n_relocs
  u32 relocs[n]   byte offsets of u32 words (inside the DL) holding block-relative
                  addresses (SETTIMG / VTX); the loader adds the load base
  ...             payload (palettes, textures, Vtx arrays) then the DL at dl_off
Display list is F3DEX1: VTX=0x04 (n=(w0>>10)&63, v0=((w0>>16)&255)/2, src=w1),
TRI1=0xBF, TRI2=0xB1 (indices stored x2), ENDDL=0xB8, SETTIMG=0xFD.
Vtx = 16 bytes: s16 x,y,z; u16 flag; s16 s,t; u8 r,g,b,a.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field


@dataclass
class DlModel:
    dl_off: int
    relocs: list[int]
    vertices: list[tuple]            # (x,y,z,s,t,r,g,b,a)
    triangles: list[tuple]           # indices into vertices
    textures: list[int] = field(default_factory=list)   # SETTIMG block-relative addrs


def parse_header(blk: bytes) -> tuple[int, list[int]] | None:
    """Return (dl_off, relocs) when the block has a self-consistent reloc header."""
    if len(blk) < 16:
        return None
    dl_off, n = struct.unpack_from(">II", blk, 0)
    if not (0 < n < 4096) or 8 + 4 * n > len(blk) or dl_off % 8 or dl_off >= len(blk):
        return None
    relocs = list(struct.unpack_from(f">{n}I", blk, 8))
    if any(r < dl_off or r + 4 > len(blk) for r in relocs):
        return None
    return dl_off, relocs


def parse_model(blk: bytes) -> DlModel | None:
    hdr = parse_header(blk)
    if hdr is None:
        return None
    dl_off, relocs = hdr
    vbuf: list[tuple | None] = [None] * 64
    verts: list[tuple] = []
    key: dict[tuple, int] = {}
    tris: list[tuple] = []
    texs: list[int] = []

    def tri(a, b, c):
        ids = []
        for i in (a, b, c):
            v = vbuf[i] if 0 <= i < 64 else None
            if v is None:
                return
            if v not in key:
                key[v] = len(verts)
                verts.append(v)
            ids.append(key[v])
        tris.append(tuple(ids))

    pos = dl_off
    while pos + 8 <= len(blk):
        w0, w1 = struct.unpack_from(">II", blk, pos)
        op = w0 >> 24
        pos += 8
        if op == 0xB8:
            break
        if op == 0xFD:
            texs.append(w1)
        elif op == 0x04:
            n, v0 = (w0 >> 10) & 63, ((w0 >> 16) & 255) // 2
            if w1 + 16 * n > len(blk) or v0 + n > 64:
                return None
            for k in range(n):
                x, y, z, _f, s, t, r, g, b, a = struct.unpack_from(">hhhHhhBBBB", blk, w1 + 16 * k)
                vbuf[v0 + k] = (x, y, z, s, t, r, g, b, a)
        elif op == 0xBF:
            tri((w1 >> 16 & 255) // 2, (w1 >> 8 & 255) // 2, (w1 & 255) // 2)
        elif op == 0xB1:
            tri((w0 >> 16 & 255) // 2, (w0 >> 8 & 255) // 2, (w0 & 255) // 2)
            tri((w1 >> 16 & 255) // 2, (w1 >> 8 & 255) // 2, (w1 & 255) // 2)
    return DlModel(dl_off, relocs, verts, tris, texs)


def to_obj(m: DlModel, name: str = "forsaken") -> str:
    out = [f"o {name}"]
    out += [f"v {v[0]} {v[1]} {v[2]}" for v in m.vertices]
    out += [f"f {a+1} {b+1} {c+1}" for a, b, c in m.triangles]
    return "\n".join(out) + "\n"
