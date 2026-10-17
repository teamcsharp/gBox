"""Geist (USA, GITE01) -- owned-disc inventory for character-replacement work.

Catalog 34dd475ee86a0b74 is the HyperSpin Dolphin GCZ
"collections/Nintendo GameCube/roms/Geist (USA).gcz".  This module reads the GCZ *in
place* through `gcdisc.GCDisc` (gbox.gcz inflates only the touched 16 KiB blocks; the
GCZ is never modified) and emits a source manifest: exact build identity, source hash,
main.dol (source executable) hash, container layout and the character/sprite/mesh/
texture/animation asset census.

Disc facts (assimilate fingerprint, result_sha256 da3ba1d630db4aff4b8f0554e853af08…):
  engine     Nintendo GC/Wii SDK formats (0.78)  -- TPL textures only; no model magic
  models     none recognized -> headerless/packed; the single .m3d is the prime candidate
  textures   GameCube TPL x3
  extensions .gsf x32, .olc x32, .spt x32, .spd x32, .song x41, .sdf_gc x14, .bin x8,
             .tpl x3, .adp x2, .m3d x1, .mmf x1, .samp x1, .$$$ x2, .acky x1, .txt x1

`python -m gbox.geist_inventory SRC [--source-sha256 SHA] [--out manifest.json]` writes
the manifest.  This is stage 1 (inventory); analysis/reader/writer follow in later runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

GAME_ID = "34dd475ee86a0b74"
TITLE = "Geist (USA)"
DISC_ID = "GITE01"
SOURCE_REL = "collections/Nintendo GameCube/roms/Geist (USA).gcz"
GC_MAGIC = 0xC2339F3D
TPL_MAGIC = 0x0020AF30
REGIONS = {0: "NTSC-J", 1: "NTSC-U", 2: "PAL"}
GX_FORMATS = {0: "I4", 1: "I8", 2: "IA4", 3: "IA8", 4: "RGB565", 5: "RGB5A3", 6: "RGBA8",
              8: "C4", 9: "C8", 10: "C14X2", 14: "CMPR"}

# Asset-format census is grounded in the extensions the disc actually carries (assimilate
# fingerprint).  Nothing here is guessed as "the model format" -- .m3d is recorded as a
# *candidate* container and stays unproven until the analysis stage opens it in Ghidra.
ASSET_ROLES = {
    ".tpl": "texture (GameCube GX TPL)",
    ".m3d": "model candidate (headerless/unproven)",
    ".mmf": "unknown (single file)",
    ".bin": "binary data",
    ".sdf_gc": "sound definition (GC)",
    ".gsf": "sound/stream data",
    ".song": "music sequence",
    ".adp": "ADPCM audio",
    ".samp": "audio sample",
    ".olc": "level/object container",
    ".spt": "sprite/table data",
    ".spd": "sprite/table data",
    ".acky": "unknown",
    ".$$$": "scratch/unknown",
    ".txt": "text",
}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                return h.hexdigest()
            h.update(b)


def disc_header(head: bytes, bi2: bytes) -> dict:
    """Boot header (first 0x440 bytes) + bi2 (0x440..) -> identity, DOL/FST location and region."""
    if len(head) < 0x430 or len(bi2) < 0x1C:
        raise ValueError("disc header too short")
    if struct.unpack_from(">I", head, 0x1C)[0] != GC_MAGIC:
        raise ValueError("not a GameCube disc (magic at 0x1C)")
    dol_off, fst_off, fst_size = struct.unpack_from(">III", head, 0x420)
    region = struct.unpack_from(">I", bi2, 0x18)[0]
    return {"disc_id": head[:6].decode("ascii", "replace"), "maker": head[4:6].decode("ascii", "replace"),
            "disc_number": head[6] + 1, "version": head[7],
            "title": head[0x20:0x60].split(b"\0")[0].decode("latin-1"),
            "dol_offset": dol_off, "fst_offset": fst_off, "fst_size": fst_size,
            "region": REGIONS.get(region, f"unknown({region})")}


def tpl_images(b: bytes) -> list[dict]:
    """[{w, h, fmt}] for a GameCube TPL (magic 0x0020AF30)."""
    if len(b) < 12 or struct.unpack_from(">I", b, 0)[0] != TPL_MAGIC:
        raise ValueError("not a TPL (magic 0x0020AF30)")
    n, table = struct.unpack_from(">II", b, 4)
    if table + 8 * n > len(b):
        raise ValueError("TPL image table runs past the end")
    out = []
    for i in range(n):
        ih = struct.unpack_from(">I", b, table + 8 * i)[0]
        if ih + 12 > len(b):
            raise ValueError(f"TPL image header {i} outside the file")
        h, w, fmt, data = struct.unpack_from(">HHII", b, ih)
        if data > len(b):
            raise ValueError(f"TPL image {i} data outside the file")
        out.append({"w": w, "h": h, "fmt": GX_FORMATS.get(fmt, str(fmt))})
    return out


def dol_entry(dol: bytes) -> int:
    """Entry point from the DOL header (0xE0)."""
    if len(dol) < 0xE4:
        raise ValueError("DOL too short")
    return struct.unpack_from(">I", dol, 0xE0)[0]


def inventory(src: Path, source_sha256: str | None = None, source_format: str = "Dolphin GCZ (zlib blocks)") -> dict:
    from .gcdisc import GCDisc

    disc = GCDisc(str(src))
    hdr = disc_header(disc._r(0, 0x440), disc._r(0x440, 0x20))
    if hdr["disc_id"] != DISC_ID:
        raise ValueError(f"{src}: disc id {hdr['disc_id']}, expected {DISC_ID}")

    dol = disc.dol()

    dirs: dict[str, Counter] = defaultdict(Counter)
    sizes: Counter = Counter()
    ext_counts: Counter = Counter()
    ext_sizes: Counter = Counter()
    for name, (_off, size) in disc.files.items():
        top = name.split("/", 1)[0] if "/" in name else "<root>"
        base = name.rsplit("/", 1)[-1]
        ext = ("." + base.rsplit(".", 1)[-1]) if "." in base else ""
        dirs[top][ext or "(no ext)"] += 1
        sizes[top] += size
        ext_counts[ext or "(no ext)"] += 1
        ext_sizes[ext or "(no ext)"] += size

    # Per-file census with hashes for the small, format-bearing files (full-disc walk stays
    # bounded: only the touched blocks are inflated by the GCZ reader).
    assets: list[dict] = []
    for name in sorted(disc.files):
        size = disc.files[name][1]
        base = name.rsplit("/", 1)[-1]
        ext = ("." + base.rsplit(".", 1)[-1]) if "." in base else ""
        if ext not in ASSET_ROLES:
            continue
        row = {"file": name, "ext": ext, "size": size, "role": ASSET_ROLES[ext]}
        if size <= 4 << 20:  # hash only small format-bearing files; skip huge streams
            row["sha256"] = _sha(disc.read(name))
        if ext == ".tpl":
            try:
                row["images"] = tpl_images(disc.read(name))
            except (ValueError, struct.error, IndexError) as exc:
                row["tpl_error"] = str(exc)
        assets.append(row)

    layout = {d: {"files": sum(c.values()), "bytes": sizes[d], "ext": dict(c)} for d, c in sorted(dirs.items())}

    return {
        "game_id": GAME_ID, "title": TITLE,
        "source": {"catalog_rel_path": SOURCE_REL, "path": str(src), "sha256": source_sha256,
                   "format": source_format, "bytes": src.stat().st_size},
        "disc": hdr,
        "files": len(disc.files),
        "dol": {"size": len(dol), "sha256": _sha(dol), "entry": hex(dol_entry(dol))},
        "layout": layout,
        "extensions": {"counts": dict(ext_counts), "bytes": dict(ext_sizes), "roles": ASSET_ROLES},
        "assets": assets,
        "launch": {
            "core": "dolphin", "region": hdr["region"],
            "prereq": "Dolphin emulator; source is a GCZ, never modified -- mods are copies via filemods",
        },
        "next_stage": (
            "analysis: open main.dol (and the single .m3d) in Ghidra; the disc carries no recognized "
            "model magic, so locate the asset loader by string-xref on '.m3d' / '.tpl' / '.sdf_gc' "
            "and prove the .m3d header before any reader/writer work."
        ),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Geist (GITE01) owned-disc inventory manifest")
    ap.add_argument("src", type=Path)
    ap.add_argument("--source-sha256")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    m = inventory(a.src, a.source_sha256)
    text = json.dumps(m, indent=1)
    if a.out:
        a.out.write_text(text)
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
