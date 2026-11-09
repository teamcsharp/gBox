"""Constant-channel BC4/BC5 controls for measured native Switch TEX surfaces.

These controls isolate native secondary maps without inventing their shader
meaning. A zero mask is not a promise that the material disables specularity.
BC4 stores two endpoints and sixteen 3-bit indices; BC5 stores two BC4 blocks:
https://learn.microsoft.com/en-us/windows/win32/direct3d10/d3d10-graphics-programming-guide-resources-block-compression
"""
from __future__ import annotations

from . import mtf_tex


def constant_channels(data: bytes, channels: tuple[int, ...]) -> bytes:
    """Set every BC4/BC5 mip to exact UNORM channel values, retaining its container.

    Equal endpoints and zero indices select the same byte for every texel.
    Header, mip layout, GOB padding, dimensions and format remain byte-identical.
    BC5 values (128, 128) provide the near-zero XY normal control; the material
    still owns reconstruction of Z and its lighting behavior.
    """
    tex = mtf_tex.parse(data)
    expected = {0x19: 1, 0x1F: 2}.get(tex.format)
    if expected is None:
        raise ValueError('constant channels require a BC4 or BC5 TEX')
    if len(channels) != expected or any(type(v) is not int or not 0 <= v <= 255 for v in channels):
        raise ValueError(f'format 0x{tex.format:02x} requires {expected} integer byte channel(s)')
    block = b''.join(bytes((v, v)) + b'\0' * 6 for v in channels)
    out = data
    for i, mip in enumerate(tex.mips):
        count = ((mip.width + 3) // 4) * ((mip.height + 3) // 4)
        out = mtf_tex.replace_blocks(out, block * count, i)
    return out
