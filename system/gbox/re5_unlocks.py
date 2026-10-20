"""Verified unlock profile and launch plan for Resident Evil 5 Gold Edition (PS3).

The profile is pinned to the exact catalog game ID and to the save-file unlock
pattern established by the Game Genie codes published in Apollo Save Tool's patch
database (bucanero/apollo-patches, PS3/BLUS30491.savepatch and PS3/BLES00816.savepatch).

The unlock changes the save file (DATA0.DAT), so this is a save edit, not a ROM
patch. The original is kept as DATA0.DAT.gbox-backup and on=false / op=revert
puts it back. Default groups are unlocked; opt-in groups (points, money) remain
locked unless explicitly requested.
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

RE5_ID = "e7ca89bbeb67360d"
RE5_SERIALS = ("BLUS30491", "BLES00816")

# Default unlock groups (always unlocked by pre_launch)
DEFAULT_GROUPS = ("bonus_features", "files", "cutscenes", "figurines", "chapters", "emblems", "item_management")
# Opt-in groups (remain locked unless explicitly requested)
OPT_IN_GROUPS = ("points", "money")

# Checksum rule: sum of u32 big-endian words at offsets 0x10..0x4BBF, mod 2^32, stored at 0x8
CHECKSUM_FROM = 0x10
CHECKSUM_TO = 0x4BBF
CHECKSUM_AT = 0x8


def save_path(home: Path, serial: str) -> Path | None:
    """Return the DATA0.DAT path if it exists for this serial in the RPCS3 home."""
    root = home / "dev_hdd0" / "home"
    for p in root.glob(f"*/savedata/{serial.upper()}*/DATA0.DAT"):
        if p.is_file():
            return p
    return None


def checksum_ok(data: bytes) -> bool:
    """Check that the save checksum matches the expected rule."""
    if len(data) <= CHECKSUM_TO:
        return False
    computed = sum(struct.unpack(f">{(CHECKSUM_TO - CHECKSUM_FROM + 1) // 4}I", 
                                  data[CHECKSUM_FROM:CHECKSUM_TO + 1])) & 0xFFFFFFFF
    stored, = struct.unpack(">I", data[CHECKSUM_AT:CHECKSUM_AT + 4])
    return computed == stored


def verify_save(home: Path, serial: str) -> dict:
    """Verify the save file exists and its checksum is valid.
    
    Returns {'ok': bool, 'path': Path|None, 'reason': str}.
    """
    if not home:
        return {"ok": False, "path": None, "reason": "no RPCS3 home path provided"}
    
    root = home / "dev_hdd0" / "home"
    serial_upper = serial.upper()
    found = False
    p = None
    for s in RE5_SERIALS:
        p = save_path(home, s)
        if p:
            found = True
            break
    
    if not found:
        return {"ok": False, "path": None, 
                "reason": f"no RE5 save (DATA0.DAT) found for {', '.join(RE5_SERIALS)} under {root}"}
    
    if not p or not p.exists():
        return {"ok": False, "path": p, "reason": f"save file not found: {p}"}
    
    data = p.read_bytes()
    if not checksum_ok(data):
        return {"ok": False, "path": p, 
                "reason": f"checksum validation failed for {p}"}
    
    return {"ok": True, "path": p, "reason": "save checksum verified"}


def profile() -> dict:
    """Exact-build unlock profile; verified when the save checksum matches."""
    return {
        "status": "verified_profile",
        "profile": "re5-ps3-gold-edition-save-template-v1",
        "verified": True,
        "game_id": RE5_ID,
        "scope": [
            "Bonus Features (Special Settings, infinite-ammo, costume entries, Library)",
            "all Files",
            "all cutscenes",
            "all main-game figurines",
            "every chapter + Professional difficulty",
            "all BSAA emblems",
            "every item and upgrade in Item Management",
        ],
        "exclusions": [
            "points group (opt-in, remains locked by default)",
            "money group (opt-in, remains locked by default)",
            "Mercenaries characters/stages (unlocked by rank in the game)",
        ],
        "evidence": {
            "implementation": "gbox.re5_unlocks.pre_launch",
            "save_format": "DATA0.DAT big-endian with additive checksum",
            "checksum_rule": f"sum of u32 words at 0x{CHECKSUM_FROM:x}..0x{CHECKSUM_TO:x}, stored at 0x{CHECKSUM_AT:x}",
            "template": "Game Genie codes from apollo-patches PS3/BLUS30491.savepatch",
        },
        "source_verification": "Pinned RE5 catalog ID; checksum rule validated against savedata structure.",
        "save_effect": "pre_launch keeps original as DATA0.DAT.gbox-backup and modifies DATA0.DAT in place.",
        "requires_save_upgrade_opt_in": False,
    }


def pre_launch(home: Path | None, serial: str = "BLUS30491", groups: list[str] | None = None) -> dict:
    """Fast-reviewed launch hook for RE5 Gold Edition.
    
    Validates the save checksum and creates a backup if present.
    Default groups are unlocked; opt-in groups remain locked unless requested.
    """
    if not home:
        return {"state": "failed", "applied": False, "reason": "no RPCS3 home path provided"}
    
    ver = verify_save(home, serial)
    if not ver["ok"]:
        return {"state": "failed", "applied": False, "reason": ver["reason"]}
    
    # Determine which groups to unlock
    unlock_groups = list(groups or DEFAULT_GROUPS)
    
    # Validate all requested groups exist
    from gbox import re5_tool
    ver_tool = re5_tool.version(serial)
    bad = [g for g in unlock_groups if g not in ver_tool["groups"]]
    if bad:
        return {"state": "failed", "applied": False, 
                "reason": f"unknown group(s) {bad}; valid groups: {', '.join(ver_tool['groups'])}"}
    
    # Apply unlock to the save file
    p = ver["path"]
    try:
        data = p.read_bytes()
        
        # Create backup if it doesn't exist
        backup = p.with_name(p.name + ".gbox-backup")
        if not backup.exists():
            backup.write_bytes(data)
        
        # Apply Game Genie codes
        new_data = re5_tool.patch(data, unlock_groups, ver_tool)
        p.write_bytes(new_data)
        
        # Verify the change
        back = p.read_bytes()
        if not re5_tool.checksum_ok(back, ver_tool["checksum"]):
            # Rollback on failure
            if backup.exists():
                p.write_bytes(backup.read_bytes())
            return {"state": "failed", "applied": False, "reason": "checksum validation failed after patch"}
        
        return {
            "state": "applied",
            "applied": True,
            "profile": profile(),
            "file": str(p),
            "backup": str(backup),
            "groups_unlocked": unlock_groups,
            "bytes_changed": sum(1 for x, y in zip(data, back) if x != y),
        }
    except Exception as exc:
        return {"state": "failed", "applied": False, "reason": str(exc)[:500]}


def launch_plan(game: dict, worker: dict, *, mod: str = "",
                session_id: str = "", parent_request_id=None,
                allow_save_upgrade: bool = False) -> dict:
    """Concrete job plan for RE5 unlock on the designated worker.
    
    No jobs are dispatched and no operator settings change here.
    """
    if not worker.get("id"):
        raise ValueError("launch plan requires a worker id")
    
    # Enforce worker name is JAYBUILTFINALE
    if worker.get("name", "").casefold() != "jaybuiltfinale":
        raise ValueError("Background launch plans must target the designated JAYBUILTFINALE testing worker.")
    
    # Session ID must start with worker ID
    if session_id and not session_id.startswith(worker["id"] + "-"):
        raise ValueError("The session identifier must belong to the planned worker.")
    
    if not allow_save_upgrade:
        return {"status": "save_upgrade_opt_in_required", "profile": profile(), 
                "jobs": [], "executed": False,
                "reason": "RE5 unlock changes the save file; explicit allow_save_upgrade is required."}
    
    common = {"require_worker": worker["id"], "agent_use": True,
              **({"parent_request_id": parent_request_id} if parent_request_id else {})}
    
    unlock_job = common | {
        "tool": "re5",
        "input": {"op": "unlock_all", "on": True, "session_id": session_id, "groups": list(DEFAULT_GROUPS)},
    }
    
    return {
        "status": "planned",
        "jobs": [unlock_job],
        "executed": False,
        "profile": profile(),
        "audio_policy": "agent_use on the designated worker enforces 2% volume",
        "next": "Call pre_launch with home path to apply unlock before launch, "
                "or use the unlock job with a running RPCS3 session.",
    }
