"""Native reader for DOA5LR (PS3) ``char_dat`` character payloads.

Verified against two owned-source payloads from ``chara_common.lnk``
(CHCM, 2355 entries):

  entry 0018 : 58,484  bytes  sha256 d0b72267...72e6
  entry 0940 : 7,357,824 bytes sha256 965a99ab...eb481

Format (byte order: big-endian, PS3; offsets absolute from payload start):

Outer header (0x00..0x40, 64 bytes)::

  0x00  magic     b"char_dat"
  0x08  reserved  0xFF000101
  0x14  flags     0x00000001 (same in all sampled entries)
  0x18  flags     0x00000001
  0x20  hdr_size  0x00000030 (48)
  0x30  data_ptr  0x00000040 -> inner subheader

Inner subheader (0x40..0x9C, 76 bytes)::

  0x40  magic     b"char_dat"
  0x48  reserved  0xFF000101
  0x54  n_sec     0x00000007 (7)
  0x58  n_entries 0x00000006 (6 per-block tables)
  0x60  hdr_size  0x00000030 (48)
  0x70  data_ptr  0x00000050

Section pointer array (0x74..0x90, ``n_sec`` u32, last entry null)::

  0x78  sec0 ptr  (32B header record)
  0x7C  sec1 ptr  (136 u16 table)
  0x80  sec2 ptr  (128 u32 table)
  0x84  sec3 ptr  (32 u32 record)
  0x88  sec4 ptr  (large trailing data; end of payload)
  0x8C  null      0x00000000
  0x90  count     0x00000010 (16 ptable slots)

Pointer table (0x94..0xB4, 16 u32)::

  0x94  geometry table start (u16 stream, ends at texture table)
  0x98  texture table start  (u16 stream, ends at sec0)
  0x9C  reserved 0
  0xA0  6 per-block table starts (consecutive)
  0xC4  4 reserved/duplicate pointers

Layout between pointers (entry 0018, identical topology for 0940)::

  0x0010 .. block0   header data (unclassified u16/u32)
  0x0310 .. 0x0400   block table 0 (120 u16; sparse 0/offset pairs)
  0x0400 .. 0x0510   block table 1 (136 u16)
  0x0510 .. 0x05C0   block table 2 ( 88 u16)
  0x05C0 .. 0x06E0   block table 3 (144 u16)
  0x06E0 .. 0x07F0   block table 4 (136 u16)
  0x07F0 .. 0x0910   block table 5 (128 u16)
  0x0910 .. 0x0A90   extra table (mixed; 0x910 repeated 3x in ptable)
  0x0A90 .. 0x4170   (continues into geometry region)
  0x4170 .. 0x8950   geometry table (u16 stream)
  0x8950 .. 0xBB40   texture table (u16 stream)
  0xBB40 .. 0xBB60   sec0: 8 u32 record
  0xBB60 .. 0xBC70   sec1: 136 u16
  0xBC70 .. 0xBE70   sec2: 128 u32
  0xBE70 .. 0xBEB0   sec3: 32 u32
  0xBEB0 .. 0xE474   sec4: trailing data (4834 u16 for 0018)

The per-block tables contain 10-bit values plus tag bits in the upper
bits (block0 sampled: 0x000/0x400-class offsets for mesh/texture block
offsets; blocks 1-5 hold 6-bit tag + 10-bit index triples). Exact
semantic mapping per table requires Ghidra loader analysis on the
native worker; this reader is a verified structural baseline that
proves byte-exact section extraction.
"""
from __future__ import annotations

import hashlib
import struct

__all__ = ["parse_char_dat", "CharDatError"]

MAGIC = b"char_dat"
RESERVED = 0xFF000101

_PTABLE_SLOTS = 16
_N_SECTIONS = 7
_N_ENTRIES = 6


class CharDatError(ValueError):
    """Raised when a char_dat payload fails structural validation."""


def _u32(buf: bytes, off: int) -> int:
    return struct.unpack_from(">I", buf, off)[0]


def _u16(buf: bytes, off: int) -> int:
    return struct.unpack_from(">H", buf, off)[0]


def _expect(buf: bytes, off: int, field: str, expected, actual):
    if actual != expected:
        raise CharDatError(
            f"{field} mismatch at 0x{off:04x}: expected 0x{expected:x}, got 0x{actual:x}"
        )


