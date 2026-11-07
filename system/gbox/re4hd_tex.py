"""Resident Evil 4 (Switch / HD port) textures: the in-pack descriptor, and the archive the pixels live in.

Two separate things, and this module is explicit about which is which.

**The descriptor.** A character pack's DAT slots name `TPL`, but the payload is not a GameCube TPL (magic
0x0020AF30) - it is a 96-byte little-endian record with magic `0x12345678`. Measured over the whole title (1,702 `TPL`
slots in 162 packs):

```
0x00 u32  magic 0x12345678                     all 1,702 slots
0x04 u32  version 1                            all
0x08 u32  16 (header word)                     all
0x20 u32  width (u16) | height (u16)           the 779 "image" slots; 0 high half on the 923 "reference" slots
0x24 u32  format 14                            the image slots (GX CMPR number); 0 on the reference slots
0x28 u32  data offset 0x48                     the image slots; 0 on the reference slots
0x48      descriptor payload: u32 type 0x10, u32 texture id     (observed ids 45, 46, 47, 48 ...)
```

The image slots are 96 bytes however large the surface is (a 256x256 at format 14 would be 32 KB of CMPR), so **the
slot carries no pixels** - it names a texture by id and the pixels are elsewhere. That is what makes "replace a skin"
a two-part problem on this title.

**The archive.** `bio4/imagepackhd` holds 1,813 `.pack.fen` files, 6,144,462,613 B, and they are compressed:

```
u32 uncompressed size, then a zlib stream (0x78 0x9C)
```

Verified on three packs of very different sizes (1.8 MB / 4.4 MB / 14.0 MB of file for 4.2 MB / 10.3 MB / 34.6 MB of
body): the declared size equals the decompressed length exactly in every case. The decompressed body opens with two
u32 counts and then a table of 64-bit, 8-aligned, increasing offsets (0x70, 0x155670, 0x2AAC70 ... for the 1.8 MB pack;
0x2F0, 0xC3F0, 0x184F0 ... for the 14 MB one). Their stride relationship and the meaning of the second count are **not
established**, so `fen_open` returns the body and the raw table and the caller is told the entry map is unmapped
rather than being handed a guess.

Nothing here decodes pixels: the surface codec (format 14) and the mapping from a descriptor's id to an entry are the
next step, and they are stated as missing in `fen_open`'s answer.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

TPL_MAGIC = 0x12345678
FEN_ZLIB_AT = 4                     # the u32 before the zlib stream is the uncompressed size
# GX texture-format numbers, the vocabulary the GC reader already uses (gbox/re4gc_inventory.GX_FORMATS)
FORMATS = {0: "none", 14: "CMPR"}
DESCRIPTOR_HEADER = 0x48            # 72 bytes, the image slots' data offset


class TexError(ValueError):
    """Not an HD texture descriptor, or a FEN archive that will not decompress."""


def tex_info(data: bytes) -> dict:
    """One `TPL` slot of a character pack, decoded as far as it is understood.

    Returns `kind`:
      * `"image"`     - a descriptor: width/height/format, and the payload's (type, id) that names the texture;
      * `"reference"` - the other 923 slots: the same container, but format 0 and no data offset, so no dimensions
                        and no id. They are reported as such instead of being read as 8x0 pictures.
    """
    if len(data) < 0x30:
        raise TexError(f"texture slot too short ({len(data)} bytes)")
    magic = struct.unpack_from("<I", data, 0)[0]
    if magic != TPL_MAGIC:
        # the GameCube TPL's magic is stored big-endian, so match its bytes rather than an endian-bound integer
        if data[:4] == b"\x00\x20\xaf\x30":
            raise TexError("this is a GameCube TPL (0x0020AF30), not an RE4 Switch descriptor")
        raise TexError(f"not an HD texture descriptor (magic {magic:#010x}, want {TPL_MAGIC:#010x})")
    version, header_word = struct.unpack_from("<II", data, 4)
    dims, fmt, data_offset = struct.unpack_from("<I", data, 0x20)[0], struct.unpack_from("<I", data, 0x24)[0], \
        struct.unpack_from("<I", data, 0x28)[0]
    out = {"magic": TPL_MAGIC, "version": version, "header_word": header_word, "format_code": fmt,
           "format": FORMATS.get(fmt, f"unknown({fmt})"), "slots": len(data)}
    if fmt == 0 and data_offset == 0:
        out.update({"kind": "reference", "word_0020": dims, "note": "no dimensions and no texture id in this record"})
        return out
    width, height = struct.unpack_from("<HH", data, 0x20)
    out.update({"kind": "image", "width": width, "height": height, "data_offset": data_offset})
    if not (0 < data_offset <= len(data)):
        out.update({"id": None, "note": f"data offset {data_offset:#x} is outside the slot"})
        return out
    payload = data[data_offset:]
    if len(payload) >= 8:
        kind_word, tex_id = struct.unpack_from("<II", payload, 0)
        out.update({"payload_type": kind_word, "id": tex_id,
                    "payload_bytes": len(payload) - 8})
    else:
        out.update({"id": None, "note": "descriptor payload is shorter than its (type, id) pair"})
    # how many bytes a full surface would need, so a caller can see the slot is a pointer rather than a picture
    if out.get("format_code") == 14:                       # CMPR: 4 bits per pixel
        out["surface_bytes"] = max(1, (width * height) // 2)
        out["carries_pixels"] = bool(out.get("payload_bytes", 0) >= out["surface_bytes"])
        if not out["carries_pixels"]:
            out["note"] = ("descriptor only: a " f"{width}x{height} CMPR surface needs {out['surface_bytes']:,} B and "
                           "the slot carries the texture id, not the pixels (see fen_open)")
    return out


def fen_open(data: bytes) -> dict:
    """One `imagepackhd/*.pack.fen`: `u32 uncompressed size` followed by a zlib stream.

    The entry map is established: the body opens with two u32 counts, then `count_b` 64-bit offsets; the entries are
    the slices between consecutive offsets, and the last one ends exactly at the body end. Verified on 40 of 40
    archives of very different sizes. `count_a` is NOT understood (it is 6 / 9 / 19 for bodies with 3 / 13 / 89
    entries, so it is not the entry count) and is reported as-is.
    """
    if len(data) <= FEN_ZLIB_AT:
        raise TexError(f"FEN too short ({len(data)} bytes)")
    declared = struct.unpack_from("<I", data, 0)[0]
    stream = data[FEN_ZLIB_AT:]
    if stream[:2] not in (b"\x78\x9c", b"\x78\x01", b"\x78\xda"):
        raise TexError(f"not a zlib stream at {FEN_ZLIB_AT} (starts {stream[:2].hex()}, want 789c/7801/78da)")
    try:
        body = zlib.decompress(stream)
    except zlib.error as exc:
        raise TexError(f"the FEN stream did not decompress: {exc}") from exc
    if len(body) != declared:
        raise TexError(f"the FEN declared {declared} bytes and decompressed to {len(body)}")
    out = {"declared_size": declared, "body_size": len(body), "body": body}
    if len(body) < 8:
        out["note"] = "the body is shorter than its two counts"
        return out
    count_a, count_b = struct.unpack_from("<II", body, 0)
    out.update({"count_a": count_a, "count_b": count_b})
    if count_b > 1 << 20 or 8 + 8 * count_b > len(body):
        out["note"] = f"count_b {count_b} cannot index a {len(body)}-byte body"
        return out
    offsets = list(struct.unpack_from(f"<{count_b}Q", body, 8))
    if any(o >= len(body) for o in offsets) or any(b2 <= a for a, b2 in zip(offsets, offsets[1:])):
        out["note"] = "the offset table is not increasing inside the body"
        return out
    ends = offsets[1:] + [len(body)]
    out.update({"offsets": offsets,
                "map": "count_b entries, contiguous, the last ending at the body end",
                "entries": [{"index": i, "offset": o, "size": e - o, "ends_at_body": e == len(body)}
                            for i, (o, e) in enumerate(zip(offsets, ends))]})
    out["note"] = ("count_a is not understood and is not used to index anything; the entry map is count_b offsets "
                   "whose slices cover the body exactly")
    return out


def fen_entry(data: bytes, index: int) -> bytes:
    """One entry's bytes out of a FEN archive (the unit a texture replacement would rewrite in place)."""
    out = fen_open(data)
    entries = out.get("entries")
    if not entries:
        raise TexError(f"this FEN has no entry map: {out.get('note')}")
    if not 0 <= index < len(entries):
        raise TexError(f"this FEN holds {len(entries)} entries; #{index} is out of range")
    entry = entries[index]
    return out["body"][entry["offset"]:entry["offset"] + entry["size"]]


