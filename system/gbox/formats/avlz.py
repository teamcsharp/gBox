"""Amusement Vision LZ (AvLz) — F-Zero GX / F-Zero AX / Super Monkey Ball GC compression.

Header (little-endian), then an LZSS stream (ring buffer N=4096, F=18, THRESHOLD=3,
BUFF_INIT=0x00 for F-Zero GX):

    u32 compressed_size     (F-Zero GX stores the compressed stream size exactly;
                             SMB/AX variants add the 8-byte header to this field)
    u32 uncompressed_size
    u8  compressed_data[compressed_size]

The stream is decoded with flag bytes read LSB-first (bit set = literal byte, bit clear =
2-byte back-reference: index = ((b1 & 0xF0) << 4) | b0, count = (b1 & 0x0F) + 3, both into
a 4096-byte ring buffer that starts zero-filled at position N-F = 4078).

Reference: RaphaelTetreault/GameCube.AmusementVision (Lz.cs, LzDecoder.cs, LzssParameters.cs),
ported here so gBox has a shared codec (one implementation per codec).
"""
from __future__ import annotations

import struct

N = 4096          # ring buffer size
F = 18            # max match length for coding
THRESHOLD = 3     # min match length
BUFF_INIT = 0x00  # F-Zero GX uses 0 (SMB uses space)


class AvLzError(ValueError):
    pass


def _header(data: bytes) -> tuple[int, int]:
    """(compressed_size, uncompressed_size) for a GCZ/SMB AvLz header, or raise."""
    if len(data) < 8:
        raise AvLzError("AvLz header too short")
    compressed, uncompressed = struct.unpack_from("<II", data, 0)
    # F-Zero GX stores the compressed size exactly (no +8); SMB/AX add 8.
    for cand in (compressed, compressed - 8):
        if cand >= 0 and 8 + cand == len(data):
            return cand, uncompressed
    raise AvLzError(
        f"AvLz header size field {compressed} matches neither {len(data)} nor "
        f"{len(data) - 8} (file length {len(data)})"
    )


def decompress(data: bytes) -> bytes:
    """Decompress a full AvLz buffer (header + stream)."""
    comp_size, out_size = _header(data)
    return decompress_stream(data[8:8 + comp_size], out_size)


def decompress_stream(src: bytes, out_size: int) -> bytes:
    """Decode an AvLz LZSS stream to exactly `out_size` bytes."""
    ring = bytearray([BUFF_INIT]) * N
    out = bytearray()
    pos = 0           # read position in src
    rp = N - F        # ring buffer write position
    flags = 0
    while pos < len(src) and len(out) < out_size:
        if (flags & 0xFF00) == 0:
            if pos >= len(src):
                raise AvLzError("AvLz stream truncated at flag byte")
            flags = src[pos] | 0x8000
            pos += 1
        if flags & 1:
            if pos >= len(src):
                raise AvLzError("AvLz stream truncated at literal")
            c = src[pos]
            pos += 1
            out.append(c)
            ring[rp % N] = c
            rp += 1
        else:
            if pos + 2 > len(src):
                raise AvLzError("AvLz stream truncated at back-reference")
            b0 = src[pos]
            b1 = src[pos + 1]
            pos += 2
            index = ((b1 & 0xF0) << 4) | b0
            count = (b1 & 0x0F) + THRESHOLD
            for i in range(count):
                c = ring[(index + i) % N]
                out.append(c)
                ring[rp % N] = c
                rp += 1
        flags >>= 1
    if len(out) != out_size:
        raise AvLzError(f"AvLz decoded {len(out)} bytes, expected {out_size}")
    return bytes(out)


U8_MAGIC = b"\x55\xaa\x38\x2d"
TPL_MAGIC = b"\x00\x20\xaf\x30"
