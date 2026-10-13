"""Mega Drive / Genesis art codecs shared by the 2D Sega readers (one implementation each; titles import from here).

  Nemesis      nemesis_decompress / nemesis_compress      tile art in Sonic 1/2 (PLC lists), S3K title/HUD art
  Kosinski     kosinski_decompress / kosinski_compress    level blocks/chunks in Sonic 1/2/3K, S3K misc art
  4bpp tiles   tiles_to_indices                           8x8 VDP tiles (32 bytes, row-major, high nybble first)
  palettes     md_color / palette_rgba                    VDP colour words 0000BBB0GGG0RRR0 -> RGBA

Formats follow the Sonic Retro wiki (Nemesis/Kosinski compression pages) and the routines in the sonicretro
s1disasm / s2disasm / skdisasm sources (NemDec, KosDec). The encoders exist so tests can round-trip synthetic data;
they emit valid streams the games' own decoders accept, not the original compressor's byte-exact output.
"""
from __future__ import annotations

import struct
from collections import Counter

import numpy as np


class CodecError(ValueError):
    pass


# ------------------------------------------------------------------------------------------------ Nemesis

class _Bits:
    """MSB-first bit reader."""
    def __init__(self, d: bytes, pos: int):
        self.d, self.pos, self.buf, self.n = d, pos, 0, 0

    def bit(self) -> int:
        if self.n == 0:
            if self.pos >= len(self.d):
                raise CodecError("Nemesis stream ends early")
            self.buf, self.n = self.d[self.pos], 8
            self.pos += 1
        self.n -= 1
        return (self.buf >> self.n) & 1

    def bits(self, k: int) -> int:
        v = 0
        for _ in range(k):
            v = (v << 1) | self.bit()
        return v


def nemesis_decompress(d: bytes, pos: int = 0, with_end: bool = False):
    """Decode a Nemesis stream at ``pos``: the 4bpp tile bytes (``tiles * 32``). ``with_end`` also returns the offset
    just past the stream (rounded to the byte the decoder stopped in)."""
    if pos + 2 > len(d):
        raise CodecError("no Nemesis header")
    head = struct.unpack_from(">H", d, pos)[0]
    xor, tiles = bool(head & 0x8000), head & 0x7FFF
    if tiles == 0 or tiles > 0x800:
        raise CodecError(f"implausible Nemesis tile count {tiles}")
    p = pos + 2
    table: dict[tuple[int, int], tuple[int, int]] = {}
    nyb = 0
    while True:
        if p >= len(d):
            raise CodecError("Nemesis code table runs off the data")
        b = d[p]
        p += 1
        if b == 0xFF:
            break
        if b & 0x80:
            nyb = b & 0x0F
            continue
        if p >= len(d):
            raise CodecError("Nemesis code table runs off the data")
        run, length, code = ((b >> 4) & 7) + 1, b & 0x0F, d[p]
        p += 1
        if not 1 <= length <= 8:
            raise CodecError(f"Nemesis code length {length}")
        table[(length, code)] = (nyb, run)
    br = _Bits(d, p)
    rows_needed = tiles * 8
    out = bytearray()
    row, filled, prev = 0, 0, 0
    while len(out) < rows_needed * 4:
        code, length = 0, 0
        while True:
            code = (code << 1) | br.bit()
            length += 1
            if (length, code) in table:
                nyb, run = table[(length, code)]
                break
            if length == 6 and code == 0x3F:
                v = br.bits(7)
                run, nyb = ((v >> 4) & 7) + 1, v & 0xF
                break
            if length >= 8:
                raise CodecError(f"bad Nemesis code at byte {br.pos}")
        for _ in range(run):
            row = (row << 4) | nyb
            filled += 1
            if filled == 8:
                if xor:
                    row ^= prev
                    prev = row
                out += struct.pack(">I", row)
                row, filled = 0, 0
                if len(out) >= rows_needed * 4:
                    break
    out = bytes(out[:rows_needed * 4])
    return (out, br.pos) if with_end else out


