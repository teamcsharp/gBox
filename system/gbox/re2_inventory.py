"""Inventory for Resident Evil 2 (Nintendo 64, USA Rev 1).

Reads an owned RE2 N64 ROM image (``.z64``/``.v64``/``.n64``, or a zip holding
one), normalises it to big-endian cart order, walks the game's own tables and
produces a manifest covering:

* source identity (file/ROM hashes, game code, build stamp)
* the static ROM region map
* the code overlay table (cart address, compressed size, load/end addresses)
* the asset directory (RE2's file container: 8-byte {offset, size} records
  plus an 8-byte per-file trailer carrying the storage codec)
* the character tables in overlay 1: for each of the four entity tables,
  every character's mesh asset, animation assets and texture set

Container facts (USA Rev 1, cart ``NREE``):

* Overlay table: 16-byte records at ROM 0x12CD0, magic record
  ``OVERLAYTABLENUMC``.  Entry 1 is the main binary; entry 0x43 points at the
  asset directory.  Each code overlay is a raw-deflate stream behind a 2-byte
  block header.
* Asset directory: 0x28-byte header (u32 file count, ASCII build stamp),
  then 8-byte records {u32 offset relative to the directory base, u32 stored
  size}; 0xFFFFFFFF marks a null slot.  A file's payload sits at
  ``base + offset``, is padded to an even length, and is followed by an
  8-byte trailer {u32 tag, u32 decompressed size} with ``tag >> 16`` the
  storage codec: 1 stored verbatim, 2 byte PackBits, 4 16-bit-unit PackBits,
  16 raw deflate behind a 2-byte header.
* Character tables (inside decompressed overlay 1, loads at 0x80018A80):
  the character asset table at 0x80126C80 holds 8 u16 asset ids per character
  (mesh at slot 7, animations in slots 1-6), the pair table at 0x801275C0
  maps a character to its texture ids, and the four entity tables at
  0x801287B0/0x80128A10/0x80128C70/0x80128ED0 tie entity slots to the pair
  table and the character asset table.

Usage::

    python -m gbox.re2_inventory ROM [--zip-sha256 H] [--out manifest.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

ROM_LENGTH = 0x4000000  # 64 MiB retail cart
OVERLAY_MAGIC = b"OVERLAYTABLENUMC"
OVERLAY_RECORD = 0x10
OVERLAY_TABLE_ROM = 0x12CD0          # RAM 0x80012150
OVERLAY_TABLE_SCAN_START = 0x10000
OVERLAY_TABLE_SCAN_END = 0x14422
OVERLAY_DIRECTORY_INDEX = 0x43       # record pointing at the asset directory
OVERLAY_MAIN_INDEX = 1

ASSET_HEADER = 0x28
ASSET_RECORD = 8
ASSET_TRAILER = 8
ASSET_NULL = 0xFFFFFFFF
DEFLATE_BLOCK_HEADER = 2

# Overlay 1 (Rev 1) tables, RAM addresses.
CHAR_ASSET_TABLE = 0x80126C80        # 8 u16 asset ids per character
PAIR_TABLE = 0x801275C0              # texture sets
ENTITY_TABLES = (0x801287B0, 0x80128A10, 0x80128C70, 0x80128ED0)
ENTITY_RECORD = 8
LAST_TABLE_RECORDS = 0x170 // ENTITY_RECORD
ASSETS_PER_CHARACTER = 8
MESH_SLOT = 7
NO_VALUE = 0xFFFF

# Static layout of the retail image (USA Rev 1).
REGIONS = [
    ("header", 0x0000000, 0x0001000),
    ("boot", 0x0001000, 0x000FD00),
    ("overlay.zlib", 0x000FD00, 0x0014422),
    ("code.deflate", 0x0014422, 0x00B624D),
    ("overlays.bank2", 0x00B624D, 0x00C8624),
    ("tables", 0x00C8624, 0x00D8000),
    ("assets.a", 0x00D8000, 0x2BDEFB2),
    ("backgrounds", 0x2BDEFB2, 0x3AF17FE),
    ("assets.b", 0x3AF17FE, 0x3FD0DF5),
    ("padding", 0x3FD0DF5, 0x4000000),
]


def u16(data: bytes, off: int) -> int:
    return struct.unpack_from(">H", data, off)[0]


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from(">I", data, off)[0]


def packbits_decode(data: bytes) -> bytes:
    """Decode a byte-unit PackBits stream (0x80-based runs, 0 terminates)."""
    out = bytearray()
    at = 0
    n = len(data)
    while at < n:
        control = data[at]
        at += 1
        if control == 0:
            break
        if control < 0x80:
            count = min(control, n - at)
            out += data[at:at + count]
            at += count
        else:
            if at >= n:
                break
            out += bytes([data[at]]) * (0x100 - control)
            at += 1
    return bytes(out)


def packbits16_decode(data: bytes) -> bytes:
    """Decode a 16-bit-unit PackBits stream (signed BE control words)."""
    out = bytearray()
    at = 0
    n = len(data)
    while at + 2 <= n:
        control = struct.unpack_from(">h", data, at)[0]
        at += 2
        if control == 0:
            break
        if control > 0:
            count = min(control * 2, n - at)
            out += data[at:at + count]
            at += count
        else:
            if at + 2 > n:
                break
            out += data[at:at + 2] * (-control)
            at += 2
    return bytes(out)


def raw_inflate(data: bytes, limit: int) -> bytes | None:
    """Inflate a raw-deflate stream that sits behind a 2-byte header."""
    if len(data) < DEFLATE_BLOCK_HEADER + limit:
        limit = max(0, len(data) - DEFLATE_BLOCK_HEADER)
    try:
        dec = zlib.decompressobj(wbits=-15)
        out = dec.decompress(data[DEFLATE_BLOCK_HEADER:DEFLATE_BLOCK_HEADER + limit])
        out += dec.flush()
        return out
    except zlib.error:
        return None


def detect_order(raw: bytes) -> str:
    magic = u32(raw, 0)
    if magic == 0x80371240:
        return "z64"
    if magic == 0x37804012:
        return "v64"
    if magic == 0x40123780:
        return "n64"
    raise ValueError(f"unrecognised N64 magic 0x{magic:08X}")


def normalize(raw: bytes) -> bytes:
    order = detect_order(raw)
    if order == "z64":
        return raw
    data = bytearray(raw)
    if order == "v64":
        for i in range(0, len(data) - 1, 2):
            data[i], data[i + 1] = data[i + 1], data[i]
    else:  # n64: 32-bit words little-endian
        for i in range(0, len(data) - 3, 4):
            data[i:i + 4] = data[i + 3:i - 1:-1]
    return bytes(data)


@dataclass
class OverlayEntry:
    index: int
    cart_addr: int
    compressed_size: int
    load_addr: int
    end_addr: int

    @property
    def rom_offset(self) -> int:
        return self.cart_addr & 0x0FFFFFFF

    @property
    def payload_offset(self) -> int:
        return self.rom_offset + DEFLATE_BLOCK_HEADER

    @property
    def decompressed_size(self) -> int:
        return self.end_addr - self.load_addr

    @property
    def empty(self) -> bool:
        return self.compressed_size == 0 or self.decompressed_size <= 0

    def decompress(self, rom: bytes) -> bytes | None:
        if self.empty or self.payload_offset >= len(rom):
            return None
        out = raw_inflate(rom[self.rom_offset:], self.compressed_size + 64)
        if out is None or len(out) != self.decompressed_size:
            return None
        return out


def find_overlay_table(rom: bytes) -> int:
    if rom[OVERLAY_TABLE_ROM:OVERLAY_TABLE_ROM + OVERLAY_RECORD] == OVERLAY_MAGIC:
        return OVERLAY_TABLE_ROM
    for at in range(OVERLAY_TABLE_SCAN_START,
                    min(OVERLAY_TABLE_SCAN_END, len(rom) - OVERLAY_RECORD),
                    OVERLAY_RECORD):
        if rom[at:at + OVERLAY_RECORD] == OVERLAY_MAGIC:
            return at
    raise ValueError("overlay table not found")


def read_overlays(rom: bytes) -> list[OverlayEntry]:
    table = find_overlay_table(rom)
    entries: list[OverlayEntry] = []
    for index in range(1, 256):
        at = table + index * OVERLAY_RECORD
        if at + OVERLAY_RECORD > len(rom):
            break
        cart = u32(rom, at)
        if not (0xB0000000 <= cart < 0xB4000000):
            break
        load = u32(rom, at + 8)
        if not (0x80000000 <= load < 0x80800000):
            break
        entries.append(OverlayEntry(index, cart, u32(rom, at + 4), load, u32(rom, at + 12)))
    return entries


@dataclass
class AssetEntry:
    index: int
    rel_offset: int
    stored_size: int
    kind: int
    declared_size: int

    @property
    def padded_size(self) -> int:
        return self.stored_size + (self.stored_size & 1)

    def decode(self, rom: bytes, base: int) -> bytes | None:
        start = base + self.rel_offset
        stored = rom[start:start + self.stored_size]
        if len(stored) != self.stored_size:
            return None
        if self.kind == 1:
            out = stored
        elif self.kind == 2:
            out = packbits_decode(stored)
        elif self.kind == 4:
            out = packbits16_decode(stored)
        elif self.kind == 16:
            out = raw_inflate(stored, self.stored_size)
            if out is None:
                return None
        else:
            return None
        return out if len(out) == self.declared_size else None


@dataclass
class AssetDirectory:
    base: int
    count: int
    build_stamp: str
    entries: list[AssetEntry]
    null_slots: int


def read_asset_directory(rom: bytes, overlays: list[OverlayEntry]) -> AssetDirectory:
    # The directory record lives at a fixed table slot; the overlay parse
    # stops before it (its load address is outside the code range).
    at = find_overlay_table(rom) + OVERLAY_DIRECTORY_INDEX * OVERLAY_RECORD
    if at + 4 > len(rom):
        raise ValueError("overlay table does not extend to the directory record")
    base = u32(rom, at) & 0x0FFFFFFF
    if base < 0x1000 or base + ASSET_HEADER > len(rom):
        raise ValueError(f"implausible directory base 0x{base:X}")
    count = u32(rom, base)
    if count <= 0 or base + ASSET_HEADER + count * ASSET_RECORD > len(rom):
        raise ValueError(f"implausible file count {count} at 0x{base:X}")
    stamp_bytes = rom[base + 8:base + ASSET_HEADER]
    stamp = stamp_bytes.split(b"\n", 1)[0].decode("latin1").strip("\x00 ")
    entries: list[AssetEntry] = []
    nulls = 0
    for i in range(count):
        rec = base + ASSET_HEADER + i * ASSET_RECORD
        offset = u32(rom, rec)
        stored = u32(rom, rec + 4)
        if offset == ASSET_NULL:
            nulls += 1
            continue
        start = base + offset
        trailer = start + stored + (stored & 1)
        if trailer + ASSET_TRAILER > len(rom):
            nulls += 1
            continue
        tag = u32(rom, trailer)
        entries.append(AssetEntry(i, offset, stored, tag >> 16, u32(rom, trailer + 4)))
    return AssetDirectory(base, count, stamp, entries, nulls)


def _at(overlay: bytes, load_base: int, address: int, length: int) -> int:
    off = address - load_base
    if off < 0 or off + length > len(overlay):
        raise ValueError(f"address 0x{address:08X} outside overlay 1")
    return off


def read_characters(rom: bytes, overlays: list[OverlayEntry]) -> dict:
    main = next((e for e in overlays if e.index == OVERLAY_MAIN_INDEX), None)
    if main is None:
        raise ValueError("no main overlay (entry 1)")
    data = main.decompress(rom)
    if data is None:
        raise ValueError("main overlay does not inflate to its declared size")
    load = main.load_addr

    tables = []
    for ti, table_addr in enumerate(ENTITY_TABLES):
        chars = []
        limit = LAST_TABLE_RECORDS if ti == len(ENTITY_TABLES) - 1 else 128
        for i in range(limit):
            rec = _at(data, load, table_addr + i * ENTITY_RECORD, ENTITY_RECORD)
            pair_index = u16(data, rec + 4)
            asset_base = u16(data, rec + 6)
            if pair_index == NO_VALUE or asset_base == NO_VALUE:
                continue
            base_off = _at(data, load, CHAR_ASSET_TABLE + asset_base * 2,
                           ASSETS_PER_CHARACTER * 2)
            ids = [u16(data, base_off + s * 2) for s in range(ASSETS_PER_CHARACTER)]
            mesh = ids[MESH_SLOT]
            if mesh == NO_VALUE:
                continue
            animations = [v for v in ids[1:MESH_SLOT] if v != NO_VALUE]
            pair_off = _at(data, load, PAIR_TABLE + pair_index * 2, 4)
            tex_count = u16(data, pair_off)
            tex_kind = u16(data, pair_off + 2)
            if not (0 < tex_count <= 256):
                continue
            words = 2 + tex_count * (2 if tex_kind == 2 else 1)
            tex_off = _at(data, load, PAIR_TABLE + pair_index * 2, words * 2)
            texture_ids = [u16(data, tex_off + 4 + k * 2) for k in range(tex_count)]
            alternates = ([u16(data, tex_off + 4 + (tex_count + k) * 2)
                           for k in range(tex_count)] if tex_kind == 2 else [])
            chars.append({
                "index": i,
                "pair_index": pair_index,
                "asset_base": asset_base,
                "mesh_asset": mesh,
                "animation_assets": animations,
                "texture_ids": texture_ids,
                "alternate_texture_ids": alternates,
            })
        tables.append({"ram_address": table_addr, "characters": chars})
    return {"load_address": load, "entity_tables": tables}


def _load_source(src: Path) -> tuple[bytes, str]:
    """Return (normalised ROM bytes, byte order of the stored image)."""
    raw = src.read_bytes()
    order = detect_order(raw)
    if order in ("z64", "v64", "n64"):
        return normalize(raw), order
    raise ValueError("source is neither an N64 image nor a zip of one")


def load_rom(src: Path) -> tuple[bytes, str, str | None]:
    """Return (normalised ROM, stored byte order, zip sha256 or None)."""
    if zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            if len(names) != 1:
                raise ValueError(f"zip must hold exactly one ROM, has {names}")
            raw = zf.read(names[0])
        order = detect_order(raw)
        return normalize(raw), order, hashlib.sha256(src.read_bytes()).hexdigest()
    raw = src.read_bytes()
    return normalize(raw), detect_order(raw), None


def inventory(src: Path, source_sha256: str | None = None) -> dict:
    rom, order, zip_sha = load_rom(src)
    if len(rom) > ROM_LENGTH:
        raise ValueError(f"ROM larger than the retail 64 MiB image ({len(rom)} bytes)")
    sha = source_sha256 or zip_sha or hashlib.sha256(src.read_bytes()).hexdigest()

    overlays = read_overlays(rom)
    directory = read_asset_directory(rom, overlays)
    kinds: dict[str, int] = {}
    for e in directory.entries:
        kinds[str(e.kind)] = kinds.get(str(e.kind), 0) + 1
    decoded = 0
    for e in directory.entries:
        if e.decode(rom, directory.base) is not None:
            decoded += 1
    characters = read_characters(rom, overlays)

    mesh_ids = sorted({c["mesh_asset"]
                       for t in characters["entity_tables"] for c in t["characters"]})
    anim_ids = sorted({a
                       for t in characters["entity_tables"] for c in t["characters"]
                       for a in c["animation_assets"]})
    tex_ids = sorted({x
                      for t in characters["entity_tables"] for c in t["characters"]
                      for x in c["texture_ids"]})
    mesh_decoded = 0
    mesh_heads: dict[int, str] = {}
    for e in directory.entries:
        if e.index not in mesh_ids:
            continue
        decoded_data = e.decode(rom, directory.base)
        if decoded_data is not None and len(decoded_data) >= 4:
            mesh_decoded += 1
            mesh_heads[e.index] = decoded_data[:4].hex()

    build_stamp = rom[0xC862C:0xC862C + 0x30].split(b"\n", 1)[0].decode("latin1").strip("\x00 ")

    return {
        "game": {
            "title": "Resident Evil 2 (USA) (Rev 1)",
            "platform": "n64",
            "game_code": rom[0x3B:0x3F].decode("ascii", "replace"),
            "internal_name": rom[0x20:0x34].decode("ascii").strip("\x00 "),
            "version": rom[0x3F],
            "build_stamp": build_stamp,
            "boot_checksum_multiplier": "0x"
            + rom[0x5A6:0x5A8].hex() + rom[0x5AA:0x5AC].hex(),
        },
        "source": {
            "sha256": sha,
            "stored_byte_order": order,
            "rom_sha256": hashlib.sha256(rom).hexdigest(),
            "rom_md5": hashlib.md5(rom).hexdigest(),
            "rom_crc32": format(zlib.crc32(rom) & 0xFFFFFFFF, "08x"),
            "header_crc1": format(u32(rom, 0x10), "08x"),
            "length": len(rom),
        },
        "launch": {
            "library": "hyperspin",
            "core": "parallel_n64",
            "node": "windows-node",
            "note": "64 MiB cart; custom RSP ucode (video tasks), IPL2 checksum boot.",
        },
        "regions": [{"name": n, "start": s, "end": min(e, len(rom))}
                    for n, s, e in REGIONS if s < len(rom)],
        "overlay_table": {
            "rom_offset": find_overlay_table(rom),
            "entries": [
                {
                    "index": e.index,
                    "rom_offset": e.rom_offset,
                    "compressed_size": e.compressed_size,
                    "load_address": hex(e.load_addr),
                    "end_address": hex(e.end_addr),
                    "decompressed_size": e.decompressed_size,
                    "decompresses": e.decompress(rom) is not None,
                }
                for e in overlays
            ],
        },
        "asset_directory": {
            "base_offset": directory.base,
            "file_count": directory.count,
            "null_slots": directory.null_slots,
            "build_stamp": directory.build_stamp,
            "storage_kinds": kinds,
            "entries": len(directory.entries),
            "decoded": decoded,
            "total_stored_bytes": sum(e.stored_size for e in directory.entries),
            "total_decoded_bytes": sum(e.declared_size for e in directory.entries),
        },
        "characters": {
            "ram_tables": {
                "character_assets": hex(CHAR_ASSET_TABLE),
                "pairs": hex(PAIR_TABLE),
                "entities": [hex(a) for a in ENTITY_TABLES],
            },
            "mesh_asset_ids": mesh_ids,
            "animation_asset_ids": anim_ids,
            "texture_asset_ids": tex_ids,
            "mesh_assets_decoded": mesh_decoded,
            "mesh_asset_heads": mesh_heads,
            "entity_tables": characters["entity_tables"],
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Inventory a Resident Evil 2 (N64) ROM.")
    ap.add_argument("src", type=Path, help=".z64/.v64/.n64 image or a zip holding one")
    ap.add_argument("--zip-sha256", help="sha256 of the owned source archive")
    ap.add_argument("--out", type=Path, help="write the manifest JSON here")
    args = ap.parse_args(argv)
    manifest = inventory(args.src, args.zip_sha256)
    text = json.dumps(manifest, indent=2)
    if args.out:
        args.out.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
