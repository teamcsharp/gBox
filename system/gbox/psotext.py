"""Phantasy Star Online text archives (.pr2 + .pr3): PSO v2 stream cipher -> PRS -> pointer tables of strings.
Used for item names (the item sidebar), area names, etc. PR2 = u32 size, u32 key, then cipher(PRS(data))."""
import struct

from .ninja import prs_decompress


class PSOV2Cipher:
    """PSO PC/DC v2 stream cipher (the public 'CRYPT_PC' algorithm): 57-word lagged-subtract generator."""
    def __init__(self, seed: int):
        k = [0] * 57
        esi, ebx, edi = 1, seed & 0xFFFFFFFF, 0x15
        k[56] = k[55] = ebx
        while edi <= 0x46E:
            edx = edi % 55
            ebx = (ebx - esi) & 0xFFFFFFFF
            edi += 0x15
            k[edx] = esi
            esi, ebx = ebx, k[edx]
        self.k = k
        for _ in range(4):
            self._mix()
        self.pos = 56

    def _mix(self):
        k = self.k
        for i in range(1, 0x19):
            k[i] = (k[i] - k[i + 0x1F]) & 0xFFFFFFFF
        for i in range(0x19, 0x38):
            k[i] = (k[i] - k[i - 0x18]) & 0xFFFFFFFF

    def next(self) -> int:
        if self.pos == 56:
            self._mix()
            self.pos = 1
        v = self.k[self.pos]
        self.pos += 1
        return v

    def crypt(self, data: bytes, endian: str = "<") -> bytes:
        data = data + b"\0" * (-len(data) % 4)
        n = len(data) // 4
        words = struct.unpack(f"{endian}{n}I", data)
        return struct.pack(f"{endian}{n}I", *(w ^ self.next() for w in words))


def pr2_decode(pr2: bytes, endian: str = "<") -> bytes:
    size, key = struct.unpack_from(f"{endian}II", pr2, 0)
    return prs_decompress(PSOV2Cipher(key).crypt(pr2[8:], endian))[:size]


def collections(text: bytes, base_ptr: int = 0, endian: str = "<") -> list[list[str]]:
    """The decoded text file is a table of pointers to string tables (offsets relative to the file start)."""
    rd = lambda o: struct.unpack_from(f"{endian}I", text, o)[0]
    root = rd(len(text) - 16) if len(text) >= 16 else 0           # REL-style footer: pointer to the root table

    def s_at(o):
        e = text.find(b"\0", o)
        return text[o:e].decode("latin-1")
    out = []
    o = root
    while o + 4 <= len(text):
        p = rd(o)
        if not p or p >= len(text) or p <= root and False:
            break
        if p >= root:
            break
        out.append(p)
        o += 4
    cols = []
    for i, start in enumerate(out):
        end = out[i + 1] if i + 1 < len(out) else root
        strs = []
        for q in range(start, end, 4):
            sp = rd(q)
            strs.append(s_at(sp) if 0 < sp < len(text) else "")
        cols.append(strs)
    return cols
