"""Known constant BC blocks and byte-preserving native secondary-map controls."""
import struct

import numpy as np
import pytest

from gbox import mtf_secondary as S, mtf_tex as T


def fixture(fmt):
    # A 32x32 BC4 surface occupies one 512-byte GOB; BC5 needs two.
    sizes = [512 if fmt == 0x19 else 1024] + [512] * 5
    offsets = [sum(sizes[:i]) for i in range(6)]
    header = b'TEX\0\xa1\x80\0\x20' + struct.pack(
        '<3I', 6 | 32 << 6 | 32 << 19, 0x10001 | fmt << 8, sum(sizes))
    header += struct.pack('<6I', *offsets)
    return header + bytes((i * 37 + 13) % 256 for i in range(sum(sizes)))


@pytest.mark.parametrize('fmt,channels,pixel', [
    (0x19, (0,), (0, 0, 0, 255)),
    (0x19, (173,), (173, 173, 173, 255)),
    (0x1F, (128, 128), (128, 128, 0, 255)),
    (0x1F, (17, 231), (17, 231, 0, 255)),
])
def test_constant_channels_decode_exactly_in_every_mip_and_keep_padding(fmt, channels, pixel):
    original = fixture(fmt)
    changed = S.constant_channels(original, channels)
    tex = T.parse(original)
    assert T.parse(changed) == tex
    assert len(changed) == len(original)
    assert changed[:tex.data_offset] == original[:tex.data_offset]
    covered = set()
    expected_block = b''.join(bytes((v, v)) + b'\0' * 6 for v in channels)
    for i, mip in enumerate(tex.mips):
        assert np.all(np.asarray(T.decode(changed, i)) == pixel)
        count = ((mip.width + 3) // 4) * ((mip.height + 3) // 4)
        assert T.linear_blocks(changed, i) == expected_block * count
        covered.update((T._addresses(mip, len(expected_block)) + mip.offset).flat)
    assert all(a == b for i, (a, b) in enumerate(zip(original, changed)) if i not in covered)


@pytest.mark.parametrize('fmt,channels', [
    (0x19, ()), (0x19, (0, 0)), (0x1F, (128,)),
    (0x19, (-1,)), (0x19, (256,)), (0x19, (1.0,)), (0x19, (True,)),
])
def test_channel_shape_and_byte_values_are_validated(fmt, channels):
    with pytest.raises(ValueError, match='integer byte'):
        S.constant_channels(fixture(fmt), channels)


def test_bc7_requires_its_existing_image_encoder():
    with pytest.raises(ValueError, match='BC4 or BC5'):
        S.constant_channels(fixture(0x30), (0,))
