"""Resident Evil 6 (Xbox 360, title 43430819) inventory manifest.

Identify the exact owned build (disc image, default.xex) and enumerate its character
assets: the MT Framework big-endian ARC container layout, the hero part/costume roster,
texture banks, enemies, weapons, stages and loose media.

CLI:  python -m gbox.re6_inventory ISO [--out m.json] [--source-sha256 HEX]

Pure stdlib plus gbox.re6 (XDVD reader, ARC header); no numpy/PIL, so it runs on the
runtime venv and in CI without the analysis stack.
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
from .re6_models import CHARACTERS

TITLE_ID = 0x43430819                 # Resident Evil 6 (all regions)
XEX_MAGIC = b"XEX2"

# uPl00<part><Name><costume>.arc : part in ("", AcHead, Head, HandLeft, HandRight)
HERO_ARC = re.compile(r"^uPl(?P<idx>0[0-7])(?P<part>AcHead|Head|HandLeft|HandRight|)(?P<name>Leon|Helena|Chris|Piers|Jake|Sherry|Ada|Helper)(?P<rest>.*)\.arc$")
TEX_ARC = re.compile(r"^uPlTex(?P<model>\d{4})_\d+\.arc$")
EM_ARC = re.compile(r"^uEm\d+.*\.arc$")
WP_ARC = re.compile(r"^uWp\d+.*\.arc$")
ST_ARC = re.compile(r"^uS.*\.arc$")


def xex_info(data: bytes) -> dict:
    """Identity fields of default.xex. The XGD3 header table is not parsed; the title id
    is located by its little-endian byte pattern and the build string is scanned for."""
    if data[:4] != XEX_MAGIC:
        raise ValueError("not an XEX2 executable")
    mod_flags, header_size = struct.unpack_from("<II", data, 4)
    sec_off = struct.unpack_from("<I", data, 16)[0]
    pat = struct.pack(">I", TITLE_ID)            # the disc stores it big-endian; try LE as fallback
    off = data.find(pat)
    endian = "big"
    if off < 0:
        pat = struct.pack("<I", TITLE_ID)
        off = data.find(pat)
        endian = "little"
    if off < 0:
        raise ValueError(f"title id {TITLE_ID:#x} not found in XEX header")
    build = None
    for m in re.finditer(rb"[\x20-\x7e]{8,}", data[:0x4000]):
        s = m.group().decode("ascii", "replace")
        if "MasterRelease" in s or s.startswith("BH6"):
            build = s
            break
    return {"magic": "XEX2", "module_flags": f"{mod_flags:#x}", "header_size": f"{header_size:#x}",
            "security_offset": f"{sec_off:#x}", "title_id": f"{TITLE_ID:#x}",
            "title_id_offset": off, "title_id_endian": endian, "build_string": build, "size": len(data)}


def classify_arcs(files: dict) -> dict:
    """Group the XDVDFS .arc files into asset families and check the hero roster."""
    fam: dict[str, list[str]] = defaultdict(list)
    hero_parts: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    hero_costumes: dict[str, set] = defaultdict(set)
    for p in files:
        if not (p.endswith(".arc") and "/arc/X360/" in p):
            continue
        n = p.rsplit("/", 1)[-1]
        m = HERO_ARC.match(n)
        if m and m.group("idx") in ("00", "01", "02", "03", "04", "05", "06"):
            fam["uPl_hero"].append(n)
            idx = m.group("idx")
            hero_parts[idx][m.group("part") or "Body"].add(n)
            hero_costumes[idx].add(m.group("rest"))
        elif m and m.group("idx") == "07":
            fam["uPl_helper"].append(n)
        elif TEX_ARC.match(n):
            fam["uPlTex"].append(n)
        elif EM_ARC.match(n):
            fam["uEm"].append(n)
        elif WP_ARC.match(n):
            fam["uWp"].append(n)
        elif ST_ARC.match(n):
            fam["uS"].append(n)
        elif n.startswith("uPl"):
            fam["uPl_other"].append(n)
        else:
            fam["other"].append(n)
    return {"hero_parts": {k: {kk: sorted(vv) for kk, vv in v.items()} for k, v in hero_parts.items()},
            "hero_costumes": {k: sorted(v) for k, v in hero_costumes.items()},
            "families": {k: len(v) for k, v in fam.items()}}


def crosscheck(hero_costumes: dict) -> dict:
    """Compare the disc's per-hero costume sets with the reader's CHARACTERS table."""
    table = {"00": "leon", "01": "helena", "02": "chris", "03": "piers", "04": "jake", "05": "sherry", "06": "ada"}
    out = {}
    for idx, name in table.items():
        want = set(CHARACTERS[name]["costumes"])
        got = set(hero_costumes.get(idx, ()))
        out[name] = {"disc": sorted(got), "reader": sorted(want), "missing": sorted(want - got), "extra": sorted(got - want)}
    return out


def sample_arc_headers(xdvd, paths: list) -> list:
    """(magic, version, entry count, size) of sample arcs, read via cheap seeks."""
    out = []
    for p in paths:
        off, size = xdvd.files[p]
        xdvd.f.seek(off)
        h = xdvd.f.read(8)
        magic = h[:4]
        ver, n = struct.unpack(">HH", h[4:8]) if len(h) == 8 else (None, None)
        out.append({"path": p.rsplit("/", 1)[-1], "magic": magic.decode("latin-1"), "version": ver, "entries": n, "size": size})
    return out


def inventory(iso, source_sha256: str | None = None, only_headers: bool = True) -> dict:
    """Full manifest of the owned disc image. `only_headers` keeps the run cheap:
    every file is enumerated and counted, but only sample ARC headers are read."""
    iso = str(iso)
    disc = re6.XDVD(iso)
    try:
        files = disc.files
        xex = disc.read("/default.xex")
        top = Counter(p.split("/", 2)[1] if p.count("/") >= 1 else "(root)" for p in files)
        exts = Counter(p.rsplit(".", 1)[-1].lower() if "." in p else "(none)" for p in files)
        cls = classify_arcs(files)
        all_arcs = [p for p in files if p.endswith(".arc")]
        in_x360 = [p for p in all_arcs if "/arc/X360/" in p]
        samples = sample_arc_headers(disc, [
            "/nativeXenon/arc/X360/uPl00LeonUsa.arc",
            "/nativeXenon/arc/X360/uPlTex0000_0.arc",
            "/nativeXenon/arc/X360/uEm1000.arc",
        ])
        man = {
            "game": "Resident Evil 6",
            "platform": "xbox360",
            "game_id": re6.GAME_ID,
            "title_id": f"{TITLE_ID:#x}",
            "source": {"path": iso, "size": Path(iso).stat().st_size, "sha256": source_sha256},
            "executable": {"path": "/default.xex", "sha256": hashlib.sha256(xex).hexdigest(), **xex_info(xex)},
            "disc": {"partition": disc.part, "files": len(files), "bytes": sum(n for _, n in files.values()),
                     "top_dirs": dict(top), "extensions": dict(exts)},
            "arcs": {"total": len(all_arcs), "in_arc_X360": len(in_x360),
                     "families": cls["families"], "hero_costumes": cls["hero_costumes"],
                     "crosscheck_vs_reader": crosscheck(cls["hero_costumes"]),
                     "samples": samples},
            "launch": {
                "emulator": "Xenia (canary)", "boot": "extracted folder with default.xex at root",
                "base_extraction": "gbox.re6.ensure_base (XDVD extract, resumable)",
                "mod_mechanism": "hard-link copies of the extracted base in ~/gBox_alt/gbox-cache/mods/<game_id>/<mod> with only changed .arc files real; launch_game(mod=...)",
                "revert": "launch without mod, or re6_tool op=revert_all",
                "reader_writer": "gbox.re6 (XDVD/Arc/TEX/LZX), gbox.re6_models (Mod/Mrl, export_character, build_swap)",
            },
        }
        return man
    finally:
        disc.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="RE6 (Xbox 360) inventory manifest")
    ap.add_argument("iso", help="owned disc image (.iso)")
    ap.add_argument("--out", default="re6_inventory.json", help="manifest output path")
    ap.add_argument("--source-sha256", default=None, help="sha256 of the source image, if precomputed")
    args = ap.parse_args(argv)
    man = inventory(args.iso, args.source_sha256)
    Path(args.out).write_text(json.dumps(man, indent=1))
    print(json.dumps({k: man[k] for k in ("game", "title_id", "source", "executable", "disc")}, indent=1))
    print(f"manifest -> {args.out}")


if __name__ == "__main__":
    main()
