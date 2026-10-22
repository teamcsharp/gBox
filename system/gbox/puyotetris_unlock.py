"""Revision-guarded Puyo Puyo Tetris (USA, Switch) unlock registration (#2221).

Single registration point consulted by ``gbox.game_unlocks`` for the exact
catalog game ``d306523a3f20c360`` (platform=switch, owned ``.xci`` container).

Rules: catalog presence or a boot screenshot is never unlock evidence; no write
(save, memory, patch) may ship unless bound to an executable SHA-256 actually
opened in REA/Ghidra and listed in ``PROVEN_REVISIONS``; every category entry is
``unlocked`` / ``not_present`` / ``unknown`` and may leave ``unknown`` only with
evidence naming a stored artifact captured on a proven revision. Nothing here
writes, launches, or reads memory.
"""
from __future__ import annotations

import re

GAME_ID = "d306523a3f20c360"
TITLE = "Puyo Puyo Tetris (USA)"
PLATFORM = "switch"
CONTAINER = "Puyo Puyo Tetris (USA).xci"
CATEGORIES = ("characters", "hidden_characters", "modes", "levels",
              "stages", "costumes", "items", "extras")
STATUSES = ("unlocked", "not_present", "unknown")

INVENTORY: dict[str, list[dict]] = {c: [] for c in CATEGORIES}
# sha256 of the main NSO/executable -> {"artifact": id, "source": ...}
PROVEN_REVISIONS: dict[str, dict] = {}

_HEX64 = re.compile(r"[0-9a-f]{64}")


def matches(game: dict) -> bool:
    return game.get("game_id") == GAME_ID and game.get("platform") == PLATFORM


def revision_guard(executable_sha256: str) -> dict:
    """Refuse any build whose hash was not analysed; never guess."""
    digest = str(executable_sha256 or "").lower()
    ok = bool(_HEX64.fullmatch(digest)) and digest in PROVEN_REVISIONS
    return {"ok": ok, "sha256": digest,
            "reason": None if ok else "Executable hash was not analysed in REA/Ghidra; no write is allowed."}


def add_entry(category: str, name: str, status: str, evidence: str | None,
              revision: str | None = None) -> dict:
    """Record an inventory row; leaving 'unknown' requires evidence on a proven revision."""
    if category not in CATEGORIES:
        raise ValueError(f"unknown category {category!r}")
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    if status != "unknown" and not (evidence and revision and revision in PROVEN_REVISIONS):
        raise ValueError("evidence artifact and a proven revision hash are required to leave 'unknown'")
    row = {"name": name, "status": status, "evidence": evidence}
    INVENTORY[category].append(row)
    return row


def profile() -> dict:
    return {
        "game_id": GAME_ID, "title": TITLE, "platform": PLATFORM,
        "verified": False, "complete_unlock_profile": False,
        "proven_revisions": sorted(PROVEN_REVISIONS),
        "inventory": {c: list(INVENTORY[c]) for c in CATEGORIES},
        "unknown_counts": {c: sum(1 for e in INVENTORY[c] if e["status"] == "unknown") for c in CATEGORIES},
        "reason": ("No runtime-verified unlock routine for this exact Switch revision yet; "
                   "the executable must be extracted from the owned XCI and analysed in "
                   "REA/Ghidra on an x64 worker before any save or memory write."),
        "next": ("Extract main NSO from the owned XCI on i9-NUC, hash it, open it via "
                 "rea binary_session, locate the save-flag/menu eligibility checks."),
    }
