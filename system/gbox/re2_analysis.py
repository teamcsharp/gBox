"""Analysis probe for Resident Evil 2 (Nintendo 64, USA Rev 1).

This module extends the inventory work with focused reverse-engineering
of the executable and the native character-mesh container:

* scans decompressed overlay 1 (main binary, load address 0x80018A80) for
  code xrefs to the character tables (character asset table at 0x80126C80,
  pair/texture table at 0x801275C0, and the four entity tables)
* parses the 0x01410000 mesh asset container used by every character mesh
  in the game (assets 5599-5666 in the USA Rev 1 build)
* validates the internal structure (header, body, four tail records,
  sub-file index table) and returns a reproducible report

The probe is intentionally bounded: it does not decode every triangle
command or texture format, but it proves the layout and anchors it to
real code addresses.
"""

from __future__ import annotations

import dataclasses
import json
import struct
from pathlib import Path
from typing import Any

import hashlib

from gbox import re2_inventory as ri

# Known RAM addresses of the character tables inside overlay 1.
# These are the same constants used by re2_inventory; we import them so
# the analysis and inventory stay in sync.
CHAR_ASSET_TABLE = ri.CHAR_ASSET_TABLE
PAIR_TABLE = ri.PAIR_TABLE
ENTITY_TABLES = ri.ENTITY_TABLES

# Header size observed in every mesh asset.
MESH_HEADER_SIZE = 0x110
MESH_MAGIC = 0x01410000

# MIPS instruction bit fields.
MIPS_OPCODE = 26
MIPS_RT = 16
MIPS_RS = 21
MIPS_IMM = 0xFFFF

# Opcodes we care about for xref discovery.
OP_LUI = 0x0F
OP_ADDIU = 0x09
OP_ADDI = 0x08
OP_ORI = 0x0D


@dataclasses.dataclass(frozen=True)
class CodeXref:
    """A reproducible code reference to a data table inside overlay 1."""

    table_name: str
    table_address: int
    lui_address: int
    use_address: int
    use_kind: str  # "ADDIU", "ORI", "ADDI"
    immediate: int


@dataclasses.dataclass(frozen=True)
class TailRecord:
    """One 16-byte record at the end of a mesh asset."""

    record_type: int
    offset: int


@dataclasses.dataclass(frozen=True)
class MeshAsset:
    """A parsed 0x01410000 character-mesh asset."""

    asset_id: int
    raw: bytes
    magic: int
    version: int
    body_size: int
    chunk_count: int
    tail_records: list[TailRecord]
    index_table_offset: int | None
    index_table_type: int | None
    index_entries: list[tuple[int, int]]
    valid: bool
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "magic": f"0x{self.magic:08x}",
            "version": self.version,
            "body_size": self.body_size,
            "chunk_count": self.chunk_count,
            "total_size": len(self.raw),
            "tail_records": [
                {"type": r.record_type, "offset": r.offset, "offset_hex": f"0x{r.offset:x}"}
                for r in self.tail_records
            ],
            "index_table": {
                "type": self.index_table_type,
                "offset": self.index_table_offset,
                "offset_hex": f"0x{self.index_table_offset:x}" if self.index_table_offset is not None else None,
                "entries": [
                    {"a": a, "b": b, "a_hex": f"0x{a:x}", "b_hex": f"0x{b:x}"}
                    for a, b in self.index_entries
                ],
            },
            "valid": self.valid,
            "notes": self.notes,
        }


