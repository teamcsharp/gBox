"""Crazy Taxi: Fare Wars (PSP) BINC*.AFS container probe -- request #2453, analysis stage.

The BINC*.AFS files in PSP_GAME/USRDIR/DATA/CT{1,2}/ do NOT use the standard
"AFS\\0" archive layout. Evidence from the owned build (CT2/BINC1.AFS,
sha256 40c4099027b2de8dc7033fa6f53efcdc65dab19bc06e9c874a13b80ebe72cdeb):

  * bytes 0..23: five little-endian u32 values, strictly increasing, each
    within the file, followed by a zero u32 -- these are SECTION OFFSETS,
    not a member count/table (the earlier "count 568" reading was wrong);
  * payload data starts immediately at byte 24 (vertex-like records) and the
    five offsets slice the rest of the file into five sections;
  * section 0 of CT2/BINC1.AFS is 9985 bytes; from byte 24 through 10552 the
    blob is a run of 329 x 32-byte records (section 0 proper holds 312 of
    them).  Each 32-byte record is 6 IEEE-754 floats (position/normal-like
    magnitudes) + one packed u32 (two u16 fields, e.g. 0x0017001e) + a zero
    pad word.  97% of the float slots in the first 200 records are finite and
    in a plausible geometry range -- this is binary model data, so BINC*.AFS
    is the character/mesh pack, not an archive of named files.

This module parses that layout read-only from the owned CSO image and returns
typed sections/records for the reader stage to build on.  It never modifies
the owned image.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from .cso import CSO

# Owned identity (unchanged from the inventory stage; same source, same hash).
OWNED_CSO_REL = "collections/Sony PlayStation Portable/roms/Crazy Taxi - Fare Wars (USA).cso"
BINC1_CT2_OFFSET = 164552704
BINC1_CT2_SIZE = 5454920
BINC1_CT2_SHA256 = "40c4099027b2de8dc7033fa6f53efcdc65dab19bc06e9c874a13b80ebe72cdeb"

SECTION_TABLE_END = 24  # 5 offsets + terminator word
RECORD_SIZE = 32


@dataclass(frozen=True)
class BincRecord:
    floats: tuple  # 6 little-endian f32 values
    packed: int    # one u32 (two u16 fields, meaning TBD by reader stage)
    pad: int       # trailing u32, always 0 in the decoded section


@dataclass(frozen=True)
class BincFile:
    sections: tuple  # (start, end) byte spans, from the header table
    records: tuple   # decoded 32-byte records of the first record-shaped section


def parse_binc(data: bytes) -> BincFile:
    """Parse a BINC*.AFS blob from the owned build."""
    if len(data) < SECTION_TABLE_END:
        raise ValueError(f"BINC too short: {len(data)} bytes")
    words = struct.unpack("<6I", data[:SECTION_TABLE_END])
    if words[5] != 0:
        raise ValueError(f"BINC header terminator non-zero: {words[5]:#x}")
    offs = words[:5]
    if any(b <= a for a, b in zip(offs, offs[1:])):
        raise ValueError(f"BINC section offsets not increasing: {[hex(o) for o in offs]}")
    if offs[0] < SECTION_TABLE_END or offs[-1] >= len(data):
        raise ValueError("BINC section offsets out of file range")
    spans = tuple(zip(offs, offs[1:] + (len(data),)))

    # Decode the leading record-shaped run starting right after the header.
    # Records are 32 bytes; the run ends at the first record whose trailing
    # pad word is non-zero (or at the first section boundary).
    end = min(spans[0][1], len(data))
    run_end = SECTION_TABLE_END
    while run_end + RECORD_SIZE <= end:
        if struct.unpack_from("<I", data, run_end + 28)[0] != 0:
            break
        run_end += RECORD_SIZE
    records = []
    for off in range(SECTION_TABLE_END, run_end, RECORD_SIZE):
        fs = struct.unpack_from("<6f", data, off)
        packed, pad = struct.unpack_from("<2I", data, off + 24)
        records.append(BincRecord(tuple(fs), packed, pad))
    return BincFile(spans, tuple(records))
