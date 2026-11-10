"""Prince of Persia: The Sands of Time (GameCube, GPTE41) native reader.

The character/asset container is prince.bf, an Ubisoft "BIG\\0" bigfile (240 MB).
This module decodes the BIG header, file listing, file tab and folder tab, then
enumerates every entry with its data-offset magic -- the authoritative owned-build
inventory needed before any character/asset extraction.

Format reference (BIG little-endian, bigfile_parameters == 0x25):
  header      @ 0x00
    0x00 u32   magic "BIG\\0"
    0x04 u32   bigfile_parameters (== 0x25)
    0x08 u32   files1
    0x0c u32   folders1
    0x10 u32   normal_key_01 (0)        0x14 normal_key_02 (0)
    0x18 u32   inverted_key_01 (0xffffffff)  0x1c inverted_key_02 (0xffffffff)
    0x20 u32   skips1
    0x24 u32   file_indices (1)
    0x28 u32   univers_oin
  file index header @ 0x2c (0x18 bytes)
    files2 u32, folders2 u32, file_listing_offset u32, next_listing_offset u32,
    bf_16 u32, skips2 u32
  file listing  @ file_listing_offset   := files2 * 8 bytes, each {offset u32, name_hash u32}
  file tab      @ file_listing_offset + skips1*8 := files2 * 0x54, each
    {file_size u32, next u32, prev u32, folder u32, time u32, name[0x40]}
  folder tab    @ file_tab_offset + skips1*0x54 := folders2 * 0x54, each
    {a u32, b u32, c u32, d u32, e u32, name[0x40]}

The "skips1" field is NOT a skip count; the tab offset formula above is the one the
reference extractor uses verbatim and reproduces entry names exactly.
"""
import hashlib
import struct

GAME_ID = "GPTE41"
BIGFILE = "prince.bf"
BIG_MAGIC = b"BIG\x00"

FILE_INDEX_HEADER_OFF = 0x2C
FILE_INDEX_HEADER_SIZE = 0x18
ENTRY_NAME_SIZE = 0x40          # 64-byte name in file/folder tabs
FILE_TAB_ENTRY_SIZE = 0x54
FOLDER_TAB_ENTRY_SIZE = 0x54


def sha256_stream(chunks) -> str:
    h = hashlib.sha256()
    for c in chunks:
        h.update(c)
    return h.hexdigest()


def parse_big_header(buf: bytes) -> dict:
    if len(buf) < 16 or buf[:4] != BIG_MAGIC:
        raise ValueError("not a BIG bigfile")
    (version, files1, folders1) = struct.unpack_from("<III", buf, 4)
    return {
        "magic": "BIG",
        "bigfile_parameters": version,
        "files1": files1,
        "folders1": folders1,
    }


def _unpack(buf: bytes, off: int, fmt: str):
    return struct.unpack_from(fmt, buf, off)


def _cstr(b: bytes) -> str:
    return b.split(b"\x00", 1)[0].decode("latin-1", "replace")


def parse_big_index_header(buf: bytes) -> dict:
    """Decode the 0x18-byte file index header (starting at FILE_INDEX_HEADER_OFF)."""
    if len(buf) < FILE_INDEX_HEADER_SIZE:
        raise ValueError("truncated file index header")
    (files2, folders2, file_listing_offset, next_listing_offset,
     bf_16, skips2) = struct.unpack_from("<6I", buf, 0)
    return {
        "files2": files2,
        "folders2": folders2,
        "file_listing_offset": file_listing_offset,
        "next_listing_offset": next_listing_offset,
        "bf_16": bf_16,
        "skips2": skips2,
    }


def big_tab_offset(file_listing_offset: int, skips1: int) -> int:
    return file_listing_offset + (skips1 * 8)


