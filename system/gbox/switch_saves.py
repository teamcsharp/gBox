"""Switch save data: locate a title's SAVEDATA, snapshot it, and diff two snapshots.

Unlock work on a Switch title is a save edit (see gbox/re6_switch_unlock.py, which knows RE6's checksum and flag
offset). This module is the part every such edit needs and none of them should re-implement: finding the save
for a title id, taking a byte-exact backup with a hash, and reporting which regions changed between two saves —
the fastest way to see what a game writes when a feature is unlocked.

It never writes to a title's save. Callers do that themselves, from a snapshot.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

TITLE_RE = re.compile(r"^[0-9A-Fa-f]{16}$")

# Citron keeps per-title saves under <data>/citron/nand/user/save/<uid>/<account>/<title id>/
SAVE_GLOBS = (
    "runtime-linux-aarch64/citron-linux/data/citron/nand/user/save/*/*/{title}/SAVEDATA*/*",
    "runtime-linux-aarch64/citron-linux/data/citron/nand/user/save/*/*/{title}/*",
    "citron/nand/user/save/*/*/{title}/SAVEDATA*/*",
    "citron/nand/user/save/*/*/{title}/*",
)
SNAPSHOT_DIR = "switch-saves"


def data_roots() -> list[Path]:
    """Directories that may hold emulator user data (the runtime home, and the operator's gBox data dir)."""
    candidates = [
        Path.home() / "gBox" / "system" / "gbox-data",       # the real runtime data dir on this box
        Path.home() / "gBox" / "system" / "gBox-data",
        Path.home() / "gBox_alt",
    ]
    if os.environ.get("GBOX_DATA"):
        candidates.append(Path(os.environ["GBOX_DATA"]))
    return [p for p in candidates if p.is_dir()]


def save_files(title_id: str, roots: list[Path] | None = None) -> list[Path]:
    """Every existing save file for a title, de-duplicated by resolved path."""
    if not TITLE_RE.match(title_id or ""):
        raise ValueError("title id must be 16 hex characters")
    found, seen = [], set()
    for root in roots or data_roots():
        for pattern in SAVE_GLOBS:
            for path in root.glob(pattern.format(title=title_id.upper())):
                if path.is_file():
                    real = path.resolve()
                    if real not in seen:
                        seen.add(real)
                        found.append(path)
        # a narrower safety net: the nand layout can move between emulator builds
        for path in root.glob(f"**/nand/user/save/*/*/{title_id.upper()}/**/*"):
            if path.is_file():
                real = path.resolve()
                if real not in seen:
                    seen.add(real)
                    found.append(path)
    return sorted(found)


def snapshot_dir() -> Path:
    root = Path(os.environ.get("GBOX_SAVE_SNAPSHOTS") or Path.home() / "gBox_alt" / SNAPSHOT_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


def snapshot(title_id: str, source: Path | None = None, label: str = "") -> dict:
    """Copy one save file (by default the title's largest, which is the real SAVEDATA) to the snapshot store."""
    files = [source] if source else sorted(save_files(title_id), key=lambda p: p.stat().st_size, reverse=True)
    if not files:
        raise FileNotFoundError(f"no SAVEDATA found for {title_id}")
    src = Path(files[0])
    data = src.read_bytes()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", label)[:40]
    out = snapshot_dir() / f"{title_id.upper()}-{stamp}{'-' + safe if safe else ''}{src.suffix or '.sav'}"
    out.write_bytes(data)
    return {"source": str(src), "snapshot": str(out), "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "at": time.time()}


def diff(a: Path, b: Path) -> dict:
    """Byte ranges that differ between two saves (contiguous runs, with sizes)."""
    left, right = Path(a).read_bytes(), Path(b).read_bytes()
    n = min(len(left), len(right))
    runs, start, last = [], None, None
    for i in range(n):
        if left[i] != right[i]:
            if start is None:
                start = i
            last = i
        elif start is not None and i - last > 32:
            runs.append((start, last + 1))
            start = None
    if start is not None:
        runs.append((start, last + 1))
    return {"a": str(a), "b": str(b), "a_bytes": len(left), "b_bytes": len(right),
            "differing_bytes": sum(e - s for s, e in runs), "runs": len(runs),
            "first_runs": [{"offset": s, "length": e - s, "hex_offset": hex(s)} for s, e in runs[:24]],
            "size_mismatch": len(left) != len(right)}


def describe(title_id: str) -> dict:
    """What can be edited on this title right now: the save files and their sizes."""
    files = save_files(title_id)
    return {"title_id": title_id.upper(), "found": len(files),
            "files": [{"path": str(f), "bytes": f.stat().st_size} for f in files],
            "note": "no SAVEDATA for this title" if not files else
                    "back up with snapshot() before any edit; edits are checksum-guarded in most RE titles"}
