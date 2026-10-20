"""SoulCalibur entries observed in the installed libretro cheat database.

2026-10-19: the game's code shows the five database flags are entries of one table, a u16 unlock flag per fighter
at 0x8C336DFA + 4*i for 1 <= i < 21 (0x8C0E1A5C clears, 0x8C0E1A78 increments it), with Inferno as bit 0x8000 of
the u32 at 0x8C336E54 (0x8C0E1ACE). profiles/gamedata/c747331797369f74-codes.json holds the whole table for
unlock-on-load. The notes below describe the database alone.

These five halfword writes are database evidence, not verified unlock outcomes.
The database is not bound to an executable hash; test the exact game before
promoting any entry to a gameplay-verified profile. No complete unlock profile
is claimed here. Previously treating memory_search_size=4 as u32 was incorrect.
"""
from .cheats import decode_native

GAME_ID = "c747331797369f74"
DATABASE_PATH = "Sega - Dreamcast/Soul Calibur.cht"
DATABASE_SHA256 = "587976eec67826419b34f10c83203dfcc86a1aa97746b757141eabf2ae954c7e"
UNLOCK_FLAGS = {"Hwang": 0x336dfe, "Yoshimitsu": 0x336e0a, "Lizardman": 0x336e2a,
                "Siegfried": 0x336e1e, "Rock": 0x336e16}
UNVERIFIED_TARGETS = ("Seung Mina", "Cervantes", "Edge Master", "Inferno")


def unlock_ops() -> list[dict]:
    """Describe exact database encodings; callers must verify game applicability."""
    rows = []
    for name, offset in UNLOCK_FLAGS.items():
        ops, bad = decode_native("dreamcast", {"handler": 1, "address": offset, "value": 1,
                                              "memory_search_size": 4, "cheat_type": 1})
        if bad:
            raise ValueError(bad)
        _, address, data = ops[0]
        rows.append({"character": name, "address": address, "value": 1,
                     "width": len(data), "hex_bytes": data.hex(), "gameplay_verified": False})
    return rows


def profile() -> dict:
    return {"game_id": GAME_ID, "title": "SoulCalibur (USA)", "platform": "dreamcast",
            "database_entries": sorted(UNLOCK_FLAGS), "verified": [],
            "missing": sorted(UNVERIFIED_TARGETS), "gameplay_verified": False,
            "complete_unlock_profile": False, "database": DATABASE_PATH,
            "database_sha256": DATABASE_SHA256}
