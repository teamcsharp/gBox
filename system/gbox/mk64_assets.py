"""MK64 (USA) 2D asset-bank probe (request #1409 analysis stage).

Evidence-first: only structurally verified facts are reported.  Observed on the owned
build (z64 sha1 579c48e2...): 63 'TKMK00' streams from 0x7FA3C0 (UI / character-select
art, MK64's own texture codec) and 3354 MIO0 streams dominated by 4096 B textures.
Header layout (HYPOTHESIS, consistent for all 63): magic[6], u16 flags, u16 width,
u16 height, then a big-endian u32 offset table that is strictly increasing and inside
the stream.  Decompression semantics are NOT yet proven (needs the Ghidra/decomp
tkmk00decompress oracle)."""
from __future__ import annotations

import struct
from collections import Counter

TKMK_MAGIC = b"TKMK00"


def tkmk00_streams(rom: bytes) -> list[dict]:
    out, i = [], 0
    while (j := rom.find(TKMK_MAGIC, i)) != -1:
        i = j + 1
        if j % 4 or j + 16 > len(rom):
            continue
        flags, w, h = struct.unpack_from(">HHH", rom, j + 6)
        offs = []
        k = j + 12
        while k + 4 <= len(rom) and len(offs) < 64:
            v = struct.unpack_from(">I", rom, k)[0]
            if v < 16 or v > 0x100000 or (offs and v <= offs[-1]):
                break
            offs.append(v)
            k += 4
        out.append({"offset": j, "flags": flags, "width": w, "height": h,
                    "offset_table": offs[:8], "table_len": len(offs),
                    "plausible": 0 < w <= 512 and 0 < h <= 512 and len(offs) >= 2})
    return out


def mio0_size_histogram(rom: bytes) -> dict:
    """Uncompressed-size histogram of structurally valid MIO0 streams."""
    hist, i = Counter(), 0
    while (j := rom.find(b"MIO0", i)) != -1:
        i = j + 1
        if j % 4 == 0 and j + 16 <= len(rom):
            size, comp, unc = struct.unpack_from(">III", rom, j + 4)
            if 0 < size <= 0x400000 and 0 < comp <= 0x400000 and 0 < unc <= 0x400000:
                hist[size] += 1
    return dict(hist.most_common())


def probe(rom: bytes) -> dict:
    tk = tkmk00_streams(rom)
    return {"tkmk00_count": len(tk), "tkmk00_plausible": sum(t["plausible"] for t in tk),
            "tkmk00_first": tk[0]["offset"] if tk else None,
            "tkmk00_dims": sorted({(t["width"], t["height"]) for t in tk}),
            "mio0_top_sizes": dict(list(mio0_size_histogram(rom).items())[:8])}
