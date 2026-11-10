"""Halo: Combat Evolved Anniversary (Xbox 360) container format probes.

Analysis-stage parsers reverse-engineered from the owned XDVDFS disc
(sha256 3e862cf1bfb120765d862008f26a1ba4838dd2b62edea6f389385e72d58381b7):

* XDVDFS directory entries on this image use the layout
  ``left:u16 right:u16 sector:u32 size:u32 flags:u8 namelen:u8 name``
  with flags 0x10 = directory and 0x20 = file.  (The first entry of the
  root table is preceded by a 4-byte volume hint; name bytes are latin-1.)
  Validated end-to-end: walking the tree yields /default.xex whose bytes
  hash to 1412845884eba9eb61cdc00213ca3777be19c71f6196faea69e435a350fd3f19.

* Classic ``/maps_original/*.map`` caches do NOT begin with the PC `head`
  magic: they start with ``chunk_count:u32`` followed by
  ``chunk_count`` little-endian u32 offsets into the file.  Every chunk
  begins ``FF 80 00 <be u16 decompressed_size>`` (Xbox XMemCompress-style
  segment header; entropy ~= 8 bits/byte) -- i.e. the classic caches are
  chunk-compressed and a reader must decompress chunk 0 before the Blam!
  cache header is visible.

* Saber3D ``/paks360/*.s3dpak`` packages start with
  ``entry_count:u32 first_offset:u32 <entry_count-1 more u32 offsets>``
  (sorted ascending offsets into the package; the header region pads to
  the first offset, 0x40000 on the small initial_* packages).

Pure stdlib; no disc required to import.
"""

from __future__ import annotations

import struct
from pathlib import Path

XDVD_SECTOR = 2048
XDVD_ROOT_SECTOR = 32            # volume descriptor sector
FILE_FLAG = 0x20
DIR_FLAG = 0x10

MAP_CHUNK_MAGIC = b"\xff\x80\x00"   # XMemCompress-style segment header


# ---------------------------------------------------------------- XDVDFS ----

def parse_dirent(buf: bytes, off: int) -> dict | None:
    """One directory entry at *off*; ``None`` at the table terminator."""
    if off + 14 > len(buf):
        return None
    left, right = struct.unpack_from("<HH", buf, off)
    sector, size = struct.unpack_from("<II", buf, off + 4)
    flags = buf[off + 12]
    namelen = buf[off + 13]
    if namelen == 0 or off + 14 + namelen > len(buf):
        return None
    name = buf[off + 14:off + 14 + namelen].decode("latin-1")
    nxt = (off + 14 + namelen + 3) & ~3
    return {"name": name, "sector": sector, "size": size, "flags": flags,
            "is_dir": bool(flags & DIR_FLAG), "next": nxt,
            "left": left, "right": right}


def read_dir_table(buf: bytes) -> list[dict]:
    """Sequentially parse one directory table image (already sector-read)."""
    out, off = [], 0
    while True:
        e = parse_dirent(buf, off)
        if e is None:
            break
        out.append(e)
        off = e["next"]
    return out


def walk_xdvd(f, table_sector: int, table_size: int, path: str = "") -> list[tuple[str, int, int]]:
    """Depth-first ``(path, sector, size)`` listing under a directory table."""
    f.seek(table_sector * XDVD_SECTOR)
    entries = read_dir_table(f.read(table_size))
    out: list[tuple[str, int, int]] = []
    for e in entries:
        p = f"{path}/{e['name']}"
        if e["is_dir"]:
            out.extend(walk_xdvd(f, e["sector"], e["size"], p))
        else:
            out.append((p, e["sector"], e["size"]))
    return out


def extract_file(iso, sector: int, size: int) -> bytes:
    with open(iso, "rb") as f:
        f.seek(sector * XDVD_SECTOR)
        return f.read(size)


# ------------------------------------------------- classic .map chunk table --

def map_chunk_table(data: bytes) -> dict:
    """Parse the chunk index at the head of a classic maps_original cache."""
    (count,) = struct.unpack_from("<I", data, 0)
    if not 0 < count < 0x10000:
        raise ValueError(f"implausible chunk count {count}")
    offsets = list(struct.unpack_from(f"<{count}I", data, 4))
    if offsets != sorted(offsets) or offsets[0] < 4 + 4 * count:
        raise ValueError("chunk offsets not sorted/inside file")
    chunks = []
    for i, off in enumerate(offsets):
        end = offsets[i + 1] if i + 1 < count else len(data)
        hdr = data[off:off + 5]
        # Every segment except the final one carries the FF 80 00 XMemCompress
        # magic; the last chunk starts with a distinct terminator header.
        if hdr[:3] != MAP_CHUNK_MAGIC and i + 1 != count:
            raise ValueError(f"chunk {i} at {off:#x} lacks XMemCompress magic")
        (declared,) = struct.unpack_from(">H", hdr, 3)
        chunks.append({"offset": off, "stored_size": end - off,
                       "declared_uncompressed": declared,  # misnomer: this is the be16 COMPRESSED size (raw size is be16 at +1, 0x8000)
                       "declared_compressed": declared,
                       "xmem_header": hdr[:3] == MAP_CHUNK_MAGIC})
    return {"chunk_count": count, "chunks": chunks}


