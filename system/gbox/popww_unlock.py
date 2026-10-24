"""Prince of Persia - Warrior Within (GameCube) unlock research: exact-revision inventory.

Request #2218 (efccab3a17e34b3f): unlock all content of the owned
Prince of Persia - Warrior Within (USA) on load, catalog
game_id=9fc973656e2fd05d, platform=gamecube.

This module binds the research to ONE owned revision (disc G2OE41) and
records a complete category inventory with the evidence actually read out
of that build. It contains NO memory or save write targets: the native
unlock flag and its address are not yet proven for this revision, so
gbox.game_unlocks.profile_for reports pending_research and pre_launch can
never reach a writer for this title.

Evidence was read from the owned disc, not from a title string:
  * ISO9660 volume id of the owned image -> G2OE41 (PoP:WW)
  * 244 ISO9660 entries; main.dol at file offset 0x20300
  * the real code and strings live in the Ubisoft BIG archive prince.bf
    (magic BIG, 343834624 bytes at file offset 0x1a237988), not in the
    5070016-byte main.dol stub
  * localized option/menu strings and 2490 archive member names were
    scanned for unlock surfaces
"""
from __future__ import annotations

GAME_ID = "9fc973656e2fd05d"
TITLE = "Prince of Persia - Warrior Within (USA)"
PLATFORM = "gamecube"

# --- pinned owned revision (every value observed on the owned disc) ---
DISC_ID = "G2OE41"
DISC_VOLUME_TITLE = "PoP:WW"
OWNED_SOURCE = ("/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/"
                "Prince of Persia - Warrior Within (USA).gcz")
OWNED_SOURCE_SIZE = 1303782157
OWNED_SOURCE_SHA256 = "9af6ae530e5f952b7da1f3572cf4d6be8e87001d371e9e157bdd673ae5a2966a"

MAIN_DOL_FILE_OFFSET = 0x20300
MAIN_DOL_SIZE = 5070016
MAIN_DOL_SHA256 = "a41c8dac78fc9350061bad8f658e275fe8a0de2cd9e8adc5647fb9b895ab075e"

PRINCE_BF_FILE_OFFSET = 0x1A237988
PRINCE_BF_SIZE = 343834624
PRINCE_BF_SHA256 = "23a5ee37fafac8fd452bd602167a9a145ef6f165631fb7a436ec51aeed271ce5"

ISO_ENTRY_COUNT = 244

CATEGORIES = ("characters", "hidden_characters", "modes", "levels", "stages",
              "costumes", "items", "extras")

REQUIRED_EVIDENCE = ("native_unlock_flag_and_address",
                     "save_backup_receipt",
                     "rollback_receipt",
                     "live_boot_and_selection_acceptance",
                     "second_launch_verification")

SAFETY = ("No memory or save write targets exist for this title and none may be "
          "attempted before the required evidence chain is attached.",
          "Never test on the operator PC; only idle authorized test workers, 2% audio.",
          "Preserve the original .gcz and back up any save before changes.",
          "A report, an inventory or a code-only PR is not unlock completion.")


def inventory() -> dict:
    """Category inventory read out of the pinned revision.

    state is one of unlocked / not_present / unknown and describes only what
    this build's own bytes prove. Nothing here is a runtime result.
    """
    return {
        "characters": [
            {"name": "Prince", "state": "unknown",
             "evidence": "Avatar name in the owned build option strings (prince.bf+0x258d288); "
                         "default avatar, not an unlock-gated entry, so no unlock state is claimed."},
            {"name": "Kaileena (Dark Prince)", "state": "unknown",
             "evidence": "105 occurrences of Kaileena in prince.bf (first prince.bf+0x258eea3) -> "
                         "the character content is present in this revision; the flag that gates "
                         "it is not yet resolved."},
        ],
        "hidden_characters": [
            {"name": "Dark Prince (Kaileena)", "state": "unknown",
             "evidence": "Unlock wording in the same locale block as Kaileena "
                         "(prince.bf+0x258d32f, text: w unlocked); no binding from that string to "
                         "a progress flag is proven yet."},
        ],
        "modes": [
            {"name": "Duel", "state": "unknown",
             "evidence": "1 occurrence of Duel (prince.bf+0x282687e); menu eligibility and the flag "
                         "behind it are not traced."},
        ],
        "levels": [
            {"name": "World", "state": "unknown",
             "evidence": "26 occurrences of World (first prince.bf+0x2631010)."},
            {"name": "Level", "state": "unknown",
             "evidence": "4 occurrences of Level (first prince.bf+0x2fb301d)."},
        ],
        "stages": [
            {"name": "Stage set of this revision", "state": "unknown",
             "evidence": "244 ISO9660 entries: ENV01-ENV30, CHAR01-CHAR20, SWORD01-SWORD18, "
                         "DAGGER01-DAGGER06, MACE01-MACE08, ZARBI01-ZARBI06, ILLU01-ILLU15, "
                         "AXE01-AXE14, 13 NavMap*.bik, 9 MENU/*.MGM and 3 *.tpl."},
        ],
        "costumes": [
            {"name": None, "state": "not_present",
             "evidence": "No costume, skin or alternate-outfit string and no costume container "
                         "member exists in this revision."},
        ],
        "items": [
            {"name": "Dagger", "state": "unknown",
             "evidence": "2 occurrences of Dagger (prince.bf+0x327d5c9, prince.bf+0x34e8b25)."},
            {"name": "Sword set", "state": "unknown",
             "evidence": "18 SWORD*.bik members of the owned image."},
        ],
        "extras": [
            {"name": "Secret", "state": "unknown",
             "evidence": "3 occurrences of Secret (prince.bf+0x1d8778, +0x1e1730, +0x31dacae)."},
            {"name": "Cinematics", "state": "unknown",
             "evidence": "12 occurrences of Cine (first prince.bf+0x26337e2) and the CINE*.bik "
                         "members of the owned image."},
        ],
    }


