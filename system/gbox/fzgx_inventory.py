"""F-Zero GX (USA) — owned-disc inventory for native character-replacement work.

Catalog c96fc541e4b18d84 is the HyperSpin Dolphin GCZ
"collections/Nintendo GameCube/roms/F-Zero GX (USA).gcz".  The GCZ is never modified; this
module reads it in place through `gcdisc.GCDisc` (which inflates only the touched 16 KiB GCZ
blocks) and decompresses the Amusement Vision `.lz` payloads with `gbox.formats.avlz`.

Disc identity (first 0x440 bytes + bi2): GFZE01, region NTSC-U (bi2 region word 1), title
"F-ZERO GX (US Version)".  main.dol sits at the header's 0x420 offset (not in the FST);
14 fze.*.rel code modules and a `fze.str` string/name table sit in the FST.

Containers / formats (worked out on the owned disc):
  U8 archive (.arc)            magic 55 aa 38 2d (52 plain + 208 LZ'd in chara/arc/)
  Amusement Vision LZ (.lz)    gbox.formats.avlz: header u32 compressed_size, u32
                               uncompressed_size (both LE), then an LZSS stream (ring 4096,
                               THRESHOLD 3, init 0x00)
  GMA (.gma / .gma.lz)         Amusement Vision skinned model (804 files)
  TPL (.tpl / .tpl.lz)         Amusement Vision texture pack (NOT the Nintendo GX TPL magic
                               00 20 AF 30; header starts 00 00 01 e8 ... — see analysis)
  SKL (.skl)                   skeleton (306 files), MTA (.mta) motion (306 files)
  ADX (.adx) CRI audio, SFD (.sfd) Sofdec video, AHX (.ahx) audio

`python -m gbox.fzgx_inventory GCZ --out manifest.json` writes the manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path

GAME_ID = "c96fc541e4b18d84"
DISC_ID = "GFZE01"
SOURCE_REL = "collections/Nintendo GameCube/roms/F-Zero GX (USA).gcz"
GC_MAGIC = 0xC2339F3D
U8_MAGIC = b"\x55\xaa\x38\x2d"
TPL_GX_MAGIC = b"\x00\x20\xaf\x30"
REGIONS = {0: "NTSC-J", 1: "NTSC-U", 2: "PAL"}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha_file(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def disc_header(head: bytes, bi2: bytes) -> dict:
    if len(head) < 0x430 or len(bi2) < 0x1C:
        raise ValueError("disc header too short")
    if struct.unpack_from(">I", head, 0x1C)[0] != GC_MAGIC:
        raise ValueError("not a GameCube disc (magic at 0x1C)")
    dol_off, fst_off, fst_size = struct.unpack_from(">III", head, 0x420)
    region = struct.unpack_from(">I", bi2, 0x18)[0]
    return {
        "disc_id": head[:6].decode("ascii", "replace"),
        "maker": head[4:6].decode("ascii", "replace"),
        "disc_number": head[6] + 1,
        "version": head[7],
        "title": head[0x20:0x60].split(b"\0")[0].decode("latin-1"),
        "dol_offset": dol_off,
        "fst_offset": fst_off,
        "fst_size": fst_size,
        "region": REGIONS.get(region, f"unknown({region})"),
    }


def roster(disc) -> list[str]:
    """Pilot ids from chara/<name>_500.gma (LOD2 model), fall back to _100.gma."""
    names = set()
    for p in disc.files:
        if not p.startswith("chara/"):
            continue
        leaf = p.rsplit("/", 1)[-1]
        if leaf.endswith(".lz"):
            leaf = leaf[:-3]
        for suf in ("_500.gma", "_100.gma", "_face.gma"):
            if leaf.endswith(suf):
                names.add(leaf[: -len(suf)])
                break
    return sorted(names)


def probe(disc, path: str) -> dict:
    """Decompress (if .lz) and return the first 32 bytes + size + sha256."""
    raw = disc.read(path)
    out = raw
    if path.lower().endswith(".lz"):
        from gbox.formats.avlz import decompress
        out = decompress(raw)
    return {"size": len(out), "sha256": _sha(out), "head": out[:32].hex()}


def build_manifest(src: str) -> dict:
    from gbox.gcdisc import GCDisc

    disc = GCDisc(src)
    try:
        head = disc._r(0, 0x440)
        bi2 = disc._r(0x440, 0x2000)
        hdr = disc_header(head, bi2)
        if hdr["disc_id"] != DISC_ID:
            raise ValueError(f"expected {DISC_ID}, got {hdr['disc_id']}")

        dol = disc.dol()

        exts = Counter()
        tops = Counter()
        for p in disc.files:
            leaf = p.rsplit("/", 1)[-1]
            exts[leaf.rsplit(".", 1)[-1].lower() if "." in leaf else "(none)"] += 1
            tops[p.split("/")[0]] += 1

        chars = roster(disc)

        samples = {}
        for p in [
            "chara/arc/arrow_sel.arc.lz", "bg/bg_big.tpl.lz", "bg/bg_big.gma.lz",
            "bmp_e/bmp_cardt.arc",
        ]:
            if p in disc.files:
                samples[p] = probe(disc, p)

        manifest = {
            "game_id": GAME_ID,
            "title": hdr["title"],
            "disc_id": hdr["disc_id"],
            "region": hdr["region"],
            "platform": "gamecube",
            "source_rel": SOURCE_REL,
            "source_sha256": _sha_file(src),
            "source_size": Path(src).stat().st_size,
            "dol": {"sha256": _sha(dol), "size": len(dol)},
            "fst": {"offset": hdr["fst_offset"], "size": hdr["fst_size"],
                    "num_files": len(disc.files)},
            "extensions": dict(exts.most_common()),
            "top_dirs": dict(tops.most_common()),
            "roster": chars,
            "roster_count": len(chars),
            "containers": {
                "u8_archive_plain": exts.get("arc", 0),
                "u8_archive_lz": sum(1 for p in disc.files if p.endswith(".arc.lz")),
                "avlz": exts.get("lz", 0),
                "rel_modules": sum(1 for p in disc.files if p.endswith(".rel")),
            },
            "samples": samples,
            "launch": {"core": "dolphin", "format": "gcz", "library": "hyperspin"},
        }
        return manifest
    finally:
        disc.f.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m gbox.fzgx_inventory",
                                 description="F-Zero GX (USA) owned-disc inventory")
    ap.add_argument("gcz", help="path to the owned .gcz")
    ap.add_argument("--out", default="fzgx_manifest.json")
    args = ap.parse_args(argv)
    m = build_manifest(args.gcz)
    out = Path(args.out)
    out.write_text(json.dumps(m, indent=2) + "\n")
    print(json.dumps(m, indent=2))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
