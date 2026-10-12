"""Inventory helper for Tetris 4D (Japan) Dreamcast.

The owned source is a CHD under the HyperSpin library.  This module extracts it
(chdman), splits the resulting cue/bin into a GDRom-compatible .gdi + per-track
.bin files, hashes the CHD and 1ST_READ.BIN, and writes a manifest of every file
on the high-density ISO9660 area.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import subprocess
from pathlib import Path

from gbox.gdrom import GDRom

SECTOR_SIZE = 2352


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _msf_to_lba(m: int, s: int, f: int) -> int:
    return m * 4500 + s * 75 + f


def _cue_track_boundaries(cue_text: str, bin_size: int) -> list[tuple[int, int]]:
    """Return [(start_lba, end_lba)] for every track in a cue sheet.

    The end of the last track is inferred from ``bin_size``.
    """
    starts: list[int] = []
    for line in cue_text.splitlines():
        line = line.strip()
        m = re.match(r"INDEX\s+01\s+(\d+):(\d+):(\d+)", line)
        if m:
            starts.append(_msf_to_lba(int(m.group(1)), int(m.group(2)), int(m.group(3))))
    starts.append((bin_size + SECTOR_SIZE - 1) // SECTOR_SIZE)
    return [(starts[i], starts[i + 1]) for i in range(len(starts) - 1)]


def _cue_track_types(cue_text: str) -> list[bool]:
    """Return a list of is_data flags for each TRACK in the cue sheet."""
    flags: list[bool] = []
    for line in cue_text.splitlines():
        line = line.strip()
        m = re.match(r"TRACK\s+\d+\s+(\S+)", line)
        if m:
            flags.append("MODE" in m.group(1).upper())
    return flags


def split_cue_bin_to_gdi(bin_path: Path, cue_path: Path, out_dir: Path, name: str = "disc") -> Path:
    """Convert a cue/bin Dreamcast dump into a .gdi with separate data-track bins."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cue_text = cue_path.read_text()
    bin_bytes = Path(bin_path).read_bytes()
    boundaries = _cue_track_boundaries(cue_text, len(bin_bytes))
    data_flags = _cue_track_types(cue_text)
    data_tracks: list[tuple[int, int, int, Path, bool]] = []  # (track_no, start, end, path, is_data)
    track_no = 1
    for (start, end), is_data in zip(boundaries, data_flags):
        track_bytes = bin_bytes[start * SECTOR_SIZE : end * SECTOR_SIZE]
        track_file = out_dir / f"{name}.track{track_no:02d}.bin"
        track_file.write_bytes(track_bytes)
        data_tracks.append((track_no, start, end, track_file, is_data))
        track_no += 1

    gdi_path = out_dir / f"{name}.gdi"
    with open(gdi_path, "w") as f:
        data_lines = [
            f'{no} {start} 4 {SECTOR_SIZE} "{track_file.name}" 0'
            for no, start, end, track_file, is_data in data_tracks
            if is_data and track_file.stat().st_size > 0
        ]
        f.write(f"{len(data_lines)}\n")
        for line in data_lines:
            f.write(line + "\n")
    return gdi_path


def extract_chd(chd_path: Path, out_dir: Path) -> tuple[Path, Path]:
    """Run chdman extractcd and return (cue, bin)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cue = out_dir / "disc.cue"
    bin_ = out_dir / "disc.bin"
    subprocess.run(
        ["chdman", "extractcd", "-i", str(chd_path), "-o", str(cue), "-ob", str(bin_)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return cue, bin_


def inventory(gdi_path: Path, chd_sha256: str, out_json: Path | None = None) -> dict:
    """Build the inventory manifest for an already-split .gdi."""
    gdi_path = Path(gdi_path)
    disc = GDRom(gdi_path)
    exe = disc.read("1ST_READ.BIN")
    files = [
        {"name": name, "lba": lba, "size": size}
        for name, (lba, size) in sorted(disc.files.items(), key=lambda kv: kv[1][0])
    ]
    counts: dict[str, int] = {}
    for entry in files:
        ext = entry["name"].split(".")[-1].upper() if "." in entry["name"] else "OTHER"
        counts[ext] = counts.get(ext, 0) + 1

    manifest = {
        "game_id": "864538c6473a986e",
        "title": "Tetris 4D (Japan)",
        "platform": "dreamcast",
        "chd_sha256": chd_sha256,
        "disc_bin_sha256": sha256_file(gdi_path.with_name("disc.bin")) if (gdi_path.with_name("disc.bin")).exists() else None,
        "1ST_READ.BIN": {
            "size": len(exe),
            "sha256": hashlib.sha256(exe).hexdigest(),
            "lba": disc.files["1ST_READ.BIN"][0],
        },
        "asset_counts": counts,
        "files": files,
    }
    if out_json:
        Path(out_json).write_text(json.dumps(manifest, indent=2))
    return manifest


def ensure_inventory(chd_path: Path, cache_dir: Path, out_json: Path | None = None) -> dict:
    """High-level helper: extract CHD if needed, split to .gdi, and inventory."""
    cache_dir = Path(cache_dir)
    gdi_path = cache_dir / "disc.gdi"
    if not gdi_path.exists():
        cue, bin_ = extract_chd(chd_path, cache_dir)
        gdi_path = split_cue_bin_to_gdi(bin_, cue, cache_dir, name="disc")
    chd_hash = sha256_file(chd_path)
    return inventory(gdi_path, chd_hash, out_json)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Inventory Tetris 4D (Japan) Dreamcast disc")
    p.add_argument("chd", type=Path, help="path to owned CHD")
    p.add_argument("--cache-dir", type=Path, default=Path.home() / "gbox-cache" / "dc" / "864538c6473a986e")
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()
    manifest = ensure_inventory(args.chd, args.cache_dir, args.out)
    print(json.dumps(manifest["1ST_READ.BIN"], indent=2))
    print("files:", len(manifest["files"]))
    print("asset_counts:", manifest["asset_counts"])
