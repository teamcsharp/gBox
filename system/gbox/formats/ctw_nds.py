"""Owned-build inventory helpers for Grand Theft Auto: Chinatown Wars (NDS).

The owned Nintendo DS build does not keep its assets as plain NitroFS files.
`gbox.formats.nitro` reads the NitroFS container, and this module adds the
CTW-specific view on top of it:

  * the Rockstar container members named by the NitroFS directory
    (ROM.TOC / ROM.WAD / game.pak / dwc/utility.bin) with byte-exact FAT ranges,
  * the full NitroFS FAT table, which for this build enumerates every
    addressable payload range of the ROM,
  * a streaming sha256 of the owned source, so the build identity is recorded
    by hashing the actual bytes rather than copying a reference digest.

The ROM.TOC / ROM.WAD record layout was reverse engineered from the ARM9
loader (THUMB code at RAM 0x02002c98..0x02002dac of the owned build, hash
mask literal 0x00ffffff at 0x02002db0):

  * ROM.TOC is ``u32 entry_bytes`` followed by ``entry_bytes/8`` 8-byte
    records, then ``u32 count`` and ``count`` u32 sizes;
  * each record is ``{u24 hash, u24 offset (x256 bytes into ROM.WAD),
    u16 size index}``;  the byte-3 overlap is resolved because lookups mask
    the first u32 with 0x00ffffff;
  * names are hashed with Bob Jenkins' one-at-a-time hash after mapping
    ``a-z`` to ``A-Z`` (loader code at RAM 0x02002d38).

`read_wad_member` therefore resolves a member by name and returns its stored
bytes from the owned ROM (sizes come from the u32 table; no decompression is
applied, matching the loader's direct-read path for these members).
"""

from __future__ import annotations

import hashlib
import json
import os
import struct

from . import nitro

# Container members named by the NitroFS directory of the owned build.
MEMBERS = ("ROM.TOC", "ROM.WAD", "game.pak", "dwc/utility.bin")

ROM_HEADER_SIZE = 0x200


