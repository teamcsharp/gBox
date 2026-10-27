"""Super Bust-A-Move (PS2) -- mode/zone select lock inventory (request #2250).

Milestone: a pinned, static-evidence inventory of the mode-select screens'
lock checks in the owned PS2 executable, with the exact virtual addresses,
instruction words and format strings that a later runtime patch or unlock
routine would have to target.

Hard rules (same as the other unlock profiles):
  * Nothing here is verified.  ``verified`` stays False until a runtime
    acceptance run selects a locked zone/round/bubble on the i9-NUC or the
    Spark and shows the game accepting it.
  * No memory writes and no game launch happen in this module.
  * Every address below was read from the executable whose SHA-256 is
    ``EXECUTABLE_SHA256``; the test suite re-checks each one word for word.
"""
from __future__ import annotations

import os

GAME_ID = "6cd93f2e36885f31"
TITLE = "Super Bust-A-Move (PS2)"
PLATFORM = "ps2"

CATEGORIES = ("characters", "hidden_characters", "modes", "levels",
              "stages", "costumes", "items", "extras")

#: SHA-256 of the owned executable that was disassembled for these findings.
EXECUTABLE_SHA256 = "eeb913a6eac79a58d8424dc18190310f1ae5d14d762dec5a339f44ad9870d965"

#: The executable is one PT_LOAD segment: file offset 0x1000 -> vaddr 0x100000.
SEG_FILE_OFFSET = 0x1000
SEG_VADDR = 0x100000


def vaddr_to_offset(vaddr: int) -> int:
    """File offset of ``vaddr`` inside the owned executable."""
    return vaddr - SEG_VADDR + SEG_FILE_OFFSET


def owned_executable_path() -> str:
    """Where the owned executable lives in the gBox cache (may be absent)."""
    return os.path.expanduser(
        "~/gBox_alt/gbox-cache/ps2/%s/inventory/SLUS_201.15" % GAME_ID)


#: u32 global read by the mode-select screen: == 1 draws the wide selection
#: panel, any other value draws the narrow one.  It is 0 on disk (.sdata), so
#: the game sets it at runtime -- it is the switch a patch would flip.
PANEL_GLOBAL_VADDR = 0x00571640
PANEL_GLOBAL_ON_DISK = 0x00000000

#: u32 runtime pointer to the mode/zone table object.  0 on disk.
MODE_TABLE_PTR_VADDR = 0x005713DC

#: The zone-select screen, file 0x001192b4 - 0x00119340.
LOCK_SITE = {
    "vaddr_start": 0x001192B4,
    "vaddr_end": 0x00119340,
    "sprintf_vaddr": 0x001DD410,
    "buffer_vaddr": 0x005D9110,
    "format_selectable_vaddr": 0x00559F68,
    "format_only_a_vaddr": 0x00559F88,
    "zone_index_slot": "4($fp)",
    "key_index_slot": "8($fp)",
    "key_index_means": ("0 -> only key A is selectable (locked); "
                        "n -> key n + 0x41 ('A') is selectable"),
}

#: The round-select screen, file 0x00119678 - 0x001196E0.
ROUND_LOCK_SITE = {
    "vaddr_start": 0x00119654,
    "vaddr_end": 0x001196E0,
    "gate_vaddr": 0x00119658,
    "gate_word": 0x10400013,
    "sprintf_vaddr": 0x001DD410,
    "buffer_vaddr": 0x005D9110,
    "format_selectable_vaddr": 0x00559FB8,
    "format_only_one_vaddr": 0x00559FD8,
    "round_index_slot": "0x0018($t9)",
    "round_index_means": ("0 -> only round 1 is selectable (locked); "
                          "n -> round n is selectable"),
}

#: The bubble-select screen, file 0x00119A08 - 0x00119A70.
BUBBLE_LOCK_SITE = {
    "vaddr_start": 0x001199E4,
    "vaddr_end": 0x00119A70,
    "gate_vaddr": 0x001199E8,
    "gate_word": 0x10400013,
    "sprintf_vaddr": 0x001DD410,
    "buffer_vaddr": 0x005D9110,
    "format_selectable_vaddr": 0x0055A008,
    "format_only_one_vaddr": 0x0055A028,
    "bubble_index_slot": "0x0018($t9)",
    "bubble_index_means": ("0 -> only bubble size 1 is selectable (locked); "
                           "n -> bubble size n is selectable"),
}

