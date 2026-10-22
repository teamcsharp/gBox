"""Perfect Dark (Europe) (En,Fr,De,Es,It), N64, game_id 4aef9956d37ab163: unlock research gate (#2208).

Contains NO save offsets, RAM addresses or cheat lines: none are verified for the owned ROM yet.
Registered in gbox.game_unlocks so the dispatch surface reports pending_research and the
pre_launch hook can never reach a writer for this title. A future verified profile must attach
the evidence chain in REQUIRED_EVIDENCE.
"""
from __future__ import annotations

GAME_ID = "4aef9956d37ab163"
PLATFORM = "n64"
TITLE = "Perfect Dark (Europe) (En,Fr,De,Es,It)"

# Candidate identity only: gbox.pd_inventory.KNOWN_BUILDS["pal-final"]. The owned ROM has NOT been
# hashed against it yet (hash_game on an owning worker is the first next step).
CANDIDATE_BUILD = {"romid": "pal-final", "md5": "d9b5cd305d228424891ce38e71bc9213"}

CATEGORIES = ("characters", "hidden_characters", "modes", "levels", "stages", "costumes", "items", "extras")
REQUIRED_EVIDENCE = ("owned_rom_sha256", "native_unlock_routine_or_save_flags", "save_backup_receipt",
                     "rollback_receipt", "live_boot_and_selection_acceptance", "second_launch_verification")
SAFETY = ("No save or memory write exists for this title until the evidence chain is attached.",
          "Never test on the operator PC; only idle authorized i9-NUC/Spark sessions with isolated saves.",
          "Preserve the original ROM and back up the save before any change.",
          "A queued task, inventory or code-only PR is not unlock completion.")


def inventory() -> dict:
    """Per-category status; every entry is 'unknown' until traced in the owned ROM."""
    return {c: {"status": "unknown", "entries": [], "evidence": None} for c in CATEGORIES}


def profile_gate() -> dict:
    return {"game_id": GAME_ID, "title": TITLE, "platform": PLATFORM, "verified": False,
            "status": "pending_research",
            "reason": "No owned-ROM hash proof and no traced unlock routine/save flags for this exact revision.",
            "candidate_build": dict(CANDIDATE_BUILD), "requires": list(REQUIRED_EVIDENCE),
            "categories": list(CATEGORIES), "inventory": inventory(), "safety": list(SAFETY),
            "next_step": "hash_game the owned ROM on an owning worker, compare with candidate md5, then trace "
                         "cheat/solo-completion unlock flags with x64 REA/Ghidra (i9-NUC)."}
