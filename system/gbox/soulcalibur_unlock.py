"""SoulCalibur (USA) on Dreamcast — unlock every character.

Every unlockable character is gated on how many *distinct* characters have cleared Arcade mode
(each clear counts once); the flag lives in Dreamcast RAM as a plain u32. The shipped
libretro-database `Sega - Dreamcast/Soul Calibur.cht` carries one native memory cheat per
verified flag, which gBox applies through its own write engine (cheats.decode_native), so no
emulator cheat engine is required.

Verified flags (Dreamcast RAM offset -> character -> Arcade clears required):
  0x336DFE  Hwang         1
  0x336E0A  Yoshimitsu    2
  0x336E16  Rock          7
  0x336E1E  Siegfried     5
  0x336E2A  Lizardman     3

Not present in the shipped database, so gBox cannot set them yet. Their addresses must be
recovered first — encrypted GameShark CDX codes exist and are recorded as a pointer:
  Seung Mina  (9)      FA919C52 00000001
  Cervantes   (10)     AA5B5xxx 00000001
  Edge Master (17)     no published code (clear Arcade with every character)
  Inferno     (-)      Edge Master + Xianghua 3rd-costume Arcade clear
"""
from __future__ import annotations

GAME_ID = "c747331797369f74"

# Verified unlock flags: character -> (Dreamcast RAM offset, Arcade clears required)
UNLOCK_FLAGS = {
    "Hwang": (0x336DFE, 1),
    "Yoshimitsu": (0x336E0A, 2),
    "Lizardman": (0x336E2A, 3),
    "Siegfried": (0x336E1E, 5),
    "Rock": (0x336E16, 7),
}

# Documented but not yet addressable from the shipped cheat database.
MISSING = {
    "Seung Mina": 9,
    "Cervantes": 10,
    "Edge Master": 17,
    "Inferno": None,          # requires Edge Master + Xianghua 3rd-costume Arcade clear
}


def unlock_ops() -> list[dict]:
    """gBox write ops that set every verified unlock flag (u32 1 at the cached RAM address)."""
    return [{"character": c, "address": 0x8C000000 | off, "value": 1}
            for c, (off, _) in UNLOCK_FLAGS.items()]


def profile() -> dict:
    return {
        "game_id": GAME_ID, "title": "SoulCalibur (USA)", "platform": "dreamcast",
        "verified": sorted(UNLOCK_FLAGS),
        "missing": sorted(MISSING),
        "total_unlockable": len(UNLOCK_FLAGS) + len(MISSING),
    }
