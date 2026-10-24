"""Crazy Taxi 2 (US) [RDC] Dreamcast inventory for catalog game e3f480866acf7465 (request #1878).

Owned source: QuickSwap2 `Emulation/_emulation/_dc iso/[CDI] Crazy Taxi 2 (US)[RDC]/Crazy Taxi 2 (US)[RDC].cdi`
(DiscJuggler v0x80000006, 2 sessions, 811340459 bytes, streamed sha256 ac4767b6...64b9).

The fingerprint suggests gbox.jgr.afs_entries + gbox.formats.lz; those hits are CRI audio middleware. Character
banks are the NAOMI `pol` layout read by `gbox.crazy_taxi2`. This module does not assume the RDC repack is the
pinned CDI build: it hashes 1ST_READ.BIN and every POL/TEX bank straight from the image (CDIRom), compares each with
`crazy_taxi2.FILES_SHA256`, walks every POL bank (`c2.walk` raises unless the file ends exactly after its last
object) and checks that `c2.known_build` finds this executable's player tables. Read-only; nothing is written.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import crazy_taxi2 as c2
from .crazy_taxi2_usa_inventory import MODEL_RE, compare_known, driver_set

GAME_ID = "e3f480866acf7465"
TITLE = "Crazy Taxi 2 (US) [RDC]"
SOURCE_REL = "quickswap2/Emulation/_emulation/_dc iso/[CDI] Crazy Taxi 2 (US)[RDC]/Crazy Taxi 2 (US)[RDC].cdi"
DISC_SHA256 = "ac4767b69c16213d5d2ac66335dfdcd7c6d20ade4d5c26f07d0e2212358664b9"
DISC_BYTES = 811340459
LAUNCH = ("Flycast (standalone or RetroArch core) with Dreamcast BIOS dc_boot.bin/dc_flash.bin; boots the CDI "
          "directly; 1 player, VMU save optional. Agent tests only on i9-NUC/Spark, never the operator PC.")


def build(disc, *, source: str | Path | None = None, source_sha256: str | None = None,
          source_bytes: int | None = None) -> dict:
    """Manifest from an open disc reader (`.files`, `.read(name)`), e.g. gbox.gdrom.CDIRom."""
    first = disc.read("1ST_READ.BIN")
    first_sha = hashlib.sha256(first).hexdigest()
    hashes = {"1ST_READ.BIN": first_sha}
    models, failures = [], []
    for n in sorted(disc.files):
        if not MODEL_RE.match(n):
            continue
        b = disc.read(n)
        hashes[n] = hashlib.sha256(b).hexdigest()
        row = {"file": n, "bytes": len(b), "sha256": hashes[n]}
        if n.startswith("POL"):
            try:
                row |= {k: v for k, v in c2.summary(n, b).items() if k not in ("file", "bytes")}
            except ValueError as e:
                failures.append({"file": n, "error": str(e)})
                row["error"] = str(e)
        else:
            row["kind"] = "texture bank"
        models.append(row)
    pols = [m for m in models if m["file"].startswith("POL")]
    return {
        "game_id": GAME_ID, "title": TITLE,
        "source": {"file": str(source) if source else None, "bytes": source_bytes, "sha256": source_sha256,
                   "format": "DiscJuggler CDI (gbox.gdrom.CDIRom)"},
        "launch": LAUNCH,
        "first_read": {"bytes": len(first), "sha256": first_sha, "known_build_tables": c2.known_build(first)},
        "files": len(disc.files), "models": models, "walk_failures": failures,
        "pol_files": len(pols), "pol_walked": len(pols) - len(failures),
        "triangles": sum(m.get("triangles", 0) for m in pols),
        "drivers": driver_set(disc.files),
        "vs_pinned_cdi_build": compare_known(hashes),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    from .gdrom import CDIRom
    ap = argparse.ArgumentParser(description=TITLE + " inventory")
    ap.add_argument("cdi", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--hash-source", action="store_true", help="stream-hash the whole image (slow on NFS)")
    a = ap.parse_args(argv)
    sha = None
    if a.hash_source:
        h = hashlib.sha256()
        with open(a.cdi, "rb") as f:
            for blk in iter(lambda: f.read(4 << 20), b""):
                h.update(blk)
        sha = h.hexdigest()
    man = build(CDIRom(a.cdi), source=a.cdi, source_sha256=sha, source_bytes=a.cdi.stat().st_size)
    text = json.dumps(man, indent=1, sort_keys=True)
    if a.out:
        a.out.write_text(text + "\n")
    print(json.dumps({k: man[k] for k in ("first_read", "pol_files", "pol_walked", "triangles",
                                          "vs_pinned_cdi_build")}, indent=1))
    return 0 if not man["walk_failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