def nemesis_compress(tiles: bytes, xor: bool = False) -> bytes:
    """A valid Nemesis stream for ``tiles`` (a multiple of 32 bytes): the most frequent (nybble, run) pairs get 8-bit
    codes (never starting 111111, the inline escape), the rest are written inline."""
    if not tiles or len(tiles) % 32:
        raise CodecError("Nemesis input must be whole 8x8 tiles")
    rows = list(struct.unpack(f">{len(tiles) // 4}I", tiles))
    if xor:
        rows = [r ^ (rows[i - 1] if i else 0) for i, r in enumerate(rows)]
    syms: list[tuple[int, int]] = []
    for r in rows:
        nybs = [(r >> (28 - 4 * k)) & 0xF for k in range(8)]
        k = 0
        while k < 8:
            n = 1
            while k + n < 8 and nybs[k + n] == nybs[k] and n < 8:
                n += 1
            syms.append((nybs[k], n))
            k += n
    common = [s for s, _ in Counter(syms).most_common(0xFC)]
    codes = {s: i for i, s in enumerate(common)}              # 8-bit codes 0x00..0xFB
    out = bytearray(struct.pack(">H", (0x8000 if xor else 0) | (len(tiles) // 32)))
    for nyb in range(16):
        mine = [s for s in common if s[0] == nyb]
        if not mine:
            continue
        out.append(0x80 | nyb)
        for s in mine:
            out += bytes([((s[1] - 1) << 4) | 8, codes[s]])
    out.append(0xFF)
    acc, n = 0, 0
    for s in syms:
        if s in codes:
            acc, n = (acc << 8) | codes[s], n + 8
        else:
            acc, n = (acc << 13) | (0x3F << 7) | ((s[1] - 1) << 4) | s[0], n + 13
        while n >= 8:
            out.append((acc >> (n - 8)) & 0xFF)
            n -= 8
            acc &= (1 << n) - 1
    if n:
        out.append((acc << (8 - n)) & 0xFF)
    return bytes(out)


# ------------------------------------------------------------------------------------------------ Kosinski

def kosinski_decompress(d: bytes, pos: int = 0, with_end: bool = False):
    """Decode a Kosinski stream (16-bit little-endian description fields, read LSB first and reloaded as soon as the
    16th bit is taken, exactly as KosDec does)."""
    p = pos
    out = bytearray()

    def u8():
        nonlocal p
        if p >= len(d):
            raise CodecError("Kosinski stream ends early")
        v = d[p]
        p += 1
        return v

    desc, left = 0, 0

    def load():
        nonlocal desc, left
        desc, left = u8() | (u8() << 8), 16

    load()

    def bit():
        nonlocal desc, left
        b = desc & 1
        desc >>= 1
        left -= 1
        if left == 0:
            load()
        return b

    while True:
        if bit():
            out.append(u8())
            continue
        if bit():
            lo, hi = u8(), u8()
            off = (0xFFFFE000 | ((hi & 0xF8) << 5) | lo) - (1 << 32)
            cnt = hi & 7
            if cnt:
                cnt += 2
            else:
                c = u8()
                if c == 0:
                    break
                if c == 1:
                    continue
                cnt = c + 1
        else:
            cnt = ((bit() << 1) | bit()) + 2
            off = u8() - 0x100
        if -off > len(out):
            raise CodecError(f"Kosinski copy before the start of the output (offset {off})")
        for _ in range(cnt):
            out.append(out[off])
    return (bytes(out), p) if with_end else bytes(out)


def kosinski_compress(data: bytes) -> bytes:
    """A valid Kosinski stream: greedy matches (inline <= 5 bytes within 256, full form up to 256 bytes within 8 KiB),
    literals otherwise."""
    blocks = bytearray()
    bits: list[int] = []
    pend = bytearray()

    def put_bit(b):
        nonlocal pend
        bits.append(b)
        if len(bits) == 16:
            v = sum(x << i for i, x in enumerate(bits))
            blocks.extend(struct.pack("<H", v))
            blocks.extend(pend)
            bits.clear()
            pend = bytearray()

    # The decoder reads a description field first, then data bytes; a field is reloaded right after its 16th bit, so
    # the bytes of a command go after the field that was current when its last bit was taken.
    def put_bytes(bs):
        pend.extend(bs)

    i, n = 0, len(data)
    while i < n:
        best_len, best_off = 0, 0
        lo = max(0, i - 0x2000)
        maxlen = min(256, n - i)
        for j in range(i - 1, lo - 1, -1):
            k = 0
            while k < maxlen and data[j + k] == data[i + k]:
                k += 1
            if k > best_len:
                best_len, best_off = k, i - j
                if k == maxlen:
                    break
        if best_len >= 2 and best_off <= 256 and best_len <= 5:
            put_bit(0), put_bit(0)
            c = best_len - 2
            put_bit((c >> 1) & 1), put_bit(c & 1)
            put_bytes([(0x100 - best_off) & 0xFF])
            i += best_len
        elif best_len >= 3:
            off = (-best_off) & 0x1FFF
            put_bit(0), put_bit(1)
            if best_len <= 9:
                put_bytes([off & 0xFF, ((off >> 5) & 0xF8) | (best_len - 2)])
            else:
                put_bytes([off & 0xFF, (off >> 5) & 0xF8, best_len - 1])
            i += best_len
        else:
            put_bit(1)
            put_bytes([data[i]])
            i += 1
    put_bit(0), put_bit(1)
    put_bytes([0x00, 0xF0, 0x00])
    v = sum(x << k for k, x in enumerate(bits))
    blocks.extend(struct.pack("<H", v))
    blocks.extend(pend)
    return bytes(blocks)


# ------------------------------------------------------------------------------------------------ tiles / palettes

def tiles_to_indices(art: bytes) -> np.ndarray:
    """4bpp 8x8 VDP tiles -> uint8 array (tiles, 8, 8) of palette indices."""
    a = np.frombuffer(bytes(art[:len(art) // 32 * 32]), np.uint8)
    hi, lo = a >> 4, a & 0xF
    return np.stack([hi, lo], axis=-1).reshape(-1, 8, 8)


def md_color(word: int) -> tuple[int, int, int]:
    """One VDP colour word 0000BBB0GGG0RRR0 -> 8-bit RGB (levels 0..7 scaled linearly to 0..255)."""
    r, g, b = (word >> 1) & 7, (word >> 5) & 7, (word >> 9) & 7
    return tuple(int(round(v * 255 / 7)) for v in (r, g, b))


def palette_rgba(words: list[int] | bytes) -> np.ndarray:
    """Colour words (or their big-endian bytes) -> (n, 4) uint8 RGBA; index 0 of every 16-colour line is clear."""
    if isinstance(words, (bytes, bytearray)):
        words = list(struct.unpack(f">{len(words) // 2}H", bytes(words[:len(words) // 2 * 2])))
    out = np.zeros((len(words), 4), np.uint8)
    for i, w in enumerate(words):
        out[i, :3] = md_color(w)
        out[i, 3] = 0 if i % 16 == 0 else 255
    return out
