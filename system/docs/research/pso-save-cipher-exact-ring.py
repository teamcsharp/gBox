"""CP9: the cipher transcribed from the assembly (round 55)."""
import struct
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp\main-repo\system")
from gbox import pso_memcard as M  # noqa: E402

CARD = r"D:\gBox\runtime\dolphin\Dolphin-x64\User\GC\MemoryCardA.USA.raw"
M32 = 0xFFFFFFFF


def step(state):
    """FUN_8007c438, from the assembly: 24x state[k+1] -= state[k+0x20] (k=1..24), then 31x state[k+1] -= state[k-0x17] (k=25..55)."""
    for k in range(1, 25):
        state[k + 1] = (state[k + 1] - state[k + 0x20]) & M32
    for k in range(25, 56):
        state[k + 1] = (state[k + 1] - state[k - 0x17]) & M32


def seed_ring(seed):
    """FUN_8007c48c, from the assembly: fill state[(21k mod 55)+1] = a_k, with a_{k+1} = s_k - a_k, s_{k+1} = a_k."""
    st = [0] * 58
    st[0x38] = seed & M32
    st[0x39] = seed & M32
    a, s = 1, seed & M32
    for i in range(0x36):
        idx = (0x15 * i) % 0x37
        st[idx + 1] = a
        a, s = (s - a) & M32, a
    for _ in range(4):
        step(st)
    st[0] = 0x37
    return st


def key_words(state, count):
    out = []
    for _ in range(count):
        cur = state[0]
        state[0] = cur + 1
        if state[0] > 0x37:
            step(state)
            state[0] = 1
        out.append(state[state[0] + 1])
    return out


def decode(data, seed):
    n = len(data) // 4
    keys = key_words(seed_ring(seed), n)
    out = bytearray(data[:4 * n])
    for i, key in enumerate(keys):
        v = struct.unpack_from("<I", data, 4 * i)[0]
        struct.pack_into("<I", out, 4 * i, (key - v) & M32)
    return bytes(out)


def score(b):
    return b.count(0) / len(b), sum(1 for x in b if 32 <= x < 127) / len(b)


def main():
    card = M.read(CARD)
    e = next(x for x in M.saves(card) if x["name"] == "PSO_CHARACTER")
    data = card[e["first_block"] * M.BLOCK: e["first_block"] * M.BLOCK + e["bytes"]]
    body = bytes(data[0x40:])
    print("entry time:", hex(e["last_modified"]))
    for name, seed in (("0", 0), ("1", 1), ("time", e["last_modified"]),
                       ("time^hdr", e["last_modified"] ^ M32)):
        out = decode(body, seed)
        z, p = score(out)
        print(f"  seed {name:9s} zeros {z:.2f} printable {p:.2f}  head {out[:16].hex(' ')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
