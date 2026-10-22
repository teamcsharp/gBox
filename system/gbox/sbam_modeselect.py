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
    {"vaddr": 0x00119324, "word": 0x0C077504, "asm": "jal 0x001dd410   # sprintf"}
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


def profile() -> dict:
    """Static profile record for the owned build; verified is False by design."""
    return {
        "game_id": GAME_ID,
        "title": TITLE,
        "platform": PLATFORM,
        "verified": False,
        "complete_unlock_profile": False,
        "executable_sha256": EXECUTABLE_SHA256,
        "findings": list(INSTRUCTIONS),
        "lock_site": dict(LOCK_SITE),
        "panel_global": {"vaddr": PANEL_GLOBAL_VADDR,
                         "on_disk": PANEL_GLOBAL_ON_DISK},
        "ev_names": [dict(row) for row in EV_NAMES],
        "unverified_note": (
            "Static instruction evidence only. The zone/round/bubble locks are "
            "not proven selectable at runtime and no patch has been applied; "
            "registration into the unlock registry is the next step."),
    }
