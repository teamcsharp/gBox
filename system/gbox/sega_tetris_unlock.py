"""Revision-guarded Sega Tetris arcade unlock profile: REA evidence inventory.

This module records what static analysis has and has not proved for the exact
owned arcade ROM set ``game_id=0a2f3e9ce734229c`` (Sega Tetris,
platform=arcade). It is the single registration point consulted by
``gbox.game_unlocks`` for this title.

Hard rules encoded here (from the standing operator request):

* Catalog presence, a cheat database, or a boot screenshot is never unlock
  evidence. ``verified`` stays False until a runtime acceptance run proves
  each category by actually selecting and playing it.
* An unlock routine may only ship bound to an executable SHA-256 that was
  actually opened in REA/Ghidra (``executable_sha256`` below). A profile whose
  revision hash is unrecorded must not write memory or saves.
* Categories are reported per-entry as ``unlocked`` / ``not_present`` /
  ``unknown``. Anything not yet proven by this revision's disassembly is
  ``unknown`` -- never silently omitted and never guessed.

No writes, launches, or memory access happen here.
"""
from __future__ import annotations

GAME_ID = "0a2f3e9ce734229c"
TITLE = "Sega Tetris"
PLATFORM = "arcade"

CATEGORIES = ("modes", "levels", "stages", "characters", "hidden_characters", "costumes", "items", "extras")

# Entries proven by evidence in a prior run must list the artifact id and the
# exact revision hash they were gathered on. Inventory rows carry:
#   {"name": <exact in-game entry name>, "status": one of
#    "unlocked"|"not_present"|"unknown", "evidence": <artifact id or None>}
# An entry may only leave "unknown" when evidence names a stored REA/Ghidra
# artifact (or runtime receipt) captured on PROVEN_REVISION.
INVENTORY: dict[str, list[dict]] = {category: [] for category in CATEGORIES}

# Executable revisions actually opened in REA/Ghidra with a recorded SHA-256.
# Empty until a binary_session verification names the owned Sega Tetris Korea
# executable and its digest.
PROVEN_REVISIONS: dict[str, dict] = {}


def profile() -> dict:
    """Static profile record for the catalog game; verified is False by design."""
    proven = sorted(PROVEN_REVISIONS)
    return {
        "game_id": GAME_ID, "title": TITLE, "platform": PLATFORM,
        "verified": False, "complete_unlock_profile": False,
        "proven_revisions": proven,
        "inventory": {c: list(INVENTORY[c]) for c in CATEGORIES},
        "unknown_counts": {c: sum(1 for e in INVENTORY[c]
                                  if e["status"] == "unknown")
                           for c in CATEGORIES},
        "reason": ("No runtime-verified unlock routine for this exact arcade "
                   "revision yet; static REA/Ghidra evidence is required "
                   "before any memory or save write."),
    }


def validate_write(writes: list[tuple], revision: str) -> list[str]:
    """Guard a candidate memory-write plan against the recorded revision proof.

    Returns a list of blocking reasons (empty = admissible). This is the gate
    any future arcade writer must pass; it refuses writes when the running
    revision has never been inspected, when an address falls outside the
    documented inspectable window, or when a write is wider than 4 bytes.
    """
    errors: list[str] = []
    if revision not in PROVEN_REVISIONS:
        errors.append(f"revision {revision!r} has no REA/Ghidra binary_session proof")
    for op, address, data in writes:
        if op != "w":
            errors.append(f"unsupported operation {op!r}")
        if not isinstance(data, (bytes, bytearray)) or not 1 <= len(data) <= 4:
            errors.append(f"write at 0x{address:x} must be 1..4 bytes")
        if not 0 <= address < 0x0800_0000:
            errors.append(f"address 0x{address:x} outside documented arcade RAM window")
    return errors


def accept_revision(revision: str, artifact: str, categories: dict[str, list[dict]]) -> dict:
    """Record REA/Ghidra evidence for a revision (static analysis only).

    Raises on malformed input. Does NOT mark the profile verified: verification
    requires the runtime acceptance checklist below to complete.
    """
    if len(revision) != 64 or any(ch not in "0123456789abcdef" for ch in revision):
        raise ValueError("revision must be a lowercase sha256 hex digest")
    if not artifact.strip():
        raise ValueError("artifact id required")
    for category, rows in categories.items():
        if category not in INVENTORY:
            raise ValueError(f"unknown category {category!r}")
        for row in rows:
            if row["status"] not in ("unlocked", "not_present", "unknown"):
                raise ValueError(f"bad status for {row.get('name')!r}")
            if row["status"] != "unknown" and not str(row.get("evidence") or "").strip():
                raise ValueError(f"{category}:{row.get('name')} needs evidence to leave unknown")
        known = {r["name"] for r in INVENTORY[category]}
        for row in rows:
            if row["name"] in known:
                INVENTORY[category] = [r for r in INVENTORY[category]
                                       if r["name"] != row["name"]]
        INVENTORY[category].extend(rows)
        INVENTORY[category].sort(key=lambda r: r["name"])
    PROVEN_REVISIONS[revision] = {"artifact": artifact, "categories": sorted(categories)}
    return {"recorded": revision, "categories": sorted(categories),
            "verified": False,
            "next": "runtime acceptance: fresh boot, play each unlocked entry, "
                    "second launch, rollback"}
