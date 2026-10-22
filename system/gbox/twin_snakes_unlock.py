"""Metal Gear Solid: The Twin Snakes (USA) (Disc 2) unlock research gate (request #2170).

No write targets, save offsets or memory addresses are staged here: no owned
executable (main.dol / shared/mgso.rel) has been hashed and no lock check has
been located for this exact revision. The gate pins identity, declares the
category inventory as 'unknown' (never 'unlocked' without evidence) and lists
the evidence chain required before game_unlocks.profile_for may verify it.
Disc 1 and other revisions need separate proofs and stay unsupported.
"""
from __future__ import annotations

GAME_ID = "bf3675da8955e248"
TITLE = "Metal Gear Solid - The Twin Snakes (USA) (Disc 2)"
PLATFORM = "gamecube"
CATALOG_PLAYABLE = "untested"

CATEGORIES = ("characters", "hidden_characters", "modes", "levels", "stages",
              "costumes", "items", "extras")

REQUIRED_EVIDENCE = ("owned_executable_sha256", "native_lock_check_routine",
                     "save_backup_receipt", "rollback_receipt",
                     "live_boot_and_selection_acceptance", "second_launch_verification")

SAFETY = ("No save or memory writes exist for this title; none may be attempted without the evidence chain.",
          "Never test on the operator PC; only idle authorized test workers (i9-NUC/Spark, 2% audio).",
          "Preserve the original disc image and back up the memory-card save first.",
          "A queued task, roster listing or code-only PR is not unlock completion.")

# Static roster evidence (gbox.twin_snakes.CAST) proves models exist, NOT lock state.
INVENTORY = {c: {"state": "unknown", "entries": [], "evidence": None} for c in CATEGORIES}


def inventory() -> dict:
    return {c: dict(v, entries=list(v["entries"])) for c, v in INVENTORY.items()}


def profile_gate() -> dict:
    return {
        "game_id": GAME_ID, "title": TITLE, "platform": PLATFORM,
        "verified": False, "status": "pending_research",
        "reason": ("No executable-hash-bound owned-copy proof and no lock-check routine located "
                   "for this exact Twin Snakes Disc 2 revision; no verified write targets exist."),
        "requires": list(REQUIRED_EVIDENCE),
        "categories": list(CATEGORIES),
        "inventory": inventory(),
        "safety": list(SAFETY),
        "next_step": ("job_hash_game for this game_id on i9-NUC, extract main.dol/mgso.rel, open an x64 "
                      "REA/Ghidra binary_session (Spark ARM is rejected by REA 6) and trace unlock/save flags."),
    }
