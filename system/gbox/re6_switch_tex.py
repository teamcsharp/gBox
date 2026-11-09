"""RE6 (Switch) TEX surfaces: measured format table, storage layout, decode, and writers for the player textures.

The player textures live in `uPlTex####_*.arc` (and, for the extra costumes, inside the body arc) as MTF `TEX`
containers: `TEX\\0`, the bytes `a1 20 00 20`, packed mips/width/height at +8, `00 01 <format> 01` at +12, the payload
size at +16, one `u32` offset per mip at +20 and the payload. Every mip is stored in the Tegra block-linear layout
(64-byte x 8-row GOBs, the row count padded to `8 * block_height`, padding bytes zero). Measured 2026-11-09 on 119
native surfaces of Leon's sets and body arcs: the layout below reproduces every one of them byte for byte.

Formats (the storage unit is a 4x4 block for the BC formats and one texel for the others):

* ``0x19`` BC4 - the ``_MM`` mask maps (8-byte blocks).
* ``0x1F`` BC5 - the ``_NM`` / ``_DM`` normal maps (16-byte blocks).
* ``0x2B`` **BC3 holding Y'CbCr + alpha** - the ``_BM`` albedo maps. The alpha block (bytes 0-7) is the luma ``Y'``;
  the colour block (bytes 8-15) carries ``Cr`` in red, ``Cb`` in blue (both offset so that neutral is the 5-bit code
  15) and the surface's opacity in green. A grey, opaque tile is therefore the constant block ``c0 = c1 = 0x7FEF``,
  indices ``0xAAAAAAAA`` - the block an earlier reading took for "no colour in the second half". Decoded with the
  BT.601 full-range matrix, Leon's head map is a natural face (skin, pink lips, cream teeth), his eye is blue-grey
  and the effect sheets are orange fire; the same matrix turns the bytes of the earlier textured build (which wrote
  plain RGB there) into the teal quills and pink gloves the live frame showed. The engine's own shader package
  carries exactly these constants (1.402, 0.34414, 0.71414, 1.772 with a 0.5 bias) in its Y'CbCr functions.
* ``0x09`` RGBA8, four bytes a texel - the ``_MVTF`` maps and ``earLight``.
* ``0x0E`` one little-endian ``float32`` a texel - ``pl_VTF`` (128x4: rows 0 and 3 are smooth three-crest waves that
  start and end at zero, rows 1 and 2 are zero; the values are n/255).

``_VTF`` / ``_MVTF`` are **not** colour inputs. The texture-set material binds ``pl_VTF`` to ``tVtxDisplacement``
and the ``_MVTF`` to ``tVtxDispMask`` under ``FVertexDisplacementCurveUV``: they are the cloth's vertex-displacement
curve and its mask ("VTF" = vertex texture fetch). The albedo's own colour is the whole colour path; the material
adds ``CBMaterial.fDiffuseColor`` (1, 1, 1 on every player material measured) and, for ``FColorMaskAlbedoMapModulate``
materials, the blood tint ``CBColorMask.fColorMaskColor`` gated by thresholds that are zero at rest.

Nothing here is live-verified: the model is derived from the native data and from frames of earlier builds.
"""
from __future__ import annotations

import struct
import zlib

import numpy as np

TEX_VERSION = 0xA1
TITLE_ID = "01002A000CD48000"                # RE6 Switch (No Mercy)
REVISIONS = (0x20, 0x80)                     # RE6 Switch / RE5 Switch
BLOCK_BYTES = {0x19: 8, 0x1F: 16, 0x2B: 16}  # 4x4 BC blocks
TEXEL_BYTES = {0x09: 4, 0x0E: 4}             # one storage unit per texel: RGBA8 / float32
DECODABLE = {0x1F: ("bc5", 16), 0x19: ("bc4", 8), 0x30: ("bc7", 16), 0x31: ("bc7", 16)}
HEADER_TAIL = b"\x00\x20"                    # bytes 6-7 of every RE6 Switch TEX measured
#: The 5-bit chroma code of a neutral (grey) tile in native `0x2B` data: `0x7FEF` is R = B = 15, G = 63.
YCC_NEUTRAL = 15.0 / 31.0
NEUTRAL_COLOUR_BLOCK = bytes.fromhex("ef7fef7faaaaaaaa")


class TexError(ValueError):
    """The container is not a measured RE6 Switch TEX, or the format cannot be decoded yet."""


# --- storage layout --------------------------------------------------------------

def unit_of(fmt: int) -> tuple[int, int]:
    """(bytes per storage unit, texels per unit side): 4x4 blocks for the BC formats, single texels otherwise."""
    if fmt in BLOCK_BYTES:
        return BLOCK_BYTES[fmt], 4
    if fmt in TEXEL_BYTES:
        return TEXEL_BYTES[fmt], 1
    raise TexError(f"format 0x{fmt:02x} has no measured storage unit")


def mip_grid(width: int, height: int, fmt: int, mip: int = 0) -> tuple[int, int, int]:
    """(columns, rows, unit bytes) of one mip in storage units."""
    unit, cell = unit_of(fmt)
    w, h = max(1, width >> mip), max(1, height >> mip)
    return (w + cell - 1) // cell, (h + cell - 1) // cell, unit


