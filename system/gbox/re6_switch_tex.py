"""RE6 (Switch) TEX surfaces: measured format table, header parsing, decode and albedo encode.

The player textures live in `uPlTex####_*.arc` as MTF `TEX` containers. Measured on the extracted No Mercy RomFS
(2026-11-09), the container is `TEX v0xA1` with revision byte `0x20` (RE5's is `0x80`) and the usual 20-byte header
plus a `u32` offset per mip; the mip sizes validate for 16-byte blocks on the BC formats. Format codes seen in
`uPlTex0000_*`:

* ``0x19`` BC4 / ATI1 - the ``_MM`` mask maps (8-byte blocks)
* ``0x1F`` BC5 / ATI2 - the ``_NM`` normal maps (16-byte blocks)
* ``0x2B`` the ``_BM`` albedo maps. Each 16-byte block is **two channels**: bytes 0-7 decode as BC4 and resolve to the
  albedo's greyscale detail (Leon's head map is his face with the mouth/teeth atlas); bytes 8-15 decode as BC1 and hold
  a low-resolution per-4x4-tile colour that is nearly uniform inside a tile. The community format table calls ``0x2B``
  BC3_UNORM_SRGB, which does not decode this layout; the two-half model is what the pixels prove. The detail layer is
  what :meth:`Surface.decode` returns; :meth:`Surface._albedo_layers` exposes both halves and
  :func:`replace_albedo` writes a new mip chain in the same two-half layout.
* ``0x09`` / ``0x0E`` - uncoded-looking MVTF/VTF maps.

The decoder and writer de-swizzle/re-swizzle with the same Tegra GOB addressing `gbox.mtf_tex` uses (verified: a
512x512 BC5 normal map and a 256x256 BC5 normal map both decode to recognisable fabric/buckle normal maps).
"""
from __future__ import annotations

import struct
import zlib

import numpy as np

TEX_VERSION = 0xA1
TITLE_ID = "01002A000CD48000"                # RE6 Switch (No Mercy)
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


def export_textures(romfs, character: str, out_dir, *, formats=(0x2B, 0x1F, 0x19)) -> list[dict]:
    """Write a character's player textures from its `uPlTex####_*.arc` files as PNGs; returns what was written.

    The texture archives are named after the character's two-digit body prefix (`uPl00LeonUsa.arc` -> `uPlTex00*`), so
    a character's whole texture set is every `uPlTex` archive whose digits start with that prefix. Only the measured
    formats are decoded; the rest are listed and skipped.
    """
    from pathlib import Path

    from PIL import Image

    from . import characters as C, mt_arc, skin_swap

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


BODY_MATERIAL_NAMES = ("pl_cloth", "pl_cloth1", "pl_base1", "pl_base2", "pl_skin")


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


def texture_set_materials(archive) -> list[dict]:
    """Every texture-set MRL in an archive with each material's referenced texture indices.

    The material record (72 bytes) carries its name hash at +8, the size of its command region at +12 and the region
    offset at +56. Scanning that region for 32-bit values in ``1..texture_count`` yields the material's texture list in
    table order (indices are 1-based; e.g. ``pl_skin`` -> 4,5,6,7 = hand_NM, hand_BM, pl_Blood_BM, hand_MM and
    ``pl_cloth1`` -> 17..22 = the shirt set). A texture shared by two materials (the blood map) appears in both lists.
    """
    import zlib as _zlib

    out = []
    for entry in archive.entries:
        try:
            raw = _zlib.decompress(entry.data)
        except _zlib.error:
            raw = entry.data
        if raw[:4] != b"MRL\0":
            continue
        magic, version, count, texture_count, shader, texture_offset, material_offset = struct.unpack_from(
            "<4sIIIQQQ", raw)
        paths = []
        for index in range(texture_count):
            offset = texture_offset + index * 88 + 24
            paths.append(raw[offset:offset + 64].split(b"\0", 1)[0].decode("ascii", "replace"))
        materials = []
        for index in range(count):
            offset = material_offset + index * 72
            if offset + 60 > len(raw):
                break
            name_hash = struct.unpack_from("<I", raw, offset + 8)[0]
            size = struct.unpack_from("<I", raw, offset + 12)[0]
            region = struct.unpack_from("<I", raw, offset + 56)[0]
            refs = []
            for position in range(region, min(region + size, len(raw)) - 3, 4):
                value = struct.unpack_from("<I", raw, position)[0]
                if 1 <= value <= texture_count:
                    refs.append(value - 1)
            materials.append({"name_hash": name_hash, "region_size": size,
                              "textures": refs, "paths": [paths[i] for i in refs]})
        out.append({"entry": entry.name.rsplit("\\", 1)[-1], "version": version, "texture_count": texture_count,
                    "paths": paths, "materials": materials})
    return out


def texture_set_mrl(archive) -> dict:
    """The material→texture MRL that every `uPlTex####_*.arc` ends with (`pl0003_0`).

    Measured header: `MRL v36`, 10 materials, 17 textures, texture table at 40 (88-byte records, path at +24) and the
    material table at 1536. The texture paths are full resource paths (`data\\chara\\pl\\pl0000\\model\\pl0000_00head_NM`),
    which is exactly the material→texture binding the body MRL lacks; the material command records still need their
    field layout decoded, so this returns the container facts and the paths only.
    """
    import zlib as _zlib

    entry = archive.entries[-1]
    try:
        raw = _zlib.decompress(entry.data)
    except _zlib.error:
        raw = entry.data
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
                     "decodable": surface.format in DECODABLE or surface.format == 0x2B})
    return rows


# --- writing the two-half albedo -------------------------------------------------

