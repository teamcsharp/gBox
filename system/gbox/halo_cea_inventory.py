"""Halo: Combat Evolved Anniversary (Xbox 360) inventory manifest.

Dual-engine title on a single XDVDFS disc:
  * classic Halo CE (Bungie "Blam!") engine -> /maps_original/*.map tag caches
    (a10/a30/a50/b30/b40/c10/c20/c40/d20/d40/ui) with the `head` cache-file magic;
  * the Anniversary remaster (Saber Interactive "Saber3D" on a Reach-engine XEX)
    -> /paks360/*.s3dpak packages (per-level a10..d40, initial_*, ui and the ~1 GB
    pak_stream) plus remastered /maps/cex_*.map caches and /maps/shared.map.
A Reach Title Update executable (ReachTU1.xex) sits beside the main default.xex, and
the XEX title id 0x4D5308CE is Reach-family.

CLI:  python -m gbox.halo_cea_inventory ISO [--out m.json] [--source-sha256 HEX]

Pure stdlib plus gbox.re6 (the shared Xbox 360 XDVD reader); no numpy/PIL, so it runs
on the runtime venv and in CI without the analysis stack.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from collections import Counter, defaultdict
from pathlib import Path

from . import re6

TITLE_ID = 0x4D5308CE                  # Reach-family title id on this build
XEX_MAGIC = b"XEX2"

# Classic Blam! level cache: a10 (Pillar of Autumn) .. d40 (The Maw), plus ui.
CLASSIC_MAP = re.compile(r"^/maps_original/(?P<code>[a-d]\d0|ui)\.map$")
# Remastered Anniversary level cache (cex_* = "Combat Evolved eXtras"), shared + menu.
CEX_MAP = re.compile(r"^/maps/(?P<code>cex_[a-z0-9_]+|shared|mainmenu)\.map$")
# Saber3D streaming/level packages.
S3DPAK = re.compile(r"^/paks360/(?P<name>.+)\.s3dpak$")


def xex_info(data: bytes) -> dict:
    """Identity fields of default.xex. The title id is located by its big-endian byte
    pattern (XEX2 base-file data is compressed, so no build string is visible)."""
    if data[:4] != XEX_MAGIC:
        raise ValueError("not an XEX2 executable")
    mod_flags, header_size = struct.unpack_from("<II", data, 4)
    sec_off = struct.unpack_from("<I", data, 16)[0]
    off, tid, endian = -1, None, "big"
    for m in re.finditer(rb"\x4d\x53[\x07\x08][\x00-\xff]", data):
        tid = struct.unpack(">I", m.group())[0]
        off = m.start()
        break
    if off < 0:
        for m in re.finditer(rb"[\x07\x08]\x53\x4d\x00", data):   # little-endian fallback
            tid = struct.unpack("<I", m.group())[0]
            off = m.start()
            endian = "little"
            break
    return {"magic": "XEX2", "module_flags": f"{mod_flags:#x}", "header_size": f"{header_size:#x}",
            "security_offset": f"{sec_off:#x}", "title_id": (f"{tid:#x}" if tid else None),
            "title_id_offset": off, "title_id_endian": endian, "size": len(data)}


def classify(files: dict) -> dict:
    """Group the disc into the two engines' asset families and list every level cache."""
    fam: dict[str, list[str]] = defaultdict(list)
    for p in files:
        n = p.rsplit("/", 1)[-1]
        m = CLASSIC_MAP.match(p)
        if m:
            fam["classic_map"].append(n)
        elif CEX_MAP.match(p):
            fam["anniv_map"].append(n)
        elif S3DPAK.match(p):
            fam["s3dpak"].append(n)
        elif p.startswith("/shaders/") and n.lower().endswith((".fx", ".vsh", ".psh")):
            fam["shader"].append(n)
        elif n.lower().endswith(".fsb"):
            fam["fmod_fsb"].append(n)
        elif n.lower().endswith(".blf"):
            fam["blf"].append(n)
        elif n.lower().endswith(".usm"):
            fam["video_usm"].append(n)
        elif n.lower().endswith(".xex"):
            fam["xex"].append(n)
    return {k: sorted(v) for k, v in fam.items()}


def inventory(iso, source_sha256: str | None = None) -> dict:
    """Full manifest of the owned disc image. Every file is enumerated; the classic and
    remastered map rosters and the Saber3D package list are extracted, and the executable
    is hashed."""
    iso = str(iso)
    disc = re6.XDVD(iso)
    try:
        files = disc.files
        xex = disc.read("/default.xex")
        top = Counter(p.strip("/").split("/", 1)[0] if "/" in p.strip("/") else "(root)"
                      for p in files)
        exts = Counter(p.rsplit(".", 1)[-1].lower() if "." in p else "(none)" for p in files)
        cls = classify(files)
        man = {
            "game": "Halo - Combat Evolved Anniversary",
            "platform": "xbox360",
            "title_id": f"{TITLE_ID:#x}",
            "engine": ["Blam! (classic Halo CE)", "Saber3D (Anniversary, Reach-engine XEX)"],
            "source": {"path": iso, "size": Path(iso).stat().st_size, "sha256": source_sha256},
            "executable": {"path": "/default.xex",
                           "sha256": hashlib.sha256(xex).hexdigest(),
                           **xex_info(xex)},
            "disc": {"partition": disc.part, "files": len(files),
                     "bytes": sum(n for _, n in files.values()),
                     "top_dirs": dict(top.most_common()), "extensions": dict(exts.most_common())},
            "assets": {k: v for k, v in cls.items()},
            "counts": {k: len(v) for k, v in cls.items()},
            "launch": {
                "emulator": "Xenia (Xbox 360)",
                "boot": "extracted XDVDFS folder with default.xex at root",
                "note": "reader/writer not yet registered; inventory stage only",
            },
        }
        return man
    finally:
        disc.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Halo CEA (Xbox 360) inventory manifest")
    ap.add_argument("iso", help="owned disc image (.iso)")
    ap.add_argument("--out", default="halo_cea_inventory.json", help="manifest output path")
    ap.add_argument("--source-sha256", default=None, help="sha256 of the source image, if precomputed")
    args = ap.parse_args(argv)
    man = inventory(args.iso, args.source_sha256)
    Path(args.out).write_text(json.dumps(man, indent=1))
    print(json.dumps({k: man[k] for k in ("game", "title_id", "engine", "source", "executable",
                                          "disc", "counts")}, indent=1))
    print(f"manifest -> {args.out}")


if __name__ == "__main__":
    main()
