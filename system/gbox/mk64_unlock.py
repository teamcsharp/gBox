"""Mario Kart 64 (USA, N64, game_id 7f5c674909d63b5f) unlock research gate (request #2159).

Honest dispatch-surface record only: NO save offsets, ROM patches or write targets live here.
The ROM identity is pinned to the single US revision already hashed in ``mk64_inventory``.
The inventory below is a hypothesis list from the public n64decomp/mk64 layout; each entry
carries its evidence level. Nothing is Ghidra- or runtime-verified for this executable, so
``verified`` stays False and ``game_unlocks.pre_launch`` cannot reach a writer.
"""
from __future__ import annotations

GAME_ID = "7f5c674909d63b5f"
PLATFORM = "n64"
TITLE = "Mario Kart 64 (USA)"
ROM_SHA1_Z64 = "579c48e211ae952530ffc8738709f078d5dd215e"  # z64-normalized, see mk64_inventory.KNOWN
CATEGORIES = ("characters", "hidden_characters", "modes", "levels", "stages", "costumes", "items", "extras")

U, N, K = "unlocked_at_start", "not_present", "unknown"
# (category, entry, state, evidence)
INVENTORY = (
    ("characters", "Mario, Luigi, Peach, Toad, Yoshi, Donkey Kong, Wario, Bowser", U,
     "decomp assets/character_select (8 drivers); no lock check known; not Ghidra-verified"),
    ("hidden_characters", "any", N, "decomp roster has exactly 8 drivers; not Ghidra-verified"),
    ("modes", "Grand Prix, Time Trials, VS, Battle", U, "decomp menu list; not runtime-verified"),
    ("modes", "Extra (mirror) mode", K, "gated by save progress in EEPROM; flag location unresolved"),
    ("levels", "Special Cup / 150cc class", K, "progress-gated; exact EEPROM flags unresolved"),
    ("stages", "16 race courses + 4 battle courses", K, "course availability tied to cup unlocks; unresolved"),
    ("costumes", "any", N, "no costume system in this title"),
    ("items", "any", N, "items are in-race pickups, not unlockable"),
    ("extras", "staff ghosts / time-trial ghosts", K, "save-dependent; unresolved"),
)

REQUIRED_EVIDENCE = ("owned_rom_sha1_match", "ghidra_or_rea_lock_check_xrefs", "eeprom_layout_and_checksum",
                     "save_backup_receipt", "rollback_receipt", "live_boot_and_selection_acceptance",
                     "second_launch_verification")
SAFETY = ("No write routine exists; never write EEPROM/ROM without the full evidence chain.",
          "Never test on the operator PC; only idle authorized test workers with isolated saves.",
          "Preserve the original ROM and back up saves before any change.")


def profile_gate() -> dict:
    return {
        "game_id": GAME_ID, "title": TITLE, "platform": PLATFORM,
        "verified": False, "status": "pending_research",
        "reason": ("Static inventory is decomp-derived only; EEPROM progress flags, lock checks and "
                   "checksum are not resolved for this ROM, so no verified writer exists."),
        "evidence": {"rom_sha1_z64": ROM_SHA1_Z64,
                     "inventory": [dict(category=c, entry=e, state=s, evidence=v) for c, e, s, v in INVENTORY]},
        "unresolved_categories": sorted({c for c, _, s, _ in INVENTORY if s == K}),
        "requires": list(REQUIRED_EVIDENCE), "categories": list(CATEGORIES), "safety": list(SAFETY),
        "next_step": ("Open the owned ROM in an x64 REA/Ghidra session (code segment 0, CIC-6102), locate the "
                      "EEPROM read/write (osEepromLongRead/Write) and the save checksum, resolve cup/mirror "
                      "unlock flags, then implement a monotonic overlay with backup and rollback."),
    }