# -------------------------------------------------------- .s3dpak entries ----

def s3dpak_table(data: bytes) -> dict:
    """Parse the Saber3D package entry-offset table."""
    (count,) = struct.unpack_from("<I", data, 0)
    if not 0 < count < 0x10000:
        raise ValueError(f"implausible entry count {count}")
    offsets = list(struct.unpack_from(f"<{count}I", data, 4))
    if offsets != sorted(offsets) or len(data) < offsets[0]:
        raise ValueError("entry offsets not sorted/inside package")
    sizes = [offsets[i + 1] - offsets[i] for i in range(count - 1)] + \
            [max(0, len(data) - offsets[-1])]
    return {"entry_count": count, "offsets": offsets, "sizes": sizes,
            "header_region": offsets[0]}


# ---- classic Blam! .map (Xbox 360 CEA /maps_original): decode + tag index ----
# Verified on a10.map: each table entry is one independent XMemCompress LZX
# frame `FF <be16 raw> <be16 comp> <comp bytes>` (window 2**17, fresh decoder
# per frame; shared state fails).  Concatenated frames == header length and
# end with 'foot' at 0x7FC.  The decoded image is big-endian Xbox CE (v7).

MAP_LZX_WINDOW_BITS = 17


def map_decompress(data: bytes) -> bytes:
    from gbox import re6
    t = map_chunk_table(data)
    offs = [c["offset"] for c in t["chunks"]]
    out = bytearray()
    for p in offs:
        if data[p] != 0xFF:
            raise ValueError(f"bad frame marker at 0x{p:x}")
        raw = data[p + 1] << 8 | data[p + 2]
        comp = data[p + 3] << 8 | data[p + 4]
        out += re6.LZXDecoder(MAP_LZX_WINDOW_BITS).frame(data[p + 5:p + 5 + comp], raw)
    img = bytes(out)
    hdr_len = struct.unpack_from(">I", img, 8)[0]
    if img[:4] != b"head" or hdr_len != len(img) or img[0x7FC:0x800] != b"foot":
        raise ValueError("decoded map fails head/length/foot check")
    return img


def map_header(img: bytes) -> dict:
    magic, ver, length, _, index_off, tag_data_size = struct.unpack_from(">6I", img, 0)
    return {"magic": magic.to_bytes(4, "big").decode(), "version": ver, "length": length,
            "index_offset": index_off, "tag_data_size": tag_data_size,
            "name": img[0x20:0x40].split(b"\0")[0].decode("latin-1"),
            "build": img[0x40:0x60].split(b"\0")[0].decode("latin-1")}


def map_tag_index(img: bytes) -> dict:
    """Parse the tag index.  pointer->file offset is ptr + bias (bias =
    index_offset + 0x28 - tag_array_ptr); verified: cyborg_unarmed bipd's
    mod2 tagref resolves to characters/cyborg/cyborg."""
    h = map_header(img)
    io = h["index_offset"]
    tag_ptr, _base, _mapid, count = struct.unpack_from(">4I", img, io)
    bias = io + 0x28 - tag_ptr
    tags = []
    for i in range(count):
        c1, _c2, _c3, tid, nptr, dptr, ext, _ = struct.unpack_from(">4s4s4s5I", img, io + 0x28 + 32 * i)
        no = nptr + bias
        tags.append({"class": c1.decode("latin-1"), "id": tid,
                     "path": img[no:img.index(b"\0", no)].decode("latin-1"),
                     "data_offset": dptr + bias, "external": ext})
    return {"count": count, "bias": bias, "tags": tags, "by_id": {t["id"]: t for t in tags}}


def bipd_model_ref(img: bytes, idx: dict, bipd: dict) -> dict | None:
    """Resolve a biped's model tagref (first 'mod2' fourcc within the tag header)."""
    blk = img[bipd["data_offset"]:bipd["data_offset"] + 0x400]
    i = blk.find(b"mod2")
    if i < 0:
        return None
    return idx["by_id"].get(struct.unpack_from(">I", blk, i + 12)[0])
