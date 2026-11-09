"""Switch MT Framework TEX surfaces, with header/mip/padding-preserving BC7 edits.

The TEX fields and formats follow Random Talking Bush's Switch TEX converter:
https://github.com/RandomTBush/RTB-QuickBMS-Scripts/blob/master/Textures/CapcomMTFrameworkSwitch_TEX.bms
Tegra X1 GOB addressing follows the published hardware layout (64-byte by 8-row
GOBs), also described by https://github.com/ScanMountGoat/tegra_swizzle.

Only the measured Switch v0xa1, one-surface 2D power-of-two layout is accepted.
BC4/BC5 can be decoded; image replacement deliberately supports BC7 only. BC7
encoding uses the optional ``gbox[textures]`` CPU encoder, never a guessed codec.
Inputs/outputs are uncompressed TEX bytes; ARC compression belongs to mt_arc.
"""
from __future__ import annotations

from dataclasses import dataclass
import io
import struct

import numpy as np
from PIL import Image


_FORMATS = {0x19: (8, 80), 0x1F: (16, 83), 0x30: (16, 98), 0x31: (16, 99)}


@dataclass(frozen=True)
class Mip:
    width: int
    height: int
    offset: int
    size: int
    block_height: int


@dataclass(frozen=True)
class Texture:
    width: int
    height: int
    format: int
    data_offset: int
    mips: tuple[Mip, ...]


