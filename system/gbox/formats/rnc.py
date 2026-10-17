"""Rob Northen Compression (RNC ProPack) methods 1 and 2: header "RNC" + method byte, u32 BE unpacked size, u32 BE
packed size, u16 unpacked CRC-16 (0xA001), u16 packed CRC, then the bit stream from +18.

Moved verbatim from gbox.turok_inventory (Turok: Dinosaur Hunter / Turok 2, N64), which re-imports every name.
"""
from __future__ import annotations

import struct


def crc16(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc & 0xFFFF


class _Source:
    """Shared byte position for bit words and literal copies."""

    __slots__ = ("d", "pos", "end")

    def __init__(self, data: bytes, end: int | None = None):
        self.d = data
        self.pos = 0
        self.end = len(data) if end is None else min(end, len(data))

    def peek(self, off: int) -> int:
        at = self.pos + off
        return self.d[at] if at < self.end else 0

    def take(self, n: int) -> bytes:
        if self.pos + n > self.end:
            raise ValueError("raw bytes run past the packed size")
        b = self.d[self.pos: self.pos + n]
        self.pos += n
        return b


class _Bits1:
    __slots__ = ("s", "buf", "cnt")

    def __init__(self, src: _Source):
        self.s = src
        self.buf = 0
        self.cnt = 0

    def refill(self):
        low = self.s.peek(0)
        high = self.s.peek(1)
        self.s.pos += 2
        self.buf = low | (high << 8) | (self.s.peek(0) << 16) | (self.s.peek(1) << 24)
        self.cnt = 16

    def bits(self, n: int) -> int:
        v = 0
        sh = 0
        while n:
            if not self.cnt:
                self.refill()
            t = min(n, self.cnt)
            v |= (self.buf & ((1 << t) - 1)) << sh
            self.buf >>= t
            self.cnt -= t
            sh += t
            n -= t
        return v

    def peek(self, n: int) -> int:
        return self.buf & ((1 << n) - 1)

    def resync(self):
        ahead = self.s.peek(0) | (self.s.peek(1) << 8) | (self.s.peek(2) << 16)
        kept = self.buf & ((1 << self.cnt) - 1)
        self.buf = ((ahead << self.cnt) | kept) & 0xFFFFFFFF


def _canonical_codes(depths: list[int]) -> list[tuple[int, int]]:
    codes = [(0, 0)] * len(depths)
    nxt = 0
    for d in range(1, 16):
        for s, sd in enumerate(depths):
            if sd == d:
                codes[s] = (d, int(f"{nxt:0{d}b}"[::-1], 2))
                nxt += 1
        nxt <<= 1
    return codes


class _Table1:
    __slots__ = ("lookup", "ds")

    def __init__(self, b: _Bits1):
        n = b.bits(5)
        if n > 16:
            raise ValueError(f"table declares {n} symbols")
        depths = [b.bits(4) for _ in range(n)]
        if sum(1 << (15 - d) for d in depths if d) > 1 << 15:
            raise ValueError("code lengths over-subscribe the code space")
        self.lookup = {c: s for s, c in enumerate(_canonical_codes(depths)) if c[0]}
        self.ds = sorted({d for d in depths if d})

    def value(self, b: _Bits1) -> int:
        for d in self.ds:
            s = self.lookup.get((d, b.peek(d)))
            if s is not None:
                b.bits(d)
                if s < 2:
                    return s
                return b.bits(s - 1) | (1 << (s - 1))
        raise ValueError("no table code matches the bit stream")


def _unpack_1(src: _Source, target: int) -> bytes:
    b = _Bits1(src)
    out = bytearray()
    b.bits(1)
    b.bits(1)  # locked / keyed flags (keyed refuses, but stock carts never use it)
    while len(out) < target:
        runs = _Table1(b)
        dists = _Table1(b)
        lens = _Table1(b)
        subchunks = b.bits(16)
        if not subchunks:
            raise ValueError("a chunk declares no subchunks")
        for left in range(subchunks - 1, -1, -1):
            run = runs.value(b)
            if run:
                out += src.take(run)
                b.resync()
            if left:
                dist = dists.value(b) + 1
                length = lens.value(b) + 2
                for _ in range(length):
                    out.append(out[len(out) - dist])
    if len(out) != target:
        raise ValueError(f"size mismatch: {len(out)} != {target}")
    return bytes(out)


class _Bits2:
    __slots__ = ("s", "buf", "cnt")

    def __init__(self, src: _Source):
        self.s = src
        self.buf = 0
        self.cnt = 0

    def bit(self) -> int:
        if not self.cnt:
            self.buf = self.s.take(1)[0]
            self.cnt = 8
        self.cnt -= 1
        return (self.buf >> self.cnt) & 1

    def bits(self, n: int) -> int:
        v = 0
        for _ in range(n):
            v = (v << 1) | self.bit()
        return v


def _distance_2(b: _Bits2, src: _Source) -> int:
    high = 0
    if b.bit():
        high = b.bit()
        if b.bit():
            high = ((high << 1) | b.bit()) | 4
            if not b.bit():
                high = (high << 1) | b.bit()
        elif not high:
            high = b.bit() + 2
    return ((high << 8) | src.take(1)[0]) + 1


def _unpack_2(src: _Source, target: int) -> bytes:
    b = _Bits2(src)
    out = bytearray()
    b.bit()
    b.bit()  # flags
    while len(out) < target:
        while True:
            if not b.bit():
                out += src.take(1)
                continue
            if b.bit():
                if b.bit():
                    if b.bit():
                        length = src.take(1)[0] + 8
                        if length == 8:
                            b.bit()  # more chunks follow; the size decides
                            break
                    else:
                        length = 3
                    dist = _distance_2(b, src)
                else:
                    length = 2
                    dist = src.take(1)[0] + 1
            else:
                length = b.bit() + 4
                if b.bit():
                    length = ((length - 1) << 1) + b.bit()
                if length == 9:
                    run = (b.bits(4) << 2) + 12
                    out += src.take(run)
                    continue
                dist = _distance_2(b, src)
            for _ in range(length):
                out.append(out[len(out) - dist])
    if len(out) != target:
        raise ValueError(f"size mismatch: {len(out)} != {target}")
    return bytes(out)


def decode_rnc(blob: bytes) -> bytes:
    if len(blob) < 18 or blob[:3] != b"RNC":
        raise ValueError("no RNC magic")
    method = blob[3]
    if method not in (1, 2):
        raise ValueError(f"unknown method {method}")
    target = struct.unpack_from(">I", blob, 4)[0]
    packed = struct.unpack_from(">I", blob, 8)[0]
    crc_want = struct.unpack_from(">H", blob, 12)[0]
    src = _Source(blob[18: 18 + packed])
    out = _unpack_1(src, target) if method == 1 else _unpack_2(src, target)
    if crc16(out) != crc_want:
        raise ValueError("unpacked CRC mismatch")
    return out


def rnc_info(blob: bytes) -> dict:
    return {
        "method": blob[3],
        "unpacked": struct.unpack_from(">I", blob, 4)[0],
        "packed": struct.unpack_from(">I", blob, 8)[0],
        "crc_unpacked": struct.unpack_from(">H", blob, 12)[0],
        "crc_packed": struct.unpack_from(">H", blob, 14)[0],
    }
