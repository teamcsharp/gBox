"""CP9: the full save cipher, transcribed from assembly (round 56), plus a seed search.

Algorithm (all verified from decompiles/asm in docs/research/pso-save-cipher*.txt):
  seed_ring(seed):  state[0x38]=state[0x39]=seed; 54x {idx=(21k)%55; state[idx+1]=a; a=s-a; s=old a}; 4 ring rounds; cursor 0x37
  next_key(state):  cur=state[0]; state[0]=cur+1; if >0x37: ring_step; state[0]=1; return state[state[0]+1]
  ring_step:        24x state[k+1]-=state[k+0x20] (k=1..24); 31x state[k+1]-=state[k-0x17] (k=25..55)
  rand(state,n):    ((n & 0xffff) * (next_key() >> 16)) >> 16
  build_perm(state):A=0..255; for i in 255..0: j=rand(state,i+1); b=A[j]; A[j]=A[i]; B[b]=i; A[i]=b
  permute(src,dst): for each 256B block: dst[256k + B[j]] = src[256k + j]
  word_cipher(buf): buf[i] = key_i - buf[i]
"""
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


def seed_ring(seed):
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


def next_key(st):
    cur = st[0]
    st[0] = cur + 1
    if st[0] > 0x37:
        ring_step(st)
        st[0] = 1
    return st[st[0] + 1]


def build_perm(st):
    A = list(range(256))
    B = [0] * 256
    for i in range(255, -1, -1):
        j = (((i + 1) & 0xFFFF) * (next_key(st) >> 16)) >> 16
        b = A[j]
        A[j] = A[i]
        B[b] = i
        A[i] = b
    return B


def permute(src, B):
    out = bytearray(len(src))
    for blk in range(len(src) // 256):
        base = blk * 256
        for j in range(256):
            out[base + B[j]] = src[base + j]
    rest = len(src) - (len(src) // 256) * 256
    if rest:
        base = len(src) - rest
        out[base:] = src[base:]
    return bytes(out)


def word_cipher(data, st):
    n = len(data) // 4
    out = bytearray(data)
    for i in range(n):
        key = next_key(st)
        v = struct.unpack_from("<I", data, 4 * i)[0]
        struct.pack_into("<I", out, 4 * i, (key - v) & M32)
    return bytes(out)


def decode(data, seed):
    st = seed_ring(seed)
    B = build_perm(st)
    permuted = permute(data, B)
    return word_cipher(permuted, st)


def entropy_score(b):
    zeros = b.count(0) / len(b)
    printable = sum(1 for x in b if 32 <= x < 127) / len(b)
    return zeros + printable


def main():
    card = M.read(CARD)
    e = next(x for x in M.saves(card) if x["name"] == "PSO_CHARACTER")
    data = card[e["first_block"] * M.BLOCK: e["first_block"] * M.BLOCK + e["bytes"]]
    body = data[0x40:]
    seeds = [0, 1, 2, 0x12345678, 0xDEADBEEF, e["last_modified"], e["last_modified"] ^ M32]
    seeds += list(range(3, 32))
    best = None
    for seed in seeds:
        out = decode(body, seed)
        sc = entropy_score(out)
        if best is None or sc > best[0]:
            best = (sc, seed, out)
    print(f"best seed {best[1]:#x}: zeros {best[2].count(0)/len(best[2]):.2f} "
          f"printable {sum(1 for x in best[2] if 32 <= x < 127)/len(best[2]):.2f}")
    print("head:", best[2][:48].hex(" "))
    print("ascii:", "".join(chr(b) if 32 <= b < 127 else "." for b in best[2][:64]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