#: The instructions that implement the lock, read word for word.
INSTRUCTIONS = [
    {"vaddr": 0x001191C0, "word": 0x3C020057, "asm": "lui $v0, 0x57"},
    {"vaddr": 0x001191C4, "word": 0x8C421640, "asm": "lw $v0, 0x1640($v0)   # -> u32 global 0x571640"},
    {"vaddr": 0x001191C8, "word": 0x24030001, "asm": "addiu $v1, $zero, 1"},
    {"vaddr": 0x001191CC, "word": 0x1443001E, "asm": "bne $v0, $v1, 0x00119248  # != 1 -> narrow panel"},
    {"vaddr": 0x00119248, "word": 0x3C020057, "asm": "lui $v0, 0x57  (narrow panel branch)"},
    {"vaddr": 0x001192B4, "word": 0x8FC20008, "asm": "lw $v0, 8($fp)   # per-entry key index"},
    {"vaddr": 0x001192B8, "word": 0x10400013, "asm": "beqz $v0, 0x00119308  # 0 -> only A selectable"},
    {"vaddr": 0x001192C0, "word": 0x8FC30004, "asm": "lw $v1, 4($fp)   # zone index"},
    {"vaddr": 0x001192C4, "word": 0x24620041, "asm": "addiu $v0, $v1, 0x41  # 'A' + zone index"},
    {"vaddr": 0x001192D0, "word": 0x3C04005D, "asm": "lui $a0, 0x5d / addiu $a0, $a0, -0x6ef0  # buffer 0x5d9110"},
    {"vaddr": 0x001192D8, "word": 0x3C050056, "asm": "lui $a1, 0x56 / addiu $a1, $a1, -0x6098  # 'ZONE %c (A-%c selectable)'"},
    {"vaddr": 0x001192E8, "word": 0x0C077504, "asm": "jal 0x001dd410   # sprintf"},
    {"vaddr": 0x00119308, "word": 0x8FC30004, "asm": "lw $v1, 4($fp)   # only-A branch"},
    {"vaddr": 0x00119318, "word": 0x3C050056, "asm": "lui $a1, 0x56 / addiu $a1, $a1, -0x6078  # 'ZONE %c (only A selectable)'"},
    {"vaddr": 0x00119324, "word": 0x0C077504, "asm": "jal 0x001dd410   # sprintf"},
    # Round-select lock site
    {"vaddr": 0x00119658, "word": 0x10400013, "asm": "beq $v0, $zero, 0x001196A8  # round index == 0 -> only-1 branch"},
    {"vaddr": 0x00119678, "word": 0x3C050056, "asm": "lui $a1, 0x56 / addiu $a1, $a1, -0x6048  # 'ROUND %d (1-%d selectable)'"},
    {"vaddr": 0x001196C4, "word": 0x0C077504, "asm": "jal 0x001dd410   # sprintf"},
    # Bubble-select lock site
    {"vaddr": 0x001199E8, "word": 0x10400013, "asm": "beq $v0, $zero, 0x00119A38  # bubble index == 0 -> only-1 branch"},
    {"vaddr": 0x00119A08, "word": 0x3C050056, "asm": "lui $a1, 0x56 / addiu $a1, $a1, -0x5FF8  # 'BUBBLE %d (1-%d selectable)'"},
    {"vaddr": 0x00119A54, "word": 0x0C077504, "asm": "jal 0x001dd410   # sprintf"}
]