# ------------------------------------------------------------------ the pixels are DDS
#
# Measured 2026-11-07: every entry of an `imagepackhd` archive is a 16-byte wrapper followed by a plain **DDS** file -
# `44 44 53 20` ("DDS "), dwSize 0x7C, dwFlags 0xA1007, height/width, mip count, then the standard pixel-format block.
# The wrapper is `u32 dds_bytes, u32 -1, u32 name_hash, u32 0`, and dds_bytes equals the entry size minus 16 on
# every entry checked. So the surface is not a private codec at all: it is BC (DXT) in a DDS container, which is what
# every texture tool understands.
DDS_MAGIC = b"DDS "
DDS_HEADER = 0x80                       # magic + 0x7C header
WRAPPER = 16


def dds_info(data: bytes) -> dict:
    """Height, width, mip count and pixel format of a DDS surface, refusing anything that is not one."""
    if len(data) < DDS_HEADER:
        raise TexError(f"DDS too short ({len(data)} bytes)")
    if data[:4] != DDS_MAGIC:
        raise TexError(f"not a DDS (starts {data[:4].hex()}, want {DDS_MAGIC.hex()})")
    size, flags, height, width, pitch, depth, mips = struct.unpack_from("<7I", data, 4)
    if size != 0x7C:
        raise TexError(f"DDS header size {size:#x}, want 0x7c")
    pf_size, pf_flags = struct.unpack_from("<II", data, 0x4C)
    fourcc = data[0x54:0x58].decode("latin-1", "replace") if pf_flags & 0x4 else ""
    return {"header_size": size, "flags": flags, "height": height, "width": width,
            "pitch_or_linear_size": pitch, "depth": depth, "mipmaps": mips,
            "pixel_format_size": pf_size, "pixel_format_flags": pf_flags,
            "fourcc": fourcc or None, "format": fourcc or f"uncompressed({pf_flags:#x})",
            "surface_bytes": len(data) - DDS_HEADER}


