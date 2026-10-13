"""EA RefPack (QFS, magic 0x10FB) codec used by EA titles such as WCW Mayhem (N64, Kodiak) BIGF members.

Header: flags byte (0x80 = 4-byte size fields, 0x01 = a compressed-size field precedes the size), 0xFB, then the
big-endian unpacked size (3 or 4 bytes).  Commands:
  0xxxxxxx  2 bytes  lit = b0&3, len = ((b0>>2)&7)+3, off = ((b0&0x60)<<3)+b1+1
  10xxxxxx  3 bytes  lit = b1>>6, len = (b0&0x3f)+4, off = ((b1&0x3f)<<8)+b2+1
  110xxxxx  4 bytes  lit = b0&3, len = ((b0&0x0c)<<6)+b3+5, off = ((b0&0x10)<<12)+(b1<<8)+b2+1
  111xxxxx  1 byte   b0 < 0xFC: lit = ((b0&0x1f)+1)*4 ; b0 >= 0xFC: lit = b0&3 and stop.
`decompress` returns (data, bytes_consumed) via `decompress_ex`; `compress_literal` writes a valid literal-only stream
(no back-references) so a writer can produce loadable members before a matching encoder exists.
"""
from __future__ import annotations


def is_refpack(b: bytes) -> bool:
    return len(b) >= 5 and b[1] == 0xFB and (b[0] & 0x3E) == 0x10


def header(b: bytes) -> tuple[int, int]:
    """(unpacked size, header length)."""
    if not is_refpack(b):
        raise ValueError("not a RefPack stream")
    n = 4 if b[0] & 0x80 else 3
    p = 2 + (n if b[0] & 0x01 else 0)
    if p + n > len(b):
        raise ValueError("RefPack header truncated")
    return int.from_bytes(b[p:p + n], "big"), p + n


def decompress_ex(b: bytes) -> tuple[bytes, int]:
    size, p = header(b)
    out = bytearray()
    while True:
        if p >= len(b):
            raise ValueError("RefPack stream truncated")
        b0 = b[p]
        need = 2 if b0 < 0x80 else 3 if b0 < 0xC0 else 4 if b0 < 0xE0 else 1
        if p + need > len(b):
            raise ValueError("RefPack command truncated")
        if b0 < 0x80:
            b1 = b[p + 1]; p += 2
            lit, ln, off = b0 & 3, ((b0 >> 2) & 7) + 3, ((b0 & 0x60) << 3) + b1 + 1
        elif b0 < 0xC0:
            b1, b2 = b[p + 1], b[p + 2]; p += 3
            lit, ln, off = b1 >> 6, (b0 & 0x3F) + 4, ((b1 & 0x3F) << 8) + b2 + 1
        elif b0 < 0xE0:
            b1, b2, b3 = b[p + 1], b[p + 2], b[p + 3]; p += 4
            lit, ln, off = b0 & 3, ((b0 & 0x0C) << 6) + b3 + 5, ((b0 & 0x10) << 12) + (b1 << 8) + b2 + 1
        else:
            p += 1
            lit = ((b0 & 0x1F) + 1) * 4 if b0 < 0xFC else b0 & 3
            if p + lit > len(b):
                raise ValueError("RefPack literal run truncated")
            out += b[p:p + lit]; p += lit
            if b0 >= 0xFC:
                break
            continue
        if p + lit > len(b):
            raise ValueError("RefPack literal run truncated")
        out += b[p:p + lit]; p += lit
        if off > len(out):
            raise ValueError(f"RefPack back-reference {off} before start (out={len(out)})")
        s = len(out) - off
        for i in range(ln):                       # overlapping copies are byte-serial
            out.append(out[s + i])
    if len(out) != size:
        raise ValueError(f"RefPack size mismatch: header {size}, decoded {len(out)}")
    return bytes(out), p


def decompress(b: bytes) -> bytes:
    return decompress_ex(b)[0]


def compress_literal(data: bytes) -> bytes:
    """A valid RefPack stream made only of literal runs (larger than the input, but byte-exact on decode)."""
    n = len(data)
    big = n > 0xFFFFFF
    out = bytearray([0x90 if big else 0x10, 0xFB]) + n.to_bytes(4 if big else 3, "big")
    p = 0
    while n - p > 3:
        k = min(112, (n - p) & ~3)
        out.append(0xE0 + k // 4 - 1); out += data[p:p + k]; p += k
    out.append(0xFC + (n - p)); out += data[p:]
    return bytes(out)
