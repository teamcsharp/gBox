"""Resident Evil 6 (PS3, RPCS3) Mercenaries menus interface for gbox/mercs_bot.py (`screen(m)`, `step(scr)`,
`wandered(scr)`, `pressed(scr, key)`, `BOOT_KEY`), interface-parity with re6_x360 / re5_ps3 (docs/mercenaries_engine.md).

Static evidence so far (this request, #3279): the decrypted BLUS30855 EBOOT (9,381,200-byte SELF, KeyRev 0x001C,
decrypted image 25,060,016 bytes, ELF64 BE PPC, base 0x10000) carries MT Framework's class-name table in .rodata
with the sPlayer class name at guest 0x1413668 (file offset 0x1403668, among sMessMan / sSce...) and a serializer
member list at 0x1406223 (mPlayerInit, mAccessList, ...). What is NOT yet measured: the sPlayer singleton pointer
(no live RPCS3 session this run; the .bss descriptors are zero in the file, so the instance address needs either
xrefs from the EBOOT's DTI registration code or one live read) and the PS3 save's Mercenaries masks. Until then
`screen()` names nothing out of a round and the bot only presses BOOT_KEY, and the picks stay blind: StagePick /
Roster count D-pad presses the Navigator reports, like RE5's StagePick before its cursor was measured.

The roster below is the disc family's own (BLUS30855 ships the same Mercenaries build as the 360 disc: three
stages, nine characters — docs/re6.md, verified live on Xenia 2026-10-2x); per-PS3-disc confirmation is a live
acceptance step, not assumed.
"""
from __future__ import annotations

import random
import struct

# Guest anchors (BLUS30855 EBOOT, static). The class-name table entry is the ram map's memory match; the
# singletons' instance pointers are runtime .bss values this run could not read (see module docstring).
SPLAYER_NAME_VA = 0x1413668              # .rodata: "sPlayer\0" among the class names (sMessMan, sSce...)
SPLAYER = None                           # sPlayer singleton instance pointer: NOT yet pinned (needs live RAM or xrefs)
P1 = 0x28                                # uPlayer 1 at sPlayer+0x28 (the 360 build's layout, docs/re6.md)
LIFE, LIFE_MAX = 0xF20, 0xF22            # s16 each (360 layout; shared MT engine, confirm on PS3)
PTR_LO, PTR_HI = 0x10000, 0x40000000     # PS3 guest pointer range (elf region, then heap at 0x30000000)

STAGES = ("Urban Chaos", "Steel Beast", "Mining the Depths")          # this disc family's three (docs/re6.md)
CHARACTERS = ("Leon", "Helena", "Chris", "Piers", "Jake", "Sherry", "Ada", "Carla", "Agent")   # list order

# Out of a round, the one key that always applies on PS3 (cross would take Campaign on the title menu; RE6 PS3's
# PRESS START takes START). The notices are pressed through by the re6_tool title walker when it exists.
BOOT_KEY = "start"
STEPS = {"results": "start", "dead": "cross", "title": "start", "select_stage": "cross", "alert": "cross"}
CURSORED = ("select_player",)
MAX_ROW = len(CHARACTERS) - 1


def ptr_ok(p: int) -> bool:
    return PTR_LO <= p < PTR_HI and p % 4 == 0


def u32(m, a: int) -> int:
    return struct.unpack(">I", m.rd(a, 4))[0]


def player(m) -> dict | None:
    """Player 1's life from RAM, or None while the sPlayer singleton address is unpinned (SPLAYER None) or the
    guest is out of a round."""
    if SPLAYER is None:
        return None
    try:
        sp = u32(m, SPLAYER)
        if not ptr_ok(sp):
            return None
        up = u32(m, sp + P1)
        if not ptr_ok(up):
            return None
        hp, hp_max = struct.unpack(">hh", m.rd(up + LIFE, 4))
    except Exception:                                   # noqa: BLE001 - guest memory not mapped yet (boot)
        return None
    return {"hp": hp, "hp_max": hp_max}


def unlocked(m) -> dict | None:
    """The save's Mercenaries masks. The PS3 save's mask offsets are not yet measured (the 360 save carries them at
    +0x974/+0x978 through its save manager): returns None until a live read pins them."""
    return None


