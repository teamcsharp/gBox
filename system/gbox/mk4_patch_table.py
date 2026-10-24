"""MK4 (USA) N64 (NM4E rev 0): boot patch-table reader and asset-pointer map.

The NM4E ROM ships no plaintext file or asset table.  Instead its boot code
applies a table of 1353 ``{slot, value}`` pairs stored at ROM offset
0x12FDB8..0x132800.  Every pair patches exactly one destination:

* a ROM slot inside the asset region (0x132800..0xEB0000) whose value is the
  address of the data/code that slot must point at, and
* a RAM slot (0x8xxxxxxx) whose value is a runtime pointer written into the
  already loaded data segment.

Decoding that table therefore yields the only machine-readable map the game
itself provides between its data segment and the asset region, which is the
entry point for locating (and later replacing) a character asset.

Every offset in this module is a file offset of the byte-swapped (z64) image.
The original ROM is never modified; callers read it in place.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from pathlib import Path

Z64_MAGIC = b"\x80\x37\x12\x40"
V64_MAGIC = b"\x37\x80\x40\x12"

# Layout of the owned NM4E rev 0 build (Mortal Kombat 4 (USA), N64).
CODE_START = 0x1000
CODE_END = 0x12FDB8
PATCH_TABLE_START = 0x12FDB8
PATCH_TABLE_END = 0x132800
ASSET_START = 0x132800
ASSET_END = 0xEB0000
MAIN_ENTRY = 0x80000450
BSS_START = 0x80050800
BSS_SIZE = 0xD6770

PATCH_TABLE_ENTRIES = (PATCH_TABLE_END - PATCH_TABLE_START) // 8

DEFAULT_ROM = Path(
    "/home/ehm_eckx/gBox_alt/gbox-cache/n64/3e52c76354e8c5bb/Mortal Kombat 4 (USA).n64.v64"
)

# Offsets the earlier inventory milestone established for the owned build.
# Kept as data so the reader can be checked against a known-good build.
OWNED_Z64_SHA256 = "ea908a1f790340dc34f1056c4799f7d0984048d90344607f2910d96abf036478"


def to_z64(data: bytes) -> bytes:
    """Return the byte-swapped (z64) view of an N64 ROM image.

    A v64 image is byte-swapped per 16-bit halfword; a z64 image is returned
    unchanged.  Anything else raises ValueError.
    """
    if data[:4] == Z64_MAGIC:
        return data
    if data[:4] == V64_MAGIC:
        out = bytearray(data)
        out[0::2] = data[1::2]
        out[1::2] = data[0::2]
        return bytes(out)
    raise ValueError(f"not an N64 ROM image (magic {data[:4].hex()})")


def load_rom(path: str | Path = DEFAULT_ROM) -> bytes:
    """Read the owned ROM and return its z64 (big-endian words) view."""
    return to_z64(Path(path).read_bytes())


def classify_address(addr: int) -> str:
    """Coarse class of a 32-bit address used by the patch table."""
    if addr == 0:
        return "zero"
    if CODE_START <= addr < 0x210000:
        return "rom"
    if 0x80000000 <= addr < 0x80800000:
        return "ram"
    return "other"


def region(addr: int) -> str:
    """ROM region a file offset belongs to (only meaningful for ROM addresses)."""
    if addr < PATCH_TABLE_START:
        return "code"
    if addr < PATCH_TABLE_END:
        return "patch"
    if addr < ASSET_END:
        return "asset"
    return "pad"


@dataclass(frozen=True)
class PatchEntry:
    """One ``{slot, value}`` pair of the boot patch table."""

    index: int
    slot: int
    value: int
    slot_class: str
    value_class: str

    @property
    def slot_region(self) -> str:
        return region(self.slot) if self.slot_class == "rom" else "ram"


@dataclass
class PatchTable:
    """The decoded boot patch table."""

    entries: list[PatchEntry] = field(default_factory=list)

    @property
    def rom_slots(self) -> list[PatchEntry]:
        return [e for e in self.entries if e.slot_class == "rom"]

    @property
    def ram_slots(self) -> list[PatchEntry]:
        return [e for e in self.entries if e.slot_class == "ram"]

    @property
    def asset_values(self) -> list[int]:
        """Distinct addresses inside the asset region the table points at."""
        return sorted(
            {
                e.value
                for e in self.entries
                if e.value_class == "rom" and ASSET_START <= e.value < ASSET_END
            }
        )

    @property
    def ram_values(self) -> list[int]:
        """Distinct RAM addresses the table points at."""
        return sorted({e.value for e in self.entries if e.value_class == "ram"})

    def patch_table_window(self) -> tuple[int, int, int] | None:
        """(low, high, size) of the contiguous ROM area that is patched."""
        rom = self.rom_slots
        if not rom:
            return None
        lo = min(e.slot for e in rom)
        hi = max(e.slot for e in rom)
        return lo, hi, hi - lo + 1

    @property
    def patch_window(self) -> tuple[int, int, int] | None:
        return self.patch_table_window()


def parse_patch_table(rom: bytes) -> PatchTable:
    """Decode the 1353-entry boot patch table out of a z64 image."""
    if len(rom) < PATCH_TABLE_END or len(rom) % 4:
        raise ValueError("ROM too small or not word aligned")
    words = struct.unpack_from(">%dI" % (len(rom) // 4), rom, 0)
    entries: list[PatchEntry] = []
    off = PATCH_TABLE_START
    index = 0
    while off + 8 <= PATCH_TABLE_END:
        slot = words[off // 4]
        value = words[off // 4 + 1]
        entries.append(
            PatchEntry(index, slot, value, classify_address(slot), classify_address(value))
        )
        off += 8
        index += 1
    return PatchTable(entries)


def cluster_by_bucket(addrs, bucket: int = 0x10000) -> list[tuple[int, int]]:
    """Group addresses into ``bucket``-sized ranges -> [(base, count), ...]."""
    counts: dict[int, int] = {}
    for a in addrs:
        base = a - (a % bucket)
        counts[base] = counts.get(base, 0) + 1
    return sorted(counts.items())


def scan_magics(rom: bytes, magics, start: int = ASSET_START, end: int = ASSET_END) -> dict:
    """Find every occurrence of each byte pattern inside a ROM window."""
    blob = rom[start:end]
    out: dict[bytes, list[int]] = {}
    for magic in magics:
        hits: list[int] = []
        i = blob.find(magic)
        while i != -1:
            hits.append(start + i)
            i = blob.find(magic, i + 1)
        out[magic] = hits
    return out


def preview(rom: bytes, addr: int, length: int = 64) -> str:
    """Hex dump of ``length`` bytes at ``addr`` (read-only probe helper)."""
    return rom[addr:addr + length].hex()


def summarize(rom: bytes) -> dict:
    """Structural summary of the patch table plus the z64 image identity."""
    table = parse_patch_table(rom)
    window = table.patch_window
    return {
        "z64_sha256": hashlib.sha256(rom).hexdigest(),
        "entries": len(table.entries),
        "rom_slots": len(table.rom_slots),
        "ram_slots": len(table.ram_slots),
        "asset_values": len(table.asset_values),
        "ram_values": len(table.ram_values),
        "patch_window": (
            None if window is None else ["0x%X" % window[0], "0x%X" % window[1], window[2]]
        ),
    }


def main(argv=None) -> None:
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    rom = load_rom(argv[0] if argv else DEFAULT_ROM)
    for key, value in summarize(rom).items():
        print(f"{key}: {value}")
    table = parse_patch_table(rom)
    print("asset pointer clusters (64 KiB):")
    for base, count in cluster_by_bucket(table.asset_values):
        print(f"  0x{base:06X}  {count}")


if __name__ == "__main__":
    main()
