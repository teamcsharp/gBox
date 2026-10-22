"""Sonic Adventure 2 (USA, Dreamcast, game_id d95ed7ed1e40552a) unlock-on-load research gate (request #2233).

Identity-pinned, research-pending record. It carries NO new write targets: the only addresses referenced are the
already verified save/recount layout in gbox.sa2_mods (1ST_READ.BIN sha1 0817898a..., emblem recount 0x8C0BC5A0). Lock
checks for characters, modes, costumes (Chao/pet items) and extras have not been traced to an executable-hash-bound
routine, so those categories stay 'unknown' and game_unlocks.profile_for reports verified=False; pre_launch can never
reach a writer. Promotion needs the evidence chain in REQUIRED_EVIDENCE.
"""
from __future__ import annotations

GAME_ID = "d95ed7ed1e40552a"
PLATFORM = "dreamcast"
TITLE = "Sonic Adventure 2 (USA)"
EXECUTABLE = {"name": "1ST_READ.BIN", "sha1": "0817898aac799a8de5e8a9021d817bd7ef33a9e3", "load_address": "0x8C010000"}

CATEGORIES = ("characters", "hidden_characters", "modes", "levels", "stages", "costumes", "items", "extras")

REQUIRED_EVIDENCE = ("owned_executable_sha256", "lock_check_xrefs", "save_flag_layout", "save_backup_receipt",
                     "rollback_receipt", "live_selection_and_play_acceptance", "second_launch_verification")

# status in {unlocked, not_present, unknown, mechanism_known}; every entry names its evidence or why it is unknown.
INVENTORY = {
    "stages": [{"name": "Green Hill", "status": "mechanism_known",
                "evidence": "gbox.sa2_mods: 180 emblems on the save recount (0x8C0BC5A0) unlock Green Hill (0x8C0BC872); "
                            "not applied on load, not runtime-verified"}],
    "levels": [{"name": "29 emblem-counted action stages + Route 101/280", "status": "mechanism_known",
                "evidence": "gbox.sa2_mods EMBLEM_STAGES / save rank bytes; per-stage unlock flags not traced"}],
    "characters": [{"name": "Sonic, Shadow, Tails, Eggman, Knuckles, Rouge", "status": "unknown",
                    "evidence": "story-order unlocks; selection gate not traced"}],
    "hidden_characters": [{"name": "Amy, Metal Sonic, Tikal, Chaos (2P/ID names in sa2_mods.CHARACTERS)", "status": "unknown",
                           "evidence": "names present in the character table only; selectability gate not traced"}],
    "modes": [{"name": "Hero/Dark/Last Story, Kart Race, 2P modes, Chao World", "status": "unknown", "evidence": "not traced"}],
    "costumes": [{"name": "alternate outfits / upgrades", "status": "unknown", "evidence": "not traced"}],
    "items": [{"name": "Chao items / Black Market", "status": "unknown", "evidence": "not traced"}],
    "extras": [{"name": "Boss Attack, Mission 2-5, Sound Test/Theater", "status": "unknown", "evidence": "not traced"}],
}

SAFETY = ("No writer is reachable for this gate; saves/ROM untouched.",
          "Never test on the operator PC; only idle authorized i9-NUC/Spark workers at 2% audio.",
          "Back up the VMU/save before any change; support rollback; no online-advantage or entitlement changes.",
          "A code-only PR or inventory is not unlock-all completion.")


def profile_gate() -> dict:
    counts = {}
    for entries in INVENTORY.values():
        for e in entries:
            counts[e["status"]] = counts.get(e["status"], 0) + 1
    return {"game_id": GAME_ID, "title": TITLE, "platform": PLATFORM, "verified": False, "status": "pending_research",
            "executable": dict(EXECUTABLE), "reason": "Lock checks for characters, modes, costumes, items and extras are not "
            "traced in this revision; only the emblem-recount/Green Hill mechanism is known. No verified unlock write exists.",
            "requires": list(REQUIRED_EVIDENCE), "categories": list(CATEGORIES), "inventory": INVENTORY,
            "inventory_counts": counts, "safety": list(SAFETY),
            "next_step": "Trace character/mode lock checks via Ghidra (x64 worker, 1ST_READ.BIN SH-4) from the save "
                         "unlock flags; then add a monotonic save-overlay writer with rollback and runtime acceptance."}
