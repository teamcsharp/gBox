"""DOAX2 (Dead or Alive Xtreme 2, Xbox 360, game_id e50f98c6e603dab4) unlock research gate.

This module deliberately contains NO memory addresses, save offsets or write
targets. Request #2089's acceptance needs a real owned-executable identity
first: no owned DOAX2 executable has been hashed and no native unlock routine
has been located for this exact revision (the request history's "complete
inventory" is inherited artifact evidence, not an executable-hash-bound proof).

What this gate does:
  * pins the exact catalog game (game_id + platform) so a title string alone
    can never select an implementation (unknown revisions stay pending);
  * declares which unlock categories the standing operator request covers;
  * declares the required evidence chain (owned-exe hash -> native routine
    address -> save/rollback receipt -> live boot/selection acceptance) that a
    future implementation must attach before game_unlocks.profile_for may mark
    this game verified.

Registered in gbox.game_unlocks so the dispatch surface reports honestly
(pending_research / no_verified_profile) instead of a generic unsupported
string, and so pre_launch can never call a writer for this title.
"""
from __future__ import annotations

GAME_ID = "e50f98c6e603dab4"
TITLE = "Dead Or Alive - Xtreme 2"
PLATFORM = "xbox360"

# Catalog state observed 2026-10-19 via list_games: playable="untested".
CATALOG_PLAYABLE = "untested"

# Categories the standing operator request covers for this title.
CATEGORIES = ("characters", "beach volleyball modes", "volleyball costumes",
              "beach volleyball costumes", "festival/VS events", "minigames",
              "photo/extra modes", "difficulty/settings unlocks")

# Evidence a future verified profile must attach before promotion.
REQUIRED_EVIDENCE = ("owned_executable_sha256", "native_unlock_routine",
                     "save_backup_receipt", "rollback_receipt",
                     "live_boot_and_selection_acceptance", "second_launch_verification")

# Hard safety invariants carried from the previous runs' conclusions.
SAFETY = ("No live memory or save writes for this title exist and none may be "
          "attempted without the required evidence chain.",
          "Never test on the operator PC; only idle authorized test workers.",
          "Preserve the original ISO/XEX and back up any save before changes.",
          "A queued task, artifact report, or code-only PR is not unlock completion.")


def profile_gate() -> dict:
    """Honest dispatch-surface record: research is pending, nothing is verified."""
    return {
        "game_id": GAME_ID,
        "title": TITLE,
        "platform": PLATFORM,
        "verified": False,
        "status": "pending_research",
        "reason": ("No executable-hash-bound owned-copy proof and no native unlock routine "
                   "located for this exact DOAX2 revision; no verified write targets exist."),
        "requires": list(REQUIRED_EVIDENCE),
        "categories": list(CATEGORIES),
        "safety": list(SAFETY),
        "next_step": ("Hash the owned DOAX2 executable (job_hash_game on the owning worker), "
                      "then route an x64 worker REA/Ghidra binary session to locate the "
                      "progress-save routine; artifact evidence alone never promotes this gate."),
    }
