"""VF4 Evo (PS2) unlock research gate - revision-guarded, evidence-first.

The owned PS2 executable (SLUS_206.16) is pinned by SHA-256. Every candidate
write is bounds-checked against the documented lock surface and refused on any
revision mismatch.

Nothing in this module is runtime-verified: profile_gate() reports
research_pending and the live Play path never reaches a writer for this game.
"""
from __future__ import annotations

import hashlib

GAME_ID = "0b29e35386444551"
PLATFORM = "ps2"
EXECUTABLE_NAME = "SLUS_206.16"
EXECUTABLE_SHA256 = "3606b48549f4860d0af13a8cce3d9b3b59c38e9b80ddc564ab3f77cb194f47c2"

LOCK_SURFACE = {'mc_chara_num': {'file_offset': 3909600, 'original_hex': '090000000c000000020000000b00000002000000080000000c000000030000000d000000', 'size': 36, 'symbol': 'mc_chara_num', 'vaddr': 4958048}, 'release_flag_tbl': {'file_offset': 3049264, 'original_hex': '000000000000010008000000020020000000030080000000040000200000050000020000060000080000070000800000000002008000000002004000000002000002000002000001000002008001000002008002000002004001000002004002', 'size': 96, 'symbol': 'release_flag_tbl', 'vaddr': 4097712}}

CATEGORIES = ['characters', 'costumes', 'extras', 'hidden_characters', 'items', 'modes', 'stages']

