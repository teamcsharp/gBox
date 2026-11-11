"""EA/GCMP 'LZH1' (TERF COMP codec 5) decoder for Madden NFL 2005 GameCube.

Derived from main.dol (PPC-BE) functions: block loop 0x804a4970, MSB-first bit
reader 0x804a56c8, table readers 0x804a659c/0x6650/0x66f0 and the length/distance
tables at 0x804f1590..0x804f1623. Deflate-like: per block 1 flag bit
(1 = end of stream, followed by a 32-bit word; 0 = block), then 285 literal/length
code lengths and 30 distance code lengths (4 bits each, canonical Huffman,
MSB-first), then symbols until 0x100. 32 KiB window.
"""
from __future__ import annotations

LEN_XB = [0] * 8 + [1] * 4 + [2] * 4 + [3] * 4 + [4] * 4 + [5] * 3 + [0]
LEN_BASE = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51,
            59, 67, 83, 99, 115, 131, 163, 195, 227]
DIST_XB = [0, 0, 0, 0] + [x for k in range(1, 14) for x in (k, k)]
DIST_BASE = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385,
             513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577]
N_LIT, N_DIST = 285, 30


class _Bits:
    def __init__(self, data):
        self.d = data
        self.pos = 0  # bit position

    def get(self, n):
        v = 0
        for _ in range(n):
            byte = self.d[self.pos >> 3] if (self.pos >> 3) < len(self.d) else 0
            v = (v << 1) | ((byte >> (7 - (self.pos & 7))) & 1)
            self.pos += 1
        return v


def _build(lengths):
    count = [0] * 16
    for l in lengths:
        count[l] += 1
    count[0] = 0
    nxt, code = [0] * 17, 0
    for i in range(1, 16):
        code = (code + count[i - 1]) << 1
        nxt[i] = code
    table = {}
    for sym, l in enumerate(lengths):
        if l:
            table[(l, nxt[l])] = sym
            nxt[l] += 1
    return table


def _sym(bits, table):
    code = 0
    for l in range(1, 16):
        code = (code << 1) | bits.get(1)
        s = table.get((l, code))
        if s is not None:
            return s
    raise ValueError("bad huffman code")


def decode(data: bytes, expected_size: int | None = None) -> bytes:
    b = _Bits(data)
    out = bytearray()
    while True:
        if b.get(1):
            b.get(32)
            break
        lit = _build([b.get(4) for _ in range(N_LIT)])
        dst = _build([b.get(4) for _ in range(N_DIST)])
        while True:
            s = _sym(b, lit)
            if s < 256:
                out.append(s)
            elif s == 256:
                break
            else:
                c = s - 0x101
                if c <= 7:
                    ln = c + 3
                elif LEN_XB[c]:
                    ln = LEN_BASE[c] + b.get(LEN_XB[c])
                else:
                    ln = 227
                d = _sym(b, dst)
                dist = d + 1 if d <= 3 else DIST_BASE[d] + b.get(DIST_XB[d])
                if dist > len(out):
                    raise ValueError("distance before start")
                for _ in range(ln):
                    out.append(out[-dist])
            if expected_size is not None and len(out) > expected_size:
                raise ValueError("overrun")
    if expected_size is not None and len(out) != expected_size:
        raise ValueError(f"size {len(out)} != {expected_size}")
    return bytes(out)
