"""Call of Duty - World at War (USA) NDS unlock-all candidate profile (#2070).

Database-backed, not gameplay-verified. The two constant writes below come from
the installed libretro cheat database for this exact title and are bound here to
the pinned ROM/ARM9 digests of the owned revision so a launch hook can refuse a
mismatched build. The cheat database is not bound to an executable hash by
itself; this module records the binding and leaves verification to the live
read-back probe described in ``verification_plan``.

Addresses are ARM9 data-plane (DTCM/MAIN_RAM) absolute addresses. The .cht
"2" prefix encodes a 16-bit little-endian write; ``unlock_ops`` reproduces the
same ops through the shared decoder path so width and byte order stay in one
place (an explicit width-aware encoder is used because cheats.decode treats a
DS-prefixed token's value digits as big-endian byte length, which would flip
the 16-bit field for a 4-digit value like 0x001E).

No live session write has occurred: gameplay_verified stays False until the
read-back probe reports both fields at the target value on a real session on
the authorized worker.
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

GAME_ID = "d9467f457f53f2c7"
TITLE = "Call of Duty - World at War (USA)"
PLATFORM = "nds"
ROM_SHA256 = "c0c732dc191847dca37174260ea44c97a6c29f91085092d85eb6c3ad691e2b76"
ARM9_SHA256 = "6a57771732d4c7d4dfb7fa9c37983328cb7c3029da9391304d71d5b87fb857a2"
GAMECODE = "CALE"
ARM9_LOAD = 0x02000800

DATABASE_PATH = "Nintendo - Nintendo DS/Call of Duty - World at War (USA).cht"
DATABASE_SHA256 = "88e4afbab544fbbe713e32876ea473459c60c216cc7a54a4e8993d551c408691"

# (field, cht_prefix, ram_address, value, width, desc) straight from cheat6/cheat5
# of the pinned database. .cht tokens are ``PPPPPPPP VVVVVVVV``: the top byte is
# the operation/type ("2" = 16-bit write), NOT part of the RAM address; the real
# address is the low 24 bits mapped into the ARM9 main-RAM window.
UNLOCK_FIELDS = {
    "all_countries_quickplay": (0x22, 0x021B77A9, 0x001E, 2, "All Countries Unlocked (Quickplay)"),
    "challenge_mode_complete": (0x22, 0x021B77C1, 0x001E, 2, "Complete Challenge Mode"),
}

NDS_MAIN_RAM = (0x02000000, 0x0400000)  # matches tools.MAIN_RAM["nds"]


def rom_guard(nds_path: Path) -> dict:
    """Bind the profile to the owned revision; refuse anything else."""
    digest = hashlib.sha256(Path(nds_path).read_bytes()).hexdigest()
    return {"ok": digest == ROM_SHA256, "expected": ROM_SHA256, "actual": digest}


def in_main_ram(address: int, width: int) -> bool:
    lo, size = NDS_MAIN_RAM
    return lo <= address and address + width <= lo + size


def unlock_ops() -> list[dict]:
    """Exact-width little-endian write ops for the two database unlock fields.

    The widths/endianness replicate the .cht '2' prefix (16-bit LE); callers
    must run rom_guard before applying and read the bytes back after.
    """
    rows = []
    for name, (prefix, address, value, width, desc) in UNLOCK_FIELDS.items():
        if prefix != 0x22:
            raise ValueError(f"{name}: unexpected .cht operation prefix {prefix:#04x}")
        if not in_main_ram(address, width):
            raise ValueError(f"{name}: {address:#x} is outside the NDS ARM9 main RAM window")
        data = struct.pack("<H", value)[:width]
        rows.append({"field": name, "address": address, "value": value,
                     "width": width, "hex_bytes": data.hex(), "desc": desc,
                     "database_verified": False, "gameplay_verified": False})
    return rows


def expected_bytes(field: str) -> bytes:
    _prefix, address, value, width, _ = UNLOCK_FIELDS[field]
    return struct.pack("<H", value)[:width]


def cht_token(field: str) -> str:
    """The exact installed-database token (prefix and address as printed in the .cht)."""
    prefix, address, value, _width, _ = UNLOCK_FIELDS[field]
    # the database prints the operation-prefixed 24-bit address in its own format
    return f"{prefix:04X}+{(address & 0x00FFFFFF):07X}"


def verification_plan(session_id: str) -> dict:
    """Bounded live-acceptance steps; read-back is mandatory, no live claim without it."""
    return {
        "game_id": GAME_ID, "session_id": session_id,
        "steps": [
            "1. rom_guard(nds) must report ok before any write",
            "2. read_memory each address and record the pre-state (locked values)",
            "3. apply unlock_ops writes via the session poke path (agent session on the authorized worker only)",
            "4. read_memory both addresses back; both must equal the expected 2-byte little-endian value",
            "5. open Quickplay country list / Challenge menu in the session and record UI evidence",
        ],
        "read_back_required": True,
        "rollback": "Restore the step-2 pre-state bytes if any read-back mismatches.",
        "audio_policy": "2% volume on the agent session; never JAYBUILTFINALE",
    }


def profile() -> dict:
    return {"game_id": GAME_ID, "title": TITLE, "platform": PLATFORM,
            "gamecode": GAMECODE, "rom_sha256": ROM_SHA256, "arm9_sha256": ARM9_SHA256,
            "database": DATABASE_PATH, "database_sha256": DATABASE_SHA256,
            "database_entries": sorted(UNLOCK_FIELDS),
            "scope": ["all_countries_quickplay", "challenge_mode_complete"],
            "verified": [], "gameplay_verified": False,
            "complete_unlock_profile": False,
            "known_gap": "Request lists characters/costumes/items/extras categories; the pinned "
                         "database has no entries for them and no static lock-check has been located "
                         "in the decompressed ARM9 (cheat targets live in overlay-loaded data).",
            "requires_live_readback": True}
