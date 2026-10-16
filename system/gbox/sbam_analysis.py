"""Super Bust-A-Move (USA) PS2: static analysis of the boot ELF ``SLUS_201.15``.

The inventory (`gbox.sbam_inventory`) established the -RA- containers, the CMP3
codec and the TIM2 sprite census.  This module records what disassembly of the
owned executable (MIPS R5900, little-endian) proves about the *loader*, so a
same-size sprite writer can target the right structures.

The boot ELF has a single PT_LOAD: file offset ``f`` maps to vaddr ``f + 0xFF000``
(segment offset 0x1000 at vaddr 0x100000), so ``vaddr_to_file(v) = v - 0xFF000``.

Addresses below are vaddrs in the loaded image and were verified with capstone
(CS_MODE_MIPS32 | CS_MODE_LITTLE_ENDIAN); they are stable for this exact build
(ELF sha256 ``eeb913a6…d965``).
"""
from __future__ import annotations

import struct

# --- boot ELF identity -------------------------------------------------------
BOOT_ELF_SHA256 = "eeb913a6eac79a58d8424dc18190310f1ae5d14d762dec5a339f44ad9870d965"
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

# The loader treats an entry whose first 4 bytes are 0x00000000 as *raw* and
# copies src+4.. (VB ADPCM bodies open with a 16-byte zero block); every other
# entry is decompressed as CMP3 ("CMP3" + u32 decoded_size + LZSS).  This is the
# complement of the inventory's "starts with CMP3 -> compressed" rule and matters
# for the writer: a raw entry MUST begin with 4 zero bytes, a compressed entry
# must NOT (it begins with "CMP3").
RAW_ENTRY_MARKER = b"\x00\x00\x00\x00"
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
    if not (SEG_VADDR <= v < SEG_VADDR + SEG_FILESZ):
        raise ValueError("vaddr 0x%x outside PT_LOAD" % v)
    return v - SEG_VADDR + SEG_OFFSET


def file_to_vaddr(f: int) -> int:
    if not (SEG_OFFSET <= f < SEG_OFFSET + SEG_FILESZ):
        raise ValueError("file offset 0x%x outside PT_LOAD" % f)
    return f - SEG_OFFSET + SEG_VADDR


def dat_index_table(elf: bytes) -> list[str]:
    """The 153-entry DAT file-name table at ``DAT_INDEX_TABLE`` (descending)."""
    f = vaddr_to_file(DAT_INDEX_TABLE)
    out = []
    for i in range(DAT_INDEX_COUNT):
        rec = elf[f + i * DAT_INDEX_STRIDE: f + (i + 1) * DAT_INDEX_STRIDE]
        raw = rec.split(b"\x00", 1)[0].decode("ascii", "replace")
        name = raw.replace("\\", "/").lstrip("/").split(";", 1)[0]
        out.append(name)
    return out


def dat_index(elf: bytes) -> dict[str, int]:
    """DAT path -> 0-based index into the file-name table."""
    return {name: i for i, name in enumerate(dat_index_table(elf))}


def cmp3_decoder_constant_words(elf: bytes) -> dict:
    """Read the 0xFEE (ring cursor) immediates that pin the CMP3 decoder.

    The decoder zeroes the 4 KiB ring then sets the write cursor to 0xFEE at
    0x1C5940; the zero-fill loop bound sits at 0x1C5904.  Returns the raw
    instruction words so a test can assert they carry the 0xFEE immediate.
    """
    f_loop = vaddr_to_file(0x1C5904)
    f_cursor = vaddr_to_file(0x1C5940)
    return {
        "zero_fill_bound_word": struct.unpack_from("<I", elf, f_loop)[0],
        "cursor_init_word": struct.unpack_from("<I", elf, f_cursor)[0],
        "zero_fill_bound_imm": struct.unpack_from("<I", elf, f_loop)[0] & 0xFFFF,
        "cursor_init_imm": struct.unpack_from("<I", elf, f_cursor)[0] & 0xFFFF,
    }


def tim2_library_strings(elf: bytes) -> dict[str, int]:
    """vaddrs of the TIM2 library debug strings (evidence the game uses a TIM2
    upload lib: ``Tim2CheckFileHeader`` / ``Tim2GetPictureHeader``)."""
    marks = {
        # the shipped string carries the upstream typo "Heaer" (not "Header")
        b"Tim2CheckFileHeaer": "Tim2CheckFileHeader",
        b"Tim2GetPictureHeader": "Tim2GetPictureHeader",
        b"TIM2 header broken": "TIM2_header_broken",
    }
    out = {}
    for needle, name in marks.items():
        off = elf.find(needle)
        out[name] = file_to_vaddr(off) if off >= 0 else None
    return out