def _quant565(rgb) -> int:
    r, g, b = (int(round(v)) for v in rgb)
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def _expand565(value: int) -> tuple[int, int, int]:
    r = (value >> 11) & 0x1F
    g = (value >> 5) & 0x3F
    b = value & 0x1F
    return (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)


def _bc1_block(tile: np.ndarray) -> bytes:
    """One 8-byte BC1 block (two 565 endpoints, 16 two-bit indices) for a 4x4 RGB tile."""
    flat = tile.reshape(-1, 3).astype(np.int32)
    lo, hi = flat.min(0), flat.max(0)
    c0, c1 = _quant565(hi), _quant565(lo)
    if c0 < c1:
        c0, c1 = c1, c0
    if c0 == c1:
        c0 = min(0xFFFF, c0 + 1)
    a, b = _expand565(c0), _expand565(c1)
    palette = [a, b, tuple((2 * a[i] + b[i]) // 3 for i in range(3)),
               tuple((a[i] + 2 * b[i]) // 3 for i in range(3))]
    diff = np.abs(flat[:, None, :] - np.asarray(palette, np.int32)[None, :, :]).sum(2)
    indices = diff.argmin(1)
    bits = 0
    for pixel, index in enumerate(indices):
        bits |= int(index) << (2 * pixel)
    return struct.pack("<HHI", c0, c1, bits)


def _bc4_block(values: np.ndarray) -> bytes:
    """One 8-byte BC4 block (8-value mode) for a 4x4 uint8 tile."""
    flat = values.reshape(-1).astype(np.int32)
    a0, a1 = int(flat.max()), int(flat.min())
    if a0 == a1:
        a0 = min(255, a1 + 1)
    palette = [a0, a1] + [((5 - i) * a0 + (i + 1) * a1) // 7 for i in range(6)]
    diff = np.abs(flat[:, None] - np.asarray(palette, np.int32)[None, :])
    indices = diff.argmin(1)
    bits = 0
    for pixel, index in enumerate(indices):
        bits |= int(index) << (3 * pixel)
    return bytes((a0, a1)) + bits.to_bytes(6, "little")


def encode_albedo(image) -> bytes:
    """Encode an RGB image as `0x2B` blocks: BC4 greyscale detail (bytes 0-7) + BC1 tile tint (bytes 8-15)."""
    from PIL import Image

    rgb = np.asarray(Image.fromarray(np.asarray(image, np.uint8)).convert("RGB"), np.uint8)
    height, width = rgb.shape[:2]
    # BC blocks cover 4x4 pixels; edge-repeat the last row/column for dimensions that are not multiples of four
    padded_h, padded_w = (height + 3) // 4 * 4, (width + 3) // 4 * 4
    if (padded_h, padded_w) != (height, width):
        rgb = np.pad(rgb, ((0, padded_h - height), (0, padded_w - width), (0, 0)), mode="edge")
    height, width = rgb.shape[:2]
    luminance = ((rgb[..., 0].astype(np.int32) * 299 + rgb[..., 1].astype(np.int32) * 587
                  + rgb[..., 2].astype(np.int32) * 114) // 1000).astype(np.uint8)
    blocks = bytearray()
    for y in range(0, height, 4):
        for x in range(0, width, 4):
            tile = rgb[y:y + 4, x:x + 4]
            average = tile.reshape(-1, 3).mean(0)
            tint = _quant565(average)
            # a flat tile: both endpoints equal, every index 0
            blocks += _bc4_block(luminance[y:y + 4, x:x + 4]) + struct.pack("<HHI", tint, tint, 0)
    return bytes(blocks)


def replace_albedo(template: bytes, image) -> bytes:
    """A TEX with the same header/dimensions/mips as `template` and a new `0x2B` mip chain from `image`.

    The template must be an `0x2B` surface; header fields other than the size and mip offsets are preserved, every mip
    is regenerated (the image is scaled down with Lanczos) and stored in the same Tegra layout the reader expects.
    """
    from . import mtf_tex
    from PIL import Image

    surface = Surface(template)
    if surface.format != 0x2B:
        raise TexError(f"replace_albedo needs a 0x2B template, not 0x{surface.format:02x}")
    base = Image.fromarray(np.asarray(image, np.uint8)).convert("RGB")
    if base.size != (surface.width, surface.height):
        base = base.resize((surface.width, surface.height), Image.LANCZOS)
    payload = bytearray()
    offsets = []
    for mip in range(surface.mip_count):
        width, height = max(1, surface.width >> mip), max(1, surface.height >> mip)
        blocks = encode_albedo(base.resize((width, height), Image.LANCZOS) if mip else base)
        by = (height + 3) // 4
        bh = max(1, min(16, (1 << (by - 1).bit_length()) // 8))
        bx = (width + 3) // 4
        pitch = ((bx * 16 + 63) // 64) * 64
        size = pitch * ((by + 8 * bh - 1) // (8 * bh)) * 8 * bh
        level = mtf_tex.Mip(width, height, 0, size, bh)
        addresses = mtf_tex._addresses(level, 16)
        storage = np.zeros(size, np.uint8)
        data = np.frombuffer(blocks, np.uint8).reshape(-1, 16)
        if len(data) != addresses.shape[0]:
            raise TexError(f"mip {mip}: {len(data)} blocks do not fill {addresses.shape[0]}")
        storage[addresses] = data
        offsets.append(len(payload))
        payload += storage.tobytes()
    header = bytearray(template[:surface.start])
    struct.pack_into("<I", header, 16, len(payload))
    for index, offset in enumerate(offsets):
        struct.pack_into("<I", header, 20 + index * 4, offset)
    return bytes(header + payload)
