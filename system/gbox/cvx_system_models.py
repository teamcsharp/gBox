"""CVX Disc 2 (GCDE08) system.afs model census: candidate player-character slots.

Evidence (read from the owned disc, big-endian members inside little-endian AFS table):
  system.afs (140 entries) holds entries whose bytes 4..8 are ``MDL\\xbc`` (Capcom model,
  version dword 0x0010000N) in four contiguous runs: 20-40, 50-70, 80-99, 110-130, separated
  by 'SKIN'-tagged blobs (10-14) and TPVR texture packs (entry 2).  These are CANDIDATES for
  playable character part sets; no name mapping is asserted (AFS has no names).
"""
from __future__ import annotations

import struct

from .cvx_inventory import afs_entry_count, read_at

MDL_MAGICS = (b"MDL\xbc", b"MDL\xac")


def afs_table(disc, name: str):
    offset, _size = disc.files[name]
    count = afs_entry_count(disc, name)
    t = read_at(disc, offset, 8 + 8 * count)
    return offset, [struct.unpack_from("<II", t, 8 + 8 * i) for i in range(count)]


def classify(head: bytes) -> str:
    if len(head) >= 8 and head[4:8] in MDL_MAGICS:
        return "mdl"
    if head[:4] in (b"TPVR", b"PPVP"):
        return head[:4].decode()
    if len(head) >= 12 and head[8:12] == b"SKIN":
        return "skin"
    return "other"


def mdl_runs(entries):
    """Contiguous index runs of MDL members: [(first, last, count, total_bytes)]."""
    runs, cur = [], None
    for idx, kind, size in entries:
        if kind == "mdl":
            if cur and cur[1] == idx - 1:
                cur[1] = idx; cur[2] += 1; cur[3] += size
            else:
                cur = [idx, idx, 1, size]; runs.append(cur)
    return [tuple(r) for r in runs]


def census(disc, name: str = "system.afs"):
    base, table = afs_table(disc, name)
    entries = []
    for i, (o, s) in enumerate(table):
        head = read_at(disc, base + o, min(12, s)) if s else b""
        entries.append((i, classify(head), s))
    return entries