def fen_texture(data: bytes, index: int) -> dict:
    """One texture out of an `imagepackhd` archive: the wrapper's fields and the DDS it holds.

    The DDS is located rather than assumed: most entries put it at 16, but a variant with a 64-byte wrapper exists
    (measured: `00000010.pack.fen` declares 49,328 DDS bytes and holds 49,392, which is 64 more). The wrapper is
    returned as bytes so nothing about a variant has to be guessed in advance.

    Returns the decoded header, not decoded pixels - the DDS body is left as bytes, which is what a replace needs.
    """
    entry = fen_entry(data, index)
    if len(entry) < WRAPPER + DDS_HEADER:
        raise TexError(f"entry {index} is too short to hold a wrapped DDS ({len(entry)} bytes)")
    at = entry[:0x100].find(DDS_MAGIC)
    if at < 0:
        raise TexError(f"entry {index} holds no DDS")
    info = dds_info(entry[at:])
    declared = struct.unpack_from("<I", entry, 0)[0]
    return {"index": index, "entry_bytes": len(entry), "dds_bytes": declared, "wrapper_bytes": at,
            # NOT an archive number: measured 2026-11-07, this reads 0xe75b707d for 00000006.pack.fen and
            # 0xe7935c0f for 4400011c.pack.fen - both 0xe7..., i.e. a hash of the archive's resource name. The old name
            # is kept so existing callers do not break, and `name_hash` is the honest one.
            "name_hash": struct.unpack_from("<I", entry, 8)[0] if at >= 12 else None,
            "archive_number": struct.unpack_from("<I", entry, 8)[0] if at >= 12 else None,
            "wrapper": entry[:at],
            # informational: a variant whose wrapper is longer than 16 explains its own size this way
            "dds_bytes_match": declared == len(entry) - at,
            **info, "dds": entry[at:]}


def fen_textures(data: bytes, limit: int = 0) -> list[dict]:
    """Every texture in an archive, headers only (the DDS bodies are dropped so a listing stays small)."""
    out = fen_open(data)
    rows = []
    for entry in (out.get("entries") or [])[:limit or None]:
        try:
            texture = fen_texture(data, entry["index"])
        except TexError as exc:
            rows.append({"index": entry["index"], "error": str(exc)[:120]})
            continue
        texture.pop("dds", None)
        texture.pop("wrapper", None)
        rows.append(texture)
    return rows


