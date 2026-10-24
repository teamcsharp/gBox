"""Raidou 2 (PS2, SLUS_218.45) King Mode static evidence (#2315). Read-only; no writer.

King Mode is a difficulty choice on the "New Cycle" (new game plus) screen, not a
standalone lock flag found yet.  Static evidence from the owned boot ELF.
"""
from __future__ import annotations

import hashlib

ISO_SHA256 = "ce2a2e897185ec4f129dd3a215b53987dbdf224b49d0c2eac2f8b0747ef79a04"
BOOT_ELF_SHA256 = "66cb8e1d2fe422d562ff330a87ab98edc6d93e23c3626e12266bb91e6fbce973"
BOOT_ELF_SIZE = 4103896
# main LOAD segment: file offset 0x1000 -> vaddr 0x100000
VADDR_DELTA = 0x100000 - 0x1000
EVIDENCE = {
    "king_mode_string": {"vaddr": 0x455750, "text": "King Mode difficulty."},
    "new_cycle_menu_draw": {"code_xref": 0x1F27FC, "note": "state-machine draw fn; gp-0x2bac holds the state, draws via 0x1eb758 (text) with the strings 0x455730/0x455750"},
}
STATUS = "pending_research"  # lock check/save flag not yet located; no writes


def verify_boot_elf(data: bytes) -> bool:
    return len(data) == BOOT_ELF_SIZE and hashlib.sha256(data).hexdigest() == BOOT_ELF_SHA256


def string_at(data: bytes, vaddr: int) -> str:
    off = vaddr - VADDR_DELTA
    return data[off:data.index(b"\0", off)].decode("latin1")
