"""Super Bust-A-Move (USA) PS2: static analysis of the boot ELF ``SLUS_201.15``.

The inventory (`gbox.sbam_inventory`) established the -RA- containers, the CMP3
codec and the TIM2 sprite census.  This module records what disassembly of the
owned executable (MIPS R5900, little-endian) proves about the *loader*, as a
read-only engineering aid. No native replacement writer is provided.

The boot ELF has a single PT_LOAD: file offset ``f`` maps to vaddr ``f + 0xFF000``
(segment offset 0x1000 at vaddr 0x100000), so ``vaddr_to_file(v) = v - 0xFF000``.

Addresses below are candidate function labels in the loaded image. Selected
instruction words and data are checked against this exact build
(ELF sha256 ``eeb913a6…d965``).
"""
from __future__ import annotations

import hashlib
import re
import struct

# --- boot ELF identity -------------------------------------------------------
BOOT_ELF_SHA256 = "eeb913a6eac79a58d8424dc18190310f1ae5d14d762dec5a339f44ad9870d965"
BOOT_ELF_BYTES = 4673508
SEG_OFFSET = 0x1000   # PT_LOAD file offset
SEG_VADDR = 0x100000  # PT_LOAD vaddr
SEG_FILESZ = 0x471DAC

# --- reverse-engineered code/data addresses (vaddr) --------------------------
CMP3_DECODER = 0x1C5880        # Okumura LZSS decompressor; == cmp3_decompress
CMP3_DECODER_END = 0x1C5AFC    # jr $ra
DECOMPRESS_OR_COPY = 0x1C5B08  # per-entry dispatcher (raw vs CMP3)
FILE_TABLE_INIT = 0x1C5D30     # opens a -RA- file, reads count@0x14 + offsets@0x18
ENTRY_GETTER = 0x1C6008        # -> payload pointer for entry[index]
ENTRY_CHECK = 0x1C5BA8         # entry[index] already-loaded flag (0x14-byte record)
DAT_INDEX_TABLE = 0x56D780     # 153 x 0x20 file-name strings, descending
DAT_INDEX_COUNT = 153
DAT_INDEX_STRIDE = 0x20

# The dispatcher compares four bytes against NOCM at 0x571DA0, addressed
# through ELF .reginfo GP 0x5790F0 - 0x7350. Its equal branch copies src+4.
# This does NOT establish that arbitrary raw -RA- audio entries use this route.
RAW_ENTRY_MARKER = b"NOCM"
RAW_ENTRY_MARKER_VADDR = 0x571DA0
CMP3_MAGIC = b"CMP3"

# TIM2 picture header (48 bytes) field layout used by this game's TIM2 library.
#   +0x00 u32 total_size   +0x0C u16 header_size   +0x0E u16 clut_colors
#   +0x10 u8  pict_format  +0x11 u8  mipmaps       +0x12 u8  clut_type
#   +0x13 u8  image_type   +0x14 u16 width         +0x16 u16 height
# image data follows the header; CLUT follows the image.
IMAGE_TYPE_BPP = {1: 16, 2: 24, 3: 32, 4: 4, 5: 8}   # matches sbam_inventory.TIM2_BPP
CLUT_TYPE_32BIT = 3                                   # RGBA8888 (4 bytes/colour)


def vaddr_to_file(v: int) -> int:
    """vaddr -> file offset for the single PT_LOAD segment."""
    if type(v) is not int or not (SEG_VADDR <= v < SEG_VADDR + SEG_FILESZ):
        raise ValueError("vaddr must be an integer inside the pinned PT_LOAD")
    return v - SEG_VADDR + SEG_OFFSET


def file_to_vaddr(f: int) -> int:
    if type(f) is not int or not (SEG_OFFSET <= f < SEG_OFFSET + SEG_FILESZ):
        raise ValueError("file offset must be an integer inside the pinned PT_LOAD")
    return f - SEG_OFFSET + SEG_VADDR


def _require_elf(elf: bytes) -> None:
    if (type(elf) is not bytes or len(elf) != BOOT_ELF_BYTES or
            hashlib.sha256(elf).hexdigest() != BOOT_ELF_SHA256):
        raise ValueError("unsupported boot ELF: exact SLUS_201.15 SHA256 required")


