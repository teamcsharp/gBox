"""Mortal Kombat Trilogy (N64) unlock module.

Static-analysis-derived GameShark-style cheat codes for unlocking all
hidden content in Mortal Kombat Trilogy (USA) on Nintendo 64.

ROM identity (verified via hash_game job 072209a1dcd64a70):
  SHA1:   63d68c330558c63527f6c36f77b0b8f8dcc377f6
  CRC32:  4601fe86
  Size:   10,877,773 bytes
  Source: libretro-database cht/Nintendo - Nintendo 64/Mortal Kombat Trilogy (USA).cht

Unlock categories:
  hidden_character  – Human Smoke, Khameleon, hidden ? slots
  game_mode         – Level Select, Free Play, Bloody Kombat, etc.

All addresses are N64 RDRAM physical addresses (0x80000000-0x803FFFFF range).
Values are uint8 writes applied at boot and on each frame during gameplay.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ROM identity constants
ROM_SHA1 = "63d68c330558c63527f6c36f77b0b8f8dcc377f6"
ROM_CRC32 = "4601fe86"
ROM_SIZE = 10877773
ROM_GAME = "Mortal Kombat Trilogy (USA)"
ROM_PLATFORM = "Nintendo 64"

# Profile path (relative to system root)
PROFILE_PATH = "profiles/gamedata/cb47d622c26b67f8-unlock.json"

# Unlock flag definitions
# Each entry: (address, value, description, category)
UNLOCK_FLAGS: list[tuple[int, int, str, str]] = [
    # Hidden characters
    (0x80257519, 1, "Enable Human Smoke (hidden character)", "hidden_character"),
    (0x80257517, 1, "Enable Khameleon (hidden character)", "hidden_character"),
    (0x80169EE1, 4, "Open Red & Blue ? slots (hidden character slots)", "hidden_character"),
    # Game modes
    (0x80169EB9, 1, "Enable Level Select", "game_mode"),
    (0x801697DF, 1, "Enable Free Play", "game_mode"),
    (0x80257527, 1, "Enable Bloody Kombat (uncensored)", "game_mode"),
    (0x80257523, 1, "Enable Unlimited Run", "game_mode"),
    (0x80169E6F, 1, "Enable 1-Round Matches", "game_mode"),
    (0x80169E91, 1, "Enable Infinite Fatality Time", "game_mode"),
    (0x8014C251, 1, "Enable Collision Blocks", "game_mode"),
    (0x80257521, 1, "Enable Disable Throwing", "game_mode"),
]


def build_profile() -> dict[str, Any]:
    """Build the unlock profile dictionary."""
    cheats = [
        {
            "desc": desc,
            "address": f"0x{addr:08X}",
            "value": val,
            "type": "uint8",
            "category": cat,
        }
        for addr, val, desc, cat in UNLOCK_FLAGS
    ]
    return {
        "title": f"{ROM_GAME} - all unlockables enabled",
        "how": (
            "GameShark-style cheat codes from libretro-database cht file; "
            "addresses are N64 RDRAM physical addresses; write value at boot "
            "and on each frame during gameplay"
        ),
        "rom": {
            "sha1": ROM_SHA1,
            "crc32": ROM_CRC32,
            "size": ROM_SIZE,
            "game": ROM_GAME,
            "platform": ROM_PLATFORM,
        },
        "cheats": cheats,
        "source": "libretro-database/cht/Nintendo - Nintendo 64/Mortal Kombat Trilogy (USA).cht",
        "verification": {
            "method": "static analysis of cheat database + ROM hash match",
            "rom_sha1_verified": True,
            "cheat_addresses_range": "0x8014C251-0x80257527",
            "notes": (
                "All addresses are in RDRAM range 0x80000000-0x803FFFFF; "
                "values are uint8 writes"
            ),
        },
    }


def write_profile(system_root: Path) -> Path:
    """Write the unlock profile to the canonical location.

    Args:
        system_root: Path to the system root directory.

    Returns:
        Path to the written profile file.
    """
    profile = build_profile()
    out = system_root / PROFILE_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(profile, indent=1) + "\n")
    return out


def get_cheat_lines() -> list[str]:
    """Return GameShark-format cheat code lines.

    N64 GameShark format: TTVVAAAA VVVV
      TT = type (80 = 8-bit write, 81 = 16-bit write)
      VV = value byte(s)
      AAAA = address low 32 bits (RDRAM physical address)
      VVVV = repeat value (usually same as VV for 8-bit)
    """
    lines = []
    for addr, val, desc, _cat in UNLOCK_FLAGS:
        # 8-bit write: type=0x80, value=1 byte, address=32-bit RDRAM
        gs_code = f"80{val:02X}{addr & 0xFFFFFFFF:08X} {val:04X}"
        lines.append(f"{desc}: {gs_code}")
    return lines


def verify_profile(system_root: Path) -> dict[str, Any]:
    """Verify the unlock profile exists and matches expected structure.

    Args:
        system_root: Path to the system root directory.

    Returns:
        Dict with verification results.
    """
    profile_file = system_root / PROFILE_PATH
    if not profile_file.exists():
        return {"ok": False, "error": f"Profile not found: {profile_file}"}

    try:
        profile = json.loads(profile_file.read_text())
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"Invalid JSON: {e}"}

    errors = []
    if profile.get("rom", {}).get("sha1") != ROM_SHA1:
        errors.append(f"SHA1 mismatch: {profile.get('rom', {}).get('sha1')}")
    if len(profile.get("cheats", [])) != len(UNLOCK_FLAGS):
        errors.append(
            f"Cheat count mismatch: {len(profile.get('cheats', []))} != {len(UNLOCK_FLAGS)}"
        )

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "cheat_count": len(profile.get("cheats", [])),
        "profile_path": str(profile_file),
    }


if __name__ == "__main__":
    import sys

    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    result = verify_profile(root)
    print(json.dumps(result, indent=2))
    if result["ok"]:
        print("\nGameShark codes:")
        for line in get_cheat_lines():
            print(f"  {line}")
