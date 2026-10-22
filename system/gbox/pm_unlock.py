"""Paper Mario (USA) N64 unlock-on-load save overlay (#2205), candidate profile.

Layout comes from the pmret/papermario decomp (``ver/us``) whose US ROM sha1
(3837f44c...) matches the owned ROM. Flash save: physical slot n starts at flash
byte n*0x4000, SaveData is 0x1380 bytes (big-endian), checksum crc1 = sum of all
big-endian s32 words with crc1=0/crc2=~0 and crc2 = ~crc1 (fio.c). Not
gameplay-verified: the flash endianness of the emulator image and the in-game
result still need live acceptance (see ``live_acceptance_plan``).

Scope is deliberately limited to roster/progression *capability* fields; story
flags are never touched so the game cannot be put in an impossible state. Empty
or invalid slots are skipped, never fabricated. Planning/pure functions only;
``apply`` writes only after a byte-exact backup and ``rollback`` restores it.
"""
from __future__ import annotations

import hashlib
import shutil
import struct
from pathlib import Path

GAME_ID = "b74d223b195befba"
PLATFORM = "n64"
TITLE = "Paper Mario (USA)"
ROM_SHA1 = "3837f44cda784b466c9a2d99df70d77c322b97a0"
ROM_SHA256 = "9ec6d2a5c2fca81ab86312328779fd042b5f3b920bf65df9f6b87b376883cb5b"

MAGIC = b"Mario Story 006\x00"
SAVE_SIZE = 0x1380
SLOT_STRIDE = 0x4000
PHYSICAL_SLOTS = 6
FLASH_SIZE = 0x20000
CRC1, CRC2 = 0x30, 0x34
PLAYER = 0x40
# PlayerData offsets (relative to PLAYER)
BOOTS, HAMMER, HAS_AC = 0x000, 0x001, 0x00A
PARTNERS, PARTNER_SIZE = 0x014, 8
PARTNER_NAMES = ["Goombario", "Kooper", "Bombette", "Parakarry", "Goompa", "Watt",
                 "Sushie", "Lakilester", "Bow", "Goombaria", "Twink"]  # ids 1..11
MAX_STAR_POWER, STAR_BEAM = 0x28E, 0x292

CATEGORIES = {
    "characters": "partners 1-11 enabled (PlayerData.partners[].enabled)",
    "hidden_characters": "Goompa/Goombaria/Twink are partners 5/10/11, enabled with the roster",
    "modes": "none in this build (no separate mode lock exists in the decomp)",
    "levels": "no level lock; chapters follow story flags, intentionally untouched",
    "stages": "no stage lock in this build",
    "costumes": "none in this build",
    "items": "boots/hammer to level 2 and action commands enabled; inventory untouched",
    "extras": "star power max/beam level raised; story flags untouched",
}


def rom_guard(rom: Path) -> dict:
    data = Path(rom).read_bytes()
    sha1 = hashlib.sha1(data).hexdigest()
    return {"ok": sha1 == ROM_SHA1, "expected": ROM_SHA1, "actual": sha1,
            "sha256": hashlib.sha256(data).hexdigest()}


def checksum(save: bytes) -> int:
    buf = bytearray(save[:SAVE_SIZE])
    buf[CRC1:CRC1 + 8] = struct.pack(">II", 0, 0xFFFFFFFF)
    return sum(struct.unpack(">%dI" % (SAVE_SIZE // 4), bytes(buf))) & 0xFFFFFFFF


def slot_valid(save: bytes) -> bool:
    if len(save) < SAVE_SIZE or save[:16] != MAGIC:
        return False
    c1, c2 = struct.unpack_from(">II", save, CRC1)
    return c1 == (~c2 & 0xFFFFFFFF) and checksum(save) == c1


def seal(save: bytearray) -> None:
    c = checksum(bytes(save))
    struct.pack_into(">II", save, CRC1, c, ~c & 0xFFFFFFFF)


def unlock_save(save: bytes) -> bytes:
    """Monotonic upgrade of one valid slot; never lowers a field."""
    if not slot_valid(save):
        raise ValueError("slot is not a valid Paper Mario save")
    out = bytearray(save[:SAVE_SIZE])
    p = PLAYER
    out[p + BOOTS] = max(out[p + BOOTS], 2)
    out[p + HAMMER] = max(out[p + HAMMER], 2)
    out[p + HAS_AC] = 1
    for pid in range(1, 12):
        o = p + PARTNERS + pid * PARTNER_SIZE
        out[o] = 1
    out[p + MAX_STAR_POWER] = max(out[p + MAX_STAR_POWER], 7)
    out[p + STAR_BEAM] = max(out[p + STAR_BEAM], 2)
    seal(out)
    return bytes(out) + bytes(save[SAVE_SIZE:])


def unlock_flash(flash: bytes) -> tuple[bytes, list[int]]:
    """Upgrade every valid slot in a 128KB flash image; returns (image, slots changed)."""
    if len(flash) != FLASH_SIZE:
        raise ValueError(f"flash image must be {FLASH_SIZE:#x} bytes, got {len(flash):#x}")
    out, changed = bytearray(flash), []
    for n in range(PHYSICAL_SLOTS):
        off = n * SLOT_STRIDE
        chunk = bytes(out[off:off + SAVE_SIZE])
        if slot_valid(chunk):
            new = unlock_save(chunk)
            if new != chunk:
                out[off:off + SAVE_SIZE] = new
                changed.append(n)
    return bytes(out), changed


def apply(flash_path: Path, rom: Path, backup_dir: Path) -> dict:
    guard = rom_guard(rom)
    if not guard["ok"]:
        return {"state": "refused", "applied": False, "reason": "ROM revision mismatch", "guard": guard}
    flash_path = Path(flash_path)
    original = flash_path.read_bytes()
    new, changed = unlock_flash(original)
    if not changed:
        return {"state": "no_valid_save", "applied": False, "guard": guard,
                "reason": "No valid slot to upgrade; a save is never fabricated."}
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / (flash_path.name + "." + hashlib.sha256(original).hexdigest()[:12] + ".bak")
    if not backup.exists():
        shutil.copy2(flash_path, backup)
    flash_path.write_bytes(new)
    return {"state": "applied_unverified", "applied": True, "slots": changed, "backup": str(backup),
            "original_sha256": hashlib.sha256(original).hexdigest(),
            "result_sha256": hashlib.sha256(new).hexdigest(), "guard": guard}


def rollback(flash_path: Path, backup: Path) -> dict:
    shutil.copy2(backup, flash_path)
    return {"restored": True, "sha256": hashlib.sha256(Path(flash_path).read_bytes()).hexdigest()}


def profile() -> dict:
    return {"game_id": GAME_ID, "platform": PLATFORM, "title": TITLE, "rom_sha1": ROM_SHA1,
            "profile": "pm-n64-flash-save-overlay-candidate-v1", "verified": False,
            "gameplay_verified": False, "scope": dict(CATEGORIES),
            "exclusions": ["story flags", "inventory/badges contents", "empty or invalid slots"],
            "evidence": {"layout": "pmret/papermario ver/us include/common_structs.h, src/fio.c",
                         "rom_sha1_matches_decomp": True}}


def live_acceptance_plan() -> list[str]:
    return ["Run on i9-NUC/Spark only, idle, 2% audio; never JAYBUILTFINALE.",
            "Locate the emulator flash save file; confirm size 0x20000 and endianness (slot magic 'Mario Story 006' readable).",
            "Back up, apply(), boot, load the slot, confirm partners menu shows all 11 and boots/hammer level 2.",
            "Second launch must load the save without 'corrupt' prompt; rollback() restores original sha256."]