def menu_state(m) -> dict | None:
    """Hook for the measured menu state machine: {"where": title / select_stage / select_player / loading / alert /
    ..., "cursor": int | None}. None until its RAM is measured live (no RPCS3 session this run)."""
    return None


def screen(m, merc=None) -> dict:
    """Where RE6 is: playing / dead from the round's own life once sPlayer is pinned; out of a round whatever
    menu_state names, else unknown (the bot then only presses BOOT_KEY)."""
    p = player(m)
    out = {"where": "unknown", "cursor": None, "target": None}
    if p and p["hp_max"] > 0:
        out["where"] = "playing" if p["hp"] > 0 else "dead"
        if out["where"] == "playing" and (ROSTER.pick is not None or ROSTER.round is None):
            out["character"] = ROSTER.started()
        return out
    st = menu_state(m)
    if st and st.get("where"):
        out.update(where=st["where"], cursor=st.get("cursor"))
        if out["where"] == "select_player":
            out["target"] = ROSTER.want()
    return out


class Roster:
    """A random character each round (like RE5's / the 360 build's Roster): drawn among those played least, never
    the one just played. With the cursor unread the pick is a count of D-pad rights from the list's start;
    pressed() counts them."""

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.pick, self.last, self.round = None, None, None
        self.played = {c: 0 for c in CHARACTERS}
        self.left = None                       # blind moves still to make on this visit

    def want(self) -> int:
        if self.pick is None:
            least = min(self.played[c] for c in CHARACTERS if c != self.last)
            pool = [i for i, c in enumerate(CHARACTERS) if self.played[c] == least and c != self.last]
            self.pick = self.rng.choice(pool)
        return self.pick

    def started(self) -> str:
        name = CHARACTERS[self.pick] if self.pick is not None else (self.last or CHARACTERS[0])
        if self.round is None or self.round != name or self.pick is not None:
            self.played[name] += 1
            self.round = name
        self.last, self.pick, self.left = name, None, None
        return name


ROSTER = Roster()


class StagePick:
    """A random stage each visit to the stage page: a random count of D-pad rights (0..2) then cross; the
    Navigator reports every press it sends through pressed(), so a press held back never counts."""

    MAX_MOVES = len(STAGES) - 1

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.left = None

    def key(self, scr: dict) -> str:
        if self.left is None:
            self.left = self.rng.randint(0, self.MAX_MOVES)
        return "dright" if self.left > 0 else "cross"

    def pressed(self, scr: dict, key: str) -> None:
        if scr.get("where") != "select_stage":
            return
        if key == "dright" and self.left:
            self.left -= 1
        elif key == "cross":
            self.left = None


STAGE_PICK = StagePick()


def pressed(scr: dict, key: str) -> None:
    STAGE_PICK.pressed(scr, key)
    if scr.get("where") == "select_player" and scr.get("cursor") is None:
        if key == "dright" and ROSTER.left:
            ROSTER.left -= 1
        elif key == "cross":
            ROSTER.left = None                           # taken: started() clears the pick when the round is up


def step(scr: dict) -> str | None:
    """The one press towards the next round: START on the title / results, cross on the stage page after the random
    moves, the character row moved to the pick (cursor from RAM, or counted blind) then cross, cross after a lost
    round. Nothing on a screen RAM can't name (the bot's BOOT_KEY is separate)."""
    where = scr.get("where")
    if where == "select_stage":
        return STAGE_PICK.key(scr)
    if where == "select_player":
        cur, tgt = scr.get("cursor"), scr.get("target")
        if tgt is None:
            return None
        if cur is None:                                  # blind: tgt D-pad rights from the list's first character
            if ROSTER.left is None:
                ROSTER.left = tgt
            return "dright" if ROSTER.left > 0 else "cross"
        if cur == tgt:
            return "cross"
        return "dright" if cur < tgt else "dleft"
    return STEPS.get(where)


def wandered(scr: dict) -> str | None:
    """A story / other mode: the menu state names a screen that is not the Mercenaries'."""
    where = scr.get("where")
    if where in ("campaign", "story", "agent_hunt", "options"):
        return f"RE6 left The Mercenaries ({where})"
    return None
