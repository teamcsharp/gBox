"""Shadow In Sonic 1 (Genesis) unlock-on-load candidate profile (#2226).

Static evidence only; gameplay_verified stays False until a read-back plus
play-through runs on an authorized i9-NUC/Spark session. The ROM is a Sonic 1
REV01 hack; its title/level-select/pause/debug code keeps the stock engine's four
cheat flags in 68K work RAM ($FFFFE0-$FFFFE3). Everything gBox can unlock here is
gated by those flags, so the routine sets exactly those four bytes, in RAM, and
never edits the ROM or the battery save.

Every site below was read from the owned ROM (sha256 ROM_SHA256) and is re-checked
byte-for-byte by ``guard`` so a custom build with a moved engine is refused instead
of poked.
"""
from __future__ import annotations

import hashlib

GAME_ID = "1fff93531f10c256"
PLATFORM = "genesis"
TITLE = "Shadow In Sonic 1"
ROM_SHA256 = "a22564d49d28bfab70e2046b1c08d7a6a19f6bf4183491e0280ef916fb4863ce"
ROM_SIZE = 0x100000
HEADER_NAME = b"SHADOW THE HEDGEHOG IN SONIC THE HEDGEHOG"
HEADER_SERIAL = b"GM 00001009-00"

# flag -> (68K RAM address, ROM reader offsets, expected bytes at each reader: tst.b (abs.w) + beq)
FLAGS = {
    "f_levselcheat": (0xFFFFE0, (0x33AA,), "4a38ffe067"),
    "f_slomocheat": (0xFFFFE1, (0x132C,), "4a38ffe167"),
    "f_debugcheat": (0xFFFFE2, (0x3AF4, 0x4870), "4a38ffe267"),
    "f_creditscheat": (0xFFFFE3, (0x342A, 0x17AC6), "4a38ffe367"),
}

# Title code tables (Up,Down,Left,Right,0,$FF) that set the flags in the stock game.
CODE_TABLES = (0x350C, 0x3512)
CODE_BYTES = bytes([1, 2, 4, 8, 0, 0xFF])
# Level-select order table (zone,act word pairs) read from the ROM at LEVSEL_TABLE.
LEVSEL_TABLE = 0x34E2

CATEGORIES = ("characters", "hidden_characters", "modes", "levels", "stages", "costumes", "items", "extras")


def guard(rom: bytes) -> dict:
    """Refuse anything but this engine layout. ``exact`` is the stock owned ROM hash."""
    digest = hashlib.sha256(rom).hexdigest()
    problems = []
    if len(rom) != ROM_SIZE:
        problems.append(f"size {len(rom):#x} != {ROM_SIZE:#x}")
    if not rom[0x100:0x110].startswith(b"SEGA MEGA DRIVE"):
        problems.append("no SEGA MEGA DRIVE header")
    if len(rom) >= 0x18E and HEADER_SERIAL not in rom[0x180:0x18E] + b"":
        problems.append("serial differs")
    for name, (_ram, sites, expect) in FLAGS.items():
        want = bytes.fromhex(expect)
        for off in sites:
            if rom[off:off + len(want)] != want:
                problems.append(f"{name} reader at {off:#x} differs")
    for off in CODE_TABLES:
        if rom[off:off + len(CODE_BYTES)] != CODE_BYTES:
            problems.append(f"code table at {off:#x} differs")
    return {"ok": not problems, "exact": digest == ROM_SHA256, "sha256": digest, "problems": problems}


def unlock_ops() -> list[dict]:
    """Constant byte writes (68K RAM), one per flag. Idempotent and monotonic (0 -> 1 only)."""
    return [{"flag": n, "address": a, "width": 1, "value": 1, "hex_bytes": "01",
             "readers": [hex(s) for s in sites], "database_verified": False, "gameplay_verified": False}
            for n, (a, sites, _e) in FLAGS.items()]


def levelselect_entries(rom: bytes) -> list[tuple[int, int]]:
    """(zone, act) pairs of the level-select menu as stored in this ROM (80 00 = sound test)."""
    out, off = [], LEVSEL_TABLE
    while off + 2 <= len(rom):
        z, a = rom[off], rom[off + 1]
        out.append((z, a))
        if z == 0x80:
            break
        off += 2
    return out


def inventory() -> dict:
    """Category inventory with the evidence level; no entry is claimed runtime-verified."""
    def e(state, why):
        return {"state": state, "evidence": why}
    return {
        "characters": e("not_present", "Sonic is the only player object selected by this engine; no character-select flag is read"),
        "hidden_characters": e("unknown", "no static reader of a selectable-character flag found; replaced player art is not a lock"),
        "modes": {"level_select": e("unlocked_by_flag", "f_levselcheat read at 0x33aa"),
                  "debug_mode": e("unlocked_by_flag", "f_debugcheat read at 0x3af4 and 0x4870"),
                  "slow_motion": e("unlocked_by_flag", "f_slomocheat read at 0x132c"),
                  "hidden_credits": e("unlocked_by_flag", "f_creditscheat read at 0x342a and 0x17ac6"),
                  "sound_test": e("unlocked_by_flag", "level-select entry 80 00")},
        "levels": e("unlocked_by_flag", "level select lists every zone/act pair in the table at 0x34e2"),
        "stages": e("unlocked_by_flag", "special stage (07 00) is a level-select entry; no emerald gate read"),
        "costumes": e("not_present", "no costume table in the engine"),
        "items": e("not_present", "no purchasable/unlockable item table"),
        "extras": e("unknown", "hack-specific extras not yet traced"),
    }


def profile() -> dict:
    return {"game_id": GAME_ID, "platform": PLATFORM, "title": TITLE, "profile": "shadow-in-sonic1-ram-flags-candidate-v1",
            "verified": False, "gameplay_verified": False, "rom_sha256": ROM_SHA256,
            "scope": ["level select", "debug mode", "slow motion", "hidden credits", "sound test"],
            "ops": unlock_ops(), "inventory": inventory(),
            "save_effect": "none: RAM-only, ROM and battery save untouched",
            "rollback": "write 00 to the four bytes or relaunch; nothing persists",
            "next": "Read back $FFE0-$FFE3 on an authorized i9-NUC/Spark session, open the level select, enter each entry and debug mode, then second launch."}


def pre_launch(rom: bytes | None = None) -> dict:
    prof = profile()
    state = "candidate_pending_verification"
    if rom is not None:
        g = guard(rom)
        if not g["ok"]:
            return {"state": "refused", "applied": False, "reason": "; ".join(g["problems"])[:500], "guard": g}
        prof["guard"] = g
    return {"state": state, "applied": False, "profile": prof["profile"], "scope": prof["scope"],
            "ops": prof["ops"], "next": prof["next"]}
