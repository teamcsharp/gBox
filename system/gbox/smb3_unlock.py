"""SMB3 (NES, game_id 213e4208929ec3e9) revision-guarded unlock gate, request #2256.

No RAM addresses or write targets are defined: the lock check / progress writer in the
owned (patched) build has not been located yet. The gate pins the exact owned ROM and
reports pending_research honestly; it can never select a writer from a title string.
"""
from __future__ import annotations
import hashlib

GAME_ID = "213e4208929ec3e9"
PLATFORM = "nes"
TITLE = "Super Mario Bros. 3"
OWNED_SHA256 = "6ea0777ca520ba7ad7b0ea0f6452140d59aa0b1dffe5045cb1e8020dde10c267"
OWNED_MD5 = "bb5c4b6d4d78c101f94bdb360af502f3"
OWNED_SIZE = 393232
# iNES: 16 PRG x16K, 16 CHR x8K, flags6 0x40 (mapper 4 low nibble 4), byte8/9 = 0 (no PRG-RAM declared)
OWNED_HEADER = bytes.fromhex("4e45531a10104000")
STOCK_REV1_MD5 = "e883e0d43448d9fdd8ce626f75fe4e5d"  # differs in banks 25/31 etc.: not the owned build
CATEGORIES = ("characters", "hidden_characters", "modes", "levels", "stages", "costumes", "items", "extras")
REQUIRED_EVIDENCE = ("owned_executable_sha256", "native_lock_check_and_progress_writer", "category_inventory",
                     "original_bytes_rollback_receipt", "live_boot_and_selection_acceptance",
                     "second_launch_verification")
# Observed fact: battery flag but 0 PRG-RAM declared => no persisted SRAM; unlock must be a load-time RAM write.


def revision_guard(rom: bytes) -> dict:
    """Verify the exact owned build before any future write plan may be applied."""
    ok = (len(rom) == OWNED_SIZE and rom[:8] == OWNED_HEADER
          and hashlib.sha256(rom).hexdigest() == OWNED_SHA256 and hashlib.md5(rom).hexdigest() == OWNED_MD5)
    return {"match": ok, "size": len(rom), "sha256": hashlib.sha256(rom).hexdigest(),
            "md5": hashlib.md5(rom).hexdigest()}


def inventory() -> dict:
    return {c: {"state": "unknown", "evidence": "no REA/Ghidra analysis of the owned build yet"} for c in CATEGORIES}


def profile_gate() -> dict:
    return {"game_id": GAME_ID, "title": TITLE, "platform": PLATFORM, "verified": False,
            "status": "pending_research", "profile": None,
            "reason": "Owned ROM identified by hash but its lock check / progress RAM writer is not yet located; "
                      "no verified write targets, no runtime acceptance.",
            "guard": {"sha256": OWNED_SHA256, "md5": OWNED_MD5, "size": OWNED_SIZE},
            "requires": list(REQUIRED_EVIDENCE), "categories": list(CATEGORIES), "scope": list(CATEGORIES),
            "inventory": inventory()}
