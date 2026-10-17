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


# bits per channel (A, R, G, B) of the 16-bit pixel formats: 0 ARGB1555, 1 RGB565, 2 ARGB4444
_BITS = {0: (1, 5, 5, 5), 1: (0, 5, 6, 5), 2: (4, 4, 4, 4)}


def _quantise(v: np.ndarray, bits: int) -> np.ndarray:
    """8-bit channel -> the nearest `bits`-bit level (rounded, not truncated: truncation darkens by up to one
    level and never dithers either way). A 5-bit source widened by bit copy (a DS / N64 colour) comes back exact."""
    top = (1 << bits) - 1
    return (np.asarray(v, np.uint32) * top + 127) // 255


def _pixels16(img: np.ndarray, pix: int) -> np.ndarray:
    a = np.asarray(img)
    if pix not in _BITS:
        raise ValueError(f"Unsupported pixel format {pix}")
    ab, rb, gb, bb = _BITS[pix]
    r, g, b = _quantise(a[..., 0], rb), _quantise(a[..., 1], gb), _quantise(a[..., 2], bb)
    out = (r << (gb + bb)) | (g << bb) | b
    if ab == 1:
        out |= (a[..., 3] >= 128).astype(np.uint32) << 15
    elif ab:
        out |= _quantise(a[..., 3], ab) << 12
    return out.astype(np.uint16)


def _expand16(words: np.ndarray, pix: int) -> np.ndarray:
    """16-bit pixels -> (..., 4) RGBA floats as the PowerVR samples them (gbox.ninja._px)."""
    w = np.asarray(words, np.int64)
    ab, rb, gb, bb = _BITS[pix]
    out = np.empty(w.shape + (4,), np.float32)
    out[..., 0] = ((w >> (gb + bb)) & ((1 << rb) - 1)) * 255 // ((1 << rb) - 1)
    out[..., 1] = ((w >> bb) & ((1 << gb) - 1)) * 255 // ((1 << gb) - 1)
    out[..., 2] = (w & ((1 << bb) - 1)) * 255 // ((1 << bb) - 1)
    out[..., 3] = 255 if ab == 0 else np.where(w & 0x8000, 255, 0) if ab == 1 else ((w >> 12) & 15) * 17
    return out


def fit_image(image, width: int, height: int):
    """The donor image at the slot's size. Area averaging when an axis shrinks, texel replication when it grows: no
    resampling ringing (Lanczos haloes every edge) and no invented in-between colours, so a flat region stays flat
    and a VQ codebook only has to learn the donor's own 2x2 blocks."""
    from PIL import Image
    image = image.convert("RGBA")
    if image.size == (width, height):
        return image
    return image.resize((width, height), Image.Resampling.BOX)


def _nearest(blocks: np.ndarray, book: np.ndarray, step: int = 2048) -> tuple[np.ndarray, np.ndarray]:
    labels, dist = [], []
    bb = (book ** 2).sum(1)
    for s in range(0, len(blocks), step):
        x = blocks[s:s + step]
        d = (x ** 2).sum(1)[:, None] - 2 * x @ book.T + bb[None, :]
        k = d.argmin(1)
        labels.append(k)
        dist.append(np.maximum(d[np.arange(len(x)), k], 0))
    return np.concatenate(labels), np.concatenate(dist)


def vq_codebook(blocks: np.ndarray, size: int = 256, iterations: int = 12, seed: int = 0) -> np.ndarray:
    """Weighted k-means over the distinct 2x2 blocks: k-means++ seeding (spread over every colour the image uses, so
    a small detail such as a button keeps an entry), Lloyd steps until the labels settle (at least `iterations`, at
    most 64), empty entries re-seeded on the worst-served block."""
    unique, counts = np.unique(blocks, axis=0, return_counts=True)
    unique = unique.astype(np.float64)
    if len(unique) <= size:
        return unique
    w = counts.astype(np.float64)
    rng = np.random.default_rng(seed)
    book = np.empty((size, unique.shape[1]))
    book[0] = unique[w.argmax()]
    d = ((unique - book[0]) ** 2).sum(1)
    for k in range(1, size):
        p = w * d
        book[k] = unique[rng.choice(len(unique), p=p / p.sum())] if p.sum() > 0 else unique[rng.integers(len(unique))]
        d = np.minimum(d, ((unique - book[k]) ** 2).sum(1))
    labels = None
    for step in range(max(64, iterations)):
        new, dist = _nearest(unique, book)
        if labels is not None and step >= iterations and (new == labels).all():
            break
        labels = new
        sums = np.zeros_like(book)
        np.add.at(sums, labels, unique * w[:, None])
        tot = np.bincount(labels, weights=w, minlength=size)
        filled = tot > 0
        book[filled] = sums[filled] / tot[filled, None]
        worst = np.argsort(-(dist * w))
        for k, j in zip(np.flatnonzero(~filled), worst):
            book[k] = unique[j]
    return book


def encode(tex: Texture, image, iterations: int = 12) -> bytes:
    """Encode native payload at the existing size, including VQ alpha.

    The image is fitted with fit_image (no resampling ringing), every channel is rounded to the nearest level of
    the 16-bit format and nothing is dithered. VQ colours include alpha for ARGB formats; the codebook is fitted
    with vq_codebook, quantised to the pixel format and every 2x2 block then takes the entry nearest to it as the
    hardware will show it. A donor whose alpha is binary keeps a binary alpha in the codebook.
    """
    img = np.asarray(fit_image(image, tex.width, tex.height))
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
    work = img[..., :channels].astype(np.float64)
    blocks = np.stack([work[0::2, 0::2], work[1::2, 0::2], work[0::2, 1::2], work[1::2, 1::2]], axis=2).reshape(-1, 4 * channels)
    book = vq_codebook(blocks, 256, iterations)
    rgba = np.full((256, 4, 4), 255.0)
    rgba[:len(book), :, :channels] = book.reshape(-1, 4, channels)
    if channels == 4 and np.isin(img[..., 3], (0, 255)).all():
        rgba[..., 3] = np.where(rgba[..., 3] >= 128, 255, 0)
    words = _pixels16(np.rint(rgba).clip(0, 255).astype(np.uint8), pix)
    shown = _expand16(words, pix)[:len(book), :, :channels].reshape(len(book), -1).astype(np.float64)
    label, _ = _nearest(blocks, shown)
    packed = words.astype("<u2").tobytes()
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
