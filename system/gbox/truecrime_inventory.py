"""True Crime: Streets of LA (GameCube, GTLE52) owned-build inventory.

Streams the owned GCZ through gbox.gcdisc, hashes source + main.dol, counts Char/ assets by extension.
Finding: Char/*.ngc does NOT start with auf_ngc's 0x20-byte chunk header; word0 is a small count (9) followed by a
big-endian table, so gbox.auf_ngc is NOT directly reusable (hypothesis: different table layout, loader RSRC_Load unproved).
"""
from __future__ import annotations

import collections
import hashlib
import struct


def sha256_file(path: str, bufsize: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(bufsize):
            h.update(chunk)
    return h.hexdigest()


def ngc_head(b: bytes) -> dict:
    """Raw, unproven view of a Char/*.ngc head: leading BE words and whether it looks like an auf_ngc chunk header."""
    if len(b) < 0x20:
        raise ValueError("short .ngc")
    w = struct.unpack_from(">8I", b, 0)
    return {"words": list(w), "auf_chunk_header": w[0] > 0xFFFF and w[0] <= len(b)}


def inventory(path: str) -> dict:
    from .gcdisc import GCDisc
    d = GCDisc(path)
    dol = d.dol()
    ext = collections.Counter(k.split("/")[0] + ":" + k.rsplit(".", 1)[-1].lower() for k in d.files)
    chars = sorted(k for k in d.files if k.startswith("Char/") and k.lower().endswith(".ngc"))
    return {"game_id": d.game_id, "title": d.title, "files": len(d.files), "dol_size": len(dol),
            "dol_sha256": hashlib.sha256(dol).hexdigest(), "counts": dict(ext), "char_ngc": chars,
            "sample": {chars[0]: ngc_head(d.read(chars[0]))} if chars else {}}
