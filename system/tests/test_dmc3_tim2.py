import struct, zlib
import pytest
from gbox.dmc3_tim2 import csm1_index, parse_tim2, to_png


def _tim2(img_t, w, h, img, clut, clut_t, ncol):
    hdr = struct.pack("<IIIHHBBBBHH", 0x30 + len(img) + len(clut), len(clut), len(img), 0x30, ncol, 0, 1,
                      clut_t, img_t, w, h) + bytes(0x30 - 24)
    return b"TIM2" + bytes([4, 0]) + struct.pack("<H", 1) + bytes(8) + hdr + img + clut


def test_csm1_swizzle_swaps_bits_3_and_4():
    assert [csm1_index(i) for i in (0, 7, 8, 16, 24, 32, 40)] == [0, 7, 16, 8, 24, 32, 48]
    assert sorted(csm1_index(i) for i in range(256)) == list(range(256))


def test_8bpp_csm1_palette_and_alpha_expansion():
    # file palette position p holds colour whose logical index is csm1_index(p)
    clut = bytearray()
    for p in range(256):
        clut += bytes([csm1_index(p), 0, 0, 0x80 if p >= 128 else 0x40])
    pics = parse_tim2(_tim2(5, 2, 1, bytes([8, 200]), bytes(clut), 3, 256))
    px = pics[0]["rgba"]
    assert px[0] == 8 and px[4] == 200
    assert px[3] == 0x80   # file slot 16 holds alpha 0x40 -> doubled to 0x80
    assert px[7] == 255    # file slot 200 holds alpha 0x80 -> 0xFF


def test_4bpp_nibble_order_and_rgba5551():
    clut = struct.pack("<16H", *([0x8000 | 31] + [0x7C00 | 0x8000] * 15))
    pics = parse_tim2(_tim2(4, 2, 1, bytes([0x10]), clut, 1 | 0x80, 16))
    assert pics[0]["rgba"][:4] == bytes([255, 0, 0, 255])  # low nibble 0 first
    assert pics[0]["rgba"][4:8] == bytes([0, 0, 255, 255])


def test_rejects_truncated_and_oversized():
    good = _tim2(5, 2, 1, bytes([0, 0]), bytes(1024), 3 | 0x80, 256)
    with pytest.raises(ValueError):
        parse_tim2(good[:0x50])
    bad = bytearray(good); struct.pack_into("<H", bad, 0x24, 64)  # width too big for data
    with pytest.raises(ValueError):
        parse_tim2(bytes(bad))
    with pytest.raises(ValueError):
        parse_tim2(b"XXXX" + bytes(80))


def test_png_roundtrip_header():
    p = to_png(1, 1, bytes([1, 2, 3, 4]))
    assert p[:8] == b"\x89PNG\r\n\x1a\n" and zlib.decompress(p[p.index(b"IDAT") + 4:-16])[1:] == bytes([1, 2, 3, 4])
