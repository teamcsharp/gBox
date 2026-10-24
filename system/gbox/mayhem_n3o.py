"""WCW Mayhem (N64, Kodiak/EA) ``.n3o`` model probe/reader (#1512, game 9cb579d94b6d2167).

Layout (big-endian, derived from the owned Europe build, parse+display-list decode validated on all 176 n3o members (63265 triangles, 0 out-of-range indices); field meanings marked H are hypotheses
not yet proven against the game's loader):

    0x00 u16 0x2301 magic, u16 nparts
    0x04 u32 tail_offset      H: start of a trailer holding a copy of the part-name table
    0x0C u32 vtx_off          vertex pool (N64 ``Vtx``, 16 bytes) - equals 0x20 + nparts*0x24 (rounded to 8)
    0x10 u32 vtx_count
    0x18 u32 dl_end           (0 in prop models) end of the display-list area (last part end)
    0x1C u32 H: unknown (points into trailer)
    0x20 nparts * 0x24 part records: name[8], u32 flags(H), u32 0x13/0x14 (H), u32 0, u32 dl_off, u32 H(cumulative),
         u32 dl_size, u32 0.   Part blocks are contiguous: dl_off[i] + dl_size[i] == dl_off[i+1], last end == dl_end.
    vertices: s16 x,y,z; u16 flag(=0); s16 s,t; u8 r,g,b,a (standard N64 Vtx; x/y/z are model space, small ints)
    part data: RSP display lists, 8-byte commands.  F3DEX2-style opcodes observed: 0xDA (MTX), 0x01 (VTX; segment-2 address =
    offset into the vertex pool), 0x05/0x06/0x07 (TRI1/TRI2/QUAD), 0xDF (ENDDL), 0xFD (SETTIMG).  Microcode id is H.
"""
from __future__ import annotations

import struct

MAGIC = 0x2301
PART_STRIDE = 0x24


def parse(data: bytes) -> dict:
    magic, nparts = struct.unpack_from(">HH", data, 0)
    if magic != MAGIC:
        raise ValueError(f"not an n3o (magic {magic:#x})")
    tail, _, vtx_off, vtx_count, _, dl_end, hint = struct.unpack_from(">7I", data, 4)
    parts = []
    for i in range(nparts):
        o = 0x20 + i * PART_STRIDE
        name = data[o:o + 8].split(b"\0")[0].decode("latin1")
        flags, kind, z0, dl_off, cum, dl_size, z1 = struct.unpack_from(">7I", data, o + 8)
        parts.append({"name": name, "flags": flags, "kind": kind, "dl_off": dl_off, "dl_size": dl_size, "cum": cum})
    if vtx_off + vtx_count * 16 > len(data):
        raise ValueError("vertex pool outside file")
    return {"nparts": nparts, "tail_offset": tail, "vtx_off": vtx_off, "vtx_count": vtx_count, "dl_end": dl_end,
            "hint_offset": hint, "parts": parts, "size": len(data)}


def vertices(data: bytes, m: dict) -> list[tuple]:
    o = m["vtx_off"]
    return [struct.unpack_from(">hhhHhhBBBB", data, o + i * 16) for i in range(m["vtx_count"])]


def contiguous(m: dict) -> bool:
    p = m["parts"]
    return all(p[i]["dl_off"] + p[i]["dl_size"] == p[i + 1]["dl_off"] for i in range(len(p) - 1)) and \
        (not p or not m["dl_end"] or p[-1]["dl_off"] + p[-1]["dl_size"] == m["dl_end"])


def triangles(data: bytes, part: dict, m: dict) -> list[tuple[int, int, int]]:
    """Triangles of one part as indices into the model vertex pool (F3DEX2 VTX/TRI1/TRI2/QUAD)."""
    slots: list = [None] * 64
    tris = []
    off, end = part["dl_off"], part["dl_off"] + part["dl_size"]
    while off + 8 <= end:
        w0, w1 = struct.unpack_from(">II", data, off)
        op = w0 >> 24
        if op == 0x01:
            n, vend = (w0 >> 12) & 0xFF, (w0 >> 1) & 0x7F
            base = (w1 & 0xFFFFFF) // 16
            for k in range(n):
                if vend - n + k < 64:
                    slots[vend - n + k] = base + k
        elif op in (0x05, 0x06, 0x07):
            def tri(w, shifts=(16, 8, 0)):
                return tuple(slots[((w >> s) & 0xFF) // 2] for s in shifts)
            if op == 0x05:
                tris.append(tri(w0))
            elif op == 0x06:
                tris += [tri(w0), tri(w1)]
            else:
                a, b, c = tri(w0)
                a2, b2, c2 = tri(w1)
                tris += [(a, b, c), (a2, b2, c2)]
        elif op == 0xDF:
            break
        off += 8
    return tris


def to_obj(data: bytes) -> str:
    m = parse(data)
    out = [f"# n3o {m['nparts']} parts"]
    for x, y, z, *_ in vertices(data, m):
        out.append(f"v {x} {y} {z}")
    for p in m["parts"]:
        out.append(f"g {p['name']}")
        for t in triangles(data, p, m):
            if None not in t:
                out.append("f " + " ".join(str(i + 1) for i in t))
    return "\n".join(out) + "\n"
