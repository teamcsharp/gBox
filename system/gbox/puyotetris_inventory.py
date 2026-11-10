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


# --- stage 2 probe: the 'raw02' member is a texture: 0x80-byte big-endian header + DXT5 blocks ---
RAW02_HDR = 0x80


def raw02_header(blob: bytes) -> dict:
    """Header: 02 02 00 ff | BE size @4 | data offset @0x10 (=0x80) | BE size @0x14 | BE w,h @0x20.
    Payload is DXT5/BC3 (1 byte/pixel); verified by decoding character_demo.narc members 26/27/33."""
    if bytes(blob[:4]) != b"\x02\x02\x00\xff":
        raise ValueError("not a raw02 texture")
    size, off, size2 = int.from_bytes(blob[4:8], "big"), int.from_bytes(blob[0x10:0x14], "big"), \
        int.from_bytes(blob[0x14:0x18], "big")
    w, h = int.from_bytes(blob[0x20:0x22], "big"), int.from_bytes(blob[0x22:0x24], "big")
    if off != RAW02_HDR or size != size2 or size != w * h or len(blob) != off + size:
        raise ValueError(f"raw02 header inconsistent: size={size} off={off} {w}x{h} len={len(blob)}")
    return {"width": w, "height": h, "data_offset": off, "size": size, "format": "dxt5",
            "fmt_tag": bytes(blob[0x18:0x20]).hex()}


def raw02_to_dds(blob: bytes) -> bytes:
    import struct
    hd = raw02_header(blob)
    data = bytes(blob[hd["data_offset"]:])
    head = (b"DDS " + struct.pack("<7I", 124, 0x81007, hd["height"], hd["width"], len(data), 0, 0)
            + b"\0" * 44 + struct.pack("<2I4s5I", 32, 4, b"DXT5", 0, 0, 0, 0, 0)
            + struct.pack("<5I", 0x1000, 0, 0, 0, 0))
    return head + data


def raw02_to_rgba(blob: bytes):
    """Decode to a PIL RGBA image (needs Pillow)."""
    import io
    from PIL import Image
    return Image.open(io.BytesIO(raw02_to_dds(blob))).convert("RGBA")