#: The in-game EV / character names, as cstrings in .rodata / .sdata.
EV_NAMES = [
    {"name": "EV1_KATZE", "vaddr": 0x0055F3E8},
    {"name": "EV1_FUNGILA", "vaddr": 0x0055F3F8},
    {"name": "EV1_MISST", "vaddr": 0x0055F408},
    {"name": "EV1_WOLO", "vaddr": 0x0055F418},
    {"name": "EV1_CATCH_KUN", "vaddr": 0x0055F428},
    {"name": "EV1_PUKADON", "vaddr": 0x0055F438},
    {"name": "EV1_MR_A", "vaddr": 0x0055F448},
    {"name": "EV1_PINKY", "vaddr": 0x0055F458},
    {"name": "EV1_YUM", "vaddr": 0x005717F8},
    {"name": "EV1_TOM", "vaddr": 0x00571800},
    {"name": "EV1_MOG", "vaddr": 0x00571808},
    {"name": "EV2_KATZE", "vaddr": 0x0055F358},
    {"name": "EV2_FUNGILA", "vaddr": 0x0055F368},
    {"name": "EV2_MISST", "vaddr": 0x0055F378},
    {"name": "EV2_WOLO", "vaddr": 0x0055F388},
    {"name": "EV2_CATCH_KUN", "vaddr": 0x0055F398},
    {"name": "EV2_TOMYUM", "vaddr": 0x0055F3A8},
    {"name": "EV2_PUKADON", "vaddr": 0x0055F3B8},
    {"name": "EV2_MR_A", "vaddr": 0x0055F3C8},
    {"name": "EV2_PINKY", "vaddr": 0x0055F3D8},
    {"name": "EV2_MOG", "vaddr": 0x005717F0}
]


#: Executable revisions opened and inspected in REA/Ghidra, keyed by SHA-256.
#: The owned SLUS_201.15 executable was disassembled instruction by
#: instruction for the mode-select lock site above.
PROVEN_REVISIONS: dict[str, dict] = {
    EXECUTABLE_SHA256: {
        "artifact": "static-mode-select-disassembly-0x1192B4-0x119340-0x119670-0x1196E0-0x119A00-0x119A70",
        "categories": ["modes"],
    },
}

#: Per-entry category inventory for the owned revision.  Every entry that is
#: not yet proven stays "unknown"; nothing is guessed.  The 21 EV/character
#: cstrings are pinned by address in EV_NAMES (see the module docstring).
INVENTORY: dict[str, list[dict]] = {
    category: [] for category in CATEGORIES
}
for _row in EV_NAMES:
    INVENTORY["characters"].append({
        "name": _row["name"],
        "status": "unknown",
        "evidence": "cstring pinned at vaddr 0x%08X in the owned executable"
                    % _row["vaddr"],
    })
INVENTORY["modes"].extend([
    {"name": "zone_select", "status": "unknown",
     "evidence": "lock site vaddr 0x001192B4-0x00119340 in the owned executable"},
    {"name": "round_select", "status": "unknown",
     "evidence": "lock site vaddr 0x00119678-0x001196E0 in the owned executable"},
    {"name": "bubble_select", "status": "unknown",
     "evidence": "lock site vaddr 0x00119A08-0x00119A70 in the owned executable"},
])

#: The runtime patch plan that a future writer must pass through
#: ``validate_write`` before it may be applied.  It is staged, not applied:
#: the panel-width global (0x00571640) is 0 on disk and set by the game at
#: runtime; a value of 1 selects the wide panel.  The key-index branch at
#: 0x001192B8 (beqz -> 0x00119308) is the zone-lock gate: key index 0
#: restricts a zone to key A only.
PATCH_PLAN = {
    "revision": EXECUTABLE_SHA256,
    "writes": [
        # wide selection panel (u32, 4 bytes at the documented global)
        ("w", PANEL_GLOBAL_VADDR, b"\x01\x00\x00\x00"),
    ],
    "note": (
        "Panel-width global only; the per-zone key-index gate at "
        "0x001192B8 must be proven at runtime before any further write is "
        "admitted by validate_write."
    ),
}


def inventory() -> dict:
    """Category inventory for the owned revision, copied for safe reuse."""
    return {category: list(rows) for category, rows in INVENTORY.items()}


