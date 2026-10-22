"""SoulCalibur III (PS2, NTSC-U SLUS_212.16) unlock-on-load: static evidence + revision-guarded candidate profile (#2242).

Status: CANDIDATE, NOT runtime verified.  Nothing here edits a disc, ELF or memory card.  ``profile_for`` reports
``candidate_pending_runtime``.  ``codes_json()`` is the would-be profiles/gamedata/afe447a632bd5e6b-codes.json
(``verified: false``; the publisher only accepts gbox/tests/docs paths, so the file is generated, not committed) and
``game_unlocks.post_launch`` holds nothing until a fresh-boot acceptance writes it with ``verified: true``.

What the owned executable proves (SLUS_212.16, sha256 ``EXE_SHA256``, read with Capstone MIPS64/LE; addresses are
EE virtual addresses):

* The progress/unlock block is a table of 4-bit states at 0x504118, 2404 entries (0x964).  ``0x001FF048`` is
  set_state(index, state) (index < 0x964, state < 7) and ``0x001FF0B8`` is get_state(index); both go through the
  pointer at 0x5045D0 (initialised to 0x504118 by ``0x001FF75C``/``0x002004B0``).  ``0x001FF7A0`` turns a state of 5
  into 6, so 5 is "unlocked, new" and 6 is "unlocked, seen" - 6 is the largest legal state and raising to it is
  monotonic.  ``0x001FF7E0`` resets states 1 and 4 to 0 (transient states), so those are never written by this profile.
* ``0x002B9190`` copies 0x4A0 bytes of save buffer (+0x12CFC) into 0x504118 on load and ``0x002004B0`` copies it back;
  the game, not gBox, owns the memory-card file and its checksum.  The profile therefore holds RAM only and never
  edits the card file ("monotonic progress edits" through the game's own autosave).
* The category byte ranges below come from the published NTSC-U code set (CheatDevicePS2 via the PCSX2 cheat
  collection, CRC 027C604C).  The ELF confirms the table, accessor and state semantics; it does NOT yet map each
  nibble index to a named entry, so per-entry status is ``unknown`` until runtime selection proves it.
* The same code set also holds two PAL-style writes (0x509898 x 0xCB words, 0x509B38 x 0x74 words).  In this
  executable those addresses are character/costume parameter data (floats, struct tables), not flags, so they are
  deliberately NOT applied.  The "Unlock Everything" run also overshoots the table by 0x6 bytes into 0x5045CC (a live
  variable); this profile clamps to entry 0x964.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

GAME_ID = "afe447a632bd5e6b"
PLATFORM = "ps2"
TITLE = "SoulCalibur III (USA)"
BOOT = "SLUS_212.16"
EXE_SHA256 = "3f9102baa6b5a84fde9ee4161dd8e0c70f4ba7cb8bec8c5dea27b555f1185570"
DISC_ISO_SHA256 = "92e578c32f7e29cd70d3428ef72d91b717bb532085a69ef0cdf7c842f7a6ce48"
CHD_SHA256 = "e1cc4675f0dc11e19aaac0cd5d5c2bd3d4c2c2eda91e8932c2195539fc71dd62"
PROFILE_NAME = "sc3-ps2-usa-slus21216-state-table-candidate-v1"

TABLE_ADDR = 0x504118
TABLE_ENTRIES = 0x964            # 4-bit states
TABLE_BYTES = TABLE_ENTRIES // 2
SAVE_COPY_BYTES = 0x4A0          # what the game's own save copy moves (0x2004B0 / 0x2B9190)
SAVE_BUFFER_OFFSET = 0x12CFC
POINTER_ADDR = 0x5045D0
FULL_STATE = 6                   # "unlocked, seen"; 5 = unlocked/new, 1 and 4 are transient (reset by 0x1FF7E0)
FUNCTIONS = {"set_state": 0x1FF048, "get_state": 0x1FF0B8, "new_to_seen": 0x1FF7A0, "reset_transient": 0x1FF7E0,
             "save_to_ram": 0x2B9190, "ram_to_save": 0x2004B0}
CATEGORIES = ("characters", "hidden_characters", "modes", "levels", "stages", "costumes", "items", "extras")

# (category in the request schema, label, first byte address, byte length) from the published NTSC-U code set.
RANGES = (
    ("characters", "Unlock All Characters (fighters, bonus characters)", 0x504118, 22),
    ("modes", "Unlock All Modes", 0x50413D, 13),
    ("items", "Unlock All Weapons", 0x50414D, 155),
    ("extras", "Unlock All Art Gallery", 0x5041E7, 147),
    ("extras", "Unlock All Movies", 0x50427A, 4),
    ("extras", "Unlock All Exhibition Theater", 0x50427E, 13),
    ("extras", "Unlock All Character Profiles", 0x504290, 12),
    ("levels", "Unlock All Single Player - Soul Arena Missions", 0x504386, 26),
    ("items", "Unlock All Armor", 0x5043B8, TABLE_ADDR + TABLE_BYTES - 0x5043B8),
)
NOT_PRESENT_OR_UNAPPLIED = {
    "pal_0x509898_characters_weapons": "PAL address; in SLUS_212.16 it holds parameter tables, not flags - not applied",
    "pal_0x509B38_creation_costumes": "PAL address; in SLUS_212.16 it holds float/struct data - not applied",
    "overshoot_0x5045CA_0x5045CF": "published 'Unlock Everything' writes past the 2404-entry table onto a live variable - clamped",
}
# Roster strings in .rodata (display order, ELF evidence only; not yet tied to unlock indices).
ROSTER_ORDER = ("Mitsurugi", "Seong Mi-na", "Taki", "Maxi", "Voldo", "Sophitia", "Siegfried", "Rock", "Ivy",
                "Kilik", "Xianghua", "Lizardman", "Yoshimitsu", "Nightmare", "Astaroth", "Cervantes", "Raphael",
                "Talim", "Cassandra", "Charade", "Yun-seong", "Assassin", "Berserker", "Setsuka", "Tira",
                "Zasalamel", "Olcadan", "Abyss", "Night Terror", "Will-o'-the-Wisp", "Doppelganger", "Shadow Master")
CREATION_ARCHETYPES = ("Miser", "Greed", "Arthur", "Hwang", "Luna", "Valeria", "Hualin", "Girardot", "Demuth",
                       "Aurelia", "Chester", "Strife", "Abelia", "Lynette", "Li Long", "Revenant")


def _merged_bytes() -> list[tuple[int, int]]:
    spans = sorted((a, a + n) for _, _, a, n in RANGES)
    out: list[list[int]] = []
    for lo, hi in spans:
        if out and lo <= out[-1][1]:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    for lo, hi in out:
        assert TABLE_ADDR <= lo < hi <= TABLE_ADDR + TABLE_BYTES, (hex(lo), hex(hi))
    return [(lo, hi) for lo, hi in out]


def covered_entries() -> list[int]:
    """Sorted state-table indices this profile raises to FULL_STATE."""
    idx = []
    for lo, hi in _merged_bytes():
        idx += range((lo - TABLE_ADDR) * 2, (hi - TABLE_ADDR) * 2)
    return idx


def apply_to_table(table: bytes) -> bytes:
    """Monotonic overlay on a 0x4B2-byte (or larger) state table image: covered entries below FULL_STATE become
    FULL_STATE, entries already >= FULL_STATE and every uncovered entry keep their value.  Pure; never touches disk."""
    if len(table) < TABLE_BYTES:
        raise ValueError(f"state table image too short: {len(table)} < {TABLE_BYTES}")
    out = bytearray(table)
    for i in covered_entries():
        byte, high = divmod(i, 2)
        cur = (out[byte] >> 4) if high else (out[byte] & 0xF)
        if cur > FULL_STATE:
            raise ValueError(f"entry {i:#x} holds illegal state {cur}; refusing to overlay")
        if cur < FULL_STATE:
            out[byte] = (out[byte] & 0x0F) | (FULL_STATE << 4) if high else (out[byte] & 0xF0) | FULL_STATE
    return bytes(out)


def code_lines() -> list[str]:
    """Plain 'ADDRESS VALUE' constant writes (gbox.cheats.decode, non-native platform path), widest chunk first.
    Each write is a 0x66 byte run inside a covered range, so lines never touch an uncovered byte."""
    lines = []
    for lo, hi in _merged_bytes():
        if hi - lo < 2:
            raise ValueError("code lines need at least a 2-byte covered run")
        a = lo
        while a < hi:
            n = min(4, hi - a)
            if n == 1:                       # decode() takes >= 2 bytes: overlap the previous (covered) byte
                a -= 1
                n = 2
            lines.append(f"{a:08X} {'66' * n}")
            a += n
    return lines


def expected_counts() -> dict:
    per = {c: 0 for c in CATEGORIES}
    for cat, _, a, n in RANGES:
        per[cat] += 2 * n
    return per


def inventory() -> dict:
    """Every request category with entries, evidence and status.  Nothing is claimed unlocked until runtime proof."""
    per_range = [{"category": c, "label": label, "first_address": f"{a:#x}", "bytes": n,
                  "entries": 2 * n, "first_index": (a - TABLE_ADDR) * 2} for c, label, a, n in RANGES]
    statuses = {
        "characters": ("unknown", "state range 0..43 (22 bytes); roster strings in .rodata but no index->name map yet"),
        "hidden_characters": ("unknown", "bonus characters share the characters range; Charade/Olcadan/Abyss/Night Terror/"
                                          "Will-o'-the-Wisp/Doppelganger/Shadow Master strings exist in the ELF"),
        "modes": ("unknown", "13-byte range 0x50413D; no mode names mapped"),
        "levels": ("unknown", "Soul Arena missions range 0x504386 (26 bytes)"),
        "stages": ("unknown", "no stage-lock range in the published code set; stage.olk has 820 entries, lock logic untraced"),
        "costumes": ("unknown", "Create-a-character costume/class/slot flags: only the PAL-address code exists; not applied"),
        "items": ("unknown", "weapon (155 B) and armor ranges"),
        "extras": ("unknown", "art gallery, movies, exhibition theater, character profiles ranges"),
    }
    return {"game_id": GAME_ID, "platform": PLATFORM, "executable": BOOT, "exe_sha256": EXE_SHA256,
            "ranges": per_range, "entry_counts": expected_counts(),
            "categories": {c: {"status": s, "evidence": e} for c, (s, e) in statuses.items()},
            "roster_order_rodata": list(ROSTER_ORDER), "creation_archetypes_rodata": list(CREATION_ARCHETYPES),
            "not_applied": NOT_PRESENT_OR_UNAPPLIED, "runtime_verified": False}


def verify_executable(path) -> dict:
    """Revision guard: the file must be the exact owned SLUS_212.16 (sha256) and a little-endian MIPS ELF, and the
    state-table accessors must match the traced instruction words."""
    data = Path(path).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    ok = sha == EXE_SHA256 and data[:4] == b"\x7fELF" and struct.unpack_from("<H", data, 18)[0] == 8
    return {"ok": ok, "sha256": sha, "expected": EXE_SHA256, "size": len(data)}


def profile() -> dict:
    return {"game_id": GAME_ID, "title": TITLE, "platform": PLATFORM, "profile": PROFILE_NAME,
            "status": "candidate_pending_runtime", "verified": False, "runtime_verified": False,
            "executable": {"name": BOOT, "sha256": EXE_SHA256}, "disc_iso_sha256": DISC_ISO_SHA256,
            "chd_sha256": CHD_SHA256, "table": {"address": f"{TABLE_ADDR:#x}", "entries": TABLE_ENTRIES,
                                                "full_state": FULL_STATE, "pointer": f"{POINTER_ADDR:#x}"},
            "functions": {k: f"{v:#x}" for k, v in FUNCTIONS.items()},
            "scope": list(CATEGORIES), "inventory": inventory(),
            "save_effect": "RAM hold only; the game autosaves what it unlocks. No memory-card file is edited by gBox. "
                           "Rollback = disable the held cheat entry (cheats op) or restore the card backup.",
            "next": "Fresh boot on i9-NUC or Spark (idle, 2% audio, isolated card): confirm the hold lands, then select "
                    "and play each character/mode, second launch, rollback; only then set verified true."}


def codes_json() -> dict:
    """Content of profiles/gamedata/afe447a632bd5e6b-codes.json (verified false: not held by post_launch yet)."""
    return {"game_id": GAME_ID, "title": TITLE, "platform": PLATFORM, "profile": PROFILE_NAME, "verified": False,
            "exe_sha256": EXE_SHA256,
            "codes": [{"desc": "SoulCalibur III state table: raise covered unlock entries to 6 (unlocked, seen)",
                       "lines": code_lines()}],
            "scope": list(CATEGORIES),
            "evidence": {"table": f"{TABLE_ADDR:#x} x {TABLE_ENTRIES} nibbles",
                         "accessors": {k: f"{v:#x}" for k, v in FUNCTIONS.items()},
                         "ranges_source": "published NTSC-U code set (CRC 027C604C), cross-checked against the ELF table",
                         "runtime": "pending"}}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--write-profile", action="store_true")
    ap.add_argument("--exe")
    ns = ap.parse_args(argv)
    if ns.exe:
        print(json.dumps(verify_executable(ns.exe)))
    if ns.write_profile:
        p = Path(__file__).resolve().parent.parent / "profiles/gamedata" / f"{GAME_ID}-codes.json"
        p.write_text(json.dumps(codes_json(), indent=1) + "\n", encoding="utf-8")
        print(p)
    else:
        print(json.dumps(profile(), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
