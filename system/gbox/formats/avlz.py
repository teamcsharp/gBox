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

Uses the existing gbox.formats.lz LZSS implementation. Header variants are
recognized, but a space-initialized ring variant is not supported by this wrapper.
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


def decompress(data: bytes, *, max_output_size: int = 64 * 1024 * 1024) -> bytes:
    """Decompress a full AvLz buffer (header + stream)."""
    comp_size, out_size = _header(data)
    return decompress_stream(data[8:8 + comp_size], out_size, max_output_size=max_output_size)


def decompress_stream(src: bytes, out_size: int, *, max_output_size: int = 64 * 1024 * 1024) -> bytes:
    """Decode the zero-ring variant with bounded output and exact stream consumption."""
    if type(out_size) is not int or type(max_output_size) is not int or not 0 <= out_size <= max_output_size:
        raise AvLzError("AvLz output size exceeds the configured bound")
    if out_size > len(src) * 9:
        raise AvLzError("AvLz declared output cannot fit the compressed stream")
    from .lz import lzss_decompress
    out, consumed = lzss_decompress(src, out_size=out_size)
    if len(out) != out_size or consumed != len(src):
        raise AvLzError("AvLz truncated output or trailing compressed data")
    return out


U8_MAGIC = b"\x55\xaa\x38\x2d"
TPL_MAGIC = b"\x00\x20\xaf\x30"