def validate_write(writes: list[tuple], revision: str) -> list[str]:
    """Guard a candidate memory-write plan against the recorded revision proof.

    Returns a list of blocking reasons (empty = admissible).  This is the gate
    any future PS2 writer must pass: it refuses writes when the running
    revision was never inspected, when an address falls outside the owned
    executable's documented PT_LOAD window, or when a write is wider than
    4 bytes.
    """
    errors: list[str] = []
    if revision not in PROVEN_REVISIONS:
        errors.append(f"revision {revision!r} has no REA/Ghidra binary_session proof")
    for op, address, data in writes:
        if op != "w":
            errors.append(f"unsupported operation {op!r}")
        if not isinstance(data, (bytes, bytearray)) or not 1 <= len(data) <= 4:
            errors.append(f"write at 0x{address:x} must be 1..4 bytes")
        # PT_LOAD: file 0x1000 -> vaddr 0x100000, .text/.rodata/.sdata span
        # 0x100000 .. ~0x571900; use the documented global window generously.
        if not 0x0010_0000 <= address < 0x0080_0000:
            errors.append(f"address 0x{address:x} outside documented PS2 RAM window")
    return errors


def accept_revision(revision: str, artifact: str, categories: dict[str, list[dict]]) -> dict:
    """Record REA/Ghidra evidence for a revision (static analysis only).

    Raises on malformed input.  Does NOT mark the profile verified:
    verification requires the runtime acceptance checklist to complete.
    """
    if len(revision) != 64 or any(ch not in "0123456789abcdef" for ch in revision):
        raise ValueError("revision must be a lowercase sha256 hex digest")
    if not artifact.strip():
        raise ValueError("artifact id required")
    for category, rows in categories.items():
        if category not in INVENTORY:
            raise ValueError(f"unknown category {category!r}")
        for row in rows:
            if row["status"] not in ("unlocked", "not_present", "unknown"):
                raise ValueError(f"bad status for {row.get('name')!r}")
            if row["status"] != "unknown" and not str(row.get("evidence") or "").strip():
                raise ValueError(f"{category}:{row.get('name')} needs evidence to leave unknown")
        known = {r["name"] for r in INVENTORY[category]}
        for row in rows:
            if row["name"] in known:
                INVENTORY[category] = [r for r in INVENTORY[category]
                                       if r["name"] != row["name"]]
        INVENTORY[category].extend(rows)
        INVENTORY[category].sort(key=lambda r: r["name"])
    PROVEN_REVISIONS[revision] = {"artifact": artifact, "categories": sorted(categories)}
    return {"recorded": revision, "categories": sorted(categories),
            "verified": False,
            "next": ("runtime acceptance on an authorized agent session "
                     "(i9-NUC or the Spark, idle, 2% audio): reach mode select, "
                     "apply the staged patch, select a locked zone, store a "
                     "gameplay image, then a second launch and rollback")}


def profile() -> dict:
    """Static profile record for the owned build; verified is False by design."""
    return {
        "game_id": GAME_ID,
        "title": TITLE,
        "platform": PLATFORM,
        "verified": False,
        "complete_unlock_profile": False,
        "executable_sha256": EXECUTABLE_SHA256,
        "proven_revisions": sorted(PROVEN_REVISIONS),
        "inventory": {category: list(rows)
                      for category, rows in INVENTORY.items()},
        "unknown_counts": {category: sum(1 for r in rows
                                         if r["status"] == "unknown")
                           for category, rows in INVENTORY.items()},
        "findings": list(INSTRUCTIONS),
        "lock_site": dict(LOCK_SITE),
        "round_lock_site": dict(ROUND_LOCK_SITE),
        "bubble_lock_site": dict(BUBBLE_LOCK_SITE),
        "panel_global": {"vaddr": PANEL_GLOBAL_VADDR,
                         "on_disk": PANEL_GLOBAL_ON_DISK},
        "ev_names": [dict(row) for row in EV_NAMES],
        "patch_plan": {
            "revision": PATCH_PLAN["revision"],
            "writes": [(op, addr, bytes(data)) for op, addr, data
                       in PATCH_PLAN["writes"]],
            "note": PATCH_PLAN["note"],
        },
        "unverified_note": (
            "Static instruction evidence only; the owned revision is recorded "
            "in PROVEN_REVISIONS with its static disassembly artifact. The "
            "zone/round/bubble locks are not proven selectable at runtime and "
            "no patch has been applied; runtime acceptance on an authorized "
            "agent session is the next step."),
    }