def sha256_stream(path, chunk_size=1 << 20):
    """Hash a file by streaming its bytes; never loads the whole file."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value):
    """Normalise a ROM header string field to bytes without NUL padding."""
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value.rstrip(b"\x00")
    return str(value).encode("latin-1").rstrip(b"\x00")


def _field(rom, *names):
    """Return the first present attribute of ``rom`` among ``names``."""
    for name in names:
        value = getattr(rom, name, None)
        if value is not None:
            return value
    return None


def fat_entries(rom):
    """Return every NitroFS FAT entry as an ordered list of dicts.

    The owned CTW build names four files in the NitroFS directory but the FAT
    carries one entry per addressable payload range, so this table is the
    authoritative owned-build manifest of the ROM payload.
    """
    entries = []
    for file_id, (start, end) in enumerate(rom.fat):
        entries.append({"file_id": file_id, "start": start, "end": end,
                        "size": end - start})
    return entries


def member_table(rom):
    """Return the named CTW container members with byte-exact FAT ranges."""
    members = []
    for name in MEMBERS:
        file_id = rom.ids[name.lower()]
        start, end = rom.fat[file_id]
        members.append({"name": name, "file_id": file_id, "start": start,
                        "end": end, "size": end - start})
    members.sort(key=lambda m: m["start"])
    return members


def overlaps(ranges):
    """Return every pair of ranges that share bytes.

    ``ranges`` is a list of dicts with ``start``/``end`` keys and an optional
    ``name``.  All pairs are checked, so the result does not depend on the
    order of the input table.
    """
    found = []
    for index, first in enumerate(ranges):
        for second in ranges[index + 1:]:
            if first["start"] < second["end"] and second["start"] < first["end"]:
                found.append([first.get("name", first["file_id"]),
                              second.get("name", second["file_id"])])
    return found


def manifest(path):
    """Build the authoritative manifest of the owned build at ``path``."""
    with open(path, "rb") as handle:
        data = handle.read()
    rom = nitro.NitroROM(data)
    entries = fat_entries(rom)
    members = member_table(rom)
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    return {
        "source_path": os.path.abspath(path),
        "source_size": len(data),
        "source_sha256": sha256_stream(path),
        "rom_title": _text(rom.title).decode("latin-1"),
        "rom_gamecode": _text(rom.gamecode).decode("latin-1"),
        "arm9": {"offset": rom.arm9_off, "entry": rom.arm9_entry,
                 "ram": rom.arm9_ram, "size": rom.arm9_size},
        "arm7": {"offset": _field(rom, "arm7_off", "arm7_rom_off"),
                 "entry": _field(rom, "arm7_entry"),
                 "ram": _field(rom, "arm7_ram"),
                 "size": _field(rom, "arm7_size")},
        "nitrofs": {"fnt_offset": rom.fnt_off, "fnt_size": rom.fnt_size,
                    "fat_offset": rom.fat_off, "fat_size": rom.fat_size,
                    "fat_entries": len(rom.fat)},
        "members": members,
        "member_overlaps": overlaps(members),
        "fat_overlaps": overlaps(entries),
        "out_of_bounds_fat_entries": [e for e in entries
                                      if e["start"] < 0 or e["end"] > len(data)
                                      or e["end"] < e["start"]],
        "fat_manifest_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "fat_manifest": entries,
    }


# --- ROM.TOC / ROM.WAD member directory (reverse engineered loader) ---

TOC_HASH_MASK = 0x00FFFFFF  # literal at ARM9 RAM 0x02002db0
_WAD_HEADER = struct.Struct("<4I")


def name_hash(name):
    """One-at-a-time hash (Jenkins) with a-z mapped to A-Z, as the loader at
    RAM 0x02002d38 computes it."""
    value = 0
    for char in str(name).encode("ascii"):
        if 0x61 <= char <= 0x7A:
            char -= 0x20
        value = (value + char) & 0xFFFFFFFF
        value = (value + (value << 10)) & 0xFFFFFFFF
        value ^= value >> 6
    value = (value + (value << 3)) & 0xFFFFFFFF
    value ^= value >> 11
    value = (value + (value << 15)) & 0xFFFFFFFF
    return value


def parse_toc(data):
    """Parse ROM.TOC bytes into ``{"entries": [(hash, offset, size_index)],
    "sizes": [u32...]}``."""
    entry_bytes = struct.unpack_from("<I", data, 0)[0]
    if entry_bytes % 8 or 4 + entry_bytes + 4 > len(data):
        raise ValueError("ROM.TOC entry area size 0x%x is not a table" % entry_bytes)
    entries = []
    for index in range(entry_bytes // 8):
        record = data[4 + 8 * index:12 + 8 * index]
        key = struct.unpack_from("<I", record, 0)[0] & TOC_HASH_MASK
        offset = struct.unpack_from("<I", record[3:6] + b"\0", 0)[0]
        size_index = struct.unpack_from("<H", record, 6)[0]
        entries.append((key, offset, size_index))
    tail = data[4 + entry_bytes:]
    count = struct.unpack_from("<I", tail, 0)[0]
    sizes = list(struct.unpack_from("<%dI" % count, tail, 4))
    return {"entries": entries, "sizes": sizes}


def wad_directory(rom):
    """Return the parsed ROM.TOC of ``rom`` (a nitro.NitroROM)."""
    toc_id = rom.ids["rom.toc"]
    start, end = rom.fat[toc_id]
    return parse_toc(rom.data[start:end])


def find_wad_entry(toc, name):
    """Binary-search the TOC for ``name`` (loader loop at 0x02002d76)."""
    target = name_hash(name) & TOC_HASH_MASK
    entries, sizes = toc["entries"], toc["sizes"]
    low, high = 0, len(entries)
    while high:
        half = high >> 1
        if entries[low + half][0] < target:
            low += half + 1
            high -= half + 1
        else:
            high = half
    if low < len(entries) and entries[low][0] == target:
        return low, entries[low], sizes[entries[low][2]] if entries[low][2] < len(sizes) else None
    return None, None, None


def read_wad_member(path, name):
    """Resolve and read one ROM.WAD member by name from the ROM at ``path``.

    Returns ``{"offset", "size", "data"}`` or ``None`` when the hashed name is
    not in the TOC.  ``offset`` is the member start inside the ROM file.
    """
    with open(path, "rb") as handle:
        data = handle.read()
    rom = nitro.NitroROM(data)
    toc = wad_directory(rom)
    wad_start, wad_end = rom.fat[rom.ids["rom.wad"]]
    wad = data[wad_start:wad_end]
    if len(wad) < _WAD_HEADER.size:
        raise ValueError("ROM.WAD truncated")
    index, entry, size = find_wad_entry(toc, name)
    if entry is None or size is None:
        return None
    offset = wad_start + (entry[1] << 8)
    if offset + size > len(data):
        raise ValueError("member %r exceeds ROM bounds" % name)
    return {"index": index, "offset": offset, "size": size,
            "data": data[offset:offset + size]}
