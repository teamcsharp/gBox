"""VQ mip extents and levels checked against native VQMipPoint byte offsets."""
import struct

import numpy as np
import pytest
from PIL import Image

from gbox import ninja


def _gradient(side=64):
    yy, xx = np.mgrid[:side, :side]
    return np.stack([xx * 4, yy * 4, np.full_like(xx, 128)], -1).astype(np.uint8)


def _native_level(pvr, side):
    # Flycast core/rend/TexCache.cpp's VQMipPoint, measured from the codebook start.
    offsets = {1: 0, 2: 1, 4: 2, 8: 6, 16: 0x16, 32: 0x56, 64: 0x156}
    body = pvr[16:]
    out = np.zeros((side, side, 3), np.uint8)
    for y in range(side):
        for x in range(side):
            bx, by = x // 2, y // 2
            twiddle = sum(((by >> bit) & 1) << (2 * bit) | ((bx >> bit) & 1) << (2 * bit + 1)
                          for bit in range(6))
            index = body[2048 + offsets[side] + twiddle]
            # Native 1x1 samples bottom-right of the referenced 2x2 codeword.
            corner = 3 if side == 1 else (x % 2) * 2 + y % 2
            value = struct.unpack_from("<H", body, index * 8 + corner * 2)[0]
            out[y, x] = ((value >> 11) * 255 // 31, ((value >> 5) & 63) * 255 // 63,
                         (value & 31) * 255 // 31)
    return out


def test_all_mip_levels_use_native_offsets_and_represent_reduced_image():
    image = _gradient()
    encoded = ninja.pvr_vq(image, mips=True)
    assert encoded[9] == 4 and len(encoded) == 16 + 2048 + 0x156 + 32 * 32
    for side in (1, 2, 4, 8, 16, 32, 64):
        expected = image.reshape(side, 64 // side, side, 64 // side, 3).mean((1, 3))
        decoded = _native_level(encoded, side)
        assert np.abs(decoded.astype(float) - expected).mean() < 16, side
    assert ninja.pvr_decode(encoded)[:2] == (64, 64)


def test_mip_replacement_preserves_header_gbix_padding_and_following_chunk():
    image = Image.fromarray(_gradient())
    old = ninja.pvr_vq(np.asarray(image), gbix=192, mips=True)
    tail = b"opaque padding\0NEXT\x00\xff"
    old += tail
    q = old.index(b"PVRT")
    rewritten = ninja.pvr_like(old, image)
    assert len(rewritten) == len(old) and rewritten[:q + 16] == old[:q + 16]
    assert rewritten[-len(tail):] == tail


@pytest.mark.parametrize("damage", ["missing_header", "short_header", "extent_overrun", "too_small_body"])
def test_replacement_rejects_malformed_extent_even_with_trailing_buffer_room(damage):
    image = Image.fromarray(np.full((8, 8, 3), 128, np.uint8))
    old = bytearray(ninja.pvr_vq(np.asarray(image), mips=True))
    if damage == "missing_header":
        old[:4] = b"NOPE"
    elif damage == "short_header":
        old = old[:10]
    elif damage == "extent_overrun":
        struct.pack_into("<I", old, 4, len(old) + 1)
    else:
        struct.pack_into("<I", old, 4, 8)  # The buffer has bytes, but they are outside the declared PVRT body.
    with pytest.raises(ValueError):
        ninja.pvr_like(bytes(old), image)


@pytest.mark.parametrize("pix,alpha", [(0, 0), (0, 255), (2, 102)])
def test_argb_mips_preserve_alpha(pix, alpha):
    image = np.full((8, 8, 4), [96, 128, 160, alpha], np.uint8)
    encoded = ninja.pvr_vq(image, pix=pix, mips=True)
    decoded = np.frombuffer(ninja.pvr_decode(encoded)[2], np.uint8).reshape(8, 8, 4)
    assert np.all(decoded[..., 3] == alpha)
    rewritten = ninja.pvr_like(encoded, Image.fromarray(image))
    assert np.all(np.frombuffer(ninja.pvr_decode(rewritten)[2], np.uint8).reshape(8, 8, 4)[..., 3] == alpha)


def test_batched_codeword_matching_keeps_results_across_boundaries():
    blocks = np.tile([[0., 0.], [20., 20.], [90., 90.]], (1400, 1))
    book = np.array([[0., 0.], [100., 100.]])
    result = ninja._vq_nearest(blocks, book)
    assert np.array_equal(result, np.tile([0, 0, 1], 1400))


@pytest.mark.parametrize("pix,small", [(3, False), (1, True)])
def test_unsupported_pixel_or_small_mip_format_refuses(pix, small):
    with pytest.raises(ValueError):
        ninja.pvr_vq(np.zeros((8, 8, 3)), pix=pix, small=small, mips=True)


@pytest.mark.parametrize('fmt', [1, 3, 0x10])
def test_nonmip_replacement_preserves_original_extent_and_following_data(fmt):
    image = Image.fromarray(np.full((8, 8, 3), [96, 128, 160], np.uint8))
    old = (ninja.pvr_twiddled(np.asarray(image)) if fmt == 1 else
           ninja.pvr_vq(np.asarray(image), small=fmt == 0x10))
    tail = b'opaque padding\0NEXT\x00\xff'
    original = old + tail
    rewritten = ninja.pvr_like(original, image)
    assert len(rewritten) == len(original)
    assert rewritten[:16] == original[:16] and rewritten[-len(tail):] == tail
    assert ninja.pvr_decode(rewritten) == ninja.pvr_decode(old)
    malformed = bytearray(original)
    struct.pack_into('<I', malformed, 4, 8)
    with pytest.raises(ValueError, match='declared PVRT body'):
        ninja.pvr_like(bytes(malformed), image)


@pytest.mark.parametrize('fmt', [1, 3, 4, 0x10])
@pytest.mark.parametrize('width,height', [(0, 0), (65535, 65535), (2048, 2048), (64, 32), (12, 12)])
def test_invalid_dimensions_reject_before_allocating_replacement_image(fmt, width, height):
    old = bytearray(ninja.pvr_vq(np.zeros((8, 8, 3)), mips=True))
    old[9] = fmt
    struct.pack_into('<HH', old, 12, width, height)
    class ImageMustNotBeConverted:
        def convert(self, _mode):
            pytest.fail('invalid native dimensions must be rejected before image allocation')
    with pytest.raises(ValueError, match='dimensions'):
        ninja.pvr_like(bytes(old), ImageMustNotBeConverted())
