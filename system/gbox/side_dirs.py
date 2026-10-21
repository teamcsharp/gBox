"""The Spark's gBox side folders - the hot game cache, the Hermes repo with its task and review worktrees, the deploy
clone (gBox-src) and the agents' scratch - live in ~/gBox_alt since 2026-10-20 (operator: "put those in a G Box
underscore alt folder that will basically manage any auxiliary files ... we don't want to just be dumping all of it in
root"). The names inside are the old ones, so code that finds a sibling of the Hermes repo (repo.parent /
'gbox-hermes-tasks') follows it. Paths written for the home root (gbox.toml, GBOX_HERMES_REPO, older records) still
resolve, and until a folder has moved its old place is used. Standard library only: Hermes's cron scripts import it.
"""
from __future__ import annotations

from pathlib import Path

SIDE = "gBox_alt"
SPARK_SHARE = "//10.89.1.246/ehm_eckx"          # the Spark's home as the Windows PCs see it


def side_dir(name: str, home: Path | None = None) -> Path:
    """~/gBox_alt/<name>, or ~/<name> while that has not moved."""
    home = Path.home() if home is None else Path(home)
    new, old = home / SIDE / name, home / name
    return old if old.exists() and not new.exists() else new


def moved(p, home: Path | None = None) -> Path:
    """A path inside a side folder, wherever that folder is now: ~/<name>/... and ~/gBox_alt/<name>/... name the same
    place. A path that exists, or that is outside the home folder, is returned as it is."""
    p = Path(p)
    home = Path.home() if home is None else Path(home)
    if p.exists():
        return p
    try:
        parts = p.relative_to(home).parts
    except ValueError:
        return p
    if not parts:
        return p
    other = home.joinpath(*parts[1:]) if parts[0] == SIDE else home / SIDE / Path(*parts)
    return other if other.exists() else p


def spark_share(name: str) -> Path:
    """<name> in the Spark's home through the share (the Windows PCs), in gBox_alt once it has moved."""
    new = Path(f"{SPARK_SHARE}/{SIDE}/{name}")
    return new if new.is_dir() else Path(f"{SPARK_SHARE}/{name}")