def _find_lui_use_pairs(
    code: bytes,
    load_base: int,
    target_address: int,
    table_name: str,
    max_distance: int = 64,
) -> list[CodeXref]:
    """Find LUI high-half + ADDIU/ORI/ADDI low-half references to a table.

    ADDIU/ADDI sign-extend their immediate, so for a low half >= 0x8000 the
    compiler emits LUI %hi(addr) = (addr + 0x8000) >> 16; ORI zero-extends and
    pairs with the plain high half."""
    low = target_address & 0xFFFF
    high_ori = (target_address >> 16) & 0xFFFF
    high_add = ((target_address + 0x8000) >> 16) & 0xFFFF
    results: list[CodeXref] = []
    for i in range(0, len(code) - 3, 4):
        instr = struct.unpack_from(">I", code, i)[0]
        opcode = instr >> MIPS_OPCODE
        rt = (instr >> MIPS_RT) & 0x1F
        imm = instr & MIPS_IMM
        if opcode != OP_LUI or imm not in (high_ori, high_add):
            continue
        for j in range(i + 4, min(i + max_distance, len(code) - 3), 4):
            instr2 = struct.unpack_from(">I", code, j)[0]
            opcode2 = instr2 >> MIPS_OPCODE
            rs2 = (instr2 >> MIPS_RS) & 0x1F   # the low-half add/or reads the LUI register as its source
            imm2 = instr2 & MIPS_IMM
            if rs2 != rt:
                continue
            if imm == high_add and opcode2 == OP_ADDIU and imm2 == low:
                results.append(
                    CodeXref(
                        table_name=table_name,
                        table_address=target_address,
                        lui_address=load_base + i,
                        use_address=load_base + j,
                        use_kind="ADDIU",
                        immediate=imm2,
                    )
                )
                break
            if imm == high_add and opcode2 == OP_ADDI and imm2 == low:
                results.append(
                    CodeXref(
                        table_name=table_name,
                        table_address=target_address,
                        lui_address=load_base + i,
                        use_address=load_base + j,
                        use_kind="ADDI",
                        immediate=imm2,
                    )
                )
                break
            if imm == high_ori and opcode2 == OP_ORI and imm2 == low:
                results.append(
                    CodeXref(
                        table_name=table_name,
                        table_address=target_address,
                        lui_address=load_base + i,
                        use_address=load_base + j,
                        use_kind="ORI",
                        immediate=imm2,
                    )
                )
                break
    return results


def find_table_xrefs(overlay1: bytes, load_base: int = 0x80018A80) -> list[CodeXref]:
    """Return all code references to the character tables in overlay 1."""
    targets = [
        ("char_asset_table", CHAR_ASSET_TABLE),
        ("pair_table", PAIR_TABLE),
        ("entity_table_0", ENTITY_TABLES[0]),
        ("entity_table_1", ENTITY_TABLES[1]),
        ("entity_table_2", ENTITY_TABLES[2]),
        ("entity_table_3", ENTITY_TABLES[3]),
    ]
    out: list[CodeXref] = []
    for name, addr in targets:
        out.extend(_find_lui_use_pairs(overlay1, load_base, addr, name))
    return out


def parse_mesh_asset(asset_id: int, raw: bytes) -> MeshAsset:
    """Parse a 0x01410000 mesh asset and validate its internal structure."""
    notes: list[str] = []
    valid = True

    if len(raw) < MESH_HEADER_SIZE + 64:
        return MeshAsset(
            asset_id=asset_id,
            raw=raw,
            magic=0,
            version=0,
            body_size=0,
            chunk_count=0,
            tail_records=[],
            index_table_offset=None,
            index_table_type=None,
            index_entries=[],
            valid=False,
            notes=["asset too short for 0x01410000 header + tail"],
        )

    magic = struct.unpack_from(">I", raw, 0)[0]
    version = struct.unpack_from(">I", raw, 4)[0]
    body_size = struct.unpack_from(">I", raw, 8)[0]
    chunk_count = struct.unpack_from(">I", raw, 0x14)[0]

    if magic != MESH_MAGIC:
        valid = False
        notes.append(f"unexpected magic 0x{magic:08x}")
    if version != 0x11:
        notes.append(f"unexpected version 0x{version:08x}")
    if body_size != len(raw) - MESH_HEADER_SIZE:
        notes.append(
            f"body_size 0x{body_size:x} does not match file tail boundary "
            f"(expected 0x{len(raw) - MESH_HEADER_SIZE:x})"
        )

    # Tail records are the last 64 bytes of the asset: four 16-byte records.
    tail = raw[-64:]
    tail_records: list[TailRecord] = []
    for i in range(0, 64, 16):
        rec_type = struct.unpack_from(">I", tail, i)[0]
        offset = struct.unpack_from(">I", tail, i + 4)[0]
        tail_records.append(TailRecord(rec_type, offset))
        if offset < MESH_HEADER_SIZE or offset >= len(raw) - 64:
            valid = False
            notes.append(
                f"tail record {i // 16} offset 0x{offset:x} out of bounds"
            )

    # The last tail record points at the per-chunk index table (type 2 or 3).
    index_table_offset: int | None = None
    index_table_type: int | None = None
    index_entries: list[tuple[int, int]] = []
    if tail_records:
        last = tail_records[-1]
        if last.record_type in (2, 3) and MESH_HEADER_SIZE <= last.offset < len(raw) - 64:
            index_table_offset = last.offset
            index_table_type = last.record_type
            entry_count = 0
            # Read up to chunk_count entries, each is two big-endian u32 words.
            while (
                entry_count < chunk_count
                and index_table_offset + entry_count * 8 + 8 <= len(raw) - 64
            ):
                a = struct.unpack_from(">I", raw, index_table_offset + entry_count * 8)[0]
                b = struct.unpack_from(">I", raw, index_table_offset + entry_count * 8 + 4)[0]
                index_entries.append((a, b))
                entry_count += 1
            if len(index_entries) != chunk_count:
                notes.append(
                    f"index table has {len(index_entries)} entries, chunk_count={chunk_count}"
                )
        else:
            notes.append(
                f"last tail record type {last.record_type} does not point to an index table"
            )

    return MeshAsset(
        asset_id=asset_id,
        raw=raw,
        magic=magic,
        version=version,
        body_size=body_size,
        chunk_count=chunk_count,
        tail_records=tail_records,
        index_table_offset=index_table_offset,
        index_table_type=index_table_type,
        index_entries=index_entries,
        valid=valid,
        notes=notes,
    )


