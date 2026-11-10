"""Puyo Puyo Tetris (PS3, BLJM61097): owned-build inventory helpers (stage 1).

The disc's data/ tree stores little-endian Nintendo-style NARC archives (parsed by
gbox.formats.nitro.narc). Members are tagged by a 4-byte magic; no model format has been
identified: this module only counts and classifies. It is NOT a model reader.
"""
from __future__ import annotations

import collections
import hashlib
from pathlib import Path

from .formats import nitro

TITLE_ID = "BLJM61097"
# Observed member magics (character_demo / adv_character): NCIF (texture-like, 0x18 header,
# 'nCSC' chunk), SWIF (big-endian 0x18 header, 'SWTL' chunk), 02 02 00 ff (raw 256x256-style blob).
MAGICS = {b"NCIF": "ncif", b"SWIF": "swif", b"MSFC": "msfc", b"COMP": "comp", b"DSIF": "dsif",
          b"FONT": "font", b"DDS ": "dds", b"CTPK": "ctpk", b"\x02\x02\x00\xff": "raw02"}


def sha256_file(path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while blk := f.read(chunk):
            h.update(blk)
    return h.hexdigest()


def classify(payload: bytes) -> str:
    return MAGICS.get(bytes(payload[:4]), "other")


def narc_census(path) -> dict:
    """Parse one NARC and count members by magic class; sizes are checked in range by nitro.narc."""
    blob = Path(path).read_bytes()
    members = nitro.narc(blob)
    counts = collections.Counter(classify(b) for _, b in members)
    return {"path": str(path), "members": len(members), "bytes": sum(len(b) for _, b in members),
            "classes": dict(counts)}


def tree_census(root) -> dict:
    """Parse every *.narc under root; report parse failures instead of hiding them."""
    ok, failed, classes, members = 0, [], collections.Counter(), 0
    for p in sorted(Path(root).rglob("*.narc")):
        try:
            c = narc_census(p)
        except ValueError as e:
            failed.append((str(p), str(e)))
            continue
        ok += 1
        members += c["members"]
        classes.update(c["classes"])
    return {"parsed": ok, "failed": failed, "members": members, "classes": dict(classes)}
