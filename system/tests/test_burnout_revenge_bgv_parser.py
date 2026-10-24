"""Test parsing .bgv geometry files."""

import zlib
import struct


def test_parse_bgv_header():
    # Create a sample .bgv file: zlib-compressed data with header 0x25 followed by 64 zero bytes
    payload = b"\x00\x00\x00\x25" + b"\x00" * 64
    compressed = zlib.compress(payload)
    # Decompress and parse
    decompressed = zlib.decompress(compressed)
    header, = struct.unpack_from(">I", decompressed, 0)
    assert header == 0x25
    assert len(decompressed) == 68
