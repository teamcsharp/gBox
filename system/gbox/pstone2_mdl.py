"""Capcom ``*_MODEL_VQ.MDL`` / ``*_CONNECT.BIN`` model format probe (Power Stone 2, Dreamcast).

Stage-2 analysis of the exact T-1211N V1.000 build. This module decodes the MDL *container*
header and its chunk table -- enough to locate every geometry section and confirm the
PL-id-to-character map -- but it deliberately does **not** decode the node tree or the
per-chunk payloads (vertex/normal/index/material/texture codecs), which is the reader stage.

Layout (all multi-byte integers little-endian, SH-4):

* header, 8 x u32 at offset 0::

      [0] magic       0xFFFFFFFF
      [1] object_count     node-tree roots that follow the chunk table
      [2] geom_base        absolute offset of the geometry region; every chunk offset
                           and every node pointer is RELATIVE to this
      [3] chunk_count      number of 32-byte chunk records that follow the header
      [4] 0 (reserved)
      [5] f32 bounding radius  (~111.8 on every fighter body of this build)
      [6] f32 scale            (5.0 on every fighter body of this build)
      [7] 0

* chunk table, ``chunk_count`` x 8 x u32 at offset 0x20.  Each record::

      [0],[1] 0 (reserved)
      [2]     type          e.g. 0x13/0x03 float arrays, 0x02 index list, 0x04 vertex list
      [3]     offset        RELATIVE to geom_base
      [4]     end           RELATIVE to geom_base; 0 on every record but the last
      [5],[6] extra offsets, non-zero only on the last record (sub-section spans)
      [7]     0xFFFFFFFF on the last record, else 0

* node-tree region: ``0x20 + 32*chunk_count`` .. ``geom_base`` (variable-size objects).
* geometry region: ``geom_base`` .. end of blob; a chunk's bytes are
  ``blob[geom_base + rec.offset : geom_base + (rec.end or next_rec.offset)]``.

Verified against the owned disc's PL00/PL10 slot-0 body models and CMN_MODEL_VQ.MDL
(see tests/test_pstone2_mdl.py). The PL-id mapping uses 1ST_READ.BIN's file-name table:
the 18 ``PLxy_CONNECT.BIN`` files occupy load IDs 3..20 contiguously, so the loader indexes
a character by ``load_id - 3``; the PL code's high nibble is the 0..15 character index and
the low nibble is the costume variant (0 base, 2 alternate).
"""
from __future__ import annotations

import re
import struct
from collections import namedtuple

from .pstone2_inventory import NAME_TABLE, name_table

MDL_MAGIC = 0xFFFFFFFF
HEADER_WORDS = 8
RECORD_WORDS = 8
RECORD_BYTES = RECORD_WORDS * 4

# Observed chunk types (payload codec is reader-stage work; names are best-effort):
#   0x01  small table         0x02  index/face list      0x03  float array
#   0x04  vertex/attribute    0x05  table                0x08  table
#   0x0a  table               0x0d  table                0x10  table
#   0x13  float array

ChunkRec = namedtuple("ChunkRec", "type offset end extra terminator")


def f32(u: int) -> float:
    return struct.unpack("<f", struct.pack("<I", u))[0]


def mdl_header(blob: bytes) -> dict:
    """Decode the 8-word MDL header. Raises ValueError when the magic word is absent."""
    if len(blob) < HEADER_WORDS * 4:
        raise ValueError(f"MDL too short for a header: {len(blob)} bytes")
    w = struct.unpack_from("<8I", blob, 0)
    if w[0] != MDL_MAGIC:
        raise ValueError(f"not a Capcom MDL (magic {w[0]:#x} != {MDL_MAGIC:#x})")
    return {"magic": w[0], "object_count": w[1], "geom_base": w[2], "chunk_count": w[3],
            "radius": f32(w[5]), "scale": f32(w[6]), "header_bytes": HEADER_WORDS * 4}


def chunk_records(blob: bytes) -> list[ChunkRec]:
    """The 32-byte chunk records that follow the header (offsets relative to geom_base)."""
    h = mdl_header(blob)
    n = h["chunk_count"]
    end = 0x20 + n * RECORD_BYTES
    if end > len(blob):
        raise ValueError(f"chunk table overruns the file ({end} > {len(blob)})")
    recs = []
    for i in range(n):
        w = struct.unpack_from("<8I", blob, 0x20 + i * RECORD_BYTES)
        recs.append(ChunkRec(type=w[2], offset=w[3], end=w[4],
                             extra=(w[5], w[6]), terminator=w[7]))
    if recs and recs[-1].terminator != MDL_MAGIC:
        raise ValueError("last chunk record is missing its 0xFFFFFFFF terminator")
    return recs


def parse_mdl(blob: bytes) -> dict:
    """Full container parse: header, chunk records and the region spans."""
    h = mdl_header(blob)
    recs = chunk_records(blob)
    node_region = (0x20 + h["chunk_count"] * RECORD_BYTES, h["geom_base"])
    chunks = []
    for i, r in enumerate(recs):
        e = r.end or (recs[i + 1].offset if i + 1 < len(recs) else len(blob) - h["geom_base"])
        chunks.append({"type": r.type, "offset": r.offset, "end": e,
                       "abs_start": h["geom_base"] + r.offset, "abs_end": h["geom_base"] + e,
                       "extra": r.extra})
    return {"header": h, "chunks": chunks, "node_region": node_region,
            "geometry": (h["geom_base"], len(blob))}


def chunk_bytes(blob: bytes, rec: ChunkRec, recs: list[ChunkRec], i: int) -> bytes:
    """Slice one chunk's payload out of the blob (offsets relative to geom_base)."""
    h = mdl_header(blob)
    e = rec.end or (recs[i + 1].offset if i + 1 < len(recs) else len(blob) - h["geom_base"])
    return blob[h["geom_base"] + rec.offset:h["geom_base"] + e]


def pl_character(pl_code: str) -> tuple[int, int]:
    """Map a 2-char ``PLxy`` code to (character_index 0..15, variant)."""
    return int(pl_code[0], 16), int(pl_code[1], 16)


def pl_load_ids(exe: bytes, at: int = NAME_TABLE) -> list[dict]:
    """The 1ST_READ file-name table's PL entries: load ID, code, character index, variant.

    The loader indexes characters by load ID (the table position); the 18 ``PLxy_CONNECT.BIN``
    files sit at load IDs 3..20 in code order, so ``character_index == load_id - 3`` for the
    base costume and the variants (PL12/PL72) share their base character's index.
    """
    out = []
    for i, n in enumerate(name_table(exe, at)):
        if re.fullmatch(r"PL[0-9A-F]{2}_CONNECT\.BIN", n):
            ci, variant = pl_character(n[2:4])
            out.append({"name": n, "load_id": i, "pl": n[2:4], "char_index": ci, "variant": variant})
    return out
