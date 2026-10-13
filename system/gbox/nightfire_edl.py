"""007 - Nightfire (USA) GameCube (GO7E69) -- Eurocom EDL decompressor, reconstructed from Nightfire.elf.

Nightfire.elf (sha256 ef49ce2bd8e8845309316e9426fc171ec0eecf25815b52808a1b746f16d83367, stripped PowerPC
Gekko, .text 0x800072e0) handles the 31 level databases gc/0700xxxx.bin with this small EDL module:

  0x80067c24  EDL_ParseHeader(ctx)   checks 'E','D','L' byte by byte, ctx+0x18 = flag>>7 (file is big-endian),
                                     ctx+0x10 = flag&0x7F (method 0..2, else error -4), ctx+8/+0xC = the
                                     packed/unpacked u32 at +4/+8, byte-swapped by 0x80067cdc when the file
                                     endian differs from the host (ctx+0x14); bad magic sets ctx+0x1C = -3.
  0x80067d14  EDL_UnpackedSize(src)  0x80067d58  EDL_PackedSize(src)
  0x80067d9c  EDL_Decompress(src, dst) -> 0x80067ba4 dispatch on ctx+0x10:
      method 0 -> 0x8006685c  stored copy of `unpacked` bytes from src+0xC (memmove, overlap-safe)
      method 1 -> 0x800668e4  Huffman + LZ77 (every file on this disc: flag 0x81)
      method 2 -> 0x80067300  a second LZ variant (unused on this disc; not implemented here)
  The level loader 0x8005c7a8 also calls EDL_ParseHeader; the file names come from 0x80044780
  ("%s%8.8x.bin" with "gc/", 0x801a5730).

Method 1 (0x800668e4) reads the payload from src+0xC as big-endian u32 words consumed LSB-first (the
"LE timestamp" in the inventory is really the first bit-buffer word).  It is a deflate relative with its own
block header:

  repeat:
    bit                       0 = stored: 15-bit count, then count x 8-bit literal bytes
                              1 = Huffman block:
      litlen table, then distance table, each: 9-bit symbol count n (n == 0 keeps the previous table), then
        per symbol: 1 bit; if 1 a new 4-bit code length follows, else the previous length repeats (the
        running length starts at 0 once per file and carries across tables and blocks)
      canonical Huffman codes (deflate order: by length, then symbol), stored bit-reversed; the game builds
      an 8-bit (distance, 0x802809f8) and a 10-bit (litlen, 0x8027fdf8) fast table with sub-tables
      symbols: <256 literal, 256 end of block, 257+ length code i = sym-257:
        length = LEN_BASE[i] + bits(LEN_EXTRA[i]) + 3          (tables 0x801e98a8 / 0x801e98c8)
        distance code d: dist = DIST_BASE[d] + bits(DIST_EXTRA[d]); copy from out[-dist-1]
                                                              (tables 0x801e98e6 u16 / 0x801e9924 s8)
    bit                       0 = another block follows, 1 = end of stream
  The game sets ctx+0x1C = -8 when a code is longer than fast-bits+7 and -9 when sub-tables exceed 0x1FF.

The four static tables are the deflate ones (bases minus 3 / minus 1); `elf_tables` re-reads them from
the executable so a test can pin them against the owned build.
"""
from __future__ import annotations

import struct

EXE_SHA256 = "ef49ce2bd8e8845309316e9426fc171ec0eecf25815b52808a1b746f16d83367"
FUNCS = {
    "EDL_ParseHeader": 0x80067C24, "EDL_Swap32": 0x80067CDC, "EDL_UnpackedSize": 0x80067D14,
    "EDL_PackedSize": 0x80067D58, "EDL_Decompress": 0x80067D9C, "EDL_Dispatch": 0x80067BA4,
    "EDL_Method0": 0x8006685C, "EDL_Method1": 0x800668E4, "EDL_Method2": 0x80067300,
    "LevelLoader_EDL_call": 0x8005C7A8, "HT_FileName": 0x80044780,
}
TABLE_VAS = {"len_base": (0x801E98A8, "29B"), "len_extra": (0x801E98C8, "29B"),
             "dist_base": (0x801E98E6, ">30H"), "dist_extra": (0x801E9924, "30b")}
LEN_BASE = (0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 14, 16, 20, 24, 28, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160,
            192, 224, 255)
LEN_EXTRA = (0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0)
DIST_BASE = (0, 1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256, 384, 512, 768, 1024, 1536, 2048,
             3072, 4096, 6144, 8192, 12288, 16384, 24576)
DIST_EXTRA = (0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13)


class EDLError(ValueError):
    pass


def header(data: bytes) -> dict:
    """EDL_ParseHeader: magic, flag (bit 7 = big-endian file, low 7 bits = method), packed/unpacked size."""
    if len(data) < 12 or data[:3] != b"EDL":
        raise EDLError("bad EDL magic (game error -3)")
    flag = data[3]
    method, big = flag & 0x7F, flag >> 7
    if method > 2:
        raise EDLError(f"EDL method {method} (game error -4)")
    size, unpacked = struct.unpack_from(">II" if big else "<II", data, 4)
    return {"flag": flag, "method": method, "big_endian": bool(big), "size": size, "unpacked": unpacked}


def elf_tables(elf: bytes) -> dict:
    """Read the four method-1 code tables from Nightfire.elf by virtual address (PROGBITS sections)."""
    shoff = struct.unpack_from(">I", elf, 0x20)[0]
    shentsize, shnum = struct.unpack_from(">HH", elf, 0x2E)
    secs = [struct.unpack_from(">10I", elf, shoff + i * shentsize) for i in range(shnum)]
    out = {}
    for key, (va, fmt) in TABLE_VAS.items():
        s = next(s for s in secs if s[1] == 1 and s[3] <= va < s[3] + s[5])
        out[key] = struct.unpack_from(fmt, elf, s[4] + va - s[3])
    return out


