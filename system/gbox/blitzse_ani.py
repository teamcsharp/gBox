"""GENSEQ.ANI sequence table and the Midway fs method-4 packed-stream prefix.

Owned build: NFL Blitz: Special Edition (USA), N64 (favorite ad56bf0fc382891b).
Owned source: hyperspin "NFL Blitz - Special Edition (USA).zip",
sha256 362bd74a0c9ee3a510dce7154dbd4049bad80897efb95b1d5456bac3e79419fe
(normalised z64 sha256 8e861e75e7f16a9baefe2d82525240b68dfb79e01933571537dc5967dd482cc0).

Facts recovered from the owned ROM bytes (measured, not copied from a sibling):

* ``GENSEQ.ANI`` is a *stored* fs member (method 5, 1,213,920 B, sha256
  ad59d9aacdc180333ef783af96af4d8ddb60825ecdc11af57536cc27840c767b) and
  starts with a big-endian header ``{u32 tag, u32 count, u32 limbs,
  u32 table_offset}`` with tag ``0x376A9A4E`` and ``limbs`` 15.  It is followed
  by 16-byte sequence records ``{u32 flag, u32 frames, u32 limbs, u32 offset}``
  whose ``limbs`` is constant 15, whose ``flag`` is 1 and whose ``offset``
  strictly increases (271 records tile the member).
  The Dreamcast sibling (NFL Blitz 2001, ``gbox.blitz2001_inventory.genseq``)
  has the same record shape but a different tag and little-endian words, so the
  N64 build is parsed separately here.
* The fs "method 4" (packed) stream is **not** a whole-file transform: every
  packed member starts with a readable literal prefix.  Byte 0 is the length
  of that literal run, and the bytes after it are the member's own header.
  All 1,745 packed ``.wms`` members carry the ASCII magic ``wn\x02`` at
  offset 1, and their first 24 literal bytes are a readable WMS header, so the
  packer emits literals before its back-reference stream.  The bit stream that
  follows is still a hypothesis, so nothing here decodes a packed member;
  :func:`packed_prefix` only describes the head.

``GENSEQ.ANI`` is the shared animation bank for the 15-limb player rig, so it
is the first native animation asset a reader/writer can take ownership of
without touching the unresolved packed codec.
"""
from __future__ import annotations

import struct

GENSEQ_TAG = 0x376A9A4E
GENSEQ_HEADER = struct.Struct(">4I")     # tag, count, limbs, table_offset
GENSEQ_ENTRY = struct.Struct(">4I")      # flag, frames, limbs, offset
WMS_MAGIC = b"wn\x02"


class GenseqError(ValueError):
    """Raised when GENSEQ.ANI does not match the owned build's structure."""


def genseq(data: bytes, strict: bool = True) -> dict:
    """Parse the big-endian GENSEQ.ANI sequence table of the owned N64 build.

    With ``strict`` (default) every sequence offset must land inside ``data``;
    pass ``strict=False`` for a truncated buffer (a fixture) and the offsets
    are reported without that range check.  The ``span`` of a sequence is the
    distance to the next record (the last one runs to the end of the buffer);
    it is a measurement, not a proven frame table.
    """
    if len(data) < GENSEQ_HEADER.size:
        raise GenseqError("GENSEQ.ANI too short")
    tag, count, limbs, table_offset = GENSEQ_HEADER.unpack_from(data, 0)
    if tag != GENSEQ_TAG:
        raise GenseqError(f"GENSEQ tag {tag:#x}")
    if not limbs or not count:
        raise GenseqError("GENSEQ header has no sequences")
    seqs = []
    off = GENSEQ_HEADER.size
    while off + GENSEQ_ENTRY.size <= len(data):
        flag, frames, n_limbs, doff = GENSEQ_ENTRY.unpack_from(data, off)
        if n_limbs != limbs or not frames:
            break
        if strict and doff >= len(data):
            break
        if seqs and doff <= seqs[-1]["offset"]:
            break
        seqs.append({"index": len(seqs), "flag": flag, "frames": frames,
                     "limbs": n_limbs, "offset": doff})
        off += GENSEQ_ENTRY.size
    if not seqs:
        raise GenseqError("GENSEQ.ANI has no sequence records")
    for i, s in enumerate(seqs):
        nxt = seqs[i + 1]["offset"] if i + 1 < len(seqs) else len(data)
        s["span"] = max(0, nxt - s["offset"])
    return {"tag": tag, "count_field": count, "limbs": limbs,
            "table_offset": table_offset, "scanned": len(seqs),
            "count_field_matches": count == len(seqs), "sequences": seqs}


def packed_prefix(data: bytes) -> dict:
    """Describe the head of an fs method-4 packed member.

    Byte 0 is the length of the literal run that follows; the bytes after it
    are the start of the member's own header, which for every packed ``.wms``
    is the ASCII magic ``wn\x02``.
    """
    if not data:
        raise ValueError("empty packed member")
    lead = data[0]
    return {"lead": lead, "literal_len": lead, "magic": data[1:4],
            "wms_magic": data[1:4] == WMS_MAGIC,
            "literal": data[1:1 + lead]}
