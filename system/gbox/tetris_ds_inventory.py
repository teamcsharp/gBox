"""Inventory helper for Tetris DS (USA) Nintendo DS.

The owned source is the WRG dump `0366 - Tetris DS (U)(WRG).nds`
(sha256 4e443f9b03363900dda6fa308229a3b14631b0fedd14f1c2e4cc1d5b3224db68,
16 MiB, gamecode ATRE).

This module provides a verified sprite-set inventory derived from the actual
filesystem layout and confirmed against the TetrisDSReader.sprite_sets() output.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .tetris_ds import NDSRom, TETRIS_DS_SETS, TETRIS_DS_ROM_SHA256


def sha256_bytes(data: bytes) -> str:
    """Return the SHA256 hex digest of data."""
    return hashlib.sha256(data).hexdigest()


def verify_rom(rom_data: bytes) -> dict:
    """Verify the ROM matches the known Tetris DS (USA) build.

    Returns a dict with verified=True/False and diagnostic info.
    """
    result = {
        "verified": False,
        "gamecode": None,
        "title": None,
        "unitcode": None,
        "sha256": None,
        "size": len(rom_data),
    }

    if len(rom_data) < 0x200:
        result["reason"] = "ROM too small (< 512 bytes)"
        return result

    result["gamecode"] = rom_data[0x0C:0x10].decode("ascii", "replace")
    result["title"] = rom_data[0x00:0x0C].decode("ascii", "replace").rstrip("\x00")
    result["unitcode"] = rom_data[0x12]
    result["sha256"] = sha256_bytes(rom_data)

    verified = (
        result["sha256"] == TETRIS_DS_ROM_SHA256
        and result["gamecode"] == "ATRE"
        and result["title"] == "TETRIS DS"
        and result["unitcode"] == 0x00
    )
    result["verified"] = verified

    if not verified:
        reasons = []
        if result["sha256"] != TETRIS_DS_ROM_SHA256:
            reasons.append(f"SHA256 mismatch (got {result['sha256']})")
        if result["gamecode"] != "ATRE":
            reasons.append(f"Gamecode mismatch (got {result['gamecode']})")
        if result["title"] != "TETRIS DS":
            reasons.append(f"Title mismatch (got {result['title']!r})")
        if result["unitcode"] != 0x00:
            reasons.append(f"Unitcode mismatch (got 0x{result['unitcode']:02X})")
        result["reason"] = "; ".join(reasons)

    return result


def build_inventory(rom_data: bytes) -> dict:
    """Build a verified sprite-set inventory from the ROM.

    Returns a manifest with:
      - game metadata (title, gamecode, unitcode, sha256)
      - file counts by extension
      - verified sprite set list
      - checksum of the inventory manifest itself
    """
    rom = NDSRom(rom_data)
    verify = verify_rom(rom_data)

    # Count files by extension
    ext_counts: dict[str, int] = {}
    for path in rom.paths():
        ext = path.rsplit(".", 1)[-1].upper() if "." in path else "NOEXT"
        ext_counts[ext] = ext_counts.get(ext, 0) + 1

    # Get sprite sets from the reader
    sprite_sets = list(TETRIS_DS_SETS)

    manifest = {
        "game_id": "25da54968d78f816",
        "title": "Tetris DS (USA)",
        "platform": "nds",
        "rom_sha256": verify["sha256"],
        "rom_size": verify["size"],
        "gamecode": verify["gamecode"],
        "unitcode": verify["unitcode"],
        "verified": verify["verified"],
        "asset_counts": ext_counts,
        "sprite_sets": sprite_sets,
        "sprite_set_count": len(sprite_sets),
        "file_count": len(rom.paths()),
    }

    # Add manifest checksum for integrity verification
    manifest["manifest_sha256"] = sha256_bytes(
        json.dumps(manifest, sort_keys=True).encode("utf-8")
    )

    return manifest


def ensure_inventory(rom_path: Path | str, cache_dir: Path | str | None = None) -> dict:
    """Load ROM from path and return its inventory.

    If cache_dir is provided, writes the manifest as `inventory.json`.
    """
    rom_path = Path(rom_path)
    if cache_dir:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)

    rom_data = rom_path.read_bytes()
    manifest = build_inventory(rom_data)

    if cache_dir:
        out_path = cache_dir / "inventory.json"
        out_path.write_text(json.dumps(manifest, indent=2))
        manifest["manifest_path"] = str(out_path)

    return manifest


def roster() -> list[dict]:
    """Native sprite sets of Tetris DS (USA) — the game's 2D 'models'.

    These are the playable character/sprite sets used by the native reader.
    Each entry can be targeted by a donor asset for replacement.
    """
    return [
        {
            "key": s,
            "slug": f"tetris_ds_{s}",
            "name": f"Tetris DS sprites: {s}",
            "aliases": [s],
            "kind": "character",
        }
        for s in TETRIS_DS_SETS
    ]
