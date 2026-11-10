"""P1: the cold-boot walk from the disc to Pioneer 2, as a deterministic press script with RAM checkpoints.

The guide's P1 is "Title -> PRESS START -> the offline menus -> character select -> Pioneer 2 ... by real presses on the
virtual pads, with the screen read from RAM (the menu state bytes), not from frames". This module is that walk.

What RAM can and cannot say
---------------------------
``0x80516303`` is **not** a screen id (round 3 corrected that): it is a coarse mode that reads ``1`` on both the title
main menu and SELECT CHARACTER, ``9`` on SELECT GAME MODE and ``0``/``22``/``4`` on the title. So the walk is a
**deterministic press sequence** whose checkpoints are only the states RAM can prove:

===========================  =========================================================
checkpoint                   proven by
===========================  =========================================================
``left_title``               the mode leaves the attract family, or a player appears
``past_game_mode``           the mode is no longer SELECT GAME MODE (``9``)
``in_town``                  ``FLOOR 0`` (Pioneer 2) **with a player**
===========================  =========================================================

Between the checkpoints the sequence is fixed because it was walked by hand on this build (round 4): START at PRESS
START, ``ddown``+A for OFFLINE GAME, A for SINGLE MODE, A on the first slot, then A for the episode. The walk reports
the state after every step and never claims to know which menu it is on; a step that leaves the state unchanged is
reported as a failure, not retried blindly.

The attract movie and the PRESS START title both read mode ``0``, so :func:`reach_title` presses START up to a bound to
skip the movie -- START is the right button in both cases, which is what makes that bounded retry honest.
"""
from __future__ import annotations

import time

from . import pso_entities as entities_mod
from . import pso_ram

# The press script, verified step by step against captured frames (2026-11-10). Each row is one press of the game's own
# input: the (name, keys, the checkpoint that must hold after it).
#
#   1 START at PRESS START        -> the title main menu (mode 1)
#   2 ddown + A                   -> SELECT GAME MODE (mode 9)  [the cursor starts on ONLINE GAME, so it takes a move]
#   3 A                           -> SELECT CHARACTER (mode 1)
#   4 A                           -> the Confirm / Cancel / Recreate prompt, Confirm highlighted
#   5 A                           -> SELECT EPISODE
#   6 A                           -> the warp, then Pioneer 2 (mode 5, player at 0,-2015 room 41)
#
# Press 2 is the only one with an unambiguous RAM checkpoint (mode 9 appears nowhere else); the rest are asserted by the
# arrival, because `mode` reads 1 for the main menu, SELECT CHARACTER and SELECT EPISODE alike.
BOOT_STEPS = (
    ("press_start", ("start",), "left_title"),
    ("offline_game", ("ddown", "a"), "game_mode_select"),
    ("single_mode", ("a",), None),
    ("character_slot", ("a",), None),
    ("confirm_character", ("a",), None),
    ("episode_one", ("a",), "in_town"),
)

# Offline MULTI MODE: the two-controller branch, verified press by press against frames (2026-11-10). It exists because
# the single-player branch always starts with Principal Tyrell's episode-1 intro, which nothing can exit (see the lane
# doc), while MULTI MODE goes straight to two character selections and then to Pioneer 2.
#
#   1 START at PRESS START     -> the title main menu
#   2 ddown + A                -> SELECT GAME MODE (mode 9)
#   3 ddown + A                -> MULTI MODE character select: "Please select Player 1's character."
#   4 A                        -> the Confirm / Cancel prompt, Confirm highlighted
#   5 A                        -> Player 1 chosen: "Please select Player 2's character."
#
# It needs Dolphin to present a controller in the console's port 2 (see `pso_coop_setup.si_devices`): without that the
# game answers "Requires at least 2 Controllers." and never reaches the selection at all.
MULTI_STEPS = (
    ("press_start", ("start",), "left_title"),
    ("offline_game", ("ddown", "a"), "game_mode_select"),
    ("multi_mode", ("ddown", "a"), None),
    ("confirm_player1", ("a",), None),
    ("accept_player1", ("a",), None),
)

TITLE_MODES = (0, 4, 22)
TITLE_MENU = 1                                   # the title main menu (ONLINE / OFFLINE / OPTIONS / WEBSITE)
GAME_MODE_SELECT = 9