def revision() -> dict:
    """Identity of the single owned revision this profile may ever touch."""
    return {"game_id": GAME_ID, "platform": PLATFORM, "disc_id": DISC_ID,
            "disc_volume_title": DISC_VOLUME_TITLE,
            "owned_source": OWNED_SOURCE, "owned_source_size": OWNED_SOURCE_SIZE,
            "owned_source_sha256": OWNED_SOURCE_SHA256,
            "main_dol_file_offset": MAIN_DOL_FILE_OFFSET, "main_dol_size": MAIN_DOL_SIZE,
            "main_dol_sha256": MAIN_DOL_SHA256,
            "prince_bf_file_offset": PRINCE_BF_FILE_OFFSET, "prince_bf_size": PRINCE_BF_SIZE,
            "prince_bf_sha256": PRINCE_BF_SHA256, "iso_entry_count": ISO_ENTRY_COUNT}


def verify_revision(observed: dict) -> dict:
    """Revision guard: only the pinned owned build may ever be written to.

    observed maps source_sha256 / main_dol_sha256 / prince_bf_sha256 to the
    values read from the file that is about to be used. A mismatch fails.
    """
    expected = {"source_sha256": OWNED_SOURCE_SHA256, "main_dol_sha256": MAIN_DOL_SHA256,
                "prince_bf_sha256": PRINCE_BF_SHA256}
    checks = {}
    for key, want in expected.items():
        got = observed.get(key)
        checks[key] = {"expected": want, "observed": got,
                       "match": isinstance(got, str) and got.lower() == want.lower()}
    return {"revision": DISC_ID + "/" + MAIN_DOL_SHA256[:12],
            "ok": all(c["match"] for c in checks.values()), "checks": checks}


def profile_gate() -> dict:
    """Honest dispatch-surface record: revision bound, inventory attached, no writer."""
    return {
        "game_id": GAME_ID, "title": TITLE, "platform": PLATFORM, "disc_id": DISC_ID,
        "verified": False, "status": "pending_research",
        "reason": ("Exact owned revision bound (disc G2OE41) and the category inventory read out "
                   "of it, but the native unlock flag/address and any save write path are not "
                   "proven for this build, so no verified write target exists."),
        "requires": list(REQUIRED_EVIDENCE),
        "categories": list(CATEGORIES),
        "inventory": inventory(),
        "revision": revision(),
        "save_state": {"native_save_present": False,
                       "reason": ("No G2OE41 memory-card save exists in the owned Dolphin user "
                                  "profile USA Card A directory (it holds only GPOE Sands of Time "
                                  "and other titles saves), so save-overlay acceptance cannot start "
                                  "until the game creates one.")},
        "safety": list(SAFETY),
        "next_step": ("Locate the progress/unlock flag for disc G2OE41 in the pinned main.dol with "
                      "Ghidra/REA (the Kaileena and unlock strings in prince.bf are the anchors), "
                      "then implement a backed-up, rollback-capable writer and run live boot plus "
                      "per-character/mode selection acceptance on an idle authorized worker at 2% "
                      "audio, with a second launch and rollback check."),
    }