def dat_index_table(elf: bytes) -> list[str]:
    """Exact-build 153-entry DAT file table; modified or truncated ELFs fail."""
    _require_elf(elf)
    f = vaddr_to_file(DAT_INDEX_TABLE)
    out = []
    for i in range(DAT_INDEX_COUNT):
        rec = elf[f + i * DAT_INDEX_STRIDE: f + (i + 1) * DAT_INDEX_STRIDE]
        raw = rec.split(b"\x00", 1)[0]
        if not re.fullmatch(rb"\\DATA\\DATA[0-9A-F]{2}\\DATA[0-9A-F]{2}\.DAT;1", raw):
            raise ValueError("invalid pinned DAT table entry")
        out.append(raw.decode("ascii").replace("\\", "/")[1:-2])
    if len(set(out)) != DAT_INDEX_COUNT:
        raise ValueError("duplicate pinned DAT table entry")
    return out


def dat_index(elf: bytes) -> dict[str, int]:
    """DAT path -> 0-based index into the file-name table."""
    return {name: i for i, name in enumerate(dat_index_table(elf))}


def cmp3_decoder_constant_words(elf: bytes) -> dict:
    """Read the 0xFEE (ring cursor) immediates that pin the CMP3 decoder.

    The decoder explicitly zeroes ring bytes [0, 0xFEE), then sets the cursor at
    0x1C5940; the zero-fill loop bound sits at 0x1C5904.  Returns the raw
    instruction words so a test can assert they carry the 0xFEE immediate.
    """
    _require_elf(elf)
    f_loop = vaddr_to_file(0x1C5904)
    f_cursor = vaddr_to_file(0x1C5940)
    return {
        "zero_fill_bound_word": struct.unpack_from("<I", elf, f_loop)[0],
        "cursor_init_word": struct.unpack_from("<I", elf, f_cursor)[0],
        "zero_fill_bound_imm": struct.unpack_from("<I", elf, f_loop)[0] & 0xFFFF,
        "cursor_init_imm": struct.unpack_from("<I", elf, f_cursor)[0] & 0xFFFF,
    }


def tim2_library_strings(elf: bytes) -> dict[str, int | None]:
    """vaddrs of the TIM2 library debug strings (evidence the game uses a TIM2
    upload lib: ``Tim2CheckFileHeader`` / ``Tim2GetPictureHeader``)."""
    _require_elf(elf)
    marks = {
        # the shipped string carries the upstream typo "Heaer" (not "Header")
        b"Tim2CheckFileHeaer": "Tim2CheckFileHeader",
        b"Tim2GetPictureHeader": "Tim2GetPictureHeader",
        b"TIM2 header broken": "TIM2_header_broken",
    }
    out = {}
    for needle, name in marks.items():
        off = elf.find(needle, SEG_OFFSET, SEG_OFFSET + SEG_FILESZ)
        out[name] = file_to_vaddr(off) if off >= 0 else None
    return out


def loader_marker(elf: bytes) -> bytes:
    """Marker from the exact GP-relative compare; not an inventory codec rule."""
    _require_elf(elf)
    off = vaddr_to_file(RAW_ENTRY_MARKER_VADDR)
    return elf[off:off + 4]


# Bounded offline preview profile, not a universal TIM2/GS renderer.
MAX_PAYLOAD_BYTES = 16 * 1024 * 1024
MAX_PICTURES = 64
MAX_PIXELS = 4 * 1024 * 1024  # aggregate across the file, <=16 MiB decoded RGBA


