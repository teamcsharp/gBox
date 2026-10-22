"""Devil Summoner: Raidou Kuzunoha vs. the Soulless Army (PS2, SLUS_214.31) unlock gate (#2314).

Honest research-pending gate bound to the owned disc's boot executable. No writer is reachable.
"""
GAME_IDS = ("8dc3fd60b783b24e", "7c1b8939e85bbcc5")  # two catalog entries, same disc family
PLATFORM = "ps2"
TITLE = "Devil Summoner: Raidou Kuzunoha vs. the Soulless Army"
BOOT = "SLUS_214.31"
# Extracted from the owned ISO (SYSTEM.CNF: BOOT2 = cdrom0:\SLUS_214.31;1, VER 1.00, NTSC); 3624592 bytes, ELF.
BOOT_SHA256 = "ed92b61353df7f6ce29db5f23624bce0e0d083a707b23e998da5997913776a2b"
CATEGORIES = ("characters", "costumes", "modes", "difficulty/settings unlocks")
REQUIRED_EVIDENCE = ("owned_executable_sha256", "native_unlock_routine", "save_backup_receipt",
                     "rollback_receipt", "runtime_verification")


def matches(game: dict) -> bool:
    return game.get("game_id") in GAME_IDS and game.get("platform") == PLATFORM


def profile_gate() -> dict:
    return {
        "title": TITLE, "platform": PLATFORM, "verified": False, "status": "pending_research",
        "boot": BOOT, "executable_sha256": BOOT_SHA256,
        "reason": ("Owned executable identified and hashed, but no native unlock routine or save "
                   "layout is located for this revision; no verified write targets exist."),
        "requires": list(REQUIRED_EVIDENCE), "categories": list(CATEGORIES),
        "next_step": ("Run a Ghidra session on SLUS_214.31 (language MIPS:LE:32:default; extract the "
                      "boot ELF first) to locate the progress-save routine; back up memory-card saves."),
    }
