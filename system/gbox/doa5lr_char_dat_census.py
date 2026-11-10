"""Per-section variability census over DOA5LR chara_common.lnk char_dat entries (request #2450).

Answers which parsed char_dat sections are per-character (variable) vs constant,
to choose a donor swap that can have a visible effect.  Structural only; no
semantic claim about what a section encodes.
"""
from __future__ import annotations

import collections
import hashlib

from gbox import doa5lr_chcm_extract as chcm
from gbox.doa5lr_char_dat import parse_char_dat

__all__ = ["census"]


def census(container_path: str) -> dict:
    entries = chcm.parse_entries(container_path)
    tagged = parsed = failed = 0
    hashes = collections.defaultdict(set)
    sizes = collections.defaultdict(collections.Counter)
    with open(container_path, "rb") as fh:
        for size, _dup, _zero, offset in entries:
            if size < 0xB4:
                continue
            fh.seek(offset)
            data = fh.read(size)
            if data[:8] != b"char_dat":
                continue
            tagged += 1
            try:
                info = parse_char_dat(data)
            except Exception:
                failed += 1
                continue
            parsed += 1
            for k, sec in enumerate(info["sections"]):
                blob = data[sec["start"]:sec["end"]]
                hashes[k].add(hashlib.sha256(blob).hexdigest())
                sizes[k][len(blob)] += 1
    return {
        "entries": len(entries),
        "char_dat_tagged": tagged,
        "parsed": parsed,
        "parse_failed": failed,
        "sections": {
            k: {"distinct_content": len(hashes[k]), "distinct_size": len(sizes[k])}
            for k in sorted(hashes)
        },
    }
