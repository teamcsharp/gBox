import struct, zlib
from gbox import merc3d_tex as t


def _hdr(w, h, mips, fmt):
    return b"TEX\0" + struct.pack("<3I", 0x200800A4, mips | (w << 6) | (h << 19), 1 | (fmt << 8) | 0x10000)


def test_header_and_sizes():
    d = _hdr(256, 512, 5, 0x0C) + bytes(174592)
    h = t.parse_header(d)
    assert (h["width"], h["height"], h["mips"], h["format"], h["version"]) == (256, 512, 5, 0x0C, 0xA4)
    assert t.mip_sizes(h) == [131072, 32768, 8192, 2048, 512]
    assert 0x10 + sum(t.mip_sizes(h)) == len(d) - 0


def test_etc1_flat_block():
    # standard ETC1 individual mode block, base 0xF0F0F0 both halves, table 0, all indices 0 (+2)
    std = bytes([0xFF, 0xFF, 0xFF, 0x00 << 2, 0, 0, 0, 0])
    px = t._etc1_block(std[::-1])
    assert px[0] == (255, 255, 255) and len(px) == 16


def test_etc1a4_alpha_and_png():
    blk = bytes([0xFF] * 8) + bytes([0xFF, 0xFF, 0xFF, 0x00, 0, 0, 0, 0])[::-1]
    d = _hdr(8, 8, 1, 0x0C) + blk * 4
    w, h, rgba = t.decode(d)
    assert (w, h) == (8, 8) and set(rgba[3::4]) == {255}
    p = t.png(w, h, rgba)
    assert p[:8] == b"\x89PNG\r\n\x1a\n"


def test_bad_size_rejected():
    d = _hdr(8, 8, 1, 0x0C) + bytes(10)
    try:
        t.decode(d)
    except ValueError:
        return
    raise AssertionError