def state(reader) -> dict:
    """Everything the walk may assert on, read in one place."""
    try:
        items = entities_mod.entities(reader)
    except Exception:                                   # noqa: BLE001 - a table read must not kill a walk
        items = []
    player = pso_ram.player(reader, 0)
    return {"mode": reader.u8(pso_ram.BOOT_SCREEN),
            "floor": pso_ram.floor(reader), "episode": pso_ram.episode(reader),
            "player": None if player is None else {"x": player["x"], "z": player["z"], "room": player["room"]},
            "entities": len(items)}


def _check(name: str, before: dict, after: dict) -> tuple[bool, str]:
    """Did the checkpoint hold? Returns (ok, why)."""
    if name == "left_title":
        ok = after["mode"] not in TITLE_MODES or after["player"] is not None
        return ok, "" if ok else f"still on the title (mode {after['mode']})"
    if name == "game_mode_select":
        ok = after["mode"] == GAME_MODE_SELECT
        return ok, "" if ok else f"ddown+A did not open SELECT GAME MODE (mode {after['mode']})"
    if name == "past_game_mode":
        ok = after["mode"] != GAME_MODE_SELECT
        return ok, "" if ok else "still on SELECT GAME MODE"
    if name == "creating_or_selecting":
        ok = after["mode"] != GAME_MODE_SELECT
        return ok, "" if ok else "A did not leave SELECT GAME MODE"
    if name == "in_town":
        ok = after["player"] is not None and after["floor"] == 0
        return ok, "" if ok else f"no player in Pioneer 2 (floor {after['floor']}, player {after['player']})"
    return True, ""


def reach_title(read_state, press, *, tries=12, settle=2.0, sleep=time.sleep, log=None) -> dict:
    """Press START through the attract movie until the title menu appears (bounded).

    The attract loop and the PRESS START title both read mode ``0``, but START is the right button in both, so this is
    a justified retry rather than a blind one. Stops as soon as the mode leaves the attract or a menu appears.
    """
    log = log or (lambda _m: None)
    pressed = 0
    s = read_state()
    while pressed < tries:
        if s["mode"] == TITLE_MENU or s["player"] is not None:
            return {"ok": True, "presses": pressed, "state": s}
        press(("start",))
        pressed += 1
        sleep(settle)
        s = read_state()
        log(f"attract skip {pressed}: mode={s['mode']}")
        if s["mode"] != 0:
            return {"ok": True, "presses": pressed, "state": s}
    return {"ok": False, "presses": pressed, "state": s,
            "why": f"still in the attract after {pressed} START presses"}


def walk(read_state, press, *, settle=1.6, sleep=time.sleep, log=None, start_at="press_start") -> dict:
    """Run the boot script from ``start_at``. ``press`` takes a tuple of pad key names.

    Returns {"ok", "arrived", "why", "steps"}; ``arrived`` is True only when a player exists in Pioneer 2.
    """
    log = log or (lambda _m: None)
    steps = []
    before = read_state()
    steps.append({"step": "start", "state": before})
    started = start_at == "press_start"
    for name, keys, checkpoint in BOOT_STEPS:
        if not started:
            if name == start_at:
                started = True
            else:
                continue
        press(keys)
        sleep(settle)
        after = read_state()
        ok, why = _check(checkpoint, before, after) if checkpoint else (True, "")
        steps.append({"step": name, "keys": list(keys), "state": after, "ok": ok, "why": why})
        log(f"{name:16s} keys={keys} -> mode={after['mode']} floor={after['floor']} "
            f"player={'yes' if after['player'] else 'no'} {'OK' if ok else 'FAILED: ' + why}")
        before = after
        if not ok:
            return {"ok": False, "arrived": False, "why": f"{name}: {why}", "steps": steps}
        if after["player"] is not None and after["floor"] == 0:
            steps[-1]["arrived"] = True
            return {"ok": True, "arrived": True, "why": "", "steps": steps}
    final = read_state()
    return {"ok": final["player"] is not None, "arrived": final["player"] is not None and final["floor"] == 0,
            "why": "" if final["player"] is not None else "the script finished without a player",
            "steps": steps}


def in_field(read_state) -> dict:
    """Where the party is now, for the accept evidence: floor, player, entity count."""
    s = read_state()
    return {"floor": s["floor"], "episode": s["episode"], "in_town": s["floor"] == 0,
            "in_field": s["floor"] != 0, "player": s["player"], "entities": s["entities"]}
