"""WWF War Zone (USA, NWWE) N64 -- ROM pack directory + Rob Northen (RNC1) unpacker.

Evidence (decompressed main image, base 0x8003C400, see gbox.warzone_boot):
  * 0x80042288 resolves a type-7/pack index N (1-based) via the 16-byte table at
    0x8010B390: {u32 off, u32 unpacked_size, u32 packed_size, u32 flags};
    cart address = 0xB000DDE0 + off  ->  ROM offset 0xDDE0 + off.
  * A packed entry starts with b"RNC\\x01" (ProPack method 1); raw entries have
    packed_size == unpacked_size and flags 0.
  * 0x8004237C is a binary search over 36-byte file records keyed by name
    (name hash = byte sum, 0x80042328); 0x8004286C reads rec+0x1C (u32) and the
    pack-entry word. The per-file record table is filled at runtime; its
    layout beyond what is stated here is a hypothesis.
"""
from __future__ import annotations

import struct

PACK_TABLE_VADDR = 0x8010B390
PACK_ROM_BASE = 0xDDE0
IMAGE_BASE = 0x8003C400


def parse_pack_table(image: bytes, count: int = 64, base: int = IMAGE_BASE) -> list[dict]:
    t = PACK_TABLE_VADDR - base
    out = []
    for i in range(count):
        off, usz, psz, flags = struct.unpack_from(">4I", image, t + 16 * i)
        out.append({"index": i + 1, "off": off, "rom": PACK_ROM_BASE + off,
                    "unpacked": usz, "packed": psz, "flags": flags})
    return out


def entry_bytes(rom: bytes, e: dict) -> bytes:
    # table "packed" size includes the 18-byte RNC header
    return rom[e["rom"]:e["rom"] + e["packed"]]


def crc16(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


class _Bits:
    def __init__(self, data: bytes, p: int):
        self.d, self.p, self.buf, self.cnt = data, p, 0, 0

    def bits(self, n: int) -> int:
        while self.cnt < n:
            w = self.d[self.p] | (self.d[self.p + 1] << 8) if self.p + 1 < len(self.d) else 0
            self.p += 2
            self.buf |= w << self.cnt
            self.cnt += 16
        v = self.buf & ((1 << n) - 1)
        self.buf >>= n
        self.cnt -= n
        return v

    def lit(self, n: int) -> bytes:
        # literals live in the byte stream right after the words already loaded;
        # drop buffered whole-word remainder semantics: buffer keeps <16 bits.
        s = self.d[self.p:self.p + n]
        self.p += n
        return s


def _table(br: _Bits):
    n = br.bits(5)
    lens = [br.bits(4) for _ in range(n)]
    codes = {}
    val = 0
    for l in range(1, 17):
        for sym, sl in enumerate(lens):
            if sl == l:
                codes[(l, val)] = sym
                val += 1
        val <<= 1
    return codes


def _dec(br: _Bits, codes) -> int:
    code = 0
    for l in range(1, 17):
        code = (code << 1) | br.bits(1)
        if (l, code) in codes:
            v = codes[(l, code)]
            break
    else:
        raise ValueError("bad huffman code")
    if v >= 2:
        e = v - 1
        v = (1 << e) | br.bits(e)
    return v


def rnc1_unpack(blob: bytes) -> bytes:
    if blob[:4] != b"RNC\x01":
        raise ValueError("not RNC1")
    usz, psz, ucrc, pcrc = struct.unpack_from(">IIHH", blob, 4)
    body = blob[:18 + psz]  # header psz excludes the 18-byte header
    br = _Bits(body, 18)
    br.bits(2)
    out = bytearray()
    while len(out) < usz:
        raw, dist, ln = _table(br), _table(br), _table(br)
        count = br.bits(16)
        while True:
            n = _dec(br, raw)
            if n:
                out += _lit(br, n)
            count -= 1
            if count <= 0:
                break
            d = _dec(br, dist) + 1
            m = _dec(br, ln) + 2
            for _ in range(m):
                out.append(out[-d])
    return bytes(out[:usz])


def _lit(br: _Bits, n: int) -> bytes:
    # whole 16-bit words already buffered are rewound so literals start at the
    # logical byte position (tested against the header CRC).
    back = br.cnt // 16
    br.p -= 2 * back
    br.buf &= (1 << (br.cnt % 16)) - 1
    br.cnt %= 16
    return br.lit(n)
