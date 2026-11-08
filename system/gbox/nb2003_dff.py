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

# Capacity sentinel: unused float-pool slots are 0xcdcdcdcd.
SENTINEL = struct.unpack("<f", bytes.fromhex("cdcdcdcd"))[0]  # -431602080.0


@dataclass
class Mesh:
    offset: int
    pool_count_hdr: int      # first word of 0x200f1/0x10035 blob
    pool_words: int          # float words after the 2-word blob header
    pool_off: int = 0        # byte offset of the float pool (after count+flag words)
    pool_end: int = 0        # byte offset where the pool ends (parent (0x401ffff,1) end)
    npool: int = 0           # strip index-space size
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
            # Explicit pool bounds: the blob leaf size is NOT the payload bound;
            # the float pool is [count][flag][floats] running to the parent
            # (0x401ffff,1) container end.  Validate the region before trusting it.
            pool_off = blob + 12 + 8          # skip the [count, flag] header words
            pool_end = cs + 12 + csz          # parent container end
            nwords = (pool_end - pool_off) // 4
            assert 0 <= pool_off <= pool_end <= len(data), \
                f"pool bounds out of range @ {mo:#x}: off={pool_off:#x} end={pool_end:#x}"
            assert nwords > 0, f"empty float pool @ {mo:#x}"
            assert cnt < 0x10000, f"implausible pool count {cnt} @ {mo:#x}"
            m = Mesh(mo, cnt, nwords, pool_off=pool_off, pool_end=pool_end,
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



@dataclass
class FloatRow:
    """One 17-word float-pool row: pos(3) + 4xvec3(12) + vec2(2).

    ``mask`` marks each word real (True) or 0xcdcdcdcd sentinel slot (False).
    """
    index: int
    words: tuple
    mask: tuple
    real_count: int

    @property
    def pos(self):
        return self.words[0:3]

    @property
    def unit_vecs(self):
        return [self.words[3 + 3 * t:3 + 3 * t + 3] for t in range(4)]

    @property
    def tail2(self):
        return self.words[15:17]


@dataclass
class FloatPool:
    """Stride-17 row decode of an owned NB2003 .dff float pool.

    Verified on nb2003_ape.dff mesh0 (3918 words, count hdr 225):
    rows 0..149 fully real; row 150 = 14 real with sentinel slots at
    words 13..15 (trailing word 0.0); row 151 =
    [0.0 0.0 S*15]; rows 152..229 all sentinel; 8-word all-sentinel tail.
    1352 sentinel words total.  Pools without capacity padding (ape.dff
    mesh4..7) decode with sentinel_words == 0.
    """
    stride: int
    rows: list
    tail: tuple
    n_full: int
    n_partial: int
    n_sentinel_rows: int
    sentinel_words: int
    real_words: int

    def full_rows(self):
        return [r for r in self.rows if r.real_count == self.stride]


def decode_float_pool(words, stride=17, sentinel=SENTINEL):
    """Decode a raw float-pool word list into stride-17 rows + tail.

    Every complete row carries a per-word real/sentinel mask; the ``n % stride``
    leftover words form the (all-sentinel on owned pools) tail.  No stride or
    capacity is assumed beyond ``stride``; row classes are derived from the
    sentinel mask.
    """
    n = len(words)
    rows = []
    for i in range(n // stride):
        r = tuple(words[i * stride:(i + 1) * stride])
        mask = tuple(w != sentinel for w in r)
        rows.append(FloatRow(i, r, mask, sum(mask)))
    cut = (n // stride) * stride
    tail = tuple(words[cut:])
    return FloatPool(
        stride,
        rows,
        tail,
        sum(1 for r in rows if r.real_count == stride),
        sum(1 for r in rows if 0 < r.real_count < stride),
        sum(1 for r in rows if r.real_count == 0),
        sum(stride - r.real_count for r in rows) + sum(1 for w in tail if w == sentinel),
        sum(r.real_count for r in rows) + sum(1 for w in tail if w != sentinel),
    )


if __name__ == "__main__":
    import sys
    for m in read_dff(open(sys.argv[1], "rb").read()):
        print(m.kind, hex(m.offset), m.pool_count_hdr, m.pool_words, m.npool,
              len(m.indices), max(m.indices, default=-1))