def parse_char_dat(payload: bytes) -> dict:
    """Parse a char_dat payload and return a verified structural model.

    Every section boundary is derived from the header pointers and
    validated against the actual payload length.  Raises CharDatError
    on any structural inconsistency.
    """
    if len(payload) < 0xB4:
        raise CharDatError(f"payload too short: {len(payload)} < 0xB4")
    if payload[:8] != MAGIC:
        raise CharDatError(f"outer magic: {payload[:8]!r}")
    if payload[0x40:0x48] != MAGIC:
        raise CharDatError(f"inner magic: {payload[0x40:0x48]!r}")

    # --- outer header ---
    _expect(payload, 0x08, "outer.reserved", RESERVED, _u32(payload, 0x08))
    _expect(payload, 0x20, "outer.hdr_size", 0x30, _u32(payload, 0x20))
    _expect(payload, 0x30, "outer.data_ptr", 0x40, _u32(payload, 0x30))

    # --- inner subheader ---
    _expect(payload, 0x48, "inner.reserved", RESERVED, _u32(payload, 0x48))
    _expect(payload, 0x54, "inner.n_sec", _N_SECTIONS, _u32(payload, 0x54))
    _expect(payload, 0x58, "inner.n_entries", _N_ENTRIES, _u32(payload, 0x58))
    _expect(payload, 0x60, "inner.hdr_size", 0x30, _u32(payload, 0x60))
    _expect(payload, 0x70, "inner.data_ptr", 0x50, _u32(payload, 0x70))

    # --- section pointers ---
    sec_ptrs = [_u32(payload, 0x78 + i * 4) for i in range(_N_SECTIONS)]
    if sec_ptrs[-2] != 0:
        raise CharDatError(f"section[{_N_SECTIONS - 2}] should be null: 0x{sec_ptrs[-2]:x}")
    active = sorted(set(p for p in sec_ptrs if p and p != 0x10))
    if not active:
        raise CharDatError("no active section pointers")
    # sections start at the data region (0x10); first section end = active[0]
    data_start = 0x10
    bounds = [data_start] + active + [len(payload)]
    sections = []
    for idx, (start, end) in enumerate(zip(bounds, bounds[1:])):
        if start >= end:
            raise CharDatError(f"section {idx}: start 0x{start:x} >= end 0x{end:x}")
        sections.append({
            "index": idx,
            "start": start,
            "end": end,
            "size": end - start,
            "u16_count": (end - start) // 2,
        })

    # --- pointer table ---
    ptable = [_u32(payload, 0x94 + i * 4) for i in range(_PTABLE_SLOTS)]
    if ptable[2] != 0:
        raise CharDatError(f"ptable[2] should be null: 0x{ptable[2]:x}")
    geom_ptr, tex_ptr = ptable[0], ptable[1]
    if not (0 < geom_ptr < tex_ptr < active[0]):
        raise CharDatError(
            f"geometry/texture order broken: geom=0x{geom_ptr:x} tex=0x{tex_ptr:x} sec0=0x{active[0]:x}"
        )
    block_ptrs = ptable[3:3 + _N_ENTRIES]
    if any(p == 0 for p in block_ptrs):
        raise CharDatError("a block-table pointer is null")
    extra_ptr = ptable[3 + _N_ENTRIES]
    if not (0 < extra_ptr < geom_ptr):
        raise CharDatError(
            f"extra-table pointer out of range: extra=0x{extra_ptr:x} geom=0x{geom_ptr:x}"
        )
    blk_bounds = block_ptrs + [extra_ptr]
    for a, b in zip(blk_bounds, blk_bounds[1:]):
        if not (0 < a < b):
            raise CharDatError(f"block table range broken: 0x{a:x}..0x{b:x}")

    return {
        "magic": "char_dat",
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "byte_order": "big-endian",
        "outer_header": {
            "hdr_size": _u32(payload, 0x20),
            "data_ptr": _u32(payload, 0x30),
            "flags_14": _u32(payload, 0x14),
            "flags_18": _u32(payload, 0x18),
        },
        "inner_header": {
            "n_sections": _N_SECTIONS,
            "n_entries": _N_ENTRIES,
            "data_ptr": _u32(payload, 0x70),
        },
        "section_ptrs": [hex(p) for p in sec_ptrs],
        "sections": sections,
        "geometry_table": {"start": geom_ptr, "end": tex_ptr,
                           "size": tex_ptr - geom_ptr, "u16_count": (tex_ptr - geom_ptr) // 2},
        "texture_table": {"start": tex_ptr, "end": active[0],
                          "size": active[0] - tex_ptr, "u16_count": (active[0] - tex_ptr) // 2},
        "block_tables": [
            {"start": block_ptrs[i], "end": blk_bounds[i + 1],
             "size": blk_bounds[i + 1] - block_ptrs[i],
             "u16_count": (blk_bounds[i + 1] - block_ptrs[i]) // 2}
            for i in range(_N_ENTRIES)
        ],
        "extra_table": {"start": extra_ptr, "end": geom_ptr,
                        "size": geom_ptr - extra_ptr,
                        "u16_count": (geom_ptr - extra_ptr) // 2},
        "trailing_data": sections[-1],
        "ptable": [hex(p) for p in ptable],
    }


def extract_section(payload: bytes, section_index: int) -> bytes:
    """Return the raw bytes of a named section (0..4 + trailing=5)."""
    info = parse_char_dat(payload)
    sec = info["sections"][section_index]
    return payload[sec["start"]:sec["end"]]


if __name__ == "__main__":
    import json, sys
    if len(sys.argv) < 2:
        print("usage: python doa5lr_char_dat.py <char_dat_file>")
        sys.exit(1)
    info = parse_char_dat(open(sys.argv[1], "rb").read())
    print(json.dumps(info, indent=2))