def _block_height(rows: int) -> int:
    """GOBs per block for a surface of `rows` unit rows (16 from 128 rows up, halving below, never under 1)."""
    return max(1, min(16, (1 << (rows - 1).bit_length()) // 8))


def storage_size(columns: int, rows: int, unit: int) -> int:
    """Stored bytes of one mip: a 64-byte aligned pitch times the rows padded to whole blocks of GOBs."""
    bh = _block_height(rows)
    pitch = ((columns * unit + 63) // 64) * 64
    return pitch * ((rows + 8 * bh - 1) // (8 * bh)) * 8 * bh


def _addresses(columns: int, rows: int, unit: int) -> np.ndarray:
    """Byte addresses of every storage unit, ordered by row then column (shape: units x unit bytes)."""
    bh = _block_height(rows)
    y, x = np.indices((rows, columns), dtype=np.int64)
    x *= unit
    gob_columns = (columns * unit + 63) // 64
    gob = (y // (8 * bh)) * 512 * bh * gob_columns + (x // 64) * 512 * bh + ((y // 8) % bh) * 512
    address = gob + ((x % 64) // 32) * 256 + ((y % 8) // 2) * 64 + ((x % 32) // 16) * 32 + (y % 2) * 16 + x % 16
    return address.reshape(-1, 1) + np.arange(unit)


def pack_tex(fmt: int, width: int, height: int, levels: list[bytes], *, revision: int = 0x20) -> bytes:
    """A TEX container from each mip's units in row-major order (the inverse of `Surface.linear_blocks`).

    The header is written from scratch and the payload in the measured block-linear layout with zero padding;
    repacking the units of a native surface gives the native file back byte for byte.
    """
    if not levels:
        raise TexError("a TEX needs at least one mip")
    payload = bytearray()
    offsets = []
    for mip, level in enumerate(levels):
        columns, rows, unit = mip_grid(width, height, fmt, mip)
        if len(level) != columns * rows * unit:
            raise TexError(f"mip {mip}: {len(level)} bytes do not fill {columns}x{rows} units of {unit}")
        storage = np.zeros(storage_size(columns, rows, unit), np.uint8)
        storage[_addresses(columns, rows, unit)] = np.frombuffer(bytes(level), np.uint8).reshape(-1, unit)
        offsets.append(len(payload))
        payload += storage.tobytes()
    if not (0 < width < 0x2000 and 0 < height < 0x2000 and len(levels) < 64):
        raise TexError("TEX dimensions or mip count outside the packed header field")
    header = (b"TEX\0" + bytes((TEX_VERSION, revision)) + HEADER_TAIL
              + struct.pack("<3I", len(levels) | (width << 6) | (height << 19), 0x00010001 | (fmt << 8), len(payload))
              + struct.pack(f"<{len(offsets)}I", *offsets))
    return header + bytes(payload)


# --- block decoders (numpy only) --------------------------------------------------

def _alpha_tiles(blocks: np.ndarray) -> np.ndarray:
    """BC4 / BC3-alpha blocks (n, 8) -> (n, 4, 4) uint8."""
    b = np.asarray(blocks, np.uint8).reshape(-1, 8)
    a0, a1 = b[:, 0].astype(np.int32), b[:, 1].astype(np.int32)
    bits = np.zeros(len(b), np.uint64)
    for k in range(6):
        bits |= b[:, 2 + k].astype(np.uint64) << np.uint64(8 * k)
    index = np.stack([((bits >> np.uint64(3 * p)) & np.uint64(7)).astype(np.int64) for p in range(16)], 1)
    palette = np.zeros((len(b), 8), np.int32)
    palette[:, 0], palette[:, 1] = a0, a1
    eight = a0 > a1
    for i in range(1, 7):
        palette[:, i + 1] = np.where(eight, ((7 - i) * a0 + i * a1) // 7,
                                     ((5 - i) * a0 + i * a1) // 5 if i < 5 else (0 if i == 5 else 255))
    return np.take_along_axis(palette, index, 1).astype(np.uint8).reshape(-1, 4, 4)


def _expand565(colour: np.ndarray) -> np.ndarray:
    r, g, b = (colour >> 11) & 31, (colour >> 5) & 63, colour & 31
    return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], -1)


def _colour_tiles(blocks: np.ndarray) -> np.ndarray:
    """BC3 colour blocks (n, 8) -> (n, 4, 4, 3) uint8. Inside BC3 the block is always in its four-colour mode."""
    b = np.asarray(blocks, np.uint8).reshape(-1, 8)
    c0 = b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8)
    c1 = b[:, 2].astype(np.int32) | (b[:, 3].astype(np.int32) << 8)
    e0, e1 = _expand565(c0), _expand565(c1)
    palette = np.stack([e0, e1, (2 * e0 + e1) // 3, (e0 + 2 * e1) // 3], 1)
    bits = (b[:, 4].astype(np.uint32) | (b[:, 5].astype(np.uint32) << 8) | (b[:, 6].astype(np.uint32) << 16)
            | (b[:, 7].astype(np.uint32) << 24))
    index = np.stack([((bits >> np.uint32(2 * p)) & np.uint32(3)).astype(np.int64) for p in range(16)], 1)
    return np.take_along_axis(palette, index[:, :, None].repeat(3, 2), 1).astype(np.uint8).reshape(-1, 4, 4, 3)


def _tiles_image(tiles: np.ndarray, width: int, height: int) -> np.ndarray:
    """Row-major 4x4 tiles -> an image cropped to (height, width)."""
    bx, by = (width + 3) // 4, (height + 3) // 4
    tiles = np.asarray(tiles)
    if tiles.ndim == 3:
        image = tiles.reshape(by, bx, 4, 4).transpose(0, 2, 1, 3).reshape(by * 4, bx * 4)
    else:
        channels = tiles.shape[-1]
        image = tiles.reshape(by, bx, 4, 4, channels).transpose(0, 2, 1, 3, 4).reshape(by * 4, bx * 4, channels)
    return image[:height, :width]


def _image_tiles(image: np.ndarray) -> np.ndarray:
    """An image whose sides are multiples of four -> row-major tiles (n, 16[, channels])."""
    height, width = image.shape[:2]
    if image.ndim == 2:
        return image.reshape(height // 4, 4, width // 4, 4).transpose(0, 2, 1, 3).reshape(-1, 16)
    channels = image.shape[2]
    return image.reshape(height // 4, 4, width // 4, 4, channels).transpose(0, 2, 1, 3, 4).reshape(-1, 16, channels)


# --- Y'CbCr (BT.601, full range) ---------------------------------------------------

def rgb_to_ycbcr(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(Y', Cb, Cr) of gamma-space RGB in 0..1: Y' in 0..1, the chroma pair in -0.5..0.5."""
    rgb = np.asarray(rgb, np.float64)
    y = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    return y, (rgb[..., 2] - y) / 1.772, (rgb[..., 0] - y) / 1.402


def ycbcr_to_rgb(y: np.ndarray, cb: np.ndarray, cr: np.ndarray) -> np.ndarray:
    """Gamma-space RGB (clipped to 0..1) from Y' and the chroma pair; the engine's own constants."""
    y, cb, cr = (np.asarray(v, np.float64) for v in (y, cb, cr))
    return np.clip(np.stack([y + 1.402 * cr, y - 0.34414 * cb - 0.71414 * cr, y + 1.772 * cb], -1), 0.0, 1.0)


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

    def mip_size(self, mip: int = 0) -> tuple[int, int]:
        return max(1, self.width >> mip), max(1, self.height >> mip)

    def linear_blocks(self, mip: int = 0) -> bytes:
        """The mip's storage units (BC blocks, or texels) in row-major order, without the GOB padding."""
        if not 0 <= mip < self.mip_count:
            raise TexError("mip index outside the TEX")
        columns, rows, unit = mip_grid(self.width, self.height, self.format, mip)
        begin, end = self.mips[mip], self.mips[mip + 1]
        if end - begin != storage_size(columns, rows, unit):
            raise TexError(f"mip {mip} storage is not the measured block-linear layout")
        source = np.frombuffer(self.data, dtype=np.uint8, count=end - begin, offset=self.start + begin)
        return source[_addresses(columns, rows, unit)].tobytes()

    def texels(self, mip: int = 0) -> np.ndarray:
        """An uncompressed mip: (h, w, 4) uint8 for `0x09`, (h, w) float32 for `0x0E`."""
        width, height = self.mip_size(mip)
        if self.format == 0x09:
            return np.frombuffer(self.linear_blocks(mip), np.uint8).reshape(height, width, 4).copy()
        if self.format == 0x0E:
            return np.frombuffer(self.linear_blocks(mip), "<f4").reshape(height, width).copy()
        raise TexError(f"format 0x{self.format:02x} is not an uncompressed surface")

    def _albedo_layers(self, mip: int = 0):
        """(luma, raw colour block) of an `0x2B` mip: the BC3 alpha block and its untransformed 565 colours."""
        width, height = self.mip_size(mip)
        blocks = np.frombuffer(self.linear_blocks(mip), np.uint8).reshape(-1, 16)
        detail = _tiles_image(_alpha_tiles(blocks[:, :8]), width, height)
        tint = _tiles_image(_colour_tiles(blocks[:, 8:]), width, height)
        return np.ascontiguousarray(detail), np.ascontiguousarray(tint)

    def albedo(self, mip: int = 0, *, bias: float = YCC_NEUTRAL) -> tuple[np.ndarray, np.ndarray]:
        """(RGB, opacity) of an `0x2B` mip as uint8 arrays: Y' from the alpha block, Cr/Cb from red/blue, alpha
        from green.

        ``bias`` is the stored value of zero chroma. Native neutral tiles hold the 5-bit code 15 (15/31), which is
        the default, so a grey native surface decodes to exact grey; the engine's own Y'CbCr functions use 0.5, under
        which the same tiles read about (-6, +4, -7)/255 off grey. The difference is below what the frames at hand
        can separate.
        """
        if self.format != 0x2B:
            raise TexError(f"format 0x{self.format:02x} is not an 0x2B albedo")
        luma, colour = self._albedo_layers(mip)
        colour = colour.astype(np.float64) / 255.0
        rgb = ycbcr_to_rgb(luma.astype(np.float64) / 255.0, colour[..., 2] - bias, colour[..., 0] - bias)
        return (rgb * 255.0 + 0.5).astype(np.uint8), (colour[..., 1] * 255.0 + 0.5).astype(np.uint8)

    def decode(self, mip: int = 0):
        """Decode a mip to an RGBA image: `0x2B` in colour (see :meth:`albedo`), BC4 as grey, BC5 as a normal map
        with its blue rebuilt, `0x09` as stored. `0x0E` holds floats: read it with :meth:`texels`."""
        from PIL import Image

        width, height = self.mip_size(mip)
        if self.format == 0x2B:
            rgb, alpha = self.albedo(mip)
            return Image.fromarray(np.dstack([rgb, alpha]), "RGBA")
        if self.format == 0x09:
            return Image.fromarray(self.texels(mip), "RGBA")
        if self.format not in DECODABLE:
            raise TexError(f"format 0x{self.format:02x} is not decoded yet")
        name, _block = DECODABLE[self.format]
        if name == "bc7":
            raise TexError("BC7 is not used by the RE6 player sets and is not decoded here")
        full = np.full((height, width), 255, np.uint8)
        blocks = np.frombuffer(self.linear_blocks(mip), np.uint8)
        if name == "bc4":
            grey = _tiles_image(_alpha_tiles(blocks.reshape(-1, 8)), width, height)
            return Image.fromarray(np.dstack([grey, grey, grey, full]), "RGBA")
        blocks = blocks.reshape(-1, 16)
        x = _tiles_image(_alpha_tiles(blocks[:, :8]), width, height)
        y = _tiles_image(_alpha_tiles(blocks[:, 8:]), width, height)
        nx, ny = x.astype(np.float64) / 127.5 - 1.0, y.astype(np.float64) / 127.5 - 1.0
        z = np.sqrt(np.clip(1.0 - nx * nx - ny * ny, 0.0, 1.0))
        return Image.fromarray(np.dstack([x, y, (z * 127.5 + 127.5).astype(np.uint8), full]), "RGBA")


def parse(data: bytes) -> Surface:
    """Parse an uncompressed TEX payload (ARC zlib wrapping belongs to `mt_arc`)."""
    return Surface(data)


def _entry_bytes(entry) -> bytes:
    try:
        return zlib.decompress(entry.data)
    except zlib.error:
        return entry.data


def from_arc_entry(entry) -> Surface:
    """Parse an `mt_arc` entry (zlib-wrapped or raw) as a TEX surface."""
    return Surface(_entry_bytes(entry))


def export_textures(romfs, character: str, out_dir, *, formats=(0x2B, 0x1F, 0x19)) -> list[dict]:
    """Write a character's player textures from its `uPlTex####_*.arc` files as PNGs; returns what was written.

    The texture archives are named after the character's two-digit body prefix (`uPl00LeonUsa.arc` -> `uPlTex00*`), so
    a character's whole texture set is every `uPlTex` archive whose digits start with that prefix. Only the measured
    formats are decoded; the rest are listed and skipped.
    """
    from pathlib import Path

    from . import mt_arc, skin_swap

    romfs = Path(romfs)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    known = skin_swap.CHARACTER_ARCS[TITLE_ID]
    if character not in known:
        raise TexError(f"{character!r} is not one of {sorted(known)}")
    prefix = Path(known[character]).name[3:5]
    written = []
    for path in sorted((romfs / "nativeNXx64" / "arc" / "NX").glob(f"uPlTex{prefix}*.arc")):
        arc = mt_arc.parse(path.read_bytes())
        for entry in arc.entries:
            try:
                surface = from_arc_entry(entry)
            except TexError:
                continue
            row = {"character": character, "archive": path.name, "name": entry.name.rsplit("\\", 1)[-1],
                   "format": surface.format, "width": surface.width, "height": surface.height}
            if surface.format not in formats:
                row["skipped"] = "format not decoded"
                written.append(row)
                continue
            image = surface.decode()
            png = out_dir / f"{path.stem}__{row['name']}.png"
            image.convert("RGB").save(png)
            row["png"] = str(png)
            written.append(row)
    return written


# --- texture-set materials ---------------------------------------------------------

BODY_MATERIAL_NAMES = ("pl_cloth", "pl_cloth1", "pl_base1", "pl_base2", "pl_skin", "pl_skin1", "pl_skin2",
                       "pl_skin3")
#: Shader objects a player material binds (names from the title's `AppShaderPackage.mfx`). An MRL names an object by
#: `(crc32(name) ^ 0xFFFFFFFF) & 0xFFFFF` in its upper 20 bits and the object's package index in the lower 12.
TEXTURE_SLOTS = ("tAlbedoMap", "tNormalMap", "tSpecularMap", "tDetailNormalMap", "tDetailNormalMap2",
                 "tAlbedoBlendMap", "tAlbedoBlend2Map", "tNormalBlendMap", "tVtxDisplacement", "tVtxDispMask",
                 "tHairShiftMap", "tTransparencyMap", "tEnvMap", "tEmissionMap", "tSphereMap")
FUNCTION_NAMES = ("FAlbedo", "FAlbedoMap", "FAlbedoMap2", "FAlbedoMapModulate", "FAlbedo2MapModulate",
                  "FBlendAlbedoMap", "FColorMaskAlbedoMapModulate", "FVertexDisplacement",
                  "FVertexDisplacementCurveU", "FVertexDisplacementCurveV", "FVertexDisplacementCurveUV",
                  "FVertexDisplacementDirU", "FTransparency", "FTransparencyAlpha", "FTransparencyMap",
                  "FTransparencyVolume", "FDiffuse", "FDiffuseVertexColorOcclusion", "FBump",
                  "FBumpDetailNormalMap", "FSpecular", "FSpecular2Map")
#: Constant buffers and their fields as (name, first float, float count), from the package's own definitions.
CONSTANT_BUFFERS = {
    "CBMaterial": (32, (("fDiffuseColor", 0, 3), ("fTransparency", 3, 1), ("fReflectiveColor", 4, 3),
                        ("fTransparencyVolume", 7, 1), ("fUVTransform", 8, 8), ("fUVTransform2", 16, 8),
                        ("fUVTransform3", 24, 8))),
    "CBColorMask": (24, (("fColorMaskThreshold", 0, 4), ("fColorMaskOffset", 4, 4), ("fClipThreshold", 8, 4),
                         ("fColorMaskColor", 12, 4), ("fColorMask2Threshold", 16, 4),
                         ("fColorMask2Color", 20, 4))),
    "CBVertexDisplacement": (8, (("fVtxDispStart", 0, 1), ("fVtxDispScale", 1, 1), ("fVtxDispInvArea", 2, 1),
                                 ("fVtxDispRCN", 3, 1), ("fVtxDispTiltU", 4, 1), ("fVtxDispTiltV", 5, 3))),
}
STATE_NAMES = ("BSSolid", "BSBlendAlpha", "DSZTestWrite", "DSZTest", "RSMesh")   # the render states measured
COMMAND_BYTES = 24                           # u32 info (kind in the low 4 bits), u32 pad, u64 value, u32 object, u32 pad
KIND_FUNCTION, KIND_CONSTANTS, KIND_SAMPLER, KIND_TEXTURE = 0, 1, 2, 3


def object_hash(name: str) -> int:
    """The 20-bit name hash in the upper bits of an MRL shader-object id."""
    return (zlib.crc32(name.encode()) ^ 0xFFFFFFFF) & 0xFFFFF


_KNOWN_OBJECTS = {object_hash(name): name
                  for name in TEXTURE_SLOTS + FUNCTION_NAMES + STATE_NAMES + tuple(CONSTANT_BUFFERS)}


def shader_objects(package: bytes) -> dict[int, str]:
    """{MRL object id: name} for every object of an `AppShaderPackage.mfx` (the full table; optional).

    Measured layout: `MFX\\0`, an id word at +8 (the value an MRL repeats in its header), the object count at +12,
    the string table offset at +16 and `u64` object offsets from +24 (entry 0 is null). An object starts with its
    name's string offset; its id is the 20-bit name hash shifted over its index.
    """
    package = bytes(package)
    if package[:4] != b"MFX\0":
        raise TexError("not a shader package")
    count, strings = struct.unpack_from("<II", package, 12)
    out = {}
    for index in range(1, count):
        offset = struct.unpack_from("<Q", package, 24 + index * 8)[0]
        name_at = strings + struct.unpack_from("<Q", package, offset)[0]
        name = package[name_at:package.index(b"\0", name_at)].decode("latin1")
        out[(object_hash(name) << 12) | index] = name
    return out


def _object_name(value: int, objects: dict[int, str] | None) -> str | None:
    if objects is not None and value in objects:
        return objects[value]
    return _KNOWN_OBJECTS.get(value >> 12)


def body_albedo_paths(archive) -> dict[str, list[str]]:
    """{body material name: its `_BM` texture paths} from the archive's texture-set MRLs.

    This is the body-material half of the binding: `pl_base2` -> shoes, `pl_skin` -> hands, `pl_base1` -> bottom,
    `pl_cloth1` -> shirts, and the unnamed materials cover the vest/leather/holster sets. It lets a caller replace only
    the albedos the body materials actually sample instead of every `_BM` in the character's texture set.
    """
    names = {zlib.crc32(name.encode()) ^ 0xFFFFFFFF: name for name in BODY_MATERIAL_NAMES}
    out: dict[str, list[str]] = {}
    for texture_set in texture_set_materials(archive):
        for material in texture_set["materials"]:
            name = names.get(material["name_hash"])
            if name is None:
                continue
            for path in material["paths"]:
                if path.endswith("_BM") and path not in out.get(name, []):
                    out.setdefault(name, []).append(path)
    return out


def texture_set_materials(archive, *, objects: dict[int, str] | None = None) -> list[dict]:
    """Every texture-set MRL in an archive with each material's bindings.

    The material record (72 bytes) carries its name hash at +8, the size of its command buffer at +12, the command
    count in the low 12 bits of the word at +28 and the buffer offset at +56. The buffer starts with 24-byte commands
    (kind, value, shader object) and is followed by the constant buffers the commands point into. A texture command's
    value is the **1-based** index into the MRL's texture table (0 = unbound), so each material gets:

    * ``textures`` / ``paths`` - every texture it references, in buffer order (e.g. ``pl_skin`` -> hand NM, hand BM,
      the shared blood map, hand MM);
    * ``slots`` - {shader slot: path or None}: ``tAlbedoMap`` is the albedo the surface is drawn with,
      ``tVtxDisplacement`` / ``tVtxDispMask`` the cloth displacement curve and mask (`pl_VTF`, `_MVTF`);
    * ``functions`` - {selector: chosen function}, e.g. ``FAlbedo`` -> ``FColorMaskAlbedoMapModulate``;
    * ``constants`` - the decoded ``CBMaterial`` / ``CBColorMask`` / ``CBVertexDisplacement`` values.

    Names come from ``objects`` (:func:`shader_objects`) when given, else from the names measured for this title.
    """
    out = []
    for entry in archive.entries:
        raw = _entry_bytes(entry)
        if raw[:4] != b"MRL\0":
            continue
        magic, version, count, texture_count, shader, texture_offset, material_offset = struct.unpack_from(
            "<4sIIIQQQ", raw)
        paths = []
        for index in range(texture_count):
            offset = texture_offset + index * 88 + 24
            paths.append(raw[offset:offset + 64].split(b"\0", 1)[0].decode("ascii", "replace"))
        known = {zlib.crc32(name.encode()) ^ 0xFFFFFFFF: name for name in BODY_MATERIAL_NAMES}
        materials = []
        for index in range(count):
            offset = material_offset + index * 72
            if offset + 72 > len(raw):
                break
            name_hash, size, blend, depth, raster = struct.unpack_from("<5I", raw, offset + 8)
            commands = struct.unpack_from("<I", raw, offset + 28)[0] & 0xFFF
            region = struct.unpack_from("<Q", raw, offset + 56)[0]
            refs = []
            for position in range(region, min(region + size, len(raw)) - 3, 4):
                value = struct.unpack_from("<I", raw, position)[0]
                if 1 <= value <= texture_count:
                    refs.append(value - 1)
            slots: dict[str, str | None] = {}
            functions: dict[str, str] = {}
            constants: dict[str, dict] = {}
            for command in range(commands):
                at = region + command * COMMAND_BYTES
                if at + COMMAND_BYTES > len(raw):
                    break
                info, _pad, value, target, _pad2 = struct.unpack_from("<IIQII", raw, at)
                kind, name = info & 0xF, _object_name(target, objects)
                if name is None:
                    continue
                if kind == KIND_TEXTURE:
                    slots[name] = paths[value - 1] if 1 <= value <= texture_count else None
                elif kind == KIND_FUNCTION:
                    functions[name] = _object_name(value & 0xFFFFFFFF, objects) or f"0x{value & 0xFFFFFFFF:08x}"
                elif kind == KIND_CONSTANTS and name in CONSTANT_BUFFERS:
                    floats, fields = CONSTANT_BUFFERS[name]
                    if region + value + floats * 4 <= len(raw):
                        values = struct.unpack_from(f"<{floats}f", raw, region + value)
                        constants[name] = {field: list(values[first:first + length])
                                           for field, first, length in fields}
            materials.append({"name_hash": name_hash, "name": known.get(name_hash), "region_size": size,
                              "blend": _object_name(blend, objects), "depth": _object_name(depth, objects),
                              "raster": _object_name(raster, objects),
                              "textures": refs, "paths": [paths[i] for i in refs],
                              "slots": slots, "functions": functions, "constants": constants})
        out.append({"entry": entry.name.rsplit("\\", 1)[-1], "version": version, "shader": shader,
                    "texture_count": texture_count, "paths": paths, "materials": materials})
    return out


def material_bindings(archive, material: str, *, objects: dict[int, str] | None = None) -> dict | None:
    """The first texture-set material named ``material`` in the archive (its slots, functions, constants)."""
    wanted = zlib.crc32(material.encode()) ^ 0xFFFFFFFF
    for texture_set in texture_set_materials(archive, objects=objects):
        for row in texture_set["materials"]:
            if row["name_hash"] == wanted and row["slots"]:
                return row | {"name": material, "mrl": texture_set["entry"]}
    return None


def texture_set_mrl(archive) -> dict:
    """The material→texture MRL that every `uPlTex####_*.arc` ends with (`pl0003_0`).

    Measured header: `MRL v36`, 10 materials, 17 textures, texture table at 40 (88-byte records, path at +24) and the
    material table at 1536. The texture paths are full resource paths (`data\\chara\\pl\\pl0000\\model\\pl0000_00head_NM`),
    which is exactly the material→texture binding the body MRL lacks; :func:`texture_set_materials` decodes the
    material side.
    """
    entry = archive.entries[-1]
    raw = _entry_bytes(entry)
    if raw[:4] != b"MRL\0":
        raise TexError("the archive does not end with the texture-set MRL")
    magic, version, count, texture_count, shader, texture_offset, material_offset = struct.unpack_from(
        "<4sIIIQQQ", raw)
    paths = []
    for index in range(texture_count):
        offset = texture_offset + index * 88 + 24
        if offset + 64 > len(raw):
            raise TexError("texture path record runs outside the MRL")
        paths.append(raw[offset:offset + 64].split(b"\0", 1)[0].decode("ascii", "replace"))
    return {"entry": entry.name.rsplit("\\", 1)[-1], "version": version, "materials": count,
            "textures": texture_count, "shader": shader, "texture_offset": texture_offset,
            "material_offset": material_offset, "paths": paths}


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
                     "texel_bytes": TEXEL_BYTES.get(surface.format),
                     "decodable": surface.format in (0x19, 0x1F, 0x2B, 0x09)})
    return rows


# --- writing the albedo (BC3: luma in alpha, Cr / opacity / Cb in the colour block) ----------------

def _encode_alpha_tiles(tiles: np.ndarray) -> np.ndarray:
    """(n, 16) uint8 -> (n, 8) BC4 blocks in the eight-value mode; a flat tile is `v v 00 00 00 00 00 00` as in
    native data."""
    values = np.asarray(tiles, np.uint8).reshape(-1, 16).astype(np.int32)
    a0, a1 = values.max(1), values.min(1)
    palette = np.empty((len(values), 8), np.int32)
    palette[:, 0], palette[:, 1] = a0, a1
    for i in range(1, 7):
        palette[:, i + 1] = ((7 - i) * a0 + i * a1) // 7
    index = np.abs(values[:, :, None] - palette[:, None, :]).argmin(2)
    index[a0 == a1] = 0
    bits = np.zeros(len(values), np.uint64)
    for pixel in range(16):
        bits |= index[:, pixel].astype(np.uint64) << np.uint64(3 * pixel)
    out = np.empty((len(values), 8), np.uint8)
    out[:, 0], out[:, 1] = a0, a1
    for k in range(6):
        out[:, 2 + k] = ((bits >> np.uint64(8 * k)) & np.uint64(0xFF)).astype(np.uint8)
    return out


def _encode_colour_tiles(tiles: np.ndarray) -> np.ndarray:
    """(n, 16, 3) floats in 0..1 -> (n, 8) four-colour BC1 blocks with `c0 >= c1`.

    The endpoints are the extremes along each tile's principal axis, quantised to 5:6:5; a tile whose endpoints
    quantise to one colour is written flat with the index word `0xAAAAAAAA`, which is the native flat block.
    """
    tiles = np.clip(np.asarray(tiles, np.float64).reshape(-1, 16, 3), 0.0, 1.0)
    mean = tiles.mean(1)
    centred = tiles - mean[:, None, :]
    covariance = np.einsum("npi,npj->nij", centred, centred)
    _values, vectors = np.linalg.eigh(covariance)
    axis = vectors[:, :, 2]
    along = np.einsum("npi,ni->np", centred, axis)
    ends = np.stack([mean + axis * along.max(1)[:, None], mean + axis * along.min(1)[:, None]], 1)
    ends = np.clip(ends, 0.0, 1.0)
    scale = np.array([31.0, 63.0, 31.0])
    codes = np.floor(ends * scale + 0.5 + 1e-9).astype(np.int64)
    packed = (codes[..., 0] << 11) | (codes[..., 1] << 5) | codes[..., 2]
    c0, c1 = packed.max(1), packed.min(1)
    e0, e1 = _expand565(c0).astype(np.float64), _expand565(c1).astype(np.float64)
    palette = np.stack([e0, e1, (2 * e0 + e1) // 3, (e0 + 2 * e1) // 3], 1) / 255.0
    distance = ((tiles[:, :, None, :] - palette[:, None, :, :]) ** 2).sum(-1)
    index = distance.argmin(2)
    index[c0 == c1] = 2
    bits = np.zeros(len(tiles), np.uint32)
    for pixel in range(16):
        bits |= index[:, pixel].astype(np.uint32) << np.uint32(2 * pixel)
    out = np.empty((len(tiles), 8), np.uint8)
    out[:, 0], out[:, 1] = c0 & 0xFF, c0 >> 8
    out[:, 2], out[:, 3] = c1 & 0xFF, c1 >> 8
    for k in range(4):
        out[:, 4 + k] = ((bits >> np.uint32(8 * k)) & np.uint32(0xFF)).astype(np.uint8)
    return out


def _padded_rgba(image) -> np.ndarray:
    """An image as (h, w, 4) uint8 with both sides padded to multiples of four by repeating the edge texels."""
    from PIL import Image

    source = image if isinstance(image, Image.Image) else Image.fromarray(np.asarray(image, np.uint8))
    rgba = np.asarray(source.convert("RGBA"), np.uint8)
    height, width = rgba.shape[:2]
    padded_h, padded_w = (height + 3) // 4 * 4, (width + 3) // 4 * 4
    if (padded_h, padded_w) != (height, width):
        rgba = np.pad(rgba, ((0, padded_h - height), (0, padded_w - width), (0, 0)), mode="edge")
    return rgba


def encode_albedo(image, *, chroma: bool = True, opacity: bool = False, bias: float = YCC_NEUTRAL) -> bytes:
    """Encode an image as `0x2B` blocks: BC3 with Y' in the alpha block and (Cr, opacity, Cb) in the colour block.

    ``chroma=False`` writes the image's luma only, with the neutral colour block: every tile's second half is then
    exactly the native constant block (`c0 = c1 = 0x7FEF`, indices `0xAAAAAAAA`) and the surface reads as greyscale.
    ``opacity=True`` takes the green channel from the image's alpha; by default the surface is opaque (63), as every
    native body albedo is. Colours are gamma-space values, as stored by the native maps.
    """
    rgba = _padded_rgba(image)
    rgb = rgba[..., :3].astype(np.float64) / 255.0
    luma, cb, cr = rgb_to_ycbcr(rgb)
    luma8 = np.clip(np.floor(luma * 255.0 + 0.5), 0, 255).astype(np.uint8)
    if not chroma:
        cb = np.zeros_like(cb)
        cr = np.zeros_like(cr)
    green = rgba[..., 3].astype(np.float64) / 255.0 if opacity else np.ones_like(luma)
    colour = np.stack([cr + bias, green, cb + bias], -1)
    blocks = np.concatenate([_encode_alpha_tiles(_image_tiles(luma8)),
                             _encode_colour_tiles(_image_tiles(colour))], 1)
    return blocks.tobytes()


def replace_albedo(template: bytes, image, *, chroma: bool = True, opacity: bool = False) -> bytes:
    """A TEX with the same dimensions and mip count as `template` and a new `0x2B` mip chain from `image`.

    The template must be an `0x2B` surface; every mip is regenerated (the image is scaled down with Lanczos) and
    stored in the measured layout. See :func:`encode_albedo` for ``chroma`` / ``opacity``.
    """
    from PIL import Image

    surface = Surface(template)
    if surface.format != 0x2B:
        raise TexError(f"replace_albedo needs a 0x2B template, not 0x{surface.format:02x}")
    source = image if isinstance(image, Image.Image) else Image.fromarray(np.asarray(image, np.uint8))
    base = source.convert("RGBA" if opacity else "RGB")
    if base.size != (surface.width, surface.height):
        base = base.resize((surface.width, surface.height), Image.LANCZOS)
    levels = []
    for mip in range(surface.mip_count):
        width, height = surface.mip_size(mip)
        levels.append(encode_albedo(base.resize((width, height), Image.LANCZOS) if mip else base,
                                    chroma=chroma, opacity=opacity))
    return pack_tex(0x2B, surface.width, surface.height, levels, revision=surface.revision)


def solid_albedo(template: bytes, rgb) -> bytes:
    """`template` (an `0x2B` TEX) refilled with one opaque colour, encoded through the Y'CbCr path."""
    surface = Surface(template)
    colour = np.empty((surface.height, surface.width, 3), np.uint8)
    colour[...] = np.asarray(rgb, np.uint8)
    return replace_albedo(template, colour)


# --- writing the uncompressed formats (`0x09` RGBA8, `0x0E` float32) -------------------------------

def _box_chain(pixels: np.ndarray, levels: int) -> list[np.ndarray]:
    """`levels` mips of a float image, each the 2x2 box filter of the one above (as the native chains are)."""
    height, width = pixels.shape[:2]
    if width & (width - 1) or height & (height - 1):
        raise TexError("only power-of-two surfaces are written")
    if not 1 <= levels <= max(width, height).bit_length():
        raise TexError("invalid mip count for the surface")
    chain = [pixels]
    for _ in range(1, levels):
        top = chain[-1]
        if top.shape[0] > 1:
            top = (top[0::2] + top[1::2]) / 2.0
        if top.shape[1] > 1:
            top = (top[:, 0::2] + top[:, 1::2]) / 2.0
        chain.append(top)
    return chain


def rgba8_tex(pixels, *, mips: int | None = None, revision: int = 0x20) -> bytes:
    """An `0x09` (RGBA8) TEX from an (h, w, 4) array; the mip chain is box-filtered down to 1x1 unless `mips` is
    given. Native `_MVTF` masks are grey in RGB with alpha 255."""
    array = np.asarray(pixels)
    if array.ndim != 3 or array.shape[2] != 4:
        raise TexError("rgba8_tex needs an (h, w, 4) array")
    height, width = array.shape[:2]
    count = max(width, height).bit_length() if mips is None else int(mips)
    chain = _box_chain(array.astype(np.float64), count)
    levels = [np.clip(np.floor(level + 0.5), 0, 255).astype(np.uint8).tobytes() for level in chain]
    return pack_tex(0x09, width, height, levels, revision=revision)


def float_tex(values, *, mips: int = 1, revision: int = 0x20) -> bytes:
    """An `0x0E` TEX (one little-endian float32 a texel) from an (h, w) array; one mip, as `pl_VTF` has."""
    array = np.asarray(values, np.float64)
    if array.ndim != 2:
        raise TexError("float_tex needs an (h, w) array")
    height, width = array.shape
    levels = [level.astype("<f4").tobytes() for level in _box_chain(array, int(mips))]
    return pack_tex(0x0E, width, height, levels, revision=revision)


def replace_texels(template: bytes, values) -> bytes:
    """A TEX with `template`'s format, size and mip count holding `values` (`0x09`: (h, w, 4); `0x0E`: (h, w))."""
    surface = Surface(template)
    array = np.asarray(values)
    if array.shape[:2] != (surface.height, surface.width):
        raise TexError(f"values are {array.shape[:2]}, the TEX is {(surface.height, surface.width)}")
    if surface.format == 0x09:
        return rgba8_tex(array, mips=surface.mip_count, revision=surface.revision)
    if surface.format == 0x0E:
        return float_tex(array, mips=surface.mip_count, revision=surface.revision)
    raise TexError(f"format 0x{surface.format:02x} is not an uncompressed surface")