def parse_big_entries(hdr: bytes, idx: bytes, listing: bytes, filetab: bytes,
                      foldertab: bytes):
    """Return a list of entry dicts. Each caller slice must cover the full region."""
    h = parse_big_header(hdr)
    # header fields after files1/folders1 (normal/inverted keys are 0 / 0xffffffff)
    skips1 = struct.unpack_from("<I", hdr, 0x20)[0]
    ii = parse_big_index_header(idx)
    files2 = ii["files2"]
    if len(listing) < files2 * 8:
        raise ValueError("truncated file listing")
    if len(filetab) < files2 * FILE_TAB_ENTRY_SIZE:
        raise ValueError("truncated file tab")

    entries = []
    for i in range(files2):
        file_offset, name_hash = struct.unpack_from("<2I", listing, i * 8)
        (file_size, next_f, prev_f, folder, _time) = struct.unpack_from(
            "<5I", filetab, i * FILE_TAB_ENTRY_SIZE)
        name = _cstr(filetab[i * FILE_TAB_ENTRY_SIZE + 0x14:
                              i * FILE_TAB_ENTRY_SIZE + 0x14 + ENTRY_NAME_SIZE])
        entries.append({
            "index": i,
            "offset": file_offset,
            "name_hash": name_hash,
            "file_size": file_size,
            "folder": folder,
            "next": next_f,
            "prev": prev_f,
            "name": name,
        })

    folders = []
    if foldertab:
        folders2 = ii["folders2"]
        for i in range(folders2):
            base = i * FOLDER_TAB_ENTRY_SIZE
            fn = _cstr(foldertab[base + 0x14: base + 0x14 + ENTRY_NAME_SIZE])
            folders.append({"index": i, "name": fn})

    return entries, folders, {
        "bigfile_parameters": h["bigfile_parameters"],
        "files1": h["files1"],
        "folders1": h["folders1"],
        "skips1": skips1,
        "file_listing_offset": ii["file_listing_offset"],
        "file_tab_offset": big_tab_offset(ii["file_listing_offset"], skips1),
    }


def enumerate_magic(disc, max_entries=None, _probe_bytes=8):
    """Read each entry's first bytes from the bigfile and stamp its 4-byte magic.

    Returns (files, folders, meta): files list-of-dicts enriched with 'magic'
    (latin-1 of first 4 bytes) and 'head' (hex), folders list-of-dicts, and meta
    dict with offsets/parameters.
    """
    off, size = disc.files[BIGFILE]
    hdr = disc._r(off, 0x2C + FILE_INDEX_HEADER_SIZE)
    ii = parse_big_index_header(hdr[FILE_INDEX_HEADER_OFF:])
    skips1 = struct.unpack_from("<I", hdr, 0x20)[0]
    ft = big_tab_offset(ii["file_listing_offset"], skips1)
    listing_off = ii["file_listing_offset"]
    files2 = ii["files2"]

    listing = disc._r(off + listing_off, files2 * 8)
    filetab = disc._r(off + ft, files2 * FILE_TAB_ENTRY_SIZE)
    foldertab_off = ft + skips1 * FILE_TAB_ENTRY_SIZE
    foldertab = disc._r(off + foldertab_off, ii["folders2"] * FOLDER_TAB_ENTRY_SIZE)

    entries, folders, meta = parse_big_entries(hdr, hdr[FILE_INDEX_HEADER_OFF:],
                                               listing, filetab, foldertab)
    if max_entries:
        entries = entries[:max_entries]
    for e in entries:
        raw = disc._r(off + e["offset"], _probe_bytes)
        e["magic"] = raw[:4].decode("latin-1", "replace")
        e["head"] = raw.hex()
    return entries, folders, meta


def inventory(disc) -> dict:
    """disc: gbox.gcdisc.GCDisc. Manifest of counted files plus the bigfile decode."""
    off, size = disc.files[BIGFILE]
    hdr = disc._r(off, 0x2C + FILE_INDEX_HEADER_SIZE)
    return {
        "game_id": disc.game_id,
        "file_count": len(disc.files),
        "files": {k: {"offset": v[0], "size": v[1]} for k, v in sorted(disc.files.items())},
        "bigfile": {"path": BIGFILE, "offset": off, "size": size,
                    **parse_big_header(hdr)},
        "dol_sha256": hashlib.sha256(disc.dol()).hexdigest() if hasattr(disc, "dol") else None,
    }
