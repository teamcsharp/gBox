"""Resident Evil 6 (PS3, RPCS3) Mercenaries: the menus interface gbox/mercs_bot.py boots through
(`screen(m)`, `step(scr)`, `wandered(scr)`, `pressed(scr, key)`, `BOOT_KEY`), modelled on re5_ps3 and the X360
sibling re6_x360 (docs/mercenaries_engine.md).

RE6 is MT Framework on PS3 too (BLUS30855, title 43430819, executable default_mp.self; the disc is the complete
Mercenaries set). Unlike re5_ps3 (BLUS30491, whose sPlayer/enemy/main chains were measured live on the Spark's RPCS3
2026-10-20), _no_ RE6 PS3 address has been measured yet in a live RPCS3 session: there is no sPlayer, menu cursor,
timer or round marker backed by frames. So screen() can prove nothing out of round and answers "unknown"; the bot only
presses BOOT_KEY (START is safe: PRESS START takes only START, and A on the title would take Campaign), never A.

To flip the unmeasured switches, do the live measurement the X360 branch still owes (docs/re6.md "boot_to_title"):
boot BLUS30855 on the i9-NUC or the Spark through RPCS3, point at a running frame, and locate (a) the sPlayer
singleton +0x28 -> player 1's uPlayer with its Life/LifeMax s16 pair, and (b) the menu state machine (title, stage page,
character list). Revisit the X360 map docs/re6-ram-map-0871eee3b68cdea3.json for the field offsets to redrive, then fill
SPLAYER, P1, LIFE, LIFE_MAX and menu_state() below. Until then this driver is interface-complete but runtime-silent, on
purpose: it must never claim a screen it cannot name.
"""
from __future__ import annotations

import random
import struct

# Endianness note: RPCS3 exposes PowerPC64 guest memory; MT Framework's PS3 build is big-endian like the X360
# build (both use struct ">"), so u32()/s16 reads here stay big-endian to match re5_ps3 (whose reads are BE too).
PTR_LO, PTR_HI = 0x10000, 0x300000000            # RPCS3 user memory range (PS3 PPU user VAS is up to 0x300000000)

# --- Static evidence, request 3370 (decrypted-EBOOT cross-references, no live session needed) ---
# BLUS30855 EBOOT.BIN 01.00 (SELF sha256 161788e7c0264b1b9d5cd72ac051c9ce2a64b7c85d04f954b2e35f202834af67, KeyRev
# 0x001C, 9,381,200 bytes). Decrypted image: 25,060,016 bytes, ELF64 PPC BE, segments based at 0x10000, sha256
# 3720224a5eb8b8a2e69871439aa8d8b11c8a4cbc426f4144d0531d6e5648cecb (gbox-data/analysis/re6-ps3-eboot/EBOOT.dec.ELF).
#
#   0x1a93d8  sPlayer DTI registration:
#              lis r31,0x183 / addic r3,r31,0x4d04        -> slot 0x1834D04
#              lis r4,0x141 / addic r4,r4,0x3668          -> name VA 0x1413668 (bytes "sPlayer\0" verified)
#              addic r5,r5,-0x449c (0x1900000) = 0x18FBB64 -> the node's category-list object
#              li r6,0x40d0                                -> instance size 0x40d0
#              bl 0xcb2a04 -> 0xcb2898 writes [slot+0]=0x14DCB00 (node class, shared by every DTI node),
#              [slot+4]=name pointer, [slot+0x14]=0, packs size into [slot+0x18], links the node.
#   0x1413668  "sPlayer\0" sits in the .rodata class-name table (neighbours "sMessMan", "mAccessList", "mArray").
EBOOT_DEC_SHA256 = "3720224a5eb8b8a2e69871439aa8d8b11c8a4cbc426f4144d0531d6e5648cecb"
SPLAYER_NAME_VA = 0x1413668            # .rodata "sPlayer\0" of this exact EBOOT
SPLAYER_DTI_NODE = 0x1834D04           # .bss DTI node slot registered at 0x1a93d8
SPLAYER_NODE_CLASS = 0x14DCB00         # [node+0] node-class descriptor written by the registrar 0xcb2898
SPLAYER_NODE_LIST = 0x18FBB64          # r5: the node's category-list object
SPLAYER_INSTANCE_SIZE = 0x40D0         # r6: the singleton's instance size
NODE_NAME = 0x4                        # [node+4] = name pointer (stored verbatim: 0x1413668)
NODE_INSTANCE_CANDIDATE = 0x14         # [node+0x14] zeroed at registration; instance slot is the live-read TODO

STAGES = ("Urban Chaos", "Steel Beast", "Mining the Depths")     # disc names from docs/re6.md; PS3 count pending
CHARACTERS = ("Leon", "Helena", "Chris", "Piers", "Jake", "Sherry", "Ada", "Carla", "Agent")  # console roster order

# Out of a round, the one key that confirms what RAM can't name. START, not A (see the module note); the PS3
# and X360 builds share the same PRESS START flow, and gbox.adapters.RPCS3_KEYPAD maps the PS3 START button.
BOOT_KEY = "start"
STEPS = {"results": "start", "dead": "a", "title": "start", "select_stage": "a", "alert": "a"}
CURSORED = ("select_player",)
MAX_ROW = len(CHARACTERS) - 1


