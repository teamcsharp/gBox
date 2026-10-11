"""Native texture fixture tests: packet sizes, alpha and safe BIN patching."""
import struct

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
