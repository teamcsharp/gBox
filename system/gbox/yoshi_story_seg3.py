"""Yoshi's Story (USA, NYSE rev0) segment-3 frame-texture buffer layout.

Code/data-derived from the owned z64 (sha256 e8a63388...0ce9) via yoshi_story_frames.
Fact: every frame record in the 0x9E6C00 bank (1180 records) points its TLUT at
seg3+0x400 and draws up to 6 CI8 tiles from a small set of seg3 offsets, so seg3 is a
per-frame texture buffer re-filled at runtime (not one static atlas per character).
The ROM source/decompressor that fills it is still UNMAPPED (no seg3 literal DB06000C
in main code; Yay0/Yaz0/MIO0 signatures absent).
"""
from __future__ import annotations
import collections
from . import yoshi_story_frames as F

TLUT_SEG3 = 0x400
TLUT_COLORS = 256


def seg3_layout(rom: bytes) -> dict:
    recs = F.frame_records(rom)
    frames = [F.parse_frame(rom, r) for r in recs]
    offs = collections.Counter(t["seg3"] for p in frames for t in p["tiles"])
    sizes = collections.defaultdict(set)
    for p in frames:
        for t in p["tiles"]:
            sizes[t["seg3"]].add((t["width"], t["height"]))
    return {
        "frames": len(frames),
        "tlut_offsets": sorted({p["tlut"]["seg3"] for p in frames}),
        "tiles_per_frame": dict(collections.Counter(len(p["tiles"]) for p in frames)),
        "distinct_tile_offsets": len(offs),
        "tile_offset_mod_0x400": dict(collections.Counter(o % 0x400 for o in offs.elements())),
        "min_tile_offset": min(offs),
        "max_tile_end": max(t["seg3"] + t["texels"] for p in frames for t in p["tiles"]),
        "offsets_with_multiple_sizes": sum(len(v) > 1 for v in sizes.values()),
    }
