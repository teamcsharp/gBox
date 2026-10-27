"""Static 8-category inventory for Sonic Shuffle (USA, MK-51060 V1.000).

Builds the full category inventory from the unpacked GD-ROM without Ghidra or a worker.
Each category lists what exists on the disc, with evidence from file names, MDL
container counts, and texture-name cross-checks. No unlock state is claimed — every
entry is marked ``lock_state: "unverified"`` until a native save layout is found.

    python -m gbox.sshuffle_static_inventory disc.gdi --out static_inventory.json
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from . import sshuffle_inventory as inv
from .gdrom import GDRom

GAME_ID = inv.GAME_ID
TITLE = inv.TITLE
PLATFORM = "dreamcast"

# The 8 categories defined in the unlock gate.
CATEGORIES = ("characters", "hidden_characters", "modes", "levels", "stages", "costumes", "items", "extras")


def _ext(n: str) -> str:
    return n.rsplit(".", 1)[-1].upper() if "." in n.rsplit("/", 1)[-1] else ""


def static_inventory(gdi: str | Path, hash_tracks: bool = False) -> dict:
    """Build the 8-category static inventory from the GD-ROM.

    Returns a dict keyed by category name, plus ``disc`` metadata and
    ``total_files`` / ``total_directories``.
    """
    g = GDRom(Path(gdi))
    man = inv.inventory(gdi, hash_tracks=hash_tracks)
    files = sorted(g.files.keys())

    # --- 1. characters: the 8 board characters ---
    characters = []
    for r in man["roster"]:
        characters.append({
            "name": r["name"],
            "key": r["key"],
            "file": r["file"],
            "size": r["size"],
            "counts": r["counts"],
            "name_check": r["name_check"],
            "lock_state": "unverified",
        })

    # --- 2. hidden_characters: non-board CHRDATA MDLs ---
    hidden_characters = []
    for n, c in sorted(man["other_characters"].items()):
        hidden_characters.append({
            "file": n,
            "group": c["group"],
            "size": c["size"],
            "counts": c["counts"],
            "texture_names": c["texture_names"][:8],
            "lock_state": "unverified",
        })

    # --- 3. modes: MINIGAME MDLs paired with SUBPROG BINs ---
    minigame_mdl = {f.rsplit("/", 1)[-1].split(".")[0] for f in files if f.startswith("MINIGAME/")}
    subprog_bin = {f.rsplit("/", 1)[-1].split(".")[0] for f in files if f.startswith("SUBPROG/")}
    paired = minigame_mdl & subprog_bin
    modes = []
    for name in sorted(minigame_mdl):
        modes.append({
            "name": name,
            "mdl": f"MINIGAME/{name}.MDL",
            "subprog": f"SUBPROG/{name}.BIN" if name in subprog_bin else None,
            "paired": name in paired,
            "lock_state": "unverified",
        })

    # --- 4. levels: MAPDATA files ---
    levels = []
    for f in files:
        if f.startswith("MAPDATA/"):
            levels.append({
                "file": f,
                "ext": _ext(f),
                "size": g.files[f][1],
                "lock_state": "unverified",
            })

    # --- 5. stages: EVTDATA files (story-event stage data) ---
    stages = []
    for f in files:
        if f.startswith("EVTDATA/"):
            stages.append({
                "file": f,
                "ext": _ext(f),
                "size": g.files[f][1],
                "lock_state": "unverified",
            })

    # --- 6. costumes: CHRDATA PVMs (texture packs that may be costume variants) ---
    costumes = []
    for f in sorted(man["loose_chr_pvm"]):
        costumes.append({
            "file": f,
            "size": man["loose_chr_pvm"][f]["size"],
            "room": man["loose_chr_pvm"][f]["room"],
            "lock_state": "unverified",
        })
    # Plus the PVM entries inside each board character MDL
    for r in man["roster"]:
        costumes.append({
            "file": r["file"],
            "pvm_count": r["counts"].get("pvm", 0),
            "texture_names": r["texture_names"][:8],
            "lock_state": "unverified",
        })

    # --- 7. items: MISCDATA MDLs and PVMs (gameplay items, effects, UI) ---
    items = []
    for f in files:
        if f.startswith("MISCDATA/"):
            items.append({
                "file": f,
                "ext": _ext(f),
                "size": g.files[f][1],
                "lock_state": "unverified",
            })

    # --- 8. extras: MOVIE, SUBPROG (non-minigame), root files, MISCDATA BINs/CSVs/LPCs ---
    extras = []
    for f in files:
        if f.startswith("MOVIE/"):
            extras.append({"file": f, "ext": _ext(f), "size": g.files[f][1], "category": "movie"})
        elif f.startswith("SUBPROG/"):
            base = f.rsplit("/", 1)[-1].split(".")[0]
            if base not in minigame_mdl:
                extras.append({"file": f, "ext": _ext(f), "size": g.files[f][1], "category": "subprog"})
        elif "/" not in f:
            extras.append({"file": f, "ext": _ext(f), "size": g.files[f][1], "category": "root"})

    result = {
        "game_id": GAME_ID,
        "title": TITLE,
        "platform": PLATFORM,
        "product": man["ip"]["product"],
        "version": man["ip"]["version"],
        "first_read_sha256": man["first_read"]["sha256"],
        "total_files": man["files"],
        "total_directories": len(man["directories"]),
        "directories": man["directories"],
        "categories": {
            "characters": {
                "count": len(characters),
                "entries": characters,
                "evidence": "CHRDATA/C00-C07.MDL with PVM texture name cross-check against 1ST_READ player name list",
            },
            "hidden_characters": {
                "count": len(hidden_characters),
                "entries": hidden_characters,
                "evidence": "Non-board CHRDATA MDLs; H*.MDL = high-detail event models, C*.MDL = NPC/boss/enemy",
            },
            "modes": {
                "count": len(modes),
                "paired_count": len(paired),
                "entries": modes,
                "evidence": "MINIGAME/*.MDL paired with SUBPROG/*.BIN",
            },
            "levels": {
                "count": len(levels),
                "entries": levels,
                "evidence": "MAPDATA directory (MDL + PVM files)",
            },
            "stages": {
                "count": len(stages),
                "entries": stages,
                "evidence": "EVTDATA directory (MDL + MDT files)",
            },
            "costumes": {
                "count": len(costumes),
                "entries": costumes,
                "evidence": "CHRDATA/*.PVM loose files + PVM entries inside board character MDLs",
            },
            "items": {
                "count": len(items),
                "entries": items,
                "evidence": "MISCDATA directory (MDL, PVM, MDT, BIN, CSV, FNT, LPC files)",
            },
            "extras": {
                "count": len(extras),
                "entries": extras,
                "evidence": "MOVIE, non-minigame SUBPROG, and root files",
            },
        },
        "lock_state_note": (
            "All lock states are 'unverified' — no save flag loader or character-select "
            "eligibility check has been located yet. Lock state requires Ghidra analysis "
            "of 1ST_READ.BIN."
        ),
    }
    return result


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("gdi")
    ap.add_argument("--no-track-hashes", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    result = static_inventory(a.gdi, hash_tracks=not a.no_track_hashes)
    text = json.dumps(result, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
