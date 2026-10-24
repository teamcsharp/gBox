"""Prince of Persia: Warrior Within (USA) (GameCube, G2OE41) — inventory of the owned Dolphin GCZ build.

The owned source is a .gcz (Dolphin CompressedBlob) GC disc image, so every read goes through
gbox.gcz.GCZ's random-access reader: only the 16 KiB blocks actually touched are inflated.
This module proves the GCZ path works on this title, lists the disc FST (ISO root), walks every
RARC archive on the disc, and pins the main.dol executable for the next stage (Ghidra import).

It is read-only and bounded: no full-disc decompression, no model parsing, no writes.
"""
from __future__ import annotations

import hashlib
import struct

from .formats.rarc import parse as rarc_parse, walk as rarc_walk
from .gcz import GCZ
from .gcz import GCZError
from .formats.gcfst import disc_header

GAME_ID = "9fc973656e2fd05d"

# First authoritative source identity (computed by streaming the owned file's bytes in the
# request test suite; the catalog row for this build carries no hashes).
SOURCE_SHA256 = "9af6ae530e5f952b7da1f3572cf4d6be8e87001d371e9e157bdd673ae5a2966a"
SOURCE_SIZE = 1303782157

# Container facts pinned from the owned file:
#   magic 01c00bb1 (LE read of the 0xB10BC001 GCZ CompressedBlob) -> GCZ-compressed disc
#   game id G2OE41 -> GameCube retail, Ubisoft 2004, Dolphin core; AKI engine family per
#   assimilation fingerprint (0.564) — the fingerprint is a start hint, not a reader.
CONTAINER = {"magic": "01c00bb1", "game_id": "G2OE41", "core": "dolphin",
             "manufacturer": "Ubisoft", "year": 2004, "platform": "gamecube"}


class PoPWWDisc:
    """Read-only inventory over the owned .gcz via the GCZ random-access reader."""

    def __init__(self, path: str):
        self.path = path
        self.gcz = GCZ(path, verify_hashes=True)      # the container's own Adler32 block hashes
        self.data_size = self.gcz.data_size
        self.block_size = self.gcz.block_size
        self.num_blocks = self.gcz.num_blocks
        self.game_id = self.gcz.magic == 0xB10BC001 and "GCZ" or "GCZ?"
        hdr = self.read_range(0, 0x440)
        h = disc_header(hdr)
        self.disc_id = h["game_id"]
        self.title = h["title"]
        self.dol_offset = h["dol_offset"]
        # FST walk (shared with gcdisc)
        from .formats.gcfst import parse_fst
        fst = self.read_range(h["fst_offset"], h["fst_size"])
        self.files = {p: (a, b) for p, a, b, _ in parse_fst(fst, h["fst_offset"])}

    def read_range(self, off: int, n: int) -> bytes:
        return self.gcz.read(off, n)

    def read_file(self, name: str) -> bytes:
        off, size = self.files[name]
        return self.read_range(off, size)

    def close(self):
        self.gcz.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def sha256_range(disc: PoPWWDisc, off: int, size: int, chunk: int = 0x400000) -> str:
    """Streaming SHA-256 of a disc range, block-cached inside GCZ (never materialises the disc)."""
    h = hashlib.sha256()
    pos, remaining = off, size
    while remaining:
        take = min(chunk, remaining)
        h.update(disc.read_range(pos, take))
        pos += take
        remaining -= take
    return h.hexdigest()


def inventory(path: str) -> dict:
    """Full bounded inventory: GCZ header, FST root, every RARC member, and main.dol identity."""
    out = {"path": path, "container": dict(CONTAINER), "source_sha256": SOURCE_SHA256,
           "source_size": SOURCE_SIZE}
    with PoPWWDisc(path) as d:
        out["gc_data_size"] = d.data_size
        out["gc_block_size"] = d.block_size
        out["gc_num_blocks"] = d.num_blocks
        out["disc_game_id"] = d.disc_id
        out["disc_title"] = d.title
        out["n_fst_files"] = len(d.files)
        # FST root listing (top level only, kept small in the report)
        out["fst_root"] = sorted(
            (p, s) for p, (o, s) in d.files.items() if "/" not in p)
        # main.dol (executable) identity: FST entry first, disc-header offset 0x420 fallback
        if "main.dol" in d.files:
            off, size = d.files["main.dol"]
            out["main_dol"] = {"path": "main.dol", "offset": off, "size": size,
                               "sha256": sha256_range(d, off, size)}
        else:
            out["main_dol"] = {"note": "no main.dol FST entry; header dol_offset=0x%x" % d.dol_offset}
        # RARC archives: every FST file whose first 4 bytes are RARC
        rars = []
        for p in d.files:
            try:
                off, size = d.files[p]
            except Exception:
                continue
            magic = d.read_range(off, 4)
            if magic != b"RARC":
                continue
            rarc = d.read_range(off, min(size, 0x4000000))
            try:
                t = rarc_parse(rarc)
                members = rarc_walk(rarc)
            except Exception as ex:
                rars.append({"path": p, "size": size, "error": str(ex)[:200]})
                continue
            rars.append({
                "path": p, "size": size, "data_size": t["data_size"],
                "n_nodes": len(t["nodes"]), "n_files": len(t["files"]),
                "members": sorted(m[0] for m in members)[:2000],
            })
        out["rarc_archives"] = rars
        # Named character / asset candidates among the FST files (counted, not guessed)
        out["candidate_assets"] = _candidates(d.files)
    return out


def _dol_sha256(d: PoPWWDisc) -> str:
    off, size = d.files["main.dol"]
    return sha256_range(d, off, size)


def _candidates(files: dict[str, tuple[int, int]]) -> list[str]:
    keys = ("char", "model", "mdl", "anim", "bone", "skel", "face", "player", "hero", "pop")
    out = []
    for p in files:
        low = p.lower()
        if any(k in low for k in keys):
            out.append(p)
    return sorted(out)[:400]


if __name__ == "__main__":
    import json, sys
    print(json.dumps(inventory(sys.argv[1]), indent=2))
