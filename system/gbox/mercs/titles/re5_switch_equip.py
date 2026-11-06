"""RE5 Switch's RAM equip: set any inventory slot in hand directly, no D-pad tap and no item-screen hop.

The bot's normal equip is input-side: it emits {"tap": QUICK[grid]} and the game's D-pad handler moves the in-hand
cursor (RE5 Mercenaries' real-time weapon switch). That only reaches the four QUICK slots (grids 1/3/5/7); a weapon
parked on any other grid (2/4/6/8/0) has no D-pad key and can never be pulled in hand without the pause menu.

This module writes the in-hand field directly. Each inventory slot is a 0x38-byte record (re5_switch.inventory):
  +0x00.. -> "addr" (player + P_INV + INV_SLOT*k)
  +0x08   INV_ID   u32  the item id word
  +0x1C   INV_GRID s32  the paused-menu grid position (1..8, 0 = none; the D-pad's QUICK positions are 1/3/5/7)
  +0x20   INV_HAND s32  in hand? 1 = held (the game's hand==1 read-back in inventory())

instant_equip clears every slot currently marked in hand and marks the one slot that holds the wanted item, then
reads every write back. The write is UNVERIFIED in a live round (no private slot) - same contract as aim_writer: a
failed read-back returns False and the caller falls back to the D-pad tap. The item in hand is the game's own
single-slotted state, so only one slot should ever be hand==1; a slot holding item==wanted with grid in a THROWN or
KNIVES position is still a valid target (the D-pad never reaches some of those - this hook does).
"""
from __future__ import annotations

import struct

from . import re5_switch

ERRORS = (ValueError, OSError, OverflowError, struct.error, RuntimeError)


def _hand_slot(inv: list) -> dict | None:
    """The one slot the game reports in hand (hand == 1); None when none is (inventory or read-back failure)."""
    for s in inv:
        if s.get("hand"):
            return s
    return None


def applies(m) -> bool:
    """True when the session has an adapter and modifications are on (the same gate as instant_equip's, without
    reading memory) - cheap for _equip_writer's one-time cache. Never raises."""
    ad = getattr(m, "adapter", None)
    return ad is not None and not getattr(m, "mercs_no_modifications", False)


def equip_state(m, player: int) -> dict | None:
    """{base, player, held, slots}: the player pointer (the inventory() records' addr base - 0x30F0) and the slot
    currently in hand; None without a readable player pointer. Never raises."""
    try:
        base = re5_switch.module_base(m)
        if base is None:
            return None
        inv = re5_switch.inventory(m, player)
    except ERRORS:
        return None
    return {"player": player, "held": _hand_slot(inv), "slots": inv}


def instant_equip(m, player: int, item: int | None = None) -> dict | None:
    """Put one slot in hand by writing INV_HAND directly. player = the resolved player pointer (snapshot's
    snap["player"]["ptr"], not the index). item = the wanted item id (id & 0xFF); None = put nothing in hand (clear any
    held slot). Returns {equipped, cleared, held_slot, verified}; verified False on any failed write/read-back. None
    whenever the session has no adapter or modifications are off (same gate as the aim lock - the caller keeps its
    input-side fallback). Never raises."""
    ad = getattr(m, "adapter", None)
    if ad is None or getattr(m, "mercs_no_modifications", False):
        return None
    if not isinstance(player, int) or not (0x1000000 <= player < (1 << 40)):
        return None
    try:
        inv = re5_switch.inventory(m, player)
    except ERRORS:
        return None
    held = _hand_slot(inv)
    target = None
    if item is not None:
        target = next((s for s in inv if (s["id"] & 0xFF) == (item & 0xFF)), None)
        if target is None:
            # no slot holds it: nothing to equip (report, do not clobber whatever is in hand)
            return {"equipped": None, "cleared": [], "held_slot": held["slot"] if held else None,
                    "verified": False, "reason": "item not in inventory"}
    if target is not None and held is not None and target["slot"] == held["slot"]:
        return {"equipped": target["id"] & 0xFF, "cleared": [], "held_slot": held["slot"], "verified": True}

    cleared: list[int] = []
    verified = True

    def _write(s, hand):
        ad.write_memory(s["addr"] + re5_switch.INV_HAND, struct.pack("<i", 1 if hand else 0))
        back = struct.unpack_from("<i", ad.read_memory(s["addr"] + re5_switch.INV_HAND, 4))[0]
        return back == (1 if hand else 0)

    if held is not None:
        if not _write(held, False):
            verified = False
        cleared.append(held["slot"])
    if target is not None:
        if not _write(target, True):
            verified = False
    return {"equipped": None if target is None else target["id"] & 0xFF, "cleared": cleared,
            "held_slot": target["slot"] if target is not None else None, "verified": verified}
