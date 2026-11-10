"""CP9: sweep the composition variants (permute direction, order, keystream offset) x seeds."""
import itertools
import struct
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")
from gbox import pso_memcard as M  # noqa: E402

CARD = r"D:\gBox\runtime\dolphin\Dolphin-x64\User\GC\MemoryCardA.USA.raw"
M32 = 0xFFFFFFFF


def ring_step(st):
    for k in range(1, 25):
        st[k + 1] = (st[k + 1] - st[k + 0x20]) & M32
    for k in range(25, 56):
        st[k + 1] = (st[k + 1] - st[k - 0x17]) & M32


def seed_ring(seed, prefill_variant=0):
    st = [0] * 58
    st[0x38] = st[0x39] = seed & M32
    a, s = 1, seed & M32
    for i in range(0x36):
        idx = (0x15 * i) % 0x37
        st[idx + 1] = a
        a, s = (s - a) & M32, a
    for _ in range(4):
        ring_step(st)
    st[0] = 0x37
    return st


def next_key(st, offset=1):
    cur = st[0]
    st[0] = cur + 1
    if st[0] > 0x37:
        ring_step(st)
        st[0] = 1
    return st[st[0] + offset]


def build_perm(st, inverse=False):
    A = list(range(256))
    B = [0] * 256
    for i in range(255, -1, -1):
        j = (((i + 1) & 0xFFFF) * (next_key(st) >> 16)) >> 16
        b = A[j]
        A[j] = A[i]
        B[b] = i
        A[i] = b
    if inverse:
        inv = [0] * 256
        for k, v in enumerate(B):
            inv[v] = k
        return inv
    return B


def permute(data, B):
    out = bytearray(data)
    for blk in range(len(data) // 256):
        base = blk * 256
        for j in range(256):
            out[base + B[j]] = data[base + j]
    return bytes(out)


def words(data, st, offset=1, sub=True):
    out = bytearray(data)
    for i in range(len(data) // 4):
        key = next_key(st, offset)
        v = struct.unpack_from("<I", data, 4 * i)[0]
        struct.pack_into("<I", out, 4 * i, (key - v) & M32 if sub else (key + v) & M32)
    return bytes(out)


def score(b):
    return b.count(0) / len(b), sum(1 for x in b if 32 <= x < 127) / len(b)


def main():
    card = M.read(CARD)
    e = next(x for x in M.saves(card) if x["name"] == "PSO_CHARACTER")
    data = card[e["first_block"] * M.BLOCK: e["first_block"] * M.BLOCK + e["bytes"]]
    body = data[0x40:]
    seeds = [0, 1, 2, 3, 0x12345678, 0xDEADBEEF, e["last_modified"], e["last_modified"] ^ M32]
    best = None
    for seed, inverse, order, offset, sub in itertools.product(seeds, (False, True), ("perm_first", "words_first"),
                                                               (1, 2), (True, False)):
        st = seed_ring(seed)
        B = build_perm(st, inverse)
        if order == "perm_first":
            out = words(permute(body, B), st, offset, sub)
        else:
            out = permute(words(body, st, offset, sub), B)
        z, p = score(out)
        sc = z + p
        if best is None or sc > best[0]:
            best = (sc, (hex(seed), inverse, order, offset, sub), z, p, out)
    print("best:", best[1], f"zeros {best[2]:.2f} printable {best[3]:.2f}")
    print("head:", best[4][:48].hex(" "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
