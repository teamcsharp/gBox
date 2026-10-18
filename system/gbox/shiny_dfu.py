"""Shiny Entertainment's WAD1.DFU archive (Enter the Matrix 2003, The Matrix: Path of Neo 2005, PS2): read, name,
and patch in place. Both games keep every loose game file in one hashed archive split over ``WAD1.DFU`` +
``WAD1_B.DFU`` (one address space: offsets past the end of WAD1 continue in WAD1_B).

Recovered from the owned discs and their executables (SLUS_204.54 ``0x1d8390`` lookup / ``0x241be0`` inflate,
SLUS_212.73 ``0x1f5860`` lookup), not from community notes (none describe it):

* header (little endian): ``u32 count, u32 seed_a (22313), u32 seed_b (2067), u32 seed_c (674), u32 2112, u32 flags``
  then ``count`` x 16-byte entries ``{u32 name hash, u32 packed size, u32 offset, u32 size}`` sorted by hash (the
  game binary-searches them). Data offsets are relative to the end of the table rounded up to 2048:
  ``base = (0x18 + 16 * count + 0x7ff) & ~0x7ff``.
* ``packed != size`` -> the entry is a zlib stream (zlib 1.1.4, ``inflateInit``; RFC 1950 header).
* name hash (case-insensitive, ``/`` == ``\\``): ``h += a * c; a += b + ((c & 0x30) >> 4); b += seed_c + (c & 15)``
  with ``a, b = seed_a, seed_b``. Path of Neo adds ``c << 8 * (i & 3)`` per character and hashes ``ps2\\`` + name for
  every name that does not contain ``common``.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

PARTS = ("WAD1.DFU", "WAD1_B.DFU")
MAX_ENTRIES = 1 << 18


class DfuError(ValueError):
    pass


def name_hash(name: str, seeds: tuple[int, int, int], variant: str = "etm") -> int:
    if variant == "pon" and "common" not in name.lower():
        name = "ps2\\" + name
    a, b = seeds[0], seeds[1]
    h = 0
    for i, c in enumerate(name.encode("latin-1")):
        if 65 <= c <= 90:
            c += 32
        if c == 0x2F:
            c = 0x5C
        h += a * c
        if variant == "pon":
            h += c << (8 * (i & 3))
        h &= 0xFFFFFFFF
        a = (a + b + ((c & 0x30) >> 4)) & 0xFFFFFFFF
        b = (b + seeds[2] + (c & 0xF)) & 0xFFFFFFFF
    return h


@dataclass(frozen=True)
class Entry:
    index: int
    hash: int
    packed: int
    offset: int
    size: int

    @property
    def compressed(self) -> bool:
        return self.packed != self.size


class Dfu:
    """The archive on a disc reader with ``files {NAME: (lba, size)}``, ``size(name)`` and ``read(name, off, n)``
    (gbox.chd.ChdDisc, gbox.defjam_inventory.Iso)."""

    def __init__(self, disc, variant: str = "etm", endian: str = "<", parts=None):
        if endian not in ("<", ">"):
            raise DfuError("archive byte order must be '<' or '>'")
        if parts is not None and not isinstance(parts, (list, tuple)):
            raise DfuError("archive parts must be an ordered list or tuple")
        parts = PARTS if parts is None else tuple(parts)
        if not parts or any(not isinstance(p, str) or not p for p in parts) or len(set(parts)) != len(parts):
            raise DfuError("archive parts must be nonempty unique filenames")
        self.disc, self.variant, self.endian = disc, variant, endian
        self.parts = [p for p in parts if p in disc.files]
        if parts[0] not in self.parts:
            raise DfuError(f"no {parts[0]} on this disc")
        missing = False
        for part in parts:
            if part not in disc.files:
                missing = True
            elif missing:
                raise DfuError("archive parts have a missing middle part")
        self.part_sizes = [disc.size(p) for p in self.parts]
        if any(type(n) is not int or n < 0 for n in self.part_sizes):
            raise DfuError("archive part sizes must be nonnegative integers")
        self.total = sum(self.part_sizes)
        if self.part_sizes[0] < 0x18:
            raise DfuError(f"{parts[0]} is shorter than its header")
        h = self._read_part(parts[0], 0, 0x18)
        self.count, sa, sb, sc, self.h4, self.flags = struct.unpack(endian + "6I", h)
        self.seeds = (sa, sb, sc)
        if not 0 < self.count <= MAX_ENTRIES or 0x18 + 16 * self.count > self.part_sizes[0]:
            raise DfuError(f"implausible entry count {self.count}")
        self.base = (0x18 + 16 * self.count + 0x7FF) & ~0x7FF
        tab = self._read_part(parts[0], 0x18, 16 * self.count)
        self.entries: list[Entry] = []
        self.by_hash: dict[int, Entry] = {}
        last = -1
        for i in range(self.count):
            hh, packed, off, size = struct.unpack_from(endian + "4I", tab, 16 * i)
            if hh < last:
                raise DfuError(f"entry {i}: table not sorted by hash")
            if self.base + off + packed > self.total:
                raise DfuError(f"entry {i}: data 0x{off:x}+0x{packed:x} past the archive end")
            if packed > size:
                raise DfuError(f"entry {i}: packed size {packed} larger than the file ({size})")
            e = Entry(i, hh, packed, off, size)
            self.entries.append(e)
            self.by_hash.setdefault(hh, e)
            last = hh
        self.duplicates = self.count - len(self.by_hash)

    def _read_part(self, part: str, offset: int, size: int) -> bytes:
        limit = self.part_sizes[self.parts.index(part)]
        if type(offset) is not int or type(size) is not int or offset < 0 or size < 0 or offset + size > limit:
            raise DfuError(f"{part}: read leaves the archive part")
        data = self.disc.read(part, offset, size)
        if len(data) != size:
            raise DfuError(f"{part}: short read ({len(data)} of {size} bytes)")
        return data

    def hash(self, name: str) -> int:
        return name_hash(name, self.seeds, self.variant)

    def entry(self, name: str) -> Entry | None:
        return self.by_hash.get(self.hash(name))

    def __contains__(self, name: str) -> bool:
        return self.entry(name) is not None

    def spans(self, e: Entry, length: int | None = None) -> list[tuple[str, int, int]]:
        """(part, offset in part, length) pieces of an entry's stored bytes (it may straddle WAD1 / WAD1_B)."""
        pos, left, out = self.base + e.offset, e.packed if length is None else length, []
        for part, sz in zip(self.parts, self.part_sizes):
            if left <= 0:
                break
            if pos >= sz:
                pos -= sz
                continue
            n = min(left, sz - pos)
            out.append((part, pos, n))
            left -= n
            pos = 0
        if left:
            raise DfuError(f"entry {e.index}: runs past the last archive part")
        return out

    def raw(self, e: Entry) -> bytes:
        return b"".join(self._read_part(p, o, n) for p, o, n in self.spans(e))

    def read(self, name_or_entry, *, max_size: int | None = None) -> bytes:
        e = name_or_entry if isinstance(name_or_entry, Entry) else self.entry(name_or_entry)
        if e is None:
            raise KeyError(name_or_entry)
        if max_size is not None:
            if type(max_size) is not int or max_size < 0:
                raise DfuError("read size limit must be a nonnegative integer")
            if e.size > max_size:
                raise DfuError(f"entry {e.index}: declared size {e.size} exceeds read limit {max_size}")
        b = self.raw(e)
        if e.compressed:
            try:
                decoder = zlib.decompressobj()
                b = decoder.decompress(b, e.size + 1)
                if len(b) > e.size or not decoder.eof:
                    raise DfuError(f"entry {e.index}: zlib output exceeds its size or is incomplete")
            except zlib.error as x:
                raise DfuError(f"entry {e.index}: zlib stream does not inflate ({x})") from None
        if len(b) != e.size:
            raise DfuError(f"entry {e.index}: {len(b)} bytes, the table says {e.size}")
        return b

    # ---------------------------------------------------------------- writing (into a copy of the disc image)
    def pack(self, e: Entry, data: bytes) -> bytes:
        """New bytes for an entry's slot: zlib (level 9) when the original was compressed, raw otherwise."""
        return zlib.compress(data, 9) if e.compressed else bytes(data)

    def replace_plan(self, name_or_entry, data: bytes) -> dict:
        """In-place replacement of one entry: its stored bytes (must fit the original slot) and its table row.
        -> {entry, packed, patches [(part, offset in part, bytes)]}; raises DfuError when it doesn't fit."""
        e = name_or_entry if isinstance(name_or_entry, Entry) else self.entry(name_or_entry)
        if e is None:
            raise KeyError(name_or_entry)
        blob = self.pack(e, data)
        if len(blob) > e.packed:
            raise DfuError(f"entry {e.index}: {len(blob)} packed bytes don't fit the original {e.packed}-byte slot")
        if not e.compressed and len(blob) != len(data):
            raise DfuError("raw entry size mismatch")
        patches, pos = [], 0
        for part, off, n in self.spans(e, len(blob)):
            patches.append((part, off, blob[pos:pos + n]))
            pos += n
        row = struct.pack(self.endian + "4I", e.hash, len(blob), e.offset, len(data))
        patches.append((self.parts[0], 0x18 + 16 * e.index, row))
        return {"entry": e, "packed": len(blob), "size": len(data), "patches": patches}


def image_patches(disc, plan: dict) -> list[tuple[int, bytes]]:
    """A replace_plan's patches as absolute byte offsets; readers declare offset_unit=1 for byte-based FSTs."""
    unit = getattr(disc, "offset_unit", 2048)
    if type(unit) is not int or unit not in (1, 2048):
        raise DfuError("disc offset unit must be bytes or 2048-byte sectors")
    out = []
    for part, off, blob in plan["patches"]:
        lba, size = disc.files[part]
        if type(off) is not int or off < 0 or off + len(blob) > size:
            raise DfuError(f"{part}: invalid patch offset {off!r} or range past the file")
        out.append((lba * unit + off, blob))
    return out
