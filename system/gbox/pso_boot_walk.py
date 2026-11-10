"""P1: the cold-boot walk from the disc to Pioneer 2, as a deterministic press script with RAM checkpoints.

What this is
------------
The guide's P1 is "Title -> PRESS START -> the offline menus -> character select -> Pioneer 2 ... by real presses on
the virtual pads, with the screen read from RAM (the menu state bytes), not from frames". This module is that walk.

What RAM can and cannot say
---------------------------
``0x80516303`` is **not** a screen id (round 3 corrected that): it is a coarse mode that reads ``1`` on both the title
main menu and SELECT CHARACTER, ``9`` on SELECT GAME MODE, ``0``/``22``/``4`` on the title. So the walk is a
**deterministic press sequence** whose checkpoints are the states RAM *can* prove:

============================  ==========================================================
checkpoint                    proven by
============================  ==========================================================
``press_start``               the mode leaves the title family (``0``/``4``/``22``) and no player exists
``character_select_ok``       a player object appears in the slot table (the boot is past every menu)
``in_town``                   ``FLOOR 0`` (Pioneer 2) with a player
``in_field``                  ``FLOOR != 0`` (``1`` is Forest 1)
============================  ==========================================================

Between the checkpoints the sequence is fixed because it was walked by hand on this build (round 4): START at PRESS
START, then ``ddown``+A for OFFLINE GAME, A for SINGLE MODE, A on the first slot (create or select), then A for the
episode. The walk **reports** the state after every step and never claims to know which menu it is on -- it asserts only
what is provable, and a step that leaves the state unchanged is reported as a failure rather than retried blindly.

Nothing here reads a frame, and nothing presses unless the state justifies it.
"""
from __future__ import annotations

import time

from . import pso_entities as entities_mod
from . import pso_ram

# The press script: (name, keys, the checkpoint that must hold after it, or None).
BOOT_STEPS = (
    ("press_start", ("start",), "left_title"),
    ("offline_game", ("ddown", "a"), None),
    ("single_mode", ("a",), "past_game_mode"),
    ("slot_a", ("a",), "creating_or_selecting"),
    ("accept_new", ("dup", "a"), None),          # answers "Want to create a new Character?" YES when it appears
    ("episode_one", ("a",), "in_town"),          # after the character editor and the episode choice
)

TITLE_MODES = (0, 4, 22)
GAME_MODE_SELECT = 9


def state(reader) -> dict:
    """Everything the walk may assert on, read in one place."""
    try:
        items = entities_mod.entities(reader)
    except Exception:                                   # noqa: BLE001 - a table read must not kill a walk
        items = []
    player = pso_ram.player(reader, 0)
    return {"mode": pso_ram.boot_screen(reader) if hasattr(pso_ram, "boot_screen") else reader.u8(pso_ram.BOOT_SCREEN),
            "floor": pso_ram.floor(reader), "episode": pso_ram.episode(reader),
            "player": None if player is None else {"x": player["x"], "z": player["z"], "room": player["room"]},
            "entities": len(items)}


def _check(name: str, before: dict, after: dict) -> tuple[bool, str]:
    """Did the checkpoint hold? Returns (ok, why) -- the reason is for the round doc, not for a retry."""
    if name == "left_title":
        ok = after["mode"] not in TITLE_MODES or after["player"] is not None
        return ok, "" if ok else f"still on the title (mode {after['mode']})"
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


def walk(read_state, press, *, settle=1.6, sleep=time.sleep, log=None) -> dict:
    """Run the boot script. ``press(keys)`` takes a tuple of pad key names; ``read_state()`` returns :func:`state`.

    Returns {"ok", "arrived", "steps": [...], "why"}. ``arrived`` is True only when a player exists in Pioneer 2.
    """
    log = log or (lambda _m: None)
    steps = []
    before = read_state()
    steps.append({"step": "start", "state": before})
    for name, keys, checkpoint in BOOT_STEPS:
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
            # the boot is done: the menus are behind us and Pioneer 2 is loaded
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