def analyze(
    rom_path: Path,
    mesh_assets: list[int] | None = None,
) -> dict[str, Any]:
    """Run the bounded analysis probe on an owned RE2 N64 ROM.

    *overlay_xrefs* lists every LUI+ADDIU/ORI/ADDI reference to the character
    tables inside overlay 1.  *mesh_probe* parses the 0x01410000 container for
    a sample of mesh assets and reports header/tail/index-table consistency.
    """
    rom, _, _ = ri.load_rom(rom_path)
    overlays = ri.read_overlays(rom)
    directory = ri.read_asset_directory(rom, overlays)
    by_index = {e.index: e for e in directory.entries}

    main = next(e for e in overlays if e.index == 1)
    overlay1 = main.decompress(rom)
    if overlay1 is None:
        raise ValueError("main overlay (1) does not decompress")

    xrefs = find_table_xrefs(overlay1, main.load_addr)

    if mesh_assets is None:
        # Default sample covers the first few character meshes.
        mesh_assets = [5599, 5600, 5603, 5606, 5611, 5620]

    mesh_probes: list[dict[str, Any]] = []
    for asset_id in mesh_assets:
        entry = by_index.get(asset_id)
        if entry is None:
            mesh_probes.append(
                {"asset_id": asset_id, "error": "not present in asset directory"}
            )
            continue
        decoded = entry.decode(rom, directory.base)
        if decoded is None:
            mesh_probes.append(
                {"asset_id": asset_id, "error": "failed to decode asset"}
            )
            continue
        mesh_probes.append(parse_mesh_asset(asset_id, decoded).to_dict())

    return {
        "source": {
            "rom_path": str(rom_path),
            "overlay_1_load_address": f"0x{main.load_addr:08x}",
            "overlay_1_size": len(overlay1),
            "overlay_1_sha256": hashlib.sha256(overlay1).hexdigest(),
        },
        "overlay_xrefs": [
            {
                "table": x.table_name,
                "table_address": f"0x{x.table_address:08x}",
                "lui_address": f"0x{x.lui_address:08x}",
                "use_address": f"0x{x.use_address:08x}",
                "use_kind": x.use_kind,
                "immediate": f"0x{x.immediate:04x}",
            }
            for x in xrefs
        ],
        "mesh_probe": mesh_probes,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="Run the RE2 N64 analysis probe and emit a JSON report."
    )
    ap.add_argument("src", type=Path, help=".z64/.v64/.n64 image or a zip holding one")
    ap.add_argument("--mesh-assets", type=int, nargs="+", help="asset ids to probe")
    ap.add_argument("--out", type=Path, help="write JSON report here")
    args = ap.parse_args(argv)

    report = analyze(args.src, args.mesh_assets)
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
