"""RE6 (Switch) TEX surfaces: measured format table, header parsing and the decodable formats.

The player textures live in `uPlTex####_*.arc` as MTF `TEX` containers. Measured on the extracted No Mercy RomFS
(2026-11-09), the container is `TEX v0xA1` with revision byte `0x20` (RE5's is `0x80`) and the usual 20-byte header
plus a `u32` offset per mip; the mip sizes validate for 16-byte blocks on the BC formats. Format codes seen in
`uPlTex0000_*`:

* ``0x19`` BC4 / ATI1 - the ``_MM`` mask maps (8-byte blocks)
* ``0x1F`` BC5 / ATI2 - the ``_NM`` normal maps (16-byte blocks)
* ``0x2B`` the ``_BM`` colour maps. The community format table calls it BC3_UNORM_SRGB, but decoding the mip as BC3
  (interleaved 8-byte alpha + 8-byte colour blocks) yields a uniform green channel; the block statistics (bytes 0-7
  vary, bytes 8-11 are nearly constant, bytes 12-15 are the constant ``0xAA`` padding pattern) show the 0x2B mip is not
  interleaved BC3 and still needs its own layout. :func:`decode` therefore supports the formats it can prove (BC4/BC5)
  and refuses the rest instead of emitting garbage.
* ``0x09`` / ``0x0E`` - uncoded-looking MVTF/VTF maps.

The decoder de-swizzles with the same Tegra GOB addressing `gbox.mtf_tex` uses (verified: a 512x512 BC5 normal map and a
256x256 BC5 normal map both decode to recognisable fabric/buckle normal maps).
"""
from __future__ import annotations

import struct
import zlib

import numpy as np

TEX_VERSION = 0xA1
REVISIONS = (0x20, 0x80)                     # RE6 Switch / RE5 Switch
BLOCK_BYTES = {0x19: 8, 0x1F: 16, 0x2B: 16}
DECODABLE = {0x1F: ("bc5", 16), 0x19: ("bc4", 8), 0x30: ("bc7", 16), 0x31: ("bc7", 16)}


class TexError(ValueError):
    """The container is not a measured RE6 Switch TEX, or the format cannot be decoded yet."""


