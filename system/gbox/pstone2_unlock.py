"""Honest unlock-on-load gate for Power Stone 2 (USA), Dreamcast (game 690a402443c15668).

Research is pending: the owned 1ST_READ.BIN is hash-bound and a first static pass is recorded,
but no native save/progress routine is located, so no writer is reachable from the Play path.
"""
from __future__ import annotations

GAME_ID = "690a402443c15668"
PLATFORM = "dreamcast"
TITLE = "Power Stone 2 (USA)"
FIRST_READ_SHA256 = "a3dcd09a96045839dbbc35697eb4336e4eba79b52203a46bb2f8ee9a4ba2eed8"
ELF_SHA256 = "279eb69edd9b4075c1d75a46ee721026ec2d406e5c062cbf3a2c2e77ccf5287f"
CATEGORIES = ("characters", "hidden_characters", "modes", "levels", "stages", "costumes", "items", "extras")
REQUIRED_EVIDENCE = ("owned_executable_sha256", "save_progress_flags", "native_unlock_routine",
                     "category_inventory", "runtime_verification")

# Static findings (strings/file tables only; none is a verified write target).
FINDINGS = {
    "connect_slots": "18 PLxy_CONNECT.BIN files (PL00..PLF0 plus PL12/PL72 alt costumes) in the 1ST_READ name table",
    "hidden_content_names": ["MERU_*P.BIN (Mel)", "PAPA_*P.BIN (Papa)"],
    "arcade_test_menu": ("1ST_READ carries an arcade-style test menu with '1. HIDDEN CHAR "
                         "(NONE / PRIDE OK / PRIDE & MERU OK)', '2. HIDDEN STAGE', '3. EXTRA OPTION', "
                         "'4. RELEASE ITEM', '5. GAME MODE (ARCADE / DC ORIGINAL / ADVENTURE)'; "
                         "no literal-pool or pointer reference to these strings was found, so it may be dead code"),
    "not_found": "VMU save layout and flag addresses are unresolved; native decompiler is unavailable on Linux ARM",
}


def profile_gate() -> dict:
    return {
        "game_id": GAME_ID, "title": TITLE, "platform": PLATFORM,
        "verified": False, "status": "pending_research",
        "reason": ("Executable is hash-bound and statically surveyed, but no save/progress routine "
                   "or write target is verified for this revision."),
        "requires": list(REQUIRED_EVIDENCE), "categories": list(CATEGORIES),
        "evidence": {"first_read_sha256": FIRST_READ_SHA256, "elf_sha256": ELF_SHA256, "findings": FINDINGS},
        "next_step": ("Load the ELF (SuperH4:LE:32:default, base 0x8C010000) on an x64 worker Ghidra, "
                      "locate the VMU save read/write and unlock flag tables, then runtime-verify on an idle "
                      "test worker with an isolated save."),
    }
