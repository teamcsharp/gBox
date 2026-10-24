"""NFL Blitz 2003 (GameCube) ``.dff`` model container reader (read-only).

Chunk header = 3 x u32 LE ``[type][subtype][size]``; containers (size covers
children) are 4-byte aligned.  Leaf ``size`` is NOT a reliable payload bound
for vertex blobs (sub 0x200f1/0x10035): the pool runs to the end of the parent
(0x401ffff,1) container.  Triangle-strip chunk (0x401ffff, 0x50e) payload:
``[0x401ffff][1][3][ntri_field][npool][1][u32 idx ...]`` where ``npool`` is the
index-space size: every index < ``npool`` (this resolves the earlier
"maxidx > nverts" blocker; the 0x200f1 count is not the index-space size).
"""
from __future__ import annotations
import struct
from dataclasses import dataclass, field

MAGIC = 0x0401FFFF


@dataclass
class Mesh:
    offset: int
    pool_count_hdr: int      # first word of 0x200f1/0x10035 blob
    pool_words: int          # float words after the 2-word blob header
    npool: int               # strip index-space size
    indices: list = field(default_factory=list)
    kind: str = "pos"        # pos (0x200f1) or uv (0x10035)


def chunks(d: bytes, start: int, end: int):
    o = start
    while o + 12 <= end:
        t, s, sz = struct.unpack_from("<3I", d, o)
        yield o, t, s, sz
        o += 12 + ((sz + 3) & ~3)


def read_dff(data: bytes) -> list[Mesh]:
    meshes = []
    for o, t, s, sz in chunks(data, 8, len(data)):
        if (t, s) != (0, 0x1A):
            continue
        for mo, mt, ms, msz in chunks(data, o + 12, o + 12 + sz):
            if ms != 0x0F:
                continue
            end = mo + 12 + msz
            cs = mo + 12
            _, _, csz = struct.unpack_from("<3I", data, cs)  # (0x401ffff,1,size)
            blob = cs + 12
            _, bs, _ = struct.unpack_from("<3I", data, blob)
            cnt = struct.unpack_from("<I", data, blob + 12)[0]
            m = Mesh(mo, cnt, (csz - 12 - 8) // 4, 0,
                     kind="pos" if bs == 0x200F1 else "uv")
            for so, st, ss, ssz in chunks(data, mo + 12, end):
                for xo, xt, xs, xsz in ([(so, st, ss, ssz)] +
                                        list(chunks(data, so + 12, so + 12 + ssz)
                                             if st in (0, MAGIC) else [])):
                    if xs == 0x50E:
                        w = struct.unpack_from(f"<{xsz // 4}I", data, xo + 12)
                        m.npool = w[4]
                        m.indices = list(w[6:])
            meshes.append(m)
    return meshes


def strip_triangles(idx):
    """Triangles from a strip; repeated indices act as degenerate restarts."""
    out = []
    for i in range(len(idx) - 2):
        a, b, c = idx[i:i + 3]
        if a == b or b == c or a == c:
            continue
        out.append((a, c, b) if i & 1 else (a, b, c))
    return out


if __name__ == "__main__":
    import sys
    for m in read_dff(open(sys.argv[1], "rb").read()):
        print(m.kind, hex(m.offset), m.pool_count_hdr, m.pool_words, m.npool,
              len(m.indices), max(m.indices, default=-1))
