"""Inventory for Phantasy Star Online Episode III C.A.R.D. Revolution (USA, GPSE8P), game 5b5ecb4c36a13584.

Owned source: hyperspin Dolphin GCZ ``Phantasy Star Online Episode III - C.A.R.D. Revolution (USA).gcz``
(GCZ header is 32 bytes, magic 0xB10BC001, data_size 1,459,978,240, 16 KiB blocks; decoded with gbox.gcz).

Verified against the files (not the fingerprint): the disc carries PSO-style player models as little-endian
Ninja chunk ``NJCM`` files ``pl<class><part><nn>.nj`` (class letter A..L/W..., parts bdy/hai/hed/cap) and
``plAtex.afs`` (AFS, 137 entries of 8224-byte GVR-sized textures).  Target slot for replacement work:
``plAbdy00.nj`` (NJCM, 21,308 bytes).

Usage: python -m gbox.pso3_inventory SRC.gcz --out pso3_inventory.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct

from .au_inventory import FST
from .gcz import GCZ

GAME_ID = "5b5ecb4c36a13584"
PLATFORM = "gamecube"
BUILD = "GPSE8P"
PLAYER_RE = re.compile(r"^pl([A-Z])(bdy|hai|hed|cap)(\d\d)\.nj$")


def parse_njcm_header(head: bytes) -> dict:
    """NJCM chunk header: 4-byte tag + u32 LE body size (little-endian even on GameCube)."""
    if len(head) < 8 or head[:4] != b"NJCM":
        raise ValueError("not an NJCM chunk")
    body = struct.unpack("<I", head[4:8])[0]
    return {"tag": "NJCM", "body_size": body, "end": body + 8}


def parse_afs_toc(head: bytes) -> list[tuple[int, int]]:
    """AFS: 'AFS\\0', u32 LE count, then count * (offset, size) LE."""
    if head[:4] != b"AFS\x00":
        raise ValueError("not an AFS archive")
    n = struct.unpack("<I", head[4:8])[0]
    if len(head) < 8 + 8 * n:
        raise ValueError("AFS TOC truncated")
    return [struct.unpack("<II", head[8 + 8 * i:16 + 8 * i]) for i in range(n)]


def player_name_parts(name: str):
    m = PLAYER_RE.match(name)
    return m.groups() if m else None


def _sha_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def inventory(src: str, source_sha256: str | None = None, image_sha256: bool = True) -> dict:
    with GCZ(src) as g:
        hdr = g.read(0, 0x80)
        code = hdr[:6].decode("ascii")
        if code != BUILD:
            raise ValueError(f"unexpected build {code}")
        dol_off, fst_off, fst_size, _ = struct.unpack(">IIII", g.read(0x420, 16))
        files = {p.split("/", 2)[-1]: (o, s) for p, o, s in FST(g.read(fst_off, fst_size)).walk()}
        out = {
            "game_id": GAME_ID, "platform": PLATFORM, "build": code,
            "title": hdr[0x20:0x60].split(b"\0")[0].decode("ascii"),
            "source_path": src,
            "source_sha256": source_sha256 or _sha_file(src),
            "image_size": g.data_size, "gcz_block_size": g.block_size,
            "image_sha256": g.sha256_range(0, g.data_size) if image_sha256 else None,
            "dol_offset": dol_off, "fst_offset": fst_off, "file_count": len(files),
            "byte_order": {"disc/dol": "big", "NJCM/AFS": "little"},
        }
        dol_size = None
        out["census"] = {}
        for n in files:
            ext = n.rsplit(".", 1)[-1].lower() if "." in n else "(none)"
            out["census"][ext] = out["census"].get(ext, 0) + 1
        players = []
        for n, (o, s) in sorted(files.items()):
            if not PLAYER_RE.match(n):
                continue
            head = g.read(o, 8)
            try:
                hd = parse_njcm_header(head)
            except ValueError:
                hd = None
            players.append({"name": n, "offset": o, "size": s, "njcm": hd, "sha256": g.sha256_range(o, s)})
        out["player_models"] = players
        o, s = files["plAtex.afs"]
        toc = parse_afs_toc(g.read(o, min(s, 0x4000)))
        out["plAtex_afs"] = {"offset": o, "size": s, "sha256": g.sha256_range(o, s),
                             "entries": len(toc), "in_range": all(a + b <= s for a, b in toc)}
        out["target_slot"] = "plAbdy00.nj"
        out["afs_files"] = sorted(n for n in files if n.lower().endswith(".afs"))
        out["gvm_count"] = out["census"].get("gvm", 0)
        return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out", required=True)
    ap.add_argument("--source-sha256")
    a = ap.parse_args()
    json.dump(inventory(a.src, a.source_sha256), open(a.out, "w"), indent=1)