class _Bits:
    """LSB-first reader over big-endian u32 words (the game's r4/r26/r30 bit buffer)."""
    __slots__ = ("words", "pos", "buf", "n")

    def __init__(self, data: bytes, start: int):
        body = data[start:]
        body += b"\0" * (-len(body) % 4 + 8)
        self.words = struct.unpack(f">{len(body) // 4}I", body)
        self.pos, self.buf, self.n = 0, 0, 0

    def _fill(self, need: int):
        while self.n < need:
            self.buf |= self.words[self.pos] << self.n
            self.pos += 1
            self.n += 32

    def get(self, k: int) -> int:
        if self.n < k:
            self._fill(k)
        v = self.buf & ((1 << k) - 1)
        self.buf >>= k
        self.n -= k
        return v

    def huff(self, table: tuple) -> int:
        fast, maxlen = table
        if self.n < maxlen:
            self._fill(maxlen)
        e = fast[self.buf & ((1 << maxlen) - 1)]
        if e < 0:
            raise EDLError("invalid Huffman code")
        k = e & 0xF
        self.buf >>= k
        self.n -= k
        return e >> 4


def _build(lengths: list[int]) -> tuple:
    """Canonical Huffman (deflate order), bit-reversed codes -> flat lookup of (sym << 4 | len)."""
    count = [0] * 16
    for L in lengths:
        count[L] += 1
    count[0] = 0
    maxlen = max((L for L in range(16) if count[L]), default=0)
    if maxlen == 0:
        return ((-1,), 0)
    fast = [-1] * (1 << maxlen)
    code = 0
    for L in range(1, maxlen + 1):
        for sym, sl in enumerate(lengths):
            if sl != L:
                continue
            rev = int(f"{code:0{L}b}"[::-1], 2)
            for hi in range(0, 1 << maxlen, 1 << L):
                fast[rev | hi] = sym << 4 | L
            code += 1
        code <<= 1
    return (tuple(fast), maxlen)


def decompress_method1(data: bytes, unpacked: int, start: int = 0xC) -> bytes:
    bits = _Bits(data, start)
    out = bytearray()
    run_len = 0
    lit = dist = None
    while True:
        if bits.get(1) == 0:
            for _ in range(bits.get(15)):
                out.append(bits.get(8))
        else:
            for which in ("lit", "dist"):
                n = bits.get(9)
                if n == 0:
                    continue
                lengths = []
                for _ in range(n):
                    if bits.get(1):
                        run_len = bits.get(4)
                    lengths.append(run_len)
                if which == "lit":
                    lit = _build(lengths)
                else:
                    dist = _build(lengths)
            if lit is None or dist is None:
                raise EDLError("Huffman block without tables")
            while True:
                sym = bits.huff(lit)
                if sym < 256:
                    out.append(sym)
                    continue
                if sym == 256:
                    break
                i = sym - 257
                if i >= len(LEN_BASE):
                    raise EDLError(f"length symbol {sym}")
                length = LEN_BASE[i] + (bits.get(LEN_EXTRA[i]) if LEN_EXTRA[i] else 0) + 3
                d = bits.huff(dist)
                if d >= len(DIST_BASE):
                    raise EDLError(f"distance symbol {d}")
                back = DIST_BASE[d] + (bits.get(DIST_EXTRA[d]) if DIST_EXTRA[d] else 0) + 1
                if back > len(out):
                    raise EDLError(f"distance {back} before start of output ({len(out)})")
                p = len(out) - back
                if back >= length:
                    out += out[p:p + length]
                else:
                    for k in range(length):
                        out.append(out[p + k])
        if len(out) > unpacked:
            raise EDLError(f"output {len(out)} exceeds unpacked size {unpacked}")
        if bits.get(1):
            break
    return bytes(out)


def decompress(data: bytes) -> bytes:
    """EDL_Decompress for methods 0 and 1; the result must match the header's unpacked size exactly."""
    h = header(data)
    if h["size"] != len(data):
        raise EDLError(f"EDL size field {h['size']} != file size {len(data)}")
    if h["method"] == 0:
        out = bytes(data[0xC:0xC + h["unpacked"]])
    elif h["method"] == 1:
        out = decompress_method1(data, h["unpacked"])
    else:
        raise NotImplementedError("EDL method 2 (0x80067300) is not used on GO7E69")
    if len(out) != h["unpacked"]:
        raise EDLError(f"decoded {len(out)} bytes, header says {h['unpacked']}")
    return out


def main(argv=None) -> int:
    import argparse
    import hashlib
    import json
    from pathlib import Path

    ap = argparse.ArgumentParser(description="Decompress Nightfire GC EDL files and check the unpacked size")
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, help="directory for decompressed .unpacked files")
    a = ap.parse_args(argv)
    rows, bad = [], 0
    for f in a.files:
        data = f.read_bytes()
        row = {"file": f.name, "sha256": hashlib.sha256(data).hexdigest(), **header(data)}
        try:
            out = decompress(data)
            row.update(ok=True, out_sha256=hashlib.sha256(out).hexdigest(), head=out[:16].hex())
            if a.out:
                a.out.mkdir(parents=True, exist_ok=True)
                (a.out / (f.stem + ".unpacked")).write_bytes(out)
        except (EDLError, NotImplementedError) as e:
            row.update(ok=False, error=str(e))
            bad += 1
        rows.append(row)
        print(json.dumps(row), flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
