"""Sonic Shuffle (USA, Dreamcast, MK-51060 V1.000, game_id 79ade87c3c2fad3e) unlock research gate.

Request #2239 (Sonic Shuffle unlock-on-load). Contains NO save offsets or write targets:
the static 8-category inventory (gbox.sshuffle_static_inventory) identifies all disc content
by category, and the exact-build inventory (gbox.sshuffle_inventory) pins the disc identity
and the eight board characters. No lock check / progress-flag routine has been located yet.
This gate pins the identity and reports pending_research so pre_launch can never reach a writer.
"""
from __future__ import annotations

from . import sshuffle_inventory as inv
from . import sshuffle_static_inventory as static_inv

GAME_ID = inv.GAME_ID
PLATFORM = "dreamcast"
TITLE = inv.TITLE
SOURCE_SHA256 = inv.SOURCE_SHA256
FIRST_READ_SHA256 = inv.FIRST_READ_SHA256

CATEGORIES = static_inv.CATEGORIES
REQUIRED_EVIDENCE = ("owned_executable_sha256", "native_unlock_routine", "save_backup_receipt",
                     "rollback_receipt", "live_boot_and_selection_acceptance", "second_launch_verification")
# Inventory known from disc evidence only (not unlock-state proof): board roster in 1ST_READ name order.
KNOWN_ROSTER = tuple(inv.DISPLAY[n] for n in ("SONIC", "TAILS", "KNUCKLES", "AMY", "BIG", "GAMMA", "CHAO", "SUPER SONIC"))
SAFETY = ("No save/memory writes exist for this title until the evidence chain is attached.",
          "Never test on the operator PC; only idle authorized i9-NUC/Spark workers with isolated saves.",
          "Preserve the original CHD/GDI and back up any VMU save before changes.",
          "A queued task, inventory or code-only PR is not unlock completion.")


def profile_gate() -> dict:
    return {"game_id": GAME_ID, "title": TITLE, "platform": PLATFORM, "verified": False,
            "status": "pending_research",
            "reason": ("Static 8-category inventory complete (485 files across 7 directories); "
                       "exact disc and character tables are hashed. No lock check, progress flag "
                       "or native save layout has been located; no verified write targets exist."),
            "pinned": {"source_sha256": SOURCE_SHA256, "first_read_sha256": FIRST_READ_SHA256},
            "static_inventory_module": "gbox.sshuffle_static_inventory",
            "known_roster_unverified_lock_state": list(KNOWN_ROSTER),
            "requires": list(REQUIRED_EVIDENCE), "categories": list(CATEGORIES), "safety": list(SAFETY),
            "next_step": ("Load 1ST_READ.BIN in x64 Ghidra (SH-4), xref the player "
                          "name table to find the character-select eligibility and the VMU save flag "
                          "loader; record unlocked/not_present/unknown per category.")}
