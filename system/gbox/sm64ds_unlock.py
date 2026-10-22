"""Super Mario 64 DS (USA) NDS unlock candidate profile (#2253).

Database-backed, not gameplay-verified. Writes come from the installed libretro
cheat database entry ``Super Mario 64 DS (USA).cht`` (cheat10/12/14). The .cht is
not bound to an executable hash and its revision (Rev 0 vs Rev 1 differ) is not
proven to match the owned dump, so ``gameplay_verified`` stays False until a
live read-back on an authorized agent session (i9-NUC/Spark, never JAYBUILTFINALE).

Cheat token: top nibble of the first word is the op ("0" = 32-bit, "1" = 16-bit,
"2" = 8-bit write); the low 24 bits are the offset into ARM9 main RAM
(0x02000000 + offset). Values are little-endian.
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

GAME_ID = "917483267d246594"
TITLE = "Super Mario 64 DS (USA)"
PLATFORM = "nds"
GAMECODE = "ASME"
ROM_SHA256 = "916056a27ffb07d1bae2ce0ca6f6464c1621c737dc96657a7b9eab4d3bccfc87"
DATABASE_CHT = "Nintendo - Nintendo DS/Super Mario 64 DS (USA).cht"
DATABASE_SHA256 = "bdae5307c00ab151a5b5d064c1437fe64213a7b166ec5ef7b213eb5e9a7a9f28"
NDS_MAIN_RAM = (0x02000000, 0x400000)

# name -> (address, value, width, cht description). Save-data fields at 0x02094BA4+.
UNLOCK_FIELDS = {
    "castle_doors_lo": (0x02094BA4, 0xFFFF, 2, "All Castle Doors Unlocked"),
    "castle_doors_hi": (0x02094BA6, 0xFF, 1, "All Castle Doors Unlocked"),
    "course_stars_0": (0x02094BB4, 0xFFFFFFFF, 4, "All 120 Course Stars"),
    "course_stars_1": (0x02094BB8, 0xFFFFFFFF, 4, "All 120 Course Stars"),
    "course_stars_2": (0x02094BBC, 0xFFFFFFFF, 4, "All 120 Course Stars"),
    "course_stars_3": (0x02094BC0, 0xFFFF, 2, "All 120 Course Stars"),
    "course_stars_4": (0x02094BC2, 0xFF, 1, "All 120 Course Stars"),
    "rec_room_minigames": (0x02094BE8, 0xFFFFFFFF, 4, "All Mini Games in Rec Room"),
}
# Character selector byte (cheat16-18 hold L+R+dir): 1=Luigi, 2=Wario, 3=Yoshi.
CHARACTER_BYTE = 0x02094BE1
CHARACTERS = {"mario": 0, "luigi": 1, "wario": 2, "yoshi": 3}


def in_main_ram(address: int, width: int) -> bool:
    lo, size = NDS_MAIN_RAM
    return lo <= address and address + width <= lo + size


def rom_guard(nds_path) -> dict:
    digest = hashlib.sha256(Path(nds_path).read_bytes()).hexdigest()
    return {"ok": digest == ROM_SHA256, "expected": ROM_SHA256, "actual": digest}


def unlock_ops() -> list[dict]:
    ops = []
    for field, (addr, value, width, desc) in UNLOCK_FIELDS.items():
        ops.append({"field": field, "address": addr, "value": value, "width": width,
                    "hex_bytes": struct.pack("<I", value)[:width].hex(),
                    "description": desc, "database_verified": False, "gameplay_verified": False})
    return ops


def profile() -> dict:
    return {"game_id": GAME_ID, "title": TITLE, "platform": PLATFORM, "gamecode": GAMECODE,
            "rom_sha256": ROM_SHA256, "database": DATABASE_CHT, "database_sha256": DATABASE_SHA256,
            "database_entries": sorted(UNLOCK_FIELDS),
            "scope": ["castle_doors", "course_stars_120", "rec_room_minigames", "character_select"],
            "verified": [], "gameplay_verified": False, "complete_unlock_profile": False,
            "known_gap": "Character availability (Luigi/Wario/Yoshi) is a selector byte, not a proven "
                         "save flag; the .cht revision is not bound to the owned ROM; no live read-back.",
            "requires_live_readback": True}


def live_acceptance_plan(session_id: str) -> dict:
    jobs = [{"tool": "poke", "agent_use": True,
             "input": {"session_id": session_id, "address": hex(o["address"]),
                       "type": {1: "u8", 2: "u16", 4: "u32"}[o["width"]], "value": o["value"], "hold": True}}
            for o in unlock_ops()]
    return {"game_id": GAME_ID, "session_id": session_id,
            "preconditions": ["list_workers/list_sessions confirms an authorized agent session "
                              "(i9-NUC/Spark, never JAYBUILTFINALE)",
                              "rom_guard(nds) ok", "read_memory each address and record pre-state"],
            "jobs": jobs, "success_criterion": "every poke read_back equals value and castle/star/rec-room UI is captured",
            "executed": False}