INVENTORY = {'characters': [{'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Kairi', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Zabel', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Raptor', 'status': 'unknown'}, {'evidence': {'file_offset': 5141245, 'kind': 'ascii_string_in_owned_executable', 'note': 'name string present in SLUS_206.16; not yet tied to a proven lock check or runtime-eligible entry', 'vaddr': None}, 'name': 'Jack', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Shen', 'status': 'unknown'}, {'evidence': {'file_offset': 3433614, 'kind': 'ascii_string_in_owned_executable', 'note': 'name string present in SLUS_206.16; not yet tied to a proven lock check or runtime-eligible entry', 'vaddr': 4482062}, 'name': 'Lei', 'status': 'unknown'}, {'evidence': {'file_offset': 4666746, 'kind': 'ascii_string_in_owned_executable', 'note': 'name string present in SLUS_206.16; not yet tied to a proven lock check or runtime-eligible entry', 'vaddr': 5715194}, 'name': 'Fei', 'status': 'unknown'}, {'evidence': {'file_offset': 5118207, 'kind': 'ascii_string_in_owned_executable', 'note': 'name string present in SLUS_206.16; not yet tied to a proven lock check or runtime-eligible entry', 'vaddr': None}, 'name': 'Sarah', 'status': 'unknown'}, {'evidence': {'file_offset': 5141398, 'kind': 'ascii_string_in_owned_executable', 'note': 'name string present in SLUS_206.16; not yet tied to a proven lock check or runtime-eligible entry', 'vaddr': None}, 'name': 'Wolf', 'status': 'unknown'}, {'evidence': {'file_offset': 5141263, 'kind': 'ascii_string_in_owned_executable', 'note': 'name string present in SLUS_206.16; not yet tied to a proven lock check or runtime-eligible entry', 'vaddr': None}, 'name': 'Jeff', 'status': 'unknown'}, {'evidence': {'file_offset': 4459190, 'kind': 'ascii_string_in_owned_executable', 'note': 'name string present in SLUS_206.16; not yet tied to a proven lock check or runtime-eligible entry', 'vaddr': 5507638}, 'name': 'Vanessa', 'status': 'unknown'}, {'evidence': {'file_offset': 5241571, 'kind': 'ascii_string_in_owned_executable', 'note': 'name string present in SLUS_206.16; not yet tied to a proven lock check or runtime-eligible entry', 'vaddr': None}, 'name': 'Ben', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Sonia', 'status': 'unknown'}, {'evidence': {'file_offset': 5141317, 'kind': 'ascii_string_in_owned_executable', 'note': 'name string present in SLUS_206.16; not yet tied to a proven lock check or runtime-eligible entry', 'vaddr': None}, 'name': 'Dural', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'God of Destruction', 'status': 'unknown'}], 'costumes': [{'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Costume', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'EX Costume', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Alternate', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Outfit', 'status': 'unknown'}, {'evidence': {'file_offset': 4835811, 'kind': 'ascii_string_in_owned_executable', 'note': 'name string present in SLUS_206.16; not yet tied to a proven lock check or runtime-eligible entry', 'vaddr': None}, 'name': 'Model', 'status': 'unknown'}], 'extras': [{'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Museum', 'status': 'unknown'}, {'evidence': {'file_offset': 4758951, 'kind': 'ascii_string_in_owned_executable', 'note': 'name string present in SLUS_206.16; not yet tied to a proven lock check or runtime-eligible entry', 'vaddr': 5807399}, 'name': 'Gallery', 'status': 'unknown'}, {'evidence': {'file_offset': 4872373, 'kind': 'ascii_string_in_owned_executable', 'note': 'name string present in SLUS_206.16; not yet tied to a proven lock check or runtime-eligible entry', 'vaddr': None}, 'name': 'Ending', 'status': 'unknown'}, {'evidence': {'file_offset': 5100671, 'kind': 'ascii_string_in_owned_executable', 'note': 'name string present in SLUS_206.16; not yet tied to a proven lock check or runtime-eligible entry', 'vaddr': None}, 'name': 'Movie', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Sound Test', 'status': 'unknown'}, {'evidence': {'file_offset': 4513955, 'kind': 'ascii_string_in_owned_executable', 'note': 'name string present in SLUS_206.16; not yet tied to a proven lock check or runtime-eligible entry', 'vaddr': 5562403}, 'name': 'Replay', 'status': 'unknown'}, {'evidence': {'file_offset': 5538036, 'kind': 'ascii_string_in_owned_executable', 'note': 'name string present in SLUS_206.16; not yet tied to a proven lock check or runtime-eligible entry', 'vaddr': None}, 'name': 'Trophy', 'status': 'unknown'}], 'hidden_characters': [{'evidence': {'file_offset': 5141317, 'kind': 'ascii_string_in_owned_executable', 'note': 'name string present in SLUS_206.16; not yet tied to a proven lock check or runtime-eligible entry', 'vaddr': None}, 'name': 'Dural', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'God of Destruction', 'status': 'unknown'}], 'items': [{'evidence': {'file_offset': 5104325, 'kind': 'ascii_string_in_owned_executable', 'note': 'name string present in SLUS_206.16; not yet tied to a proven lock check or runtime-eligible entry', 'vaddr': None}, 'name': 'Item', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Weapon', 'status': 'unknown'}, {'evidence': {'file_offset': 5115898, 'kind': 'ascii_string_in_owned_executable', 'note': 'name string present in SLUS_206.16; not yet tied to a proven lock check or runtime-eligible entry', 'vaddr': None}, 'name': 'Parts', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Vehicle', 'status': 'unknown'}], 'modes': [{'evidence': {'file_offset': 5116037, 'kind': 'ascii_string_in_owned_executable', 'note': 'name string present in SLUS_206.16; not yet tied to a proven lock check or runtime-eligible entry', 'vaddr': None}, 'name': 'Arcade', 'status': 'unknown'}, {'evidence': {'file_offset': 5114921, 'kind': 'ascii_string_in_owned_executable', 'note': 'name string present in SLUS_206.16; not yet tied to a proven lock check or runtime-eligible entry', 'vaddr': None}, 'name': 'Quest', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Time Attack', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Network', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Museum', 'status': 'unknown'}, {'evidence': {'file_offset': 4733711, 'kind': 'ascii_string_in_owned_executable', 'note': 'name string present in SLUS_206.16; not yet tied to a proven lock check or runtime-eligible entry', 'vaddr': 5782159}, 'name': 'Battle', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Boss', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Eagle', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Bear', 'status': 'unknown'}], 'stages': [{'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Jungle', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Labyrinth', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Great Wall', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Aqual', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Shipwreck', 'status': 'unknown'}, {'evidence': {'file_offset': 5123151, 'kind': 'ascii_string_in_owned_executable', 'note': 'name string present in SLUS_206.16; not yet tied to a proven lock check or runtime-eligible entry', 'vaddr': None}, 'name': 'Lighthouse', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Tundra', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Lava', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Heaven', 'status': 'unknown'}, {'evidence': {'file_offset': 4438088, 'kind': 'ascii_string_in_owned_executable', 'note': 'name string present in SLUS_206.16; not yet tied to a proven lock check or runtime-eligible entry', 'vaddr': 5486536}, 'name': 'Hell', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Dinosaur', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Adam', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Blood River', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Burial', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Babel', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Voldir', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Waterfall', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Canyon', 'status': 'unknown'}, {'evidence': {'kind': 'no_ascii_string_match', 'note': 'string not found in SLUS_206.16; absence of a string is not proof the content is absent'}, 'name': 'Ruins', 'status': 'unknown'}, {'evidence': {'file_offset': 5125887, 'kind': 'ascii_string_in_owned_executable', 'note': 'name string present in SLUS_206.16; not yet tied to a proven lock check or runtime-eligible entry', 'vaddr': None}, 'name': 'Tower', 'status': 'unknown'}]}

