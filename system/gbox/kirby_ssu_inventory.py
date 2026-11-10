"""Kirby Super Star Ultra (USA, NDS) owned-build inventory (#2486, stage: inventory).

Inventory only: NitroFS manifest + LZ10 classification + palette/tile candidates.
It is not a sprite reader or writer. Kirby here is 2D (4bpp tiles + BGR555
palettes), so a replacement is tile/palette work, not a mesh.
"""
from __future__ import annotations

import hashlib
import struct

from gbox.formats.lz import LZ10Error, lz10_decompress
from gbox.formats.nitro import NitroROM

GAMECODE = "YKWE"
SHA256 = "c3757cfbf4579348a65eed235a922e3431c328760ba49fa991f22b88f9fd017d"
SHA1 = "d1b019be92f8e9897e471c554c22c576dc984d55"
TARGET = "rom/beginner19/zchr_bgnbigkirby"   # 14468 B LZ10 -> 34816 B = 1088 4bpp tiles


def lz10_candidate(b: bytes) -> bool:
    """True if b looks like an LZ10 stream (type byte 0x10, plausible size)."""
    if len(b) < 5 or b[0] != 0x10:
        return False
    n = b[1] | b[2] << 8 | b[3] << 16
    # a 2-byte copy token yields at most 18 bytes, so n <= 9 * stream length; more means raw data
    return 0 < n <= 9 * len(b)


def classify(b: bytes) -> tuple[str, bytes | None]:
    """('lz10', decoded) | ('raw', None) | ('lz10-invalid', None)."""
    if not lz10_candidate(b):
        return "raw", None
    try:
        return "lz10", lz10_decompress(b)
    except (LZ10Error, IndexError):
        return "lz10-invalid", None


def bgr555_palette(b: bytes) -> list[tuple[int, int, int]]:
    out = []
    for (w,) in struct.iter_unpack("<H", b[: len(b) // 2 * 2]):
        out.append(((w & 31) << 3, ((w >> 5) & 31) << 3, ((w >> 10) & 31) << 3))
    return out


def inventory(rom: bytes) -> dict:
    r = NitroROM(rom)
    if r.gamecode != GAMECODE:
        raise ValueError(f"not Kirby Super Star Ultra USA: {r.gamecode}")
    kinds = {"lz10": 0, "raw": 0, "lz10-invalid": 0}
    invalid = []
    for fid, name in sorted(r.names.items()):
        kind, _ = classify(r.file(fid))
        kinds[kind] += 1
        if kind == "lz10-invalid":
            invalid.append(name)
    tiles = r.read_lz10(TARGET) if hasattr(r, "read_lz10") else classify(r.raw(TARGET))[1]
    return {
        "sha256": hashlib.sha256(rom).hexdigest(), "title": r.title, "gamecode": r.gamecode,
        "files": len(r.names), "kinds": kinds, "invalid_lz10": invalid,
        "target": TARGET, "target_raw_size": len(r.raw(TARGET)),
        "target_decoded_size": len(tiles), "target_tiles_4bpp": len(tiles) // 32,
        "target_sha256": hashlib.sha256(tiles).hexdigest(),
    }


# --- analysis stage: HAL "05" OBJ sprite container header (#2486) -------------------
# 24-byte LE header: u32 version=5 | u32 (tiles<<16 | x) | u32 (flags<<16 | frames)
# | u32 d3 | u32 d4 | u32 d5.  Observed on the owned build (260 files in ene05, b10, kng18,
# stay00, ...): for uncompressed containers (flags 0x2000)  size == tiles*32 + d4, and
# d4-d3 trailing bytes are an embedded palette block.  'z*' files set flags bit 0x0001
# (tile payload compressed) and do not satisfy the size identity.  Unverified: meaning of
# d3/d5 sections (frame/OAM tables) and that any slot is the player Kirby.
OBJ_HDR = struct.Struct("<6I")


def obj_header(b: bytes) -> dict | None:
    if len(b) < 24 or b[:4] != b"\x05\x00\x00\x00":
        return None
    _, d1, d2, d3, d4, d5 = OBJ_HDR.unpack_from(b)
    return {"tiles": d1 >> 16, "d1_low": d1 & 0xFFFF, "flags": d2 >> 16, "frames": d2 & 0xFFFF,
            "d3": d3, "d4": d4, "d5": d5, "compressed": bool((d2 >> 16) & 1),
            "size_ok": (d1 >> 16) * 32 + d4 == len(b), "palette_bytes": d4 - d3}


def obj_census(rom: bytes) -> dict:
    r = NitroROM(rom)
    out = {"containers": 0, "strict": 0, "compressed": 0, "other": 0, "by_dir": {}}
    for fid, name in sorted(r.names.items()):
        h = obj_header(r.file(fid))
        if h is None:
            continue
        out["containers"] += 1
        out["strict" if h["size_ok"] else "compressed" if h["compressed"] else "other"] += 1
        d = name.rsplit("/", 1)[0]
        out["by_dir"][d] = out["by_dir"].get(d, 0) + 1
    return out