class Surface:
    """A parsed TEX header: format, dimensions, mip table and payload offset."""

    def __init__(self, data: bytes):
        data = bytes(data)
        if len(data) < 24 or data[:4] != b"TEX\0":
            raise TexError("not a TEX container")
        if data[4] != TEX_VERSION:
            raise TexError(f"unexpected TEX version 0x{data[4]:02x}")
        if data[5] not in REVISIONS:
            raise TexError(f"unexpected TEX revision 0x{data[5]:02x}")
        self.version, self.revision = data[4], data[5]
        packed, kind, size = struct.unpack_from("<3I", data, 8)
        self.mip_count = packed & 63
        self.width = (packed >> 6) & 0x1FFF
        self.height = packed >> 19
        self.format = (kind >> 8) & 0xFF
        self.size = size
        if kind & 0xFFFF00FF != 0x00010001:
            raise TexError("only one-surface 2D TEX is supported")
        if not self.width or not self.height or self.width & (self.width - 1) or self.height & (self.height - 1):
            raise TexError("only power-of-two TEX dimensions are supported")
        if not 1 <= self.mip_count <= max(self.width, self.height).bit_length():
            raise TexError("invalid TEX mip count")
        self.start = 20 + self.mip_count * 4
        if len(data) != self.start + size:
            raise TexError("TEX payload length disagrees with the header")
        offsets = struct.unpack_from("<" + "I" * self.mip_count, data, 20) + (size,)
        if offsets[0] != 0:
            raise TexError("unexpected TEX first mip offset")
        self.mips = offsets
        self.data = data

    def linear_blocks(self, mip: int = 0) -> bytes:
        """The mip's compressed blocks in linear order, removing the Tegra GOB padding."""
        from . import mtf_tex

        if not 0 <= mip < self.mip_count:
            raise TexError("mip index outside the TEX")
        block = BLOCK_BYTES.get(self.format)
        if block is None:
            raise TexError(f"format 0x{self.format:02x} has no measured block size")
        width, height = max(1, self.width >> mip), max(1, self.height >> mip)
        bx, by = (width + 3) // 4, (height + 3) // 4
        bh = max(1, min(16, (1 << (by - 1).bit_length()) // 8))
        begin, end = self.mips[mip], self.mips[mip + 1]
        level = mtf_tex.Mip(width, height, self.start + begin, end - begin, bh)
        source = np.frombuffer(self.data, dtype=np.uint8, count=end - begin, offset=self.start + begin)
        return source[mtf_tex._addresses(level, block)].tobytes()

    def _albedo_layers(self, mip: int = 0):
        """(detail, tint) for an `0x2B` block: BC4 greyscale (bytes 0-7) and the BC1 half (bytes 8-15)."""
        import texture2ddecoder

        width, height = max(1, self.width >> mip), max(1, self.height >> mip)
        blocks = np.frombuffer(self.linear_blocks(mip), np.uint8).reshape(-1, 16)
        cols = width // 4
        detail = np.zeros((height, width), np.uint8)
        tint = np.zeros((height, width, 3), np.uint8)
        for index, block in enumerate(blocks):
            y, x = divmod(index, cols)
            detail[y * 4:(y + 1) * 4, x * 4:(x + 1) * 4] = np.frombuffer(
                texture2ddecoder.decode_bc4(block[:8].tobytes(), 4, 4), np.uint8).reshape(4, 4, 4)[:, :, 2]
            tint[y * 4:(y + 1) * 4, x * 4:(x + 1) * 4] = np.frombuffer(
                texture2ddecoder.decode_bc1(block[8:].tobytes(), 4, 4), np.uint8).reshape(4, 4, 4)[:, :, [2, 1, 0]]
        return detail, tint

    def decode(self, mip: int = 0):
        """Decode a mip: BC4/BC5/BC7 directly; an `0x2B` albedo yields its **greyscale detail** layer.

        `0x2B` blocks are two channels in 16 bytes: bytes 0-7 decode as BC4 and resolve to the albedo's greyscale
        detail (the head map is a face with a mouth/teeth atlas), bytes 8-15 decode as BC1 and are a low-resolution
        per-4x4-tile colour that is nearly uniform inside a tile. :meth:`_albedo_layers` returns both; the combined
        `tint * detail` is a plausible colourisation but the tint half is not yet proven to be the shader's colour
        (it decodes to a pale yellow-green over the whole face), so `decode` returns the layer that is certain.
        """
        from PIL import Image

        if self.format == 0x2B:
            detail, _tint = self._albedo_layers(mip)
            rgba = np.dstack([np.repeat(detail[..., None], 3, axis=2),
                              np.full(detail.shape, 255, np.uint8)])
            return Image.fromarray(rgba, "RGBA")
        width, height = max(1, self.width >> mip), max(1, self.height >> mip)
        if self.format not in DECODABLE:
            raise TexError(f"format 0x{self.format:02x} is not decoded yet")
        import texture2ddecoder

        name, _block = DECODABLE[self.format]
        blocks = self.linear_blocks(mip)
        if name == "bc5":
            raw = texture2ddecoder.decode_bc5(blocks, width, height)
        elif name == "bc4":
            raw = texture2ddecoder.decode_bc4(blocks, width, height)
        else:
            raw = texture2ddecoder.decode_bc7(blocks, width, height)
        rgba = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)[:, :, [2, 1, 0, 3]]
        return Image.fromarray(rgba, "RGBA")


def parse(data: bytes) -> Surface:
    """Parse an uncompressed TEX payload (ARC zlib wrapping belongs to `mt_arc`)."""
    return Surface(data)


def from_arc_entry(entry) -> Surface:
    """Parse an `mt_arc` entry (zlib-wrapped or raw) as a TEX surface."""
    try:
        raw = zlib.decompress(entry.data)
    except zlib.error:
        raw = entry.data
    return Surface(raw)


def describe_arc(archive) -> list[dict]:
    """Every TEX in an `mt_arc` archive as a row: name, format, dimensions, mips, block size."""
    rows = []
    for entry in archive.entries:
        try:
            surface = from_arc_entry(entry)
        except TexError:
            continue
        rows.append({"name": entry.name.rsplit("\\", 1)[-1], "format": surface.format,
                     "width": surface.width, "height": surface.height, "mips": surface.mip_count,
                     "block_bytes": BLOCK_BYTES.get(surface.format),
                     "decodable": surface.format in DECODABLE})
    return rows
