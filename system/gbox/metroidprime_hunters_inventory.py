"""Metroid Prime - Hunters (USA) (NDS, catalog game_id fe580e2ad4ec0052) -- owned-ROM inventory.

Owned source (HyperSpin library "hyperspin", collection "Nintendo DS"):

    collections/Nintendo DS/roms/Metroid Prime - Hunters (USA).7z            sha256 3b61dfe8...
    0367 - Metroid Prime Hunters (U)(WRG).nds  (64 MiB, the archive's only member)  sha256 7d0a98ff...

Both hashes were measured by streaming the bytes of the files on disk; neither is a reference value
copied from a database.  The catalog's source_path is the .7z, but a bare .7z is not a fingerprintable
cartridge -- that is why the ticket's first fingerprint was metadata-only.  The fingerprintable object
is the extracted .nds.

The image is a plain Nintendo DS cartridge: a NitroFS file system with 2761 paths and NO NARC
archives.  The game's own containers are the 104 "archives/*.arc" files (a proprietary archive, not a
NARC) and the model/animation payloads are "*.bin" pairs:

    models/<Name>_Model.bin              +  models/<Name>_Anim.bin
    characterselect/<who>_Model.bin      +  characterselect/<who>[_<state>]_Anim.bin

Every count below is a census of the cartridge's own file table (counted assets), never a filename
guess; decoding the payload containers is the analysis stage.

One native target asset is identified here: the selectable Samus model
"characterselect/samus_Model.bin" with its animation partners -- the slot a donor has to replace
for a native character swap.

    python -m gbox.metroidprime_hunters_inventory ROM.nds|ROM.7z --out manifest.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from .formats import nitro

GAME_IDS = {"fe580e2ad4ec0052": "Metroid Prime - Hunters (USA)"}
PLATFORM = "nds"
ROM_SHA256 = "7d0a98ff98e1b7c985d1f3d89b01730af1b2115061a4dfea847612d217a8b855"   # measured on the owned .nds
ARCHIVE_SHA256 = "3b61dfe85b1f6cc60dc507b2e27323c890a2df9dd522ee4eff82d58bf7af3672"  # measured on the owned .7z
ROM_SIZE = 67108864
TARGET_CHARACTER = "samus"


def sha256_file(path) -> str:
    """Stream the file's bytes; no reference hash is ever copied."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _seven_zip() -> str:
    exe = next((x for x in ("7z", "7zz", "7za") if shutil.which(x)), None)
    if not exe:
        raise RuntimeError("reading a .7z ROM needs the 7z CLI (or py7zr)")
    return exe


def extract_rom(archive: Path, dest: Path) -> Path:
    """The catalog's .7z -> the extracted .nds (the only member of this archive)."""
    exe = _seven_zip()
    subprocess.run([exe, "e", "-y", f"-o{dest}", str(archive)], check=True, capture_output=True)
    roms = sorted(dest.glob("*.nds"))
    if not roms:
        raise RuntimeError(f"{archive.name}: no .nds inside")
    return roms[0]


def open_rom(path):
    """(cartridge path, NitroROM) for an .nds or for the catalog's .7z."""
    p = Path(path)
    if p.suffix.lower() == ".7z":
        tmp = Path(tempfile.mkdtemp(prefix="mph_rom_"))
        rom_path = extract_rom(p, tmp)
    elif p.suffix.lower() == ".nds":
        rom_path = p
    else:
        raise ValueError(f"{p.name}: expected a .nds or the catalog's .7z")
    return rom_path, nitro.NitroROM(rom_path.read_bytes())


def inventory(rom) -> dict:
    """The cartridge's own file table: counted assets, containers and directories."""
    paths = rom.paths()
    ext = Counter(os.path.splitext(p)[1].lower() or "<none>" for p in paths)
    top = Counter(p.split("/")[0] for p in paths)
    return {
        "path_count": len(paths),
        "extensions": dict(sorted(ext.items(), key=lambda kv: (-kv[1], kv[0]))),
        "top_level_dirs": dict(sorted(top.items(), key=lambda kv: (-kv[1], kv[0]))),
        "model_files": sorted(p for p in paths if p.endswith("_Model.bin")),
        "animation_files": sorted(p for p in paths if p.endswith("_Anim.bin")),
        "archives": sorted(p for p in paths if p.endswith(".arc")),
        "narc_files": sorted(p for p in paths if rom.raw(p)[:4] == b"NARC"),
        "character_select_models": sorted(
            p for p in paths if p.startswith("characterselect/") and p.endswith("_Model.bin")
        ),
    }


def identify_target(rom, inv) -> dict:
    """The one identified native target asset: the selectable character's model slot."""
    cands = [p for p in inv["character_select_models"]
             if Path(p).stem[:-len("_Model")].lower() == TARGET_CHARACTER]
    if not cands:
        raise ValueError(f"no {TARGET_CHARACTER!r} model under characterselect/")
    model_path = cands[0]
    stem = Path(model_path).stem[: -len("_Model")]
    anims = sorted(p for p in rom.paths()
                   if p.startswith("characterselect/")
                   and Path(p).name.startswith(stem + "_")
                   and p.endswith("_Anim.bin"))
    gameplay = sorted(p for p in rom.paths()
                      if p.startswith("models/Samus") and p.endswith(("_Model.bin", "_Tex.bin", "_Anim.bin"))
                      and "Gun" not in p and "Ship" not in p)
    archives = sorted(p for p in rom.paths() if p.startswith("archives/") and "samus" in p.lower())
    blob = rom.raw(model_path)
    return {
        "character": stem,
        "model_path": model_path,
        "model_size": len(blob),
        "model_sha256": hashlib.sha256(blob).hexdigest(),
        "animation_paths": anims,
        "gameplay_samus_files": gameplay,      # in-match model/texture/anim payloads (analysis target)
        "samus_archives": archives,
        "note": "selectable-character model slot; a native donor swap has to replace this payload",
    }


def manifest(rom_path: Path, rom, inv: dict, target: dict) -> dict:
    return {
        "game_id": next(iter(GAME_IDS)),
        "title": GAME_IDS[next(iter(GAME_IDS))],
        "platform": PLATFORM,
        "source": {"path": str(rom_path), "sha256": sha256_file(rom_path),
                   "size": rom_path.stat().st_size},
        "cartridge": {"title": rom.title, "gamecode": rom.gamecode, "size": len(rom.data),
                      "arm9_size": rom.arm9_size, "overlay_count": len(rom.overlays9())},
        "counts": {"paths": inv["path_count"], "models": len(inv["model_files"]),
                   "animations": len(inv["animation_files"]), "archives": len(inv["archives"]),
                   "narcs": len(inv["narc_files"])},
        "extensions": inv["extensions"],
        "top_level_dirs": inv["top_level_dirs"],
        "target_slot": target,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Metroid Prime Hunters (NDS) owned-ROM inventory")
    ap.add_argument("rom", help="owned .nds or the catalog's .7z")
    ap.add_argument("--out", default="", help="write the manifest JSON here")
    args = ap.parse_args(argv)
    rom_path, rom = open_rom(args.rom)
    inv = inventory(rom)
    target = identify_target(rom, inv)
    text = json.dumps(manifest(rom_path, rom, inv, target), indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
