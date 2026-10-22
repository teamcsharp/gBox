"""Resident Evil 6 (Xbox 360, Xenia) Mercenaries: the menus interface gbox/mercs_bot.py boots through
(`screen(m)`, `step(scr)`, `wandered(scr)`, `pressed(scr, key)`, `BOOT_KEY`), modelled on re5_ps3 (docs/mercenaries_engine.md).

What RAM can name today (request 3023's partial map, docs/re6-ram-map-0871eee3b68cdea3.json): a round (player 1's uPlayer
through sPlayer 0x83CA52FC +0x28, its Life +0xF20 / LifeMax +0xF22), and the save's Mercenaries masks. The menu state
machine (title, Extra Content, stage page 0x82AD4160, character list 0x82ACFBF8) is NOT yet measured in RAM (no live
session: Xenia opened no window on i9-NUC, jobs 495c71b2439d48ee / f5a8831bef23496e). So `screen()` names the screens it
can prove and takes the rest from `menu_state(m)`, a hook that returns {"where", "cursor"} once a unit/cursor address is
measured; until then out-of-round is "unknown" and the bot only presses BOOT_KEY (never A: on the title, A takes
Campaign). The stage and character picks work blind meanwhile: StagePick / Roster count D-pad presses the Navigator
reports (like RE5's StagePick) and take the cursor from RAM when menu_state provides it.
"""
from __future__ import annotations

import random
import struct

SPLAYER = 0x83CA52FC                     # sPlayer singleton; +0x28 = player 1's uPlayer
P1 = 0x28
LIFE, LIFE_MAX = 0xF20, 0xF22            # s16 each
SAVE_MGR = 0x83CA4F98                    # save manager; save data = [it] + 0x30
MERC_STAGE_MASK, MERC_CHAR_MASK = 0x974, 0x978
PTR_LO, PTR_HI = 0x40000000, 0xA0000000

STAGES = ("Urban Chaos", "Steel Beast", "Mining the Depths")          # this disc's three (docs/re6.md)
CHARACTERS = ("Leon", "Helena", "Chris", "Piers", "Jake", "Sherry", "Ada", "Carla", "Agent")   # Mercenaries list order

# Out of a round, the one key that confirms what RAM can't name. START, not A: PRESS START takes only START, and A on the
# title menu would take Campaign (a story game); the notices are pressed through by re6_tool._auto_title.
BOOT_KEY = "start"
STEPS = {"results": "start", "dead": "a", "title": "start", "select_stage": "a", "alert": "a"}
CURSORED = ("select_player",)
MAX_ROW = len(CHARACTERS) - 1


def ptr_ok(p: int) -> bool:
    return PTR_LO <= p < PTR_HI and p % 4 == 0


def u32(m, a: int) -> int:
    return struct.unpack(">I", m.rd(a, 4))[0]


def player(m) -> dict | None:
    """Player 1's life from RAM, or None out of a round (no sPlayer / uPlayer yet)."""
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
    """The save's Mercenaries masks (stage 10 bits, character + costume 30 bits), when the save is loaded."""
    try:
        sv = u32(m, SAVE_MGR)
        if not ptr_ok(sv):
            return None
        stages, chars = struct.unpack(">II", m.rd(sv + 0x30 + MERC_STAGE_MASK, 8))
    except Exception:                                   # noqa: BLE001
        return None
    return {"stages": stages, "characters": chars}


def menu_state(m) -> dict | None:
    """Hook for the measured menu state machine: {"where": one of title / select_stage / select_player / loading /
    alert / ..., "cursor": int | None}. None until its RAM is measured live (see the module note)."""
    return None


def screen(m, merc=None) -> dict:
    """Where RE6 is: playing / dead from the round's own life; out of a round what menu_state names, else unknown."""
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
    """A random character each round (like RE5's Roster): drawn among those played least, never the one just played.
    With the cursor unread the pick is a count of D-pad rights from the list's start; pressed() counts them."""

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
    """A random stage each visit to the stage page: a random count of D-pad rights (0..2) then A; mercs_bot's Navigator
    reports every press it sends through pressed(), so a press held back never counts."""
    MAX_MOVES = len(STAGES) - 1

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.left = None

    def key(self, scr: dict) -> str:
        if self.left is None:
            self.left = self.rng.randint(0, self.MAX_MOVES)
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
            ROSTER.left = None                           # taken: started() clears the pick when the round is up


def step(scr: dict) -> str | None:
    """The one press towards the next round: START on the title / results, A on the stage page after the random moves,
    the character row moved to the pick (cursor from RAM, or counted blind) then A, A after a lost round. Nothing on
    a screen RAM can't name (the bot's BOOT_KEY is separate)."""
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
            return "dright" if ROSTER.left > 0 else "a"
        if cur == tgt:
            return "a"
        return "dright" if cur < tgt else "dleft"
    return STEPS.get(where)


def wandered(scr: dict) -> str | None:
    """A story / other mode: the menu state names a screen that is not the Mercenaries'."""
    where = scr.get("where")
    if where in ("campaign", "story", "agent_hunt", "options"):
        return f"RE6 left The Mercenaries ({where})"
    return None
