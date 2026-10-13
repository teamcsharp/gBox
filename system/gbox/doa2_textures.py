"""DOA2 CHR texture descriptors and native headerless BIN texture payloads.

The CHR word at 0x10 is a texture count, not a bone count. Descriptor data at
u32[2] is [u16 width, u16 height, u8 pixel, u8 format, u16 pad, u32 pointer].
Pointers are relative to the first texture pointer. The flags match the
Dreamcast PVRT pixel/data formats. See NaomiMod/games-ExtractTools DOA2.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from .formats.texture import morton as _twiddle       # shared PowerVR twiddle


@dataclass(frozen=True)
class Texture:
    index: int
    width: int
    height: int
    pixel: int
    format: int
    address: int
    offset: int
    size: int
    capacity: int
    descriptor_offset: int

    @property
    def payload_size(self) -> int:
        """Native image chain, excluding its trailing BIN alignment bytes."""
        return texture_payload_size(self.width, self.height, self.pixel, self.format)


def base_level_offset(width: int, height: int, fmt: int) -> int:
    """Offsets from Flycast's OtherMipPoint and VQMipPoint layouts.

    Raw 16-bit mips start with SIX reserved bytes before the 1x1 level.
    VQ 1x1 and 2x2 each consume one index byte after the 2048-byte book.
    Mipmapped PVR images are square; rectangular chains are not inferred.
    """
    if fmt not in (2, 4):
        return 2048 if fmt == 3 else 0
    if width != height or width <= 0 or width & (width - 1):
        raise ValueError('Native mipmapped textures must be square powers of two')
    offset = 6 if fmt == 2 else 2048
    side = 1
    while side < width:
        offset += 2 * side * side if fmt == 2 else max(1, (side // 2) ** 2)
        side *= 2
    return offset


def texture_payload_size(width: int, height: int, pixel: int, fmt: int) -> int:
    if pixel not in (0, 1, 2):
        raise ValueError(f"Unsupported native pixel format {pixel:#x}")
    if fmt in (3, 4):
        return base_level_offset(width, height, fmt) + max(1, width * height // 4)
    if fmt in (1, 2, 0x0D):
        return base_level_offset(width, height, fmt) + 2 * width * height
    raise ValueError(f"Unsupported native texture format {fmt:#x}")


def texture_size(width: int, height: int, pixel: int, fmt: int) -> int:
    size = texture_payload_size(width, height, pixel, fmt)
    return (size + 31) & ~31 if fmt in (2, 4) else size


def descriptors(chr_data: bytes, bin_data: bytes | int) -> list[Texture]:
    """Read and validate every native descriptor; preserve gaps as padding."""
    bin_size = len(bin_data) if isinstance(bin_data, (bytes, bytearray)) else int(bin_data)
    if len(chr_data) < 24:
        raise ValueError("Truncated CHR")
    header, models, tex, nmodels, count, pad = struct.unpack_from("<6I", chr_data)
    if header != 24 or not count or count > 4096 or tex + count * 12 > len(chr_data):
        raise ValueError("Invalid CHR texture table")
    raw = [struct.unpack_from("<III", chr_data, tex + i * 12) for i in range(count)]
    base = raw[0][2]
    out = []
    for i, (wh, flags, addr) in enumerate(raw):
        w, h, pixel, fmt = wh & 65535, wh >> 16, flags & 255, (flags >> 8) & 255
        if not w or not h or w & (w - 1) or h & (h - 1) or w > 4096 or h > 4096:
            raise ValueError(f"Invalid texture dimensions at slot {i}: {w}x{h}")
        size = texture_size(w, h, pixel, fmt)
        off = addr - base
        end = raw[i + 1][2] - base if i + 1 < count else bin_size
        if off < 0 or end < off or end > bin_size or off + size > end:
            raise ValueError(f"Texture {i} exceeds its BIN allocation")
        out.append(Texture(i, w, h, pixel, fmt, addr, off, size, end - off, tex + i * 12))
    return out


def pvr_chunk(tex: Texture, bin_data: bytes) -> bytes:
    """Supply the omitted PVRT header, leaving native image bytes unchanged."""
    body = bin_data[tex.offset:tex.offset + tex.payload_size]
    if len(body) != tex.payload_size:
        raise ValueError("Truncated BIN texture")
    return b"PVRT" + struct.pack("<IBBHHH", len(body) + 8, tex.pixel, tex.format, 0, tex.width, tex.height) + body


def decode(tex: Texture, bin_data: bytes):
    from gbox.ninja import pvr_decode
    from PIL import Image
    w, h, rgba, _ = pvr_decode(pvr_chunk(tex, bin_data))
    return Image.frombytes("RGBA", (w, h), rgba)


def _pixels16(img: np.ndarray, pix: int) -> np.ndarray:
    a = np.asarray(img, np.uint16)
    if pix == 0:
        return ((a[..., 3] >= 128).astype(np.uint16) << 15) | ((a[..., 0] >> 3) << 10) | ((a[..., 1] >> 3) << 5) | (a[..., 2] >> 3)
    if pix == 1:
        return ((a[..., 0] >> 3) << 11) | ((a[..., 1] >> 2) << 5) | (a[..., 2] >> 3)
    if pix == 2:
        return ((a[..., 3] >> 4) << 12) | ((a[..., 0] >> 4) << 8) | ((a[..., 1] >> 4) << 4) | (a[..., 2] >> 4)
    raise ValueError(f"Unsupported pixel format {pix}")


def encode(tex: Texture, image, iterations: int = 12) -> bytes:
    """Encode native payload at the existing size, including VQ alpha.

    VQ colors include alpha for ARGB formats; gbox.ninja.pvr_vq currently fits
    RGB only. This encoder intentionally retains alpha in its codebook.
    """
    from PIL import Image
    img = np.asarray(image.convert("RGBA").resize((tex.width, tex.height), Image.Resampling.LANCZOS))
    w, h, fmt, pix = tex.width, tex.height, tex.format, tex.pixel
    if fmt in (1, 0x0D):
        packed = _pixels16(img, pix)
        out = bytearray(w * h * 2)
        side = min(w, h)
        for y in range(h):
            for x in range(w):
                block = (y // side) * (w // side) + (x // side)
                j = block * side * side + _twiddle(x % side, y % side)
                struct.pack_into("<H", out, j * 2, int(packed[y, x]))
        return bytes(out)
    if fmt != 3 or w != h:
        raise ValueError("Only square native VQ textures can be encoded")
    # Hardware codebook stores (top-left, bottom-left, top-right, bottom-right).
    channels = 3 if pix == 1 else 4
    work = img[..., :channels].astype(np.float32)
    blocks = np.stack([work[0::2, 0::2], work[1::2, 0::2], work[0::2, 1::2], work[1::2, 1::2]], axis=2).reshape(-1, 4 * channels)
    unique, inverse = np.unique(blocks, axis=0, return_inverse=True)
    rng = np.random.default_rng(0)
    if len(unique) <= 256:
        book = unique
        label = inverse
    else:
        book = unique[rng.choice(len(unique), 256, replace=False)].copy()
        def labels():
            return np.concatenate([((blocks[s:s + 512, None, :] - book[None, ...]) ** 2).sum(2).argmin(1) for s in range(0, len(blocks), 512)])
        for _ in range(max(1, iterations)):
            label = labels()
            for k in range(256):
                mask = label == k
                book[k] = blocks[mask].mean(0) if mask.any() else blocks[rng.integers(len(blocks))]
        label = labels()
    rgba = np.full((256, 4, 4), 255, np.uint8)
    rgba[:len(book), :, :channels] = np.rint(book).clip(0, 255).reshape(-1, 4, channels).astype(np.uint8)
    packed = _pixels16(rgba, pix).astype("<u2").tobytes()
    bw, bh = w // 2, h // 2
    indices = bytearray(bw * bh)
    label = label.reshape(bh, bw)
    for y in range(bh):
        for x in range(bw):
            indices[_twiddle(x, y)] = int(label[y, x])
    return packed + bytes(indices)


def replace(chr_data: bytes, bin_data: bytes, replacements: dict[int, object], iterations: int = 12) -> bytes:
    """Replace selected images in a copy of BIN, preserving all other bytes."""
    textures = descriptors(chr_data, bin_data)
    out = bytearray(bin_data)
    for index, image in replacements.items():
        if not isinstance(index, int) or not 0 <= index < len(textures):
            raise ValueError(f"No native texture slot {index}")
        tex = textures[index]
        payload = encode(tex, image, iterations)
        if len(payload) != tex.size:
            raise ValueError(f"Texture {index} changed its allocated payload size")
        out[tex.offset:tex.offset + tex.size] = payload
    return bytes(out)
