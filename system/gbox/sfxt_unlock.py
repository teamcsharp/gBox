"""Street Fighter X Tekken (Xbox 360, game_id 1c5a728fa761de4e) revision-guarded unlock gate, request #2248.

No write targets are defined: the lock check / save-flag reader in default.xex has not been located.
The gate pins the owned disc image and executable and reports pending_research; it never selects
a writer from a title string. Static facts only (read-only XDVDFS walk, see sfxt_inventory).
"""
from __future__ import annotations
import hashlib

GAME_ID = "1c5a728fa761de4e"
PLATFORM = "xbox360"
TITLE = "Street Fighter X Tekken"
OWNED_ISO_SHA256 = "68543cd9df54721c250efe61b08c55b77a3c8e64882c21373b3884f23d6212d8"
XEX_PATH = "default.xex"
XEX_SECTOR = 7503
XEX_SIZE = 13873152
XEX_MAGIC = b"XEX2"
OWNED_XEX_SHA256 = "4a14af1c9ad385c0e0a29ebd639aaed53afb193e3b0c62bc2ff7a85892be8b58"
# Static lead: big-endian '#EAF' archives under archive/; boot\game\dlc.csv and
# ui\pre_battle\chara_select\* scripts live in archive/CMN/CMN_boot.eaf (67 entries, 0x120-byte records at 0x80).
LEADS = ("archive/CMN/CMN_boot.eaf:boot\\game\\dlc.csv", "archive/CMN/CMN_boot.eaf:boot\\game\\const.lua",
         "archive/CMN/CMN_boot.eaf:ui\\pre_battle\\chara_select\\chara_select_cluster_control.lua")
CATEGORIES = ("characters", "hidden_characters", "modes", "stages", "costumes", "gems", "extras")
REQUIRED_EVIDENCE = ("owned_executable_sha256", "native_lock_check_and_flag_reader", "category_inventory",
                     "original_bytes_rollback_receipt", "live_boot_and_selection_acceptance",
                     "second_launch_verification")


def revision_guard_xex(xex: bytes) -> dict:
    """Verify the exact owned default.xex before any future write plan may be applied."""
    h = hashlib.sha256(xex).hexdigest()
    return {"match": len(xex) == XEX_SIZE and xex[:4] == XEX_MAGIC and h == OWNED_XEX_SHA256,
            "size": len(xex), "sha256": h}


def inventory() -> dict:
    return {c: {"state": "unknown", "evidence": "no REA/Ghidra analysis of default.xex yet"} for c in CATEGORIES}


def profile_gate() -> dict:
    return {"game_id": GAME_ID, "title": TITLE, "platform": PLATFORM, "verified": False,
            "status": "pending_research", "profile": None,
            "reason": "Owned disc and default.xex identified by hash; lock check / save-flag reader not yet located; "
                      "no verified write targets, no runtime acceptance.",
            "guard": {"iso_sha256": OWNED_ISO_SHA256, "xex_sha256": OWNED_XEX_SHA256, "xex_size": XEX_SIZE,
                      "xex_sector": XEX_SECTOR},
            "leads": list(LEADS), "requires": list(REQUIRED_EVIDENCE), "categories": list(CATEGORIES),
            "scope": list(CATEGORIES), "inventory": inventory()}
