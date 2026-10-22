"""NBA 2K2 (USA, Dreamcast, game_id 8b3437c66a598cf3) unlock research gate (request #2185).

Contains NO write targets. It pins the exact owned executable identity proven by
re_executable job bd69cf279fc340e9 (receipt 0cd26c0de57b437c) and the static
findings so far, and keeps the profile unverified until a native unlock routine
or save-flag layout is located and runtime-verified.

Static findings (1ST_READ.BIN.elf, SH4, base/entry 0x8C010000):
  * Only ~450 KB of the 3.3 MB ELF is non-zero (the rest is zero fill); the
    readable strings are Katana library markers only. Game data/logic strings
    (codes, rosters, modes) are therefore not in 1ST_READ.BIN and must come from
    the unpacked disc data files and Ghidra analysis on an x64 worker.
  * No lock check, save flag, or hidden-content entry is identified yet; every
    inventory category is 'unknown'.
"""
from __future__ import annotations

GAME_ID = "8b3437c66a598cf3"
TITLE = "NBA 2K2 (USA)"
PLATFORM = "dreamcast"

EXECUTABLE = {
    "source_file": "1ST_READ.BIN",
    "source_sha256": "0024d74d1bb1fdc1e535d85ea90e5a57ff4e0b86f3c6e67aa95049f59d07cb6f",
    "elf_sha256": "54c99587f026ef2ee1321f7a805b4298b4b77623334465be5a1db542f90ee4e7",
    "processor": "SuperH4:LE:32:default",
    "entry": "0x8C010000",
    "job_id": "bd69cf279fc340e9",
    "receipt_id": "0cd26c0de57b437c",
}

CATEGORIES = ("characters", "hidden_characters", "modes", "levels", "stages",
              "costumes", "items", "extras")

REQUIRED_EVIDENCE = ("owned_executable_sha256", "native_unlock_routine",
                     "save_backup_receipt", "rollback_receipt",
                     "live_boot_and_selection_acceptance", "second_launch_verification")

SAFETY = ("No memory or save writes exist for this title until the evidence chain is complete.",
          "Never test on the operator PC; only idle authorized test workers (i9-NUC / Spark).",
          "Preserve the original CHD/GDI and back up any VMU save before changes.",
          "A queued task, artifact report, or code-only PR is not unlock completion.")


def inventory() -> dict:
    return {c: {"status": "unknown", "entries": [], "evidence": None} for c in CATEGORIES}


def profile_gate() -> dict:
    return {
        "game_id": GAME_ID, "title": TITLE, "platform": PLATFORM,
        "verified": False, "status": "pending_research",
        "reason": ("Executable identity is hashed, but no native unlock routine, save-flag "
                   "layout or lock check has been located for this revision."),
        "executable": dict(EXECUTABLE),
        "requires": list(REQUIRED_EVIDENCE),
        "categories": list(CATEGORIES),
        "inventory": inventory(),
        "safety": list(SAFETY),
        "next_step": ("Unpack the disc data files, then run a REA/Ghidra binary session on an x64 "
                      "worker (i9-NUC) against the pinned ELF to trace the code-entry/roster "
                      "unlock paths; the Spark ARM Ghidra bundle cannot host it."),
    }
