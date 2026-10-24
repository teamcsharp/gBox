"""Resident Evil: The Mercenaries 3D (3DS, Citra/Azahar) Mercenaries menus module skeleton.

Request #3349 (game 0ed22ae742e1b56b, EUR build): emulator support + RAM map + mission-select automation
for the 3DS Mercenaries. This module is the `mercs` block's `menus` entry that grox.mercs_bot boots through
(`screen(m)`, `step(scr)`, `wandered(scr)`, `pressed(scr, key)`, `BOOT_KEY`), and mirrors the re6_x360
shape: plain module functions (not the Driver class) until a live RAM map makes a real combat driver
worth writing.

Where the RAM map stands (request #1320 + PR #46, gbox/merc3d_exe.py): the owned EUR build's decompressed
.code (ARM11, base 0x100000, sha256 85a34c86eb62597d89f1dc48b2e75dc7f4b25fdfeed7def086f93e875e5821be) has
18 aligned uPl name strings / 16 unique names (Chris, Jill, Wesker, ...), the archive-path cluster at
0x4D6A40-0x4D6D90, and the ro table at 0x812720. NONE of these are measured RAM addresses in a running
guest: they are static .code offsets. The uPl names are candidate roster strings, not a verified binding
table, and their runtime addresses are not yet resolved (no live Citra session mapped them through the
exheader text/ro relocation scheme).

Because no runtime RAM offset for the round (player HP, timer, menu cursor, mission index) is measured,
this driver deliberately declares nothing as playable: `player()`, `unlocked()` and `menu_state()` return
None so `screen()` reports `unknown` out-of-round, exactly like re6 before its RAM map landed. Nothing
here invents a pointer chain or a HP offset. The mission-select automation, RAM map and `playable: True`
flip are gated on a live Citra/Azahar measurement job (text/ro base walk + the uPl table's runtime VMA),
which becomes the next acceptance step.
"""
from __future__ import annotations

STAGES = ()                          # mission list: the 30 named stages are enum/string data, not a measured RAM index yet
CHARACTERS = ()                      # uPl roster names exist in .code but their runtime order is not verified
BOOT_KEY = "start"                   # neutral advance key (like re4/re6): A's title action is unconfirmed, so never pressed
STEPS = {}
CURSORED = ()


def player(m) -> dict | None:
    """Player HP from RAM: no measured pointer chain for the 3DS round yet. None until one is mapped live."""
    return None


def unlocked(m) -> dict | None:
    """Save's mission/character masks: the 3DS save layout is not measured. None until then."""
    return None


def menu_state(m) -> dict | None:
    """The title's menu state machine ({'where', 'cursor'}): not measured in RAM. None until a live session maps it."""
    return None


def screen(m, merc=None) -> dict:
    """Where The Mercenaries 3D is. No measured RAM reader exists, so every state is the honest `unknown`;
    the bot presses only BOOT_KEY (start) and never A (A's title action is unconfirmed)."""
    out = {"where": "unknown", "cursor": None, "target": None}
    st = menu_state(m)
    if st and st.get("where"):
        out.update(where=st["where"], cursor=st.get("cursor"))
    return out


def step(scr) -> str | None:
    """Nothing measured can be stepped confidently; the bot's BOOT_KEY handles the blind advance."""
    return None


def wandered(scr) -> str | None:
    """A story/other screen the title could land on: not enumerable until the menu RAM is measured."""
    return None


def pressed(scr, key) -> None:
    """No cursor is tracked while menu_state is unmeasured."""
    return None
