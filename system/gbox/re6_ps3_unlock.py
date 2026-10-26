"""RE6 PS3 (Resident Evil 6, BLUS30855, game_id 6fc93ff62e4eb868) unlock research gate.

This module deliberately contains NO memory addresses, save offsets or write
targets. Request #3387's acceptance needs a real owned-executable identity
first: the PS3 EBOOT has been hashed and its RPCS3 launch verified, but no
native unlock routine has been located, no save structure has been mapped,
and no live RAM session has measured the menu state machine or save manager.

What this gate does:
  * pins the exact catalog game (game_id + platform + title_id + app_ver +
    eboot_sha256) so a title string alone can never select an implementation;
  * declares which unlock categories the standing operator request covers;
  * declares the required evidence chain (owned-eboot hash -> native routine
    address -> save/rollback receipt -> live boot/selection acceptance) that a
    future implementation must attach before game_unlocks.profile_for may mark
    this game verified;
  * records the known launch-verified state from mercmode.TITLES so the
    dispatch surface reports honestly.

Registered in gbox.game_unlocks so pre_launch can never call a writer for
this title and profile_for returns a structured pending_research record
instead of a generic unsupported string.
"""
from __future__ import annotations

GAME_ID = "6fc93ff62e4eb868"
TITLE = "Resident Evil 6"
PLATFORM = "ps3"
TITLE_ID = "BLUS30855"
APP_VER = "01.00"
EBOOT_SHA256 = "ddd022477e679cb1125dc327b0e43c5aeb4d8fa84352a7c8ae98ec74271d41ed"

# Categories the standing operator request covers for this title.
CATEGORIES = ("characters", "hidden_characters", "modes", "levels", "stages",
              "costumes", "items", "extras")

# Evidence a future verified profile must attach before promotion.
REQUIRED_EVIDENCE = ("owned_executable_sha256", "native_unlock_routine",
                     "save_structure_map", "save_backup_receipt",
                     "rollback_receipt", "live_boot_and_selection_acceptance",
                     "second_launch_verification")

# Hard safety invariants carried from the standing parent request.
SAFETY = ("No live memory or save writes for this title exist and none may be "
          "attempted without the required evidence chain.",
          "Never test on the operator PC; only idle authorized test workers.",
          "Preserve the original disc/EBOOT and back up any save before changes.",
          "A queued task, artifact report, or code-only PR is not unlock completion.",
          "REA 6's bundled Ghidra provider rejects Linux ARM; route REA binary "
          "sessions to an available x64 worker such as i9-NUC.")


def profile_gate() -> dict:
    """Honest dispatch-surface record: research is pending, nothing is verified."""
    return {
        "game_id": GAME_ID,
        "title": TITLE,
        "platform": PLATFORM,
        "title_id": TITLE_ID,
        "app_ver": APP_VER,
        "eboot_sha256": EBOOT_SHA256,
        "verified": False,
        "status": "pending_research",
        "reason": ("PS3 EBOOT hash pinned and RPCS3 launch verified, but no native "
                   "unlock routine located, no save structure mapped, and no live RAM "
                   "session measured for this exact BLUS30855 revision."),
        "requires": list(REQUIRED_EVIDENCE),
        "categories": list(CATEGORIES),
        "safety": list(SAFETY),
        "next_step": ("Route an x64 worker REA/Ghidra binary session to the hashed "
                      "EBOOT (default_mp.self), locate the save manager and unlock "
                      "routine, map the save structure, then implement a "
                      "revision-guarded unlock overlay with runtime acceptance."),
    }