HYPOTHESES = {
    "H1": {
        "id": "H1",
        "claim": ("release_flag_tbl holds 24 u32 per-entry release flags; a fully set slot "
                  "(0xffffffff) marks that entry released."),
        "status": "unverified_hypothesis",
        "why": ("The table was located by ELF symbol name and byte pattern only. The consuming "
                "function has not been decompiled, so the slot/bit layout is unproven and the "
                "hypothesis must not be treated as a proven unlock."),
    },
}


def profile_gate() -> dict:
    """Read-only research state for the VF4 Evo (PS2) unlock request."""
    return {
        "reason": ("VF4 Evo (PS2) unlock surface and category inventory are recorded for the owned "
                   "executable revision, but the on-load unlock routine is not runtime-verified and "
                   "no proven write target exists yet; the Play path must not modify the executable."),
        "scope": list(CATEGORIES),
        "evidence": {
            "executable": EXECUTABLE_NAME,
            "executable_sha256": EXECUTABLE_SHA256,
            "lock_surface": LOCK_SURFACE,
            "inventory": INVENTORY,
            "hypotheses": HYPOTHESES,
        },
        "blockers": [
            "release_flag_tbl consumers are not decompiled, so the flag layout (hypothesis H1) is unproven.",
            "No category entry is proven runtime-eligible: the inventory records ASCII string evidence only.",
            "No live acceptance run has confirmed an unlock on load for any category.",
        ],
        "next": ("Decompile the function that reads release_flag_tbl and confirm the slot/bit layout, "
                 "then runtime-verify one category on the test worker before enabling any write."),
    }


def revision_ok(buf: bytes, expected_sha256: str = EXECUTABLE_SHA256) -> bool:
    """True only when buf is the pinned owned executable revision."""
    return hashlib.sha256(buf).hexdigest() == expected_sha256


def plan_patches(buf: bytes) -> list:
    """Candidate writes (hypothesis H1), bounded to the documented lock surface."""
    out = []
    rf = LOCK_SURFACE["release_flag_tbl"]
    base = rf["file_offset"]
    for slot in range(rf["size"] // 4):
        off = base + slot * 4
        orig = buf[off:off + 4]
        if len(orig) != 4:
            continue
        out.append({"offset": off, "original": orig.hex(), "patched": "ffffffff",
                    "symbol": "release_flag_tbl", "slot": slot, "hypothesis": "H1"})
    return out


def apply_candidate_unlocks(buf: bytes, expected_sha256: str = EXECUTABLE_SHA256) -> dict:
    """Apply hypothesis H1 to a buffer whose revision matches the pin."""
    if not revision_ok(buf, expected_sha256):
        return {"applied": False, "reason": "revision-mismatch", "patches": 0}
    patches = plan_patches(buf)
    if not patches:
        return {"applied": False, "reason": "no-lock-surface", "patches": 0}
    out = bytearray(buf)
    for p in patches:
        out[p["offset"]:p["offset"] + 4] = bytes.fromhex(p["patched"])
    return {"applied": True, "reason": "hypothesis-H1-applied-not-runtime-verified",
            "patches": len(patches), "buffer": bytes(out)}


def inventory_summary() -> dict:
    """Per-category inventory counts plus the entries with string evidence."""
    return {cat: {"total": len(entries),
                  "string_evidence": [e["name"] for e in entries
                                      if e["evidence"]["kind"] == "ascii_string_in_owned_executable"]}
            for cat, entries in INVENTORY.items()}