def parse(data: bytes) -> Texture:
    """Validate exact mip storage before reading or changing any texels."""
    if len(data) < 24 or data[:8] != b'TEX\0\xa1\x80\0\x20':
        raise ValueError('expected Switch MT Framework TEX v0xa1')
    packed, kind, size = struct.unpack_from('<3I', data, 8)
    count, width, height = packed & 63, (packed >> 6) & 8191, packed >> 19
    fmt = (kind >> 8) & 255
    if kind & 0xFFFF00FF != 0x00010001:
        raise ValueError('only one-surface 2D TEX is supported')
    if fmt not in _FORMATS:
        raise ValueError(f'unsupported Switch TEX format 0x{fmt:02x}')
    if not width or not height or width & (width-1) or height & (height-1):
        raise ValueError('only measured power-of-two TEX dimensions are supported')
    if not 1 <= count <= max(width, height).bit_length():
        raise ValueError('invalid TEX mip count')
    start = 20 + count*4
    if len(data) != start + size:
        raise ValueError('TEX payload length disagrees with header')
    offsets = struct.unpack_from('<' + 'I'*count, data, 20) + (size,)
    if offsets[0] != 0:
        raise ValueError('unexpected TEX first mip offset')
    bpb = _FORMATS[fmt][0]
    mips = []
    for i, (begin, end) in enumerate(zip(offsets, offsets[1:])):
        w, h = max(1, width >> i), max(1, height >> i)
        bx, by = (w+3)//4, (h+3)//4
        bh = max(1, min(16, (1 << (by-1).bit_length()) // 8))
        pitch = ((bx*bpb + 63)//64)*64
        expected = pitch * ((by + 8*bh-1)//(8*bh)) * 8*bh
        if end-begin != expected:
            raise ValueError(f'TEX mip {i} storage is not the measured Tegra layout')
        mips.append(Mip(w, h, start+begin, expected, bh))
    return Texture(width, height, fmt, start, tuple(mips))


def _addresses(mip: Mip, bpb: int) -> np.ndarray:
    """Byte addresses of BC blocks, ordered by linear block row then column."""
    columns, rows = (mip.width+3)//4, (mip.height+3)//4
    y, x = np.indices((rows, columns), dtype=np.int64)
    x *= bpb
    bh = mip.block_height
    gob_columns = (columns*bpb + 63)//64
    gob = (y//(8*bh))*512*bh*gob_columns + (x//64)*512*bh + ((y//8)%bh)*512
    address = gob + ((x%64)//32)*256 + ((y%8)//2)*64 + ((x%32)//16)*32 + (y%2)*16 + x%16
    return address.reshape(-1, 1) + np.arange(bpb)


def linear_blocks(data: bytes, mip: int = 0) -> bytes:
    """Extract one mip's linear BC blocks, excluding all GOB padding."""
    tex = parse(data)
    if not 0 <= mip < len(tex.mips):
        raise ValueError('mip index outside TEX')
    level = tex.mips[mip]
    src = np.frombuffer(data, dtype=np.uint8, count=level.size, offset=level.offset)
    return src[_addresses(level, _FORMATS[tex.format][0])].tobytes()


def replace_blocks(data: bytes, blocks: bytes, mip: int = 0) -> bytes:
    """Re-swizzle exact compressed blocks; every unrelated byte stays intact."""
    tex = parse(data)
    if not 0 <= mip < len(tex.mips):
        raise ValueError('mip index outside TEX')
    level = tex.mips[mip]
    addresses = _addresses(level, _FORMATS[tex.format][0])
    if len(blocks) != addresses.size:
        raise ValueError('compressed mip byte count does not match TEX dimensions')
    out = bytearray(data)
    dst = np.frombuffer(out, dtype=np.uint8, count=level.size, offset=level.offset)
    dst[addresses] = np.frombuffer(blocks, dtype=np.uint8).reshape(addresses.shape)
    return bytes(out)


def decode(data: bytes, mip: int = 0) -> Image.Image:
    """Decode a native mip through Pillow's BC decoder (RGBA pixels)."""
    tex = parse(data)
    if not 0 <= mip < len(tex.mips):
        raise ValueError('mip index outside TEX')
    level = tex.mips[mip]
    blocks = linear_blocks(data, mip)
    header = bytearray(148)
    header[:4] = b'DDS '
    struct.pack_into('<7I', header, 4, 124, 0x81007, level.height, level.width, len(blocks), 0, 1)
    struct.pack_into('<II4s', header, 76, 32, 4, b'DX10')
    struct.pack_into('<I', header, 108, 0x1000)
    struct.pack_into('<5I', header, 128, _FORMATS[tex.format][1], 3, 0, 1, 0)
    with Image.open(io.BytesIO(header + blocks)) as image:
        return image.convert('RGBA')


def _encode_bc7(image: Image.Image) -> bytes:
    try:
        import ispc_texcomp
    except ImportError:
        raise RuntimeError('BC7 encoding requires the optional gbox[textures] dependency (ispc_texcomp)') from None
    # The native encoder consumes complete 4x4 blocks. Repeat edge texels for
    # sub-block mips; zero padding would corrupt the final 2x2 and 1x1 levels.
    pixels = np.asarray(image.convert('RGBA'))
    padded = np.pad(pixels, ((0, (-image.height)%4), (0, (-image.width)%4), (0, 0)), mode='edge')
    surface = ispc_texcomp.RGBASurface(padded.tobytes(), padded.shape[1], padded.shape[0])
    settings = ispc_texcomp.BC7EncSettings.from_profile('alpha_basic')
    encoded = ispc_texcomp.compress_blocks_bc7(surface, settings)
    expected = ((image.width+3)//4)*((image.height+3)//4)*16
    if len(encoded) != expected:
        raise ValueError('BC7 encoder returned an invalid surface size')
    return encoded


def replace_image(data: bytes, image: Image.Image) -> bytes:
    """Replace a BC7 image and regenerate its original mip chain, preserving its container.

    Dimensions must match: callers choose their atlas size explicitly. Header,
    format (including sRGB), mip count/offsets and storage padding are unchanged.
    """
    tex = parse(data)
    if tex.format not in (0x30, 0x31):
        raise ValueError('image replacement currently requires a BC7 TEX')
    if image.size != (tex.width, tex.height):
        raise ValueError(f'image dimensions must match TEX {tex.width}x{tex.height}')
    out, level_image = data, image.convert('RGBA')
    for i, mip in enumerate(tex.mips):
        if i:
            level_image = level_image.resize((mip.width, mip.height), Image.Resampling.LANCZOS)
        out = replace_blocks(out, _encode_bc7(level_image), i)
    return out
