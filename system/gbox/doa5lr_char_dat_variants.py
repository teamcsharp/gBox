"""Classify every DOA5LR (PS3) ``char_dat`` entry in chara_common.lnk by header variant (request #2450).

Diagnoses why ``parse_char_dat`` rejects 118 of 209 tagged entries.  Structural only.
Classes (checked in this order):
  ``stub``        shorter than the 0xB4-byte header region (header-only chunk).
  ``ok_v7``       n_sec=7, n_entries=6, parse_char_dat accepts.
  ``v6``          n_sec=6, n_entries=5 (one fewer section/table; sec ptr array has two nulls at 0x84/0x88).
  ``truncated``   header says sections lie beyond the stored payload (stub / continuation chunk;
                  last section pointer >= payload size).
  ``ptable2``     ptable[2] non-null (a third u16-stream table, e.g. entry 0211).
  ``reserved_00`` outer/inner reserved word 0xFF000100 instead of 0xFF000101.
  ``other``       none of the above.
"""
from __future__ import annotations

import collections
import struct

from gbox import doa5lr_chcm_extract as chcm
from gbox.doa5lr_char_dat import parse_char_dat

__all__ = ["classify", "variant_census"]


def _u32(b: bytes, o: int) -> int:
    return struct.unpack_from(">I", b, o)[0]


def classify(payload: bytes) -> str:
    if payload[:8] != b"char_dat":
        raise ValueError("not char_dat")
    try:
        parse_char_dat(payload)
        return "ok_v7"
    except Exception:
        pass
    if len(payload) < 0xB4:
        return "stub"
    if _u32(payload, 0x08) == 0xFF000100:
        return "reserved_00"
    n_sec, n_ent = _u32(payload, 0x54), _u32(payload, 0x58)
    nsec = max(1, min(n_sec, 7))
    ptrs = [_u32(payload, 0x78 + 4 * i) for i in range(nsec)]
    if ptrs and max(ptrs) >= len(payload):
        return "truncated"
    if (n_sec, n_ent) == (6, 5):
        return "v6"
    if _u32(payload, 0x9C) != 0:
        return "ptable2"
    return "other"


def variant_census(container_path: str) -> dict:
    entries = chcm.parse_entries(container_path)
    counts = collections.Counter()
    members = collections.defaultdict(list)
    with open(container_path, "rb") as fh:
        for i, (size, _d, _z, off) in enumerate(entries):
            if size < 8:
                continue
            fh.seek(off)
            data = fh.read(size)
            if data[:8] != b"char_dat":
                continue
            c = classify(data)
            counts[c] += 1
            members[c].append(i)
    return {"counts": dict(counts), "members": {k: v[:8] for k, v in members.items()}}