def tpl_images(data: bytes) -> list[dict]:
    """Every image a pack's `TPL` slot names, read from the container layout (not from one guessed field).

    The slot is a container: `magic 0x12345678`, a count, a header size, then `count` sixteen-byte table entries each
    holding a 64-bit offset, and at the end of the entry block `count` pairs of `(type, id)`. Each offset points at a
    40-byte record: `u16 width, u16 height, u32 format, u32 payload size`, then flags.

    Reading `width` from a fixed 0x20 instead - which this module did until 2026-11-07 - lands on a table offset and
    reports nonsense dimensions (32x128 for a 256x256 texture), which is how a whole round of join hypotheses came to be
    tested against the wrong numbers.
    """
    out = []
    if len(data) < 0x20 or struct.unpack_from("<I", data, 0)[0] != 0x12345678:
        return out
    count = struct.unpack_from("<I", data, 4)[0]
    if not 2 <= count <= 64 or 0x10 + 0x10 * count > len(data):
        return out
    offsets = [struct.unpack_from("<Q", data, 0x10 + 0x10 * i)[0] for i in range(count)]
    if any(o + 0x28 > len(data) for o in offsets):
        return out
    tail = offsets[-1] + 0x28
    pairs = []
    if tail + 8 * count <= len(data):
        pairs = [struct.unpack_from("<II", data, tail + 8 * i) for i in range(count)]
    for i, offset in enumerate(offsets):
        width, height, fmt, payload = struct.unpack_from("<HHII", data, offset)
        if not (0 < width <= 4096 and 0 < height <= 4096):
            return []
        out.append({"width": width, "height": height, "format_code": fmt, "payload": payload,
                    "id": pairs[i][1] if i < len(pairs) else None,
                    "type": pairs[i][0] if i < len(pairs) else None})
    return out


def pack_images(data: bytes, endian: str = "<") -> list[dict]:
    """Every image descriptor in a whole HD pack: the union over its `TPL` slots, with the slot it came from."""
    from .re4gc_inventory import udas_entries, dat_entries
    rows = []
    try:
        dat = next(e for e in udas_entries(data, endian) if e["type"] == 0)
    except (ValueError, StopIteration):
        return rows
    blob = data[dat["offset"]:dat["offset"] + dat["size"]]
    for slot, (ext, off, size) in enumerate(dat_entries(blob, endian)):
        if ext != "TPL":
            continue
        for image in tpl_images(blob[off:off + size]):
            rows.append({"slot": slot, **image})
    return rows

# The naming rule, read out of the executable rather than guessed:
#   "%s\%s\%08x.pack.fen"   (string at vaddr 0x6c8459) with args (base path, "ImagePackHD", texture id)
# The loader picks "ImagePack" or "ImagePackHD" on a global HD flag (FUN_0024c310: csel x4,x23,x22,eq with
# x23="ImagePack" @0x6c80f7 and x22="ImagePackHD" @0x6c8101), then formats the id as EIGHT HEX DIGITS. That is why the
# archives are named 00000006, 4400011c, 4b000005 - hex, not decimal - and why a lowercase "imagepackhd" byte scan found
# nothing for four rounds: the string is camel case and the ids are hex.
ARCHIVE_FORMAT = "%08x.pack.fen"


def archive_name(texture_id: int) -> str:
    """The `imagepackhd` archive a texture id names, per the format string in the loader."""
    return ARCHIVE_FORMAT % int(texture_id)


def archive_for(root, texture_id: int) -> dict:
    """Where a texture id points, and whether that archive is present in this tree."""
    folder = Path(root) / "bio4" / "imagepackhd"
    name = archive_name(texture_id)
    path = folder / name
    return {"id": int(texture_id), "archive": name, "present": path.is_file(),
            "bytes": path.stat().st_size if path.is_file() else 0}

# ------------------------------------------------------------------ writing a texture back

def _entry_slices(body: bytes, offsets: list[int], count_b: int) -> list[tuple[int, int]]:
    ends = list(offsets[1:]) + [len(body)]
    return [(offsets[i], ends[i]) for i in range(count_b)]


