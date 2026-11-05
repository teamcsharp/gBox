"""MT Framework ``.arc`` archives (Resident Evil 5 / 6 on Switch): read, list and rewrite entries.

Layout, measured 2026-11-05 on RE5's extracted RomFS (uWp06, uWp0a, uPl00ChrisNormal, uPl02JillCos1):

    0x00  "ARC\\0"
    0x04  u16 version (7)
    0x06  u16 entry count
    0x08  count * 0x50 entry records:
            +0x00  name, 64 bytes, NUL-terminated, zero padded
            +0x40  u32 hash   (constant 0x241f5deb in every entry measured)
            +0x44  u32 size
            +0x48  u32 tag    (varies per entry; preserved verbatim)
            +0x4C  u32 offset
          the data area starts at the next 0x8000 boundary after the table and the entries are contiguous
          (in all four samples the last entry's end equals the file size exactly)

Replacing an entry keeps the destination archive's entry table — the names and order the game looks up — and only
the chosen entry's payload changes. That is what makes an in-slot model swap possible: the slot still answers to
``pawn\\wp\\wp06\\model\\wep06_00_BM`` while holding another model's bytes.

Only the parts needed for that are modelled; unknown header bytes are preserved on rebuild.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"ARC\x00"
ENTRY_SIZE = 0x50
NAME_MAX = 0x40
DATA_ALIGN = 0x8000


class ArcError(ValueError):
    """The bytes are not an MT Framework archive this module can handle."""


@dataclass
class Entry:
    name: str
    hash: int
    tag: int
    size: int
    offset: int
    data: bytes = b""


@dataclass
class Arc:
    version: int
    entries: list[Entry]

    def find(self, name: str) -> Entry | None:
        want = name.replace("/", "\\")
        for entry in self.entries:
            if entry.name == want:
                return entry
        return None

    def names(self) -> list[str]:
        return [e.name for e in self.entries]


def parse(data: bytes) -> Arc:
    """Read an archive: version, entry table and each entry's payload."""
    if len(data) < 8 or data[:4] != MAGIC:
        raise ArcError("not an MT Framework archive (missing ARC\\0 magic)")
    version, count = struct.unpack_from("<HH", data, 4)
    table_end = 8 + count * ENTRY_SIZE
    if count == 0 or table_end > len(data):
        raise ArcError(f"entry table of {count} records does not fit in {len(data)} bytes")
    entries: list[Entry] = []
    for index in range(count):
        base = 8 + index * ENTRY_SIZE
        raw_name = data[base:base + NAME_MAX].split(b"\0", 1)[0]
        try:
            name = raw_name.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ArcError(f"entry {index} has a non-ASCII name") from exc
        digest, size, tag, offset = struct.unpack_from("<IIII", data, base + NAME_MAX)
        if offset + size > len(data):
            raise ArcError(f"entry {name!r} runs past the end of the archive")
        entries.append(Entry(name=name, hash=digest, tag=tag, size=size, offset=offset,
                             data=data[offset:offset + size]))
    return Arc(version=version, entries=entries)


def build(arc: Arc) -> bytes:
    """Rebuild the archive with contiguous entries and a 0x8000-aligned data area."""
    count = len(arc.entries)
    table_end = 8 + count * ENTRY_SIZE
    data_start = max(DATA_ALIGN, -(-table_end // DATA_ALIGN) * DATA_ALIGN)
    table = bytearray()
    payload = bytearray()
    for entry in arc.entries:
        name = entry.name.encode("ascii")
        if len(name) >= NAME_MAX:
            raise ArcError(f"entry name {entry.name!r} does not fit in {NAME_MAX} bytes")
        record = bytearray(ENTRY_SIZE)
        record[:len(name)] = name
        offset = data_start + len(payload)
        struct.pack_into("<IIII", record, NAME_MAX, entry.hash, len(entry.data), entry.tag, offset)
        table += record
        payload += entry.data
    return (MAGIC + struct.pack("<HH", arc.version, count) + bytes(table) + b"\0" * (data_start - table_end)
            + bytes(payload))


def replace(data: bytes, name: str, new_data: bytes) -> bytes:
    """Return the archive with one entry's payload replaced (its name, order and tag are kept)."""
    arc = parse(data)
    entry = arc.find(name)
    if entry is None:
        raise ArcError(f"no entry named {name!r} in this archive")
    entry.data = bytes(new_data)
    entry.size = len(entry.data)
    return build(arc)