def tim2_picture_meta(payload: bytes) -> list[dict]:
    """Validate every picture extent before returning any metadata.

    Single-level, linear TIM2 v4 pictures only. Unknown palette layouts remain
    inspectable as metadata but tim2_picture_rgba rejects them explicitly.
    """
    if type(payload) is not bytes or not 16 <= len(payload) <= MAX_PAYLOAD_BYTES:
        raise ValueError("TIM2 payload must be bytes within the 16 MiB limit")
    if payload[:4] != b"TIM2" or payload[4] != 4 or payload[5] not in (0, 1):
        raise ValueError("unsupported TIM2 signature/version/alignment")
    count = struct.unpack_from("<H", payload, 6)[0]
    if not 1 <= count <= MAX_PICTURES:
        raise ValueError("TIM2 picture count outside the supported bound")
    base = 128 if payload[5] == 1 else 16
    out, pixels = [], 0
    for _ in range(count):
        if base + 48 > len(payload):
            raise ValueError("TIM2 picture header past end of data")
        total, clut_size, image_size, header_size, clut_colors = struct.unpack_from(
            "<IIIHH", payload, base)
        pf, mip, clut_type, image_type = payload[base + 16:base + 20]
        width, height = struct.unpack_from("<HH", payload, base + 20)
        tex0 = struct.unpack_from("<Q", payload, base + 24)[0]
        bpp = IMAGE_TYPE_BPP.get(image_type)
        if header_size < 48 or total != header_size + image_size + clut_size:
            raise ValueError("TIM2 inconsistent picture/header/image/CLUT extents")
        if base + total > len(payload):
            raise ValueError("TIM2 picture extends past payload")
        if pf != 0 or mip != 1 or bpp is None:
            raise ValueError("unsupported TIM2 format, mipmaps or image type")
        pixels += width * height
        if not width or not height or pixels > MAX_PIXELS:
            raise ValueError("TIM2 dimensions exceed the aggregate pixel limit")
        if bpp == 4 and width % 2:
            raise ValueError("odd-width 4bpp layout is not verified")
        pixel_bytes = width * height * bpp // 8
        if image_size not in (pixel_bytes, (pixel_bytes + 15) & ~15):
            raise ValueError("TIM2 image size does not match packed/aligned dimensions")
        if any(payload[base + header_size + pixel_bytes:base + header_size + image_size]):
            raise ValueError("TIM2 image tail alignment must contain zero bytes")
        if bpp in (4, 8):
            stride = {1: 2, 2: 3, 3: 4}.get(clut_type & 15)
            if not stride or not clut_colors or clut_size != clut_colors * stride:
                raise ValueError("TIM2 palette size/type/count mismatch")
        elif clut_size or clut_colors or clut_type:
            raise ValueError("direct TIM2 image unexpectedly has a palette")
        out.append({
            "width": width, "height": height, "bpp": bpp,
            "clut_colors": clut_colors, "clut_type": clut_type,
            "image_size": image_size, "clut_size": clut_size,
            "header_size": header_size, "total_size": total, "pixel_bytes": pixel_bytes,
            "offset": base, "image_offset": base + header_size,
            "clut_offset": base + header_size + image_size,
            "image_type": image_type, "gs_tex0": tex0,
        })
        base += total
    if base != len(payload):
        raise ValueError("TIM2 trailing data is outside the verified profile")
    return out


def _display_rgba(raw: bytes) -> bytes:
    # GS alpha 0x80 is 1.0; values above saturate for a conventional preview.
    # This cannot reproduce the game's blend/texture-function state.
    out = bytearray(raw)
    for i in range(3, len(out), 4):
        out[i] = min(255, out[i] * 2)
    return bytes(out)


def tim2_picture_rgba(payload: bytes, picture_index: int = 0) -> tuple[int, int, bytes]:
    """Return bounded display RGBA for the verified single-palette profile.

    Supports even-width linear PSMT4 with exactly 16 RGBA32 colors, PSMT8
    with 256 CSM1 RGBA32 colors, and direct RGBA32. Palette banks, other GS
    layouts and pixel types fail explicitly; no palette bank is guessed.
    This is an offline texture preview, not a native gameplay rendering proof.
    """
    pictures = tim2_picture_meta(payload)
    if type(picture_index) is not int or not 0 <= picture_index < len(pictures):
        raise ValueError("picture index must identify a declared picture")
    p = pictures[picture_index]
    bpp, tex0 = p["bpp"], p["gs_tex0"]
    if bpp not in (4, 8, 32):
        raise ValueError("unsupported preview pixel type")
    if (tex0 >> 20) & 63 != {4: 20, 8: 19, 32: 0}[bpp]:
        raise ValueError("TIM2 GS pixel layout does not match image type")
    start = p["image_offset"]
    img = payload[start:start + p["pixel_bytes"]]
    if bpp == 32:
        return p["width"], p["height"], _display_rgba(img)
    if ((tex0 >> 51) & 15 or (tex0 >> 55) & 1 or (tex0 >> 56) & 31 or
            p["clut_type"] != 3 or p["clut_colors"] != (16 if bpp == 4 else 256)):
        raise ValueError("unsupported palette bank/storage format; selection is unverified")
    start = p["clut_offset"]
    palette = _display_rgba(payload[start:start + p["clut_size"]])
    if bpp == 8:
        # CSM1: interchange blocks 1/2 within each group of 32 palette colors.
        palette = b"".join(palette[j:j + 4] for i in range(256)
                          for j in [((i & ~24) | ((i & 8) << 1) | ((i & 16) >> 1)) * 4])
    out = bytearray(p["width"] * p["height"] * 4)
    for i in range(p["width"] * p["height"]):
        ci = img[i] if bpp == 8 else (img[i // 2] >> ((i & 1) * 4)) & 15
        out[i * 4:i * 4 + 4] = palette[ci * 4:ci * 4 + 4]
    return p["width"], p["height"], bytes(out)


FORMAT_CONSTRAINTS = {
    "image_types": {4: "4bpp indexed", 5: "8bpp indexed", 3: "32bpp direct"},
    "4bpp_packing": "even width, low nibble first (PSMT4)",
    "alpha": "palette/pixel alpha controls transparency; no fixed transparent index",
    "writer_verified": False,
    "character_bank_mapping_verified": False,
}
