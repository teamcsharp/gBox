"""Analysis for Dead or Alive (USA) PSX (Tecmo, 1998, SLUS-00606) - game 5b699968cf37a8ac.

Stage 2 (analysis) decoding of PS_DOA.BIN's 338-entry load table and the packed
asset-index references, plus reproducible location of the RAM/code region.

Layout model (validated against the owned disc, see tests):
  * 0x0      338-entry load table of (u32 size, u32 ref) pairs.
  * The table splits cleanly on ``ref & 0xFF``:

    1. entry 0                  -> ref == 0, size 456200: the main program block
                                  (header + tables + code + static data) that
                                  precedes the RAM overlay region.
    2. entries 1..84            -> ref & 0xFF == 0: RAM/code overlay entries.
                                  ``ref`` carries the load offset in a byte-rotated
                                  24-bit form (see ram_offset()); the matching file
                                  data is MIPS R3000 code (verified by prologue
                                  density for entries 1..21) and later data blocks.
    3. entries 85..337 (253)    -> ref & 0xFF != 0: asset-index entries. ``ref``
                                  packs three bytes: (u8 count, u8 id, u8 page),
                                  byte 3 is zero.

Asset-index reference semantics (decoded, interpretation pending loader confirmation):
  * count: 1..5, monotonic tiers across the table (55x1, 54x2, 61x3, 81x4, 2x5).
  * id:    6 groups x 10 values -> id = (group << 4) | type, group 0..5, type 0..9.
  * page:  0..116 (a per-asset selector whose meaning the reader stage must pin).

The asset blocks are stored contiguously; their file offsets are cumulative over
``size`` from the start of the asset region. The exact region base and the count/id/page
semantics (character/costume/motion selector) are the next-stage (reader) questions,
to be resolved against the SLUS_006.06 loader decompilation.
"""
from __future__ import annotations

import struct
from collections import Counter

from .doa_psx_inventory import block_table

TABLE_ENTRIES = 338
ASSET_FIRST = 85          # first asset-index entry (0-based table index)
RAM_FIRST = 0             # entry 0 is the main block


def ram_offset(ref: int) -> int:
    """Decode a RAM/code entry's load offset.

    The ref stores the 24-bit offset with a one-byte rotation: on disk the bytes
    are [lo, hi, mid, 0x00], i.e. ref & 0xFF is the low byte, (ref >> 8) & 0xFF the
    high byte and (ref >> 16) & 0xFF the middle byte of the real offset. The file
    data lives at the same offset, and the RAM address is 0x80000000 | offset.
    """
    lo = ref & 0xFF
    hi = (ref >> 8) & 0xFF
    mid = (ref >> 16) & 0xFF
    return (hi << 16) | (mid << 8) | lo


def ram_address(ref: int) -> int:
    return 0x80000000 | ram_offset(ref)


def decode_asset_ref(ref: int) -> tuple[int, int, int]:
    """Decode an asset-index entry's packed ref -> (count, id, page)."""
    return ref & 0xFF, (ref >> 8) & 0xFF, (ref >> 16) & 0xFF


def classify_entry(ref: int) -> str:
    return "asset" if ref & 0xFF else "ram"


def load_table_summary(doa: bytes) -> dict:
    """Classify the 338 table entries and decode every reference."""
    tbl = block_table(doa, max_entries=TABLE_ENTRIES)
    ram, asset = [], []
    for i, (size, ref) in enumerate(tbl):
        if classify_entry(ref) == "ram":
            ram.append((i, size, ref, ram_offset(ref)))
        else:
            count, aid, page = decode_asset_ref(ref)
            asset.append((i, size, ref, count, aid, page))
    return {
        "entries": len(tbl),
        "ram_load": ram,            # (idx, size, ref, offset)
        "asset_index": asset,       # (idx, size, ref, count, id, page)
    }


def asset_tiers(asset: list) -> list[tuple[int, int, int]]:
    """Contiguous (count, first_idx, last_idx) tiers of the asset-index entries."""
    tiers: list[tuple[int, int, int]] = []
    for idx, size, ref, count, aid, page in asset:
        if tiers and tiers[-1][0] == count:
            tiers[-1] = (count, tiers[-1][1], idx)
        else:
            tiers.append((count, idx, idx))
    return tiers


def id_grid(asset: list) -> dict:
    """Split the 253 id values into (group, type) and report coverage."""
    groups: dict[int, set[int]] = {}
    for idx, size, ref, count, aid, page in asset:
        groups.setdefault(aid >> 4, set()).add(aid & 0xF)
    return {g: sorted(ts) for g, ts in sorted(groups.items())}


def cumulative_offsets(doa: bytes) -> list[tuple[int, int, int]]:
    """(idx, offset, size) for every table entry, offset = cumulative sum of sizes.

    Correct for the asset-index region (entries 85..337), which is stored
    contiguously. RAM/code entries (1..84) instead live at ram_offset(ref); entry 0
    lives at 0. Exposed for the reader stage to slice asset blocks.
    """
    tbl = block_table(doa, max_entries=TABLE_ENTRIES)
    out, off = [], 0
    for i, (size, ref) in enumerate(tbl):
        out.append((i, off, size))
        off += size
    return out


def landmark_check(doa: bytes, landmarks: dict[int, str]) -> dict[str, str | None]:
    """Report which cumulative block contains each absolute file offset (heuristic)."""
    blocks = cumulative_offsets(doa)
    res: dict[str, str | None] = {}
    for off, name in landmarks.items():
        hit = None
        for i, boff, size in blocks:
            if boff <= off < boff + size:
                hit = f"entry {i} (off 0x{boff:x}, size 0x{size:x})"
                break
        res[name] = hit
    return res


def main(argv=None) -> int:
    import argparse
    from pathlib import Path
    ap = argparse.ArgumentParser()
    ap.add_argument("doa_bin", help="PS_DOA.BIN bytes (raw)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    doa = Path(args.doa_bin).read_bytes()
    s = load_table_summary(doa)
    if not args.json:
        print(f"table entries: {s['entries']}")
        print(f"RAM/code entries (incl. entry 0): {len(s['ram_load'])}")
        print(f"asset-index entries: {len(s['asset_index'])}")
        print("asset tiers (count, first_idx, last_idx):", asset_tiers(s["asset_index"]))
        print("asset id grid (group -> types):", id_grid(s["asset_index"]))
        for idx, size, ref, count, aid, page in s["asset_index"][:8]:
            print(f"  asset {idx:3d} size=0x{size:08x} count={count} id={aid} page={page}")
    else:
        import json
        print(json.dumps({
            "entries": s["entries"],
            "ram_load": [{"idx": i, "size": sz, "ref": r, "offset": o}
                         for i, sz, r, o in s["ram_load"]],
            "asset_index": [{"idx": i, "size": sz, "ref": r, "count": c, "id": a, "page": p}
                            for i, sz, r, c, a, p in s["asset_index"]],
            "tiers": [list(t) for t in asset_tiers(s["asset_index"])],
            "id_grid": {str(k): v for k, v in id_grid(s["asset_index"]).items()},
        }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
