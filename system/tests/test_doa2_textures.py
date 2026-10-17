"""Native texture fixture tests: packet sizes, alpha and safe BIN patching."""
import struct

import numpy as np
import pytest
from PIL import Image

from gbox import doa2_textures as T


def fixture(spec):
    """Minimal CHR containing only a valid texture directory and a native BIN."""
    chr_data = bytearray(struct.pack("<6I", 24, 24, 24, 0, len(spec), 0))
    bin_data = bytearray()
    for w, h, pix, fmt in spec:
        chr_data.extend(struct.pack("<III", w | h << 16, pix | fmt << 8, 0x0D200000 + len(bin_data)))
        bin_data.extend(bytes(T.texture_size(w, h, pix, fmt)))
    chr_data.extend(bytes(4))
    return bytes(chr_data), bytes(bin_data)


@pytest.mark.parametrize("pix", [0, 1, 2])
@pytest.mark.parametrize("fmt,shape", [(1, (8, 8)), (13, (16, 8)), (3, (8, 8))])
def test_native_pixel_and_data_formats(pix, fmt, shape):
    c, b = fixture([(*shape, pix, fmt)])
    tex = T.descriptors(c, b)[0]
    original = Image.new("RGBA", shape, (255, 0, 0, 255))
    # Rectangle twiddling must cross the square tile boundary correctly.
    original.paste((0, 255, 0, 255), (shape[0] // 2, 0, shape[0], shape[1]))
    result = T.replace(c, b, {0: original})
    assert len(result) == len(b)
    image = T.decode(tex, result)
    assert image.getpixel((0, 0)) == (255, 0, 0, 255)
    assert image.getpixel((shape[0] - 1, shape[1] - 1)) == (0, 255, 0, 255)


@pytest.mark.parametrize("pix", [0, 2])
@pytest.mark.parametrize("fmt", [1, 13, 3])
def test_argb_alpha_survives_native_encoding(pix, fmt):
    shape = (16, 8) if fmt == 13 else (8, 8)
    c, b = fixture([(*shape, pix, fmt)])
    tex = T.descriptors(c, b)[0]
    image = Image.new("RGBA", shape, (255, 0, 0, 255))
    image.paste((0, 0, 255, 0), (0, 0, shape[0] // 2, shape[1]))
    rebuilt = T.decode(tex, T.replace(c, b, {0: image}))
    assert rebuilt.getpixel((0, 0))[3] == 0
    assert rebuilt.getpixel((shape[0] - 1, 0))[3] == 255


def test_replacing_a_slot_preserves_other_native_data():
    c, b = fixture([(8, 8, 1, 1), (8, 8, 2, 3), (16, 8, 1, 13)])
    b = bytes((k * 17 + 9) & 255 for k in range(len(b)))
    tex = T.descriptors(c, b)[1]
    out = T.replace(c, b, {1: Image.new("RGBA", (8, 8), (0, 255, 0, 255))})
    assert out[:tex.offset] == b[:tex.offset]
    assert out[tex.offset + tex.size:] == b[tex.offset + tex.size:]
    assert T.replace(c, b, {}) == b


def test_native_budget_rejects_truncated_and_overlapping_payloads():
    c, b = fixture([(8, 8, 1, 1), (8, 8, 1, 1)])
    with pytest.raises(ValueError, match="allocation"):
        T.descriptors(c, b[:-1])
    corrupt = bytearray(c)
    struct.pack_into("<I", corrupt, 24 + 12 + 8, 0x0D200001)
    with pytest.raises(ValueError, match="allocation"):
        T.descriptors(bytes(corrupt), b)


def test_rejects_malformed_dimensions_table_and_unknown_slot():
    c, b = fixture([(8, 8, 1, 1)])
    corrupt = bytearray(c)
    struct.pack_into("<I", corrupt, 24, 7 | (8 << 16))
    with pytest.raises(ValueError, match="dimensions"):
        T.descriptors(bytes(corrupt), b)
    with pytest.raises(ValueError, match="table"):
        T.descriptors(c[:30], b)
    with pytest.raises(ValueError, match="slot"):
        T.replace(c, b, {10: Image.new("RGBA", (8, 8))})


def _ds(v5):
    """A 5-bit channel widened by bit copy, as the DS / N64 readers produce it."""
    return (v5 << 3) | (v5 >> 2)


@pytest.mark.parametrize("pix", [0, 1])
def test_bit_copied_5bit_colours_survive(pix):
    """Rounding to the nearest level (not truncation) returns a DS colour's own level; nothing is dithered."""
    rng = np.random.default_rng(3)
    v = rng.integers(0, 32, (8, 8, 3))
    img = np.dstack([_ds(v), np.full((8, 8), 255)]).astype(np.uint8)
    words = T._pixels16(img, pix)
    assert ((words >> (11 if pix == 1 else 10)) & 31 == v[..., 0]).all() and (words & 31 == v[..., 2]).all()
    back = T._expand16(words, pix)[..., :3]
    assert (np.abs(back - img[..., :3]) <= 4).all()


def test_argb4444_rounds_to_the_nearest_level():
    img = np.array([[[8, 9, 247, 255], [25, 26, 136, 119]]], np.uint8)
    w = T._pixels16(img, 2)
    assert (T._expand16(w, 2)[0] == [[0, 17, 255, 255], [17, 34, 136, 119]]).all()


@pytest.mark.parametrize("pix,fmt", [(1, 1), (1, 3), (2, 3), (0, 13)])
def test_flat_colour_stays_flat(pix, fmt):
    shape = (16, 8) if fmt == 13 else (16, 16)
    c, b = fixture([(*shape, pix, fmt)])
    tex = T.descriptors(c, b)[0]
    out = np.asarray(T.decode(tex, T.replace(c, b, {0: Image.new("RGBA", (8, 8), (41, 49, 82, 255))})))
    assert len(np.unique(out.reshape(-1, 4), axis=0)) == 1


def test_fit_image_replicates_up_and_averages_down():
    src = np.zeros((2, 2, 4), np.uint8)
    src[..., 3] = 255
    src[0, 0, :3] = (255, 0, 0)
    up = np.asarray(T.fit_image(Image.fromarray(src), 4, 4))
    assert (up[:2, :2, :3] == (255, 0, 0)).all() and (up[2:, 2:, :3] == 0).all()     # no ringing, no blends
    down = np.asarray(T.fit_image(Image.fromarray(up), 2, 2))
    assert (down == src).all()


def test_vq_keeps_a_small_detail_and_binary_alpha():
    """A 64x64 gradient has far more than 256 distinct 2x2 blocks; a yellow 2x2 'button' must keep its own
    codebook entry, and a cut-out's alpha stays 0 / 255 through the codebook."""
    y, x = np.mgrid[0:64, 0:64]
    img = np.dstack([x * 4, y * 4, (x + y) * 2, np.full_like(x, 255)]).clip(0, 255).astype(np.uint8)
    img[20:22, 30:32, :3] = (255, 230, 0)
    img[:, :8, 3] = 0
    c, b = fixture([(64, 64, 2, 3)])
    tex = T.descriptors(c, b)[0]
    out = np.asarray(T.decode(tex, T.replace(c, b, {0: Image.fromarray(img)}))).astype(int)
    assert np.abs(out[20:22, 30:32, :3] - (255, 230, 0)).max() <= 17
    assert set(np.unique(out[..., 3]).tolist()) <= {0, 255}
    assert (out[:, :8, 3] == 0).all() and (out[:, 8:, 3] == 255).all()
    c1, b1 = fixture([(64, 64, 1, 3)])
    tex1 = T.descriptors(c1, b1)[0]
    out1 = np.asarray(T.decode(tex1, T.replace(c1, b1, {0: Image.fromarray(img)}))).astype(float)
    mse = ((out1[..., :3] - img[..., :3]) ** 2).mean()
    assert 10 * np.log10(255 ** 2 / mse) > 30
