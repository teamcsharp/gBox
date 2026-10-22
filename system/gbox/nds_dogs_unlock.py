"""Nintendogs - Dachshund & Friends (USA) NDS unlock candidate profile (#2202).

Database-backed inventory only; NOT gameplay-verified. Evidence comes from the
installed libretro cheat database for this exact title. ROM/ARM9 digests are not
yet captured (re_executable job 70d1d22a5a524e64 queued on lilspark), so
``rom_guard`` refuses every ROM until ROM_SHA256 is pinned: no write op is
reachable from pre_launch.
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

GAME_ID = "84c4cf28c565aa5e"
TITLE = "Nintendogs - Dachshund & Friends (USA)"
PLATFORM = "nds"
ROM_SHA256 = None   # pending re_executable job 70d1d22a5a524e64
ARM9_SHA256 = None
DATABASE_PATH = "Nintendo - Nintendo DS/Nintendogs - Dachshund  Friends (USA).cht"
DATABASE_SHA256 = "70388395f23ce10df25db13241fa4f367b1485f803245bdd392dbffca40dba82"
NDS_MAIN_RAM = (0x02000000, 0x400000)

# field -> (address, value, width, desc): plain 32/16-bit writes from cheat1/cheat2.
UNLOCK_FIELDS = {
    "cash_slot_a": (0x021A292C, 999999999, 4, "Infinite Cash (cheat1 part 1)"),
    "cash_slot_b": (0x021A2FDC, 999999999, 4, "Infinite Cash (cheat1 part 2)"),
    "trainer_points": (0x021A28C0, 99999, 4, "Max Trainer Points (cheat2)"),
}

# Database 'all items' (cheat4) is a SELECT-triggered pointer-relative loop
# (E21A2AFC+0x29C table), so it is not reproduced as static writes here.
CATEGORY_INVENTORY = {
    "characters": {"state": "unknown", "evidence": "20 breeds selectable via save-time modifier cheats14-33 "
                   "(Beagle..Siberian Husky) plus Boy/Girl; no lock flag located"},
    "hidden_characters": {"state": "unknown", "evidence": "no database entry; ARM9 not yet analysed"},
    "modes": {"state": "unknown", "evidence": "competitions (cheat3/cheat5 entry codes) exist; lock check not located"},
    "levels": {"state": "not_present", "evidence": "no level structure in database; unverified"},
    "stages": {"state": "not_present", "evidence": "no stage structure in database; unverified"},
    "costumes": {"state": "unknown", "evidence": "cheat4 item table includes clothing-like ids; table not decoded"},
    "items": {"state": "candidate", "evidence": "cheat4 'Press SELECT to Have All Items' pointer loop, ~0x29C entries"},
    "extras": {"state": "candidate", "evidence": "interior designs cheat37-45 write 221A2930/221A2FE0: Designer Condo=2, "
               "Early American=4, Urban Living=5, Northern European=0, Ranch House=1, Tatami Room=3, Desktop=7, "
               "Outer Space=6, Sea Side=0x1F"},
}


def rom_guard(nds_path: Path) -> dict:
    digest = hashlib.sha256(Path(nds_path).read_bytes()).hexdigest()
    return {"ok": ROM_SHA256 is not None and digest == ROM_SHA256,
            "expected": ROM_SHA256, "actual": digest}


def in_main_ram(address: int, width: int) -> bool:
    lo, size = NDS_MAIN_RAM
    return lo <= address and address + width <= lo + size


def unlock_ops() -> list[dict]:
    rows = []
    for name, (address, value, width, desc) in UNLOCK_FIELDS.items():
        if not in_main_ram(address, width):
            raise ValueError(f"{name}: {address:#x} outside NDS main RAM")
        rows.append({"field": name, "address": address, "value": value, "width": width,
                     "hex_bytes": struct.pack("<I", value)[:width].hex(), "desc": desc,
                     "gameplay_verified": False})
    return rows


def profile() -> dict:
    return {"game_id": GAME_ID, "title": TITLE, "platform": PLATFORM,
            "rom_sha256": ROM_SHA256, "arm9_sha256": ARM9_SHA256,
            "database": DATABASE_PATH, "database_sha256": DATABASE_SHA256,
            "scope": sorted(UNLOCK_FIELDS), "categories": CATEGORY_INVENTORY,
            "gameplay_verified": False, "complete_unlock_profile": False,
            "writes_enabled": ROM_SHA256 is not None,
            "known_gap": "ROM/ARM9 hashes and Ghidra lock-check trace pending."}
