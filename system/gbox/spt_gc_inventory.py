"""Inventory for Tom Clancy's Splinter Cell - Pandora Tomorrow (USA) (GameCube, game_id d11d44eeacdd5e31).

Builds the authoritative owned-build manifest for the Dolphin .gcz source:
  * the disc FST (name, absolute offset, size) read read-only from the owned image
  * a content classification of every file by its first bytes
  * the Unreal Engine 3 package census (LE package magic 0x9E2A83C1 stored little-endian)
  * one identified native target asset for a character replacement

Nothing here writes to the owned image; the reader is gbox.gcdisc.GCDisc (gcz read in place).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import time
from collections import Counter
from pathlib import Path

GAME_ID = "d11d44eeacdd5e31"
TITLE = "Tom Clancy's Splinter Cell - Pandora Tomorrow (USA)"
UE3_LE = b"\xc1\x83\x2a\x9e"   # 0x9E2A83C1 stored little-endian
UE3_BE = b"\x9e\x2a\x83\xc1"   # big-endian (PS3/X360 cooked packages)
CHAR_HINTS = ("sam", "fisher", "char", "mesh", "skeletal", "soldier", "enforcer",
              "npc", "model", "body", "head", "arm", "leg", "sc_")


def classify(head: bytes) -> str:
    if not head:
        return "empty"
    if head[:4] == UE3_LE:
        return "unreal_package_le"
    if head[:4] == UE3_BE:
        return "unreal_package_be"
    if head[:4] == b"\x7fELF":
        return "elf"
    if head[:4] == b"RIFF":
        return "riff"
    if head[:4] == b"oT  ":
        return "ogg"
    if head[:4] == b"\x89PNG":
        return "png"
    if head[:4] == b"\x00\x00\x00\x01":
        return "big_endian_container"
    if head[:4] == b"\x01\x00\x00\x00":
        return "little_endian_container"
    return "other"


def sha256_file(path, chunk=4 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb", buffering=0) as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def disc_header(disc) -> dict:
    h = disc._r(0, 0x60)

    def s(a, b):
        return h[a:b].decode("latin-1", "replace") if len(h) >= b else ""

    return {
        "game_code": s(0, 6),
        "maker_code": s(6, 8),
        "game_title": s(0x20, 0x60).split("\x00")[0],
        "disc_number": h[0x48] if len(h) > 0x48 else None,
        "revision": h[0x49] if len(h) > 0x49 else None,
    }


def census(disc, limit=600, budget_s=240.0):
    """Classify each FST member by its first bytes. Bounded by count and wall clock."""
    t0 = time.time()
    rows = []
    for name, (off, size) in sorted(disc.files.items()):
        if len(rows) >= limit or time.time() - t0 > budget_s:
            break
        head = disc._r(off, min(16, size)) if size else b""
        rows.append({"path": name, "offset": off, "size": size,
                     "label": classify(head), "head": head.hex()})
    return rows, {"scanned": len(rows), "total": len(disc.files),
                  "truncated": len(rows) < len(disc.files),
                  "elapsed_s": round(time.time() - t0, 1)}


def select_target(rows):
    """Pick one native target asset: a UE3 package whose member path names a character/body."""
    pkgs = [r for r in rows if r["label"] == "unreal_package_le"]

    def score(r):
        n = r["path"].lower()
        return (sum(1 for h in CHAR_HINTS if h in n), r["size"])

    return sorted(pkgs, key=score, reverse=True)[0] if pkgs else None


def build_manifest(disc, rows, stats, source_path=None, source_sha256=None,
                   source_bytes=None, dol_sha256=None, dol_bytes=None, dol_entry=None):
    return {
        "game_id": GAME_ID,
        "title": TITLE,
        "platform": "gamecube",
        "revision": disc_header(disc),
        "source": {
            "path": source_path,
            "bytes": source_bytes,
            "sha256": source_sha256,
            "container": "dolphin_gcz (magic 0xB10BC001), single 16 KiB-block compressed image",
            "member_byte_order": "little-endian (UE3 package magic 0x9E2A83C1 stored LE)",
            "executable_byte_order": "big-endian PowerPC 750 (main.dol)",
        },
        "offset_base": ("absolute byte offset in the uncompressed GameCube disc image, 0-based; "
                        "gbox.gcdisc.GCDisc maps .gcz block offsets onto it"),
        "census": dict(Counter(r["label"] for r in rows)),
        "census_stats": stats,
        "packages_le": [r["path"] for r in rows if r["label"] == "unreal_package_le"],
        "target_asset": select_target(rows),
        "executable": {"name": "main.dol", "bytes": dol_bytes, "sha256": dol_sha256,
                       "entry": dol_entry, "byte_order": "big-endian (PowerPC, GameCube)"},
        "files": rows,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--out")
    ap.add_argument("--source-sha")
    ap.add_argument("--source-sha-file")
    ap.add_argument("--limit", type=int, default=600)
    ap.add_argument("--budget", type=float, default=240.0)
    a = ap.parse_args(argv)
    from .gcdisc import GCDisc
    disc = GCDisc(a.image)
    rows, stats = census(disc, limit=a.limit, budget_s=a.budget)
    sha = a.source_sha
    if not sha and a.source_sha_file and Path(a.source_sha_file).exists():
        sha = Path(a.source_sha_file).read_text().split()[0]
    try:
        size = Path(a.image).stat().st_size
    except OSError:
        size = None
    dol_bytes = dol_sha = entry = None
    try:
        dol = disc.dol()
        dol_bytes = len(dol)
        dol_sha = hashlib.sha256(dol).hexdigest()
        entry = hex(struct.unpack_from(">I", dol, 0xD8)[0])
    except Exception as exc:                                   # pragma: no cover
        print("DOL_ERROR", type(exc).__name__, exc)
    man = build_manifest(disc, rows, stats, a.image, sha, size, dol_sha, dol_bytes, entry)
    out = json.dumps(man, indent=1)
    if a.out:
        Path(a.out).write_text(out)
    print(json.dumps({k: man[k] for k in ("game_id", "revision", "census", "census_stats",
                                          "source", "executable", "target_asset")}, indent=1)[:3000])
    print("PACKAGES_LE", len(man["packages_le"]))
    for p in man["packages_le"][:20]:
        print("  PKG", p)
    return man


if __name__ == "__main__":
    main()