# --- TIM2 decode (the actionable format probe) -------------------------------
def _clut_rgba(clut: bytes, clut_type: int, count: int) -> bytes:
    """Decode a CLUT to RGBA8888 bytes (count * 4)."""
    if clut_type == CLUT_TYPE_32BIT:          # RGBA8888, 4 bytes/colour
        return clut[: count * 4]
    if clut_type == 1:                        # RGBA5551, 2 bytes/colour
        out = bytearray()
        for i in range(count):
            v = struct.unpack_from("<H", clut, i * 2)[0]
            r = (v & 0x1F) << 3
            g = ((v >> 5) & 0x1F) << 3
            b = ((v >> 10) & 0x1F) << 3
            a = 0xFF if (v >> 15) else 0
            out += bytes((r, g, b, a))
        return bytes(out)
    raise ValueError("unsupported clut_type %d" % clut_type)


def tim2_picture_rgba(payload: bytes, picture_index: int = 0) -> tuple[int, int, bytes]:
    """Decode one TIM2 picture to ``(width, height, RGBA8888 bytes)``.

    Supports 4bpp (16-colour CLUT), 8bpp (256-colour CLUT) and 32bpp direct.
    4bpp pixels are packed low-nibble-first (PS2 PSMCT4: left pixel in the low
    nibble).
    """
    if payload[:4] != b"TIM2" or len(payload) < 16:
        raise ValueError("not a TIM2 file")
    fmt = payload[5]
    count = struct.unpack_from("<H", payload, 6)[0]
    base = 128 if fmt == 1 else 16
    for idx in range(count):
        if base + 48 > len(payload):
            raise ValueError("TIM2 picture header past end of data")
        total, clut_size, image_size, header_size, clut_colors = struct.unpack_from(
            "<IIIHH", payload, base
        )
        _pict_format, _mipmaps, clut_type, image_type = payload[base + 16: base + 20]
        width, height = struct.unpack_from("<HH", payload, base + 20)
        if idx != picture_index:
            base += total
            continue
        img = payload[base + header_size: base + header_size + image_size]
        clut = payload[base + header_size + image_size:
                       base + header_size + image_size + clut_size]
        bpp = IMAGE_TYPE_BPP.get(image_type)
        if bpp is None:
            raise ValueError("unsupported image_type %d" % image_type)
        rgba = bytearray(width * height * 4)
        if bpp == 4:
            palette = _clut_rgba(clut, clut_type, clut_colors)
            for y in range(height):
                row = img[y * (width // 2): (y + 1) * (width // 2)]
                for x in range(width):
                    b = row[x // 2]
                    ci = (b & 0xF) if (x & 1) == 0 else (b >> 4)
                    rgba[(y * width + x) * 4:(y * width + x) * 4 + 4] = palette[ci * 4: ci * 4 + 4]
        elif bpp == 8:
            palette = _clut_rgba(clut, clut_type, clut_colors)
            for y in range(height):
                row = img[y * width: (y + 1) * width]
                for x in range(width):
                    ci = row[x]
                    rgba[(y * width + x) * 4:(y * width + x) * 4 + 4] = palette[ci * 4: ci * 4 + 4]
        elif bpp == 32:
            rgba[:] = img[: width * height * 4]
        else:
            raise ValueError("unhandled bpp %d" % bpp)
        return width, height, bytes(rgba)
    raise IndexError("picture %d not found" % picture_index)


def tim2_picture_meta(payload: bytes) -> list[dict]:
    """Header summary of every picture in a TIM2 payload."""
    if payload[:4] != b"TIM2" or len(payload) < 16:
        raise ValueError("not a TIM2 file")
    fmt = payload[5]
    count = struct.unpack_from("<H", payload, 6)[0]
    base = 128 if fmt == 1 else 16
    out = []
    for _ in range(count):
        if base + 48 > len(payload):
            raise ValueError("TIM2 picture header past end of data")
        total, clut_size, image_size, header_size, clut_colors = struct.unpack_from(
            "<IIIHH", payload, base
        )
        _pf, _mip, clut_type, image_type = payload[base + 16: base + 20]
        width, height = struct.unpack_from("<HH", payload, base + 20)
        out.append({
            "width": width, "height": height,
            "bpp": IMAGE_TYPE_BPP.get(image_type),
            "clut_colors": clut_colors, "clut_type": clut_type,
            "image_size": image_size, "clut_size": clut_size,
        })
        if total <= 0:
            break
        base += total
    return out


# --- writer constraints (documented for the next stage) ----------------------
FORMAT_CONSTRAINTS = {
    "character_sprites_are_2d": True,
    "image_types": {4: "4bpp indexed, 16-colour CLUT (the character frames)",
                    5: "8bpp indexed, 256-colour CLUT",
                    3: "32bpp direct RGBA8888"},
    "clut_type_3": "RGBA8888, 4 bytes/colour (clut_size == clut_colors * 4)",
    "4bpp_packing": "2 pixels/byte, low nibble = left pixel (PSMCT4)",
    "transparent_index": 0,
    "picture_header_size": 48,
    "same_size_writer_rule": (
        "a replacement sprite must keep the original picture's width/height and "
        "image_type, fit in the original image_size (w*h*bpp//8) with the same "
        "16-colour RGBA8888 CLUT, and be re-packed as CMP3 (cmp3_compress_literal "
        "is a valid all-literal encoding) or raw (4-zero-byte prefix) at the same "
        "-RA- entry size or smaller"
    ),
}