def fen_patch(data: bytes, index: int, replacement: bytes, *, allow_resize: bool = True) -> bytes:
    """Replace one entry of a FEN archive and re-deflate it.

    The entry table is a list of 64-bit offsets into the decompressed body, so a replacement that changes length is
    still a coherent archive: every later offset shifts by the same delta and the declared size is the new body size.
    `allow_resize=False` demands a byte-exact fit instead, which is the rule the GameCube writer uses (a patched pack
    keeps its slot sizes) and the safer choice when something outside the archive has cached a size.

    `count_a` is left untouched: it is not the entry count and is not understood, so this carries it through rather than
    inventing a value.
    """
    opened = fen_open(data)
    if "offsets" not in opened:
        raise TexError(f"this FEN's entry map is not usable: {opened.get('note')}")
    offsets, count_b = opened["offsets"], opened["count_b"]
    if not 0 <= int(index) < count_b:
        raise TexError(f"entry {index} is out of range (this archive has {count_b})")
    body = bytearray(opened["body"])
    start, end = _entry_slices(bytes(body), offsets, count_b)[int(index)]
    existing = end - start
    if not allow_resize and len(replacement) != existing:
        raise TexError(f"entry {index} is {existing} bytes and the replacement is {len(replacement)}; "
                       f"pass allow_resize=True to change the archive's layout")
    delta = len(replacement) - existing
    new_body = bytes(body[:start]) + bytes(replacement) + bytes(body[end:])
    new_offsets = [o if o <= start else o + delta for o in offsets]
    header = bytearray(new_body[:8 + 8 * count_b])
    struct.pack_into(f"<{count_b}Q", header, 8, *new_offsets)
    rebuilt = bytes(header) + new_body[8 + 8 * count_b:]
    packed = zlib.compress(rebuilt, 9)
    return struct.pack("<I", len(rebuilt)) + packed


def fen_replace_texture(data: bytes, index: int, dds: bytes, *, allow_resize: bool = True) -> bytes:
    """Put a whole DDS surface into one entry, keeping whatever wrapper the entry already had.

    Archives store an optional header before the `DDS ` magic (16 bytes usually, 64 in one measured case) whose first
    word is the DDS byte count. That wrapper is carried over and its count updated, so the result keeps the shape the
    reader expects.
    """
    if not dds.startswith(DDS_MAGIC):
        raise TexError(f"the replacement does not start with {DDS_MAGIC!r} (it is a DDS surface file, not a PNG)")
    opened = fen_open(data)
    if "offsets" not in opened:
        raise TexError(f"this FEN's entry map is not usable: {opened.get('note')}")
    start, end = _entry_slices(opened["body"], opened["offsets"], opened["count_b"])[int(index)]
    entry = opened["body"][start:end]
    at = entry.find(DDS_MAGIC)
    wrapper = bytearray(entry[:at]) if at > 0 else bytearray()
    if wrapper and len(wrapper) >= 4:
        struct.pack_into("<I", wrapper, 0, len(dds))
    return fen_patch(data, index, bytes(wrapper) + bytes(dds), allow_resize=allow_resize)

def solid_dds(width: int, height: int, rgb: tuple[int, int, int], *, fourcc: str = "DXT5") -> bytes:
    """A DDS surface of one flat colour, built block by block - no compressor needed, and valid for the GPU.

    Used to prove that a replaced texture is actually drawn: a magenta character is not ambiguous. DXT1 packs colour into
    one 8-byte block, DXT3/DXT5 put an 8-byte alpha block in front of it.
    """
    if width <= 0 or height <= 0 or width % 4 or height % 4:
        raise TexError(f"block formats need dimensions in fours, got {width}x{height}")
    r, g, b = (max(0, min(255, int(c))) for c in rgb)
    color = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
    colour_block = struct.pack("<HHI", color, color, 0)
    if fourcc == "DXT1":
        block = colour_block
    elif fourcc == "DXT3":
        block = b"\xff" * 8 + colour_block                 # every pixel fully opaque
    elif fourcc == "DXT5":
        block = bytes([0xFF, 0xFF]) + b"\0" * 6 + colour_block
    else:
        raise TexError(f"solid_dds cannot build {fourcc}")
    blocks = (width // 4) * (height // 4)
    payload = block * blocks
    head = bytearray(DDS_HEADER)
    head[0:4] = DDS_MAGIC
    struct.pack_into("<7I", head, 4, 0x7C, 0x00081007, height, width, max(1, width // 2), 0, 1)
    struct.pack_into("<II", head, 0x4C, 32, 0x4)
    head[0x54:0x58] = fourcc.encode("latin-1")
    struct.pack_into("<I", head, 0x6C, 0x1000)             # caps: texture
    return bytes(head) + payload