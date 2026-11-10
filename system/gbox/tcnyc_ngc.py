"""Format probe for the True Crime: New York City (GameCube) ``.ngc`` container.

Evidence (owned build, request 42a42d654ff546d2; survey of all 1,463 ``.ngc``/
``.exm`` FST entries, big-endian):

* All 1,431 ``.ngc`` files open with ``00000009 00060000 0000006c 000400NN``;
  ``NN`` (low byte of word 3) is a record count (58 for the body models).
* Header words 4..6 for ``Char/Bodies/Body_F_Bum.ngc``: ``0x70`` (record
  table offset), ``1``, ``0xf00`` (data offset). ``0x70 + 58*0x40 = 0xef0``;
  ``0xf00`` is that end rounded up by a 0x10 pad.  Across the disc
  ``data_offset - (table_offset + count*0x40)`` is 0x10 for 1,203 files and 0
  for 230; 30 ``.exm`` mission files use a different layout (not handled).
* Records are 0x40 bytes: big-endian float4 rows (the first 20 body records
  end in ``3f800000`` = 1.0), i.e. a per-node transform/skeleton table.  The
  entropy of the later 16 KiB blocks (5.4-7.4 bits/byte) and the failed zlib
  probes mean the data region (>= data_offset) is NOT plain floats and is
  not decoded here.
* No HSD header (u32[0] == file size) is present, so ``gbox.melee_models``
  does not apply as-is.

This is an analysis-stage probe, not a geometry extractor.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import List, Optional

TC2_HEADER = bytes.fromhex("00000009000600000000006c")
TC2_VERSION = 9
TC2_HEADER_WORD = 0x6C
HEADER_SIZE = 0x10
RECORD_BYTES = 0x40


class TC2FormatError(Exception):
    """Raised when a blob does not match the TC2 .ngc container layout."""


@dataclass
class NodeRecord:
    offset: int
    words: tuple  # 16 big-endian u32

    @property
    def floats(self) -> tuple:
        return struct.unpack(">16f", struct.pack(">16I", *self.words))


@dataclass
class TC2ModelHeader:
    version: int
    flags: int
    header_word: int
    record_count: int
    record_type: int
    table_offset: int
    word5: int
    data_offset: int
    data_size: int
    pad: int
    records: List[NodeRecord] = field(default_factory=list)


def _u32(data: bytes, off: int) -> int:
    if off + 4 > len(data):
        raise TC2FormatError(f"truncated: need 4 bytes at 0x{off:x}")
    return struct.unpack_from(">I", data, off)[0]


def is_tc2_container(data: bytes) -> bool:
    return len(data) >= 16 and data[:12] == TC2_HEADER


def is_hsd_archive(data: bytes, total_size: int) -> bool:
    """HSD archives start with u32 == file size; TC2 starts with 9."""
    if len(data) < 4:
        return False
    first = _u32(data, 0)
    return first == total_size or (0 < first <= total_size and total_size - first < 16)


def parse_tc2_model(data: bytes) -> TC2ModelHeader:
    """Decode the header and the 0x40-byte node-record table of a ``.ngc``."""
    if not is_tc2_container(data):
        raise TC2FormatError(f"not a TC2 container: head {data[:12].hex()}")
    w = [_u32(data, i * 4) for i in range(7)]
    count = w[3] & 0xFF
    if count == 0:
        raise TC2FormatError("record count is zero")
    table, dat = w[4], w[6]
    end = table + count * RECORD_BYTES
    if table < 0x1C or end > len(data):
        raise TC2FormatError(f"record table {table:#x}..{end:#x} outside blob {len(data):#x}")
    if not (end <= dat <= min(end + 0x10, len(data))):
        raise TC2FormatError(f"data offset {dat:#x} not within 0x10 after table end {end:#x}")
    recs = [NodeRecord(table + i * RECORD_BYTES,
                       struct.unpack_from(">16I", data, table + i * RECORD_BYTES))
            for i in range(count)]
    return TC2ModelHeader(w[0], w[1], w[2], count, w[3] >> 16, table, w[5], dat,
                          len(data) - dat, dat - end, recs)


def classify(data: bytes, total_size: Optional[int] = None) -> str:
    total_size = len(data) if total_size is None else total_size
    if is_tc2_container(data):
        return "tc2_model"
    return "hsd" if is_hsd_archive(data, total_size) else "unknown"
