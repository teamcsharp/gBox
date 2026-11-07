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