def ptr_ok(p: int) -> bool:
    return PTR_LO <= p < PTR_HI and p % 4 == 0


def u32(m, a: int) -> int:
    return struct.unpack(">I", m.rd(a, 4))[0]


def splayer_node(m) -> dict | None:
    """Validate the statically pinned sPlayer DTI node (0x1834D04) against live RAM. The node is revision
    scoped: its [node+4] name pointer must lead to the exact .rodata bytes "sPlayer\\0" of this EBOOT, so a
    different BLUS30855 revision (or an unmapped/garbage node) is rejected instead of guessed. Returns
    {"node", "name", "class", "instance"}; "instance" is the candidate slot [node+0x14] only while it holds a
    guest pointer — whether that slot is the live singleton instance is the one fact still owed to a live
    RPCS3 read (the registrar only proves it is zeroed at boot)."""
    try:
        if u32(m, SPLAYER_DTI_NODE) != SPLAYER_NODE_CLASS:
            return None
        name_p = u32(m, SPLAYER_DTI_NODE + NODE_NAME)
        if not ptr_ok(name_p) or m.rd(name_p, 7) != b"sPlayer":
            return None
        inst = u32(m, SPLAYER_DTI_NODE + NODE_INSTANCE_CANDIDATE)
    except Exception:                                   # noqa: BLE001 - guest memory not mapped yet (boot)
        return None
    return {"node": SPLAYER_DTI_NODE, "name": "sPlayer", "class": SPLAYER_NODE_CLASS,
            "instance": inst if ptr_ok(inst) else None}


def player(m) -> dict | None:
    """Player 1's life from RAM. Reads through the validated sPlayer DTI node when its instance slot is
    populated: instance+0x28 -> uPlayer, +0xF20/+0xF22 Life/LifeMax s16 (offsets inherited from the verified
    360 map, same MT Framework build family). The chain must still pass re6ps3_player's sanity bounds, so a
    stale pointer or wrong revision answers None instead of a fabricated round."""
    from gbox import re6ps3_player as RP

    n = splayer_node(m)
    if not n or n["instance"] is None:
        return None
    try:
        up = u32(m, n["instance"] + RP.OFF_PLAYER_PTR)
        hp, hp_max = struct.unpack(">hh", m.rd(up + RP.OFF_HP, 4))
    except Exception:                                   # noqa: BLE001 - guest memory not mapped yet (boot)
        return None
    if not (0 <= hp <= RP.HP_MAX_LIMIT and 0 < hp_max <= RP.HP_MAX_LIMIT and hp <= hp_max):
        return None
    return {"hp": hp, "hp_max": hp_max}


def menu_state(m) -> dict | None:
    """Hook for the measured menu state machine: {"where": title / select_stage / select_player / loading / alert,
    "cursor": int | None}. None until a live RPCS3 session names the cursor (the X360 sibling returns None identically
    for its still-unmeasured menu machine)."""
    return None


def screen(m, merc=None) -> dict:
    """Where RE6 is: playing / dead from a round's own Life once measured; out of a round (the only state this driver
    can currently prove) it deliberately reports "unknown" rather than guessing, so the bot never sends A blind."""
    out = {"where": "unknown", "cursor": None, "target": None}
    p = player(m)
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
    """A random character each round (RE5's Roster pattern): drawn among those played least, never the one just
    played. With the cursor unread (present state), the pick is a count of D-pad rights from the list's start."""

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.pick, self.last, self.round = None, None, None
        self.played = {c: 0 for c in CHARACTERS}
        self.left = None

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
    """A random stage each visit to the stage page: a random count of D-pad rights then A (the X360 sibling's
    blind-stage scheme, its cursor also unread)."""

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.left = None

    def key(self, scr: dict) -> str:
        if self.left is None:
            self.left = self.rng.randint(0, len(STAGES) - 1)
        return "dright" if self.left > 0 else "a"

    def pressed(self, scr: dict, key: str) -> None:
        if scr.get("where") != "select_stage":
            return
        if key == "dright" and self.left:
            self.left -= 1
        elif key == "a":
            self.left = None


STAGE_PICK = StagePick()


def pressed(scr: dict, key: str) -> None:
    STAGE_PICK.pressed(scr, key)
    if scr.get("where") == "select_player" and scr.get("cursor") is None:
        if key == "dright" and ROSTER.left:
            ROSTER.left -= 1
        elif key == "a":
            ROSTER.left = None


def step(scr: dict) -> str | None:
    """The one press towards the next round; None on a screen RAM can't name (present state: every out-of-round
    screen is "unknown", so this returns None and the boot presses only BOOT_KEY)."""
    where = scr.get("where")
    if where == "select_stage":
        return STAGE_PICK.key(scr)
    if where == "select_player":
        cur, tgt = scr.get("cursor"), scr.get("target")
        if tgt is None:
            return None
        if cur is None:
            if ROSTER.left is None:
                ROSTER.left = tgt
            return "dright" if ROSTER.left > 0 else "a"
        if cur == tgt:
            return "a"
        return "dright" if cur < tgt else "dleft"
    return STEPS.get(where)


def wandered(scr: dict) -> str | None:
    """A story / other mode: once menu_state() names one. Identifies the mode the X360 sibling escapes too."""
    where = scr.get("where")
    if where in ("campaign", "story", "agent_hunt", "options"):
        return f"RE6 left The Mercenaries ({where})"
    return None
