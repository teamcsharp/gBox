"""Dead Or Alive ++ (Japan, doapp / Tecmo TPS): revision-guarded unlock-on-load.

Status: research checkpoint. The owned program has been decoded and its fighter
tables, costume tables, mode-menu table and the two unlock notices ("NEW COSTUME
GET!", "EXTRA CONFIG OPEN!") are located in the decoded RAM image. The save or
memory flags behind those notices are not yet located, so no write offset is
trusted yet. This module registers the game in gbox.game_unlocks with the honest
state (static inventory done, flag offsets pending, runtime test pending) and a
single safe hook that never writes until the flag offsets are verified.
"""
from __future__ import annotations

import hashlib
import json

GAME_ID = "a19b4e641b155364"          # Dead Or Alive ++ (Japan), mame set doapp
GAME_ID_KR = "59c55e95af61abbe"       # Dead Or Alive ++ (Korea), mame set doappk
MAME_SET = "doapp"
BIOS_SET = "coh1002m"
PROGRAM_SHA1 = "614873868c77e64076730e3525c672f20363d654"

# Decoded-program evidence (static; gbox.doapp_inventory + gbox.zn_tps_boot)
RAM_SHA256 = "17c897096423b03c2843e5559e216520769c003e62e052845b839e4285669650"
FILE_TABLE_RAM = "0x800515a4"
MODE_MENU_TABLE_RAM = "0x80088a90"    # 19-byte stride: 8 mode strings
NOTICE_COSTUME_RAM = "0x80088aa4"     # "NEW COSTUME GET!"
NOTICE_EXTRA_RAM = "0x80088ab8"       # "EXTRA CONFIG OPEN!"
MODE_VAR_RAM = "0x800962ec"

MODES = ["TOURNAMENT", "TIME ATTACK", "VERSUS", "SURVIVAL", "KUMITE", "TRAINING",
         "TEAM BATTLE", "OPTION"]

FIGHTERS = {
    0: "ZACK", 1: "TINA", 2: "JANN LEE", 4: "HAYABUSA", 5: "KASUMI", 6: "GEN FU",
    8: "BAYMAN", 9: "BASS", 11: "RAIDOU", 12: "LEI FANG", 13: "AYANE",
}

INVENTORY = {
    "characters": {"count": len(FIGHTERS), "status": "unlocked",
                   "evidence": "fighters_from_ram() on the decoded owned program; all 11 roster ids in the per-fighter tables at 0x80087334"},
    "hidden_characters": {"count": 0, "status": "not_present",
                          "evidence": "fighter ids 3/7/10 are unused slots aliasing existing files; no 12th fighter id exists"},
    "costumes": {"count_per_character": 4, "status": "unlocked",
                 "evidence": "19-slot model table at 0x80087334; slots 0-3 distinct, slot 4 zero-size, 5-18 repeat slot 0; hidden-costume file index per fighter recorded"},
    "modes": {"count": len(MODES), "status": "unknown", "evidence": "menu string table at 0x80088a90; per-mode lock flags not yet traced"},
    "levels": {"status": "unknown", "evidence": "level progression not mapped in this revision"},
    "stages": {"status": "unknown", "evidence": "stage file groups exist in FILE_TABLE; stage name/lock mapping not yet extracted"},
    "items": {"count": 0, "status": "not_present", "evidence": "no item-system strings or tables in the decoded program"},
    "extras": {"status": "unknown", "evidence": "'EXTRA CONFIG OPEN!' notice at 0x80088ab8; gating flag not yet located"},
}


def revision_match(program_sha1: str, ram_sha256: str) -> bool:
    """Guard: the owned build must be the exact revision this evidence was taken from."""
    return program_sha1 == PROGRAM_SHA1 and ram_sha256 == RAM_SHA256


def pre_launch(game: dict, ctx, mod: str = "") -> dict:
    """No-op until the unlock flag offsets are located and runtime-verified.

    Never writes save/memory/settings. Returns an honest research state so the
    launcher can report 'unlock pending' instead of pretending to unlock.
    """
    if game.get("game_id") not in (GAME_ID, GAME_ID_KR):
        return {"state": "unsupported", "applied": False,
                "reason": "not a Dead Or Alive ++ catalog game"}
    return {"state": "research_pending", "applied": False,
            "profile": "doapp-jp-static-inventory-v1",
            "reason": "static inventory complete (11 characters, 4+1 costumes each, 8 mode entries, 2 unlock notices); "
                      "save/memory flag offsets behind NEW COSTUME GET / EXTRA CONFIG OPEN not yet located; "
                      "runtime selection test on i9-NUC or Spark with an isolated save still required",
            "inventory": INVENTORY}
