"""P1: PSO's boot menus, read from RAM (never from frames).

The guide's P1 asks for the title -> PRESS START -> the offline menus walk "with the screen read from RAM (the menu
state bytes), not from frames". This module is that state: the boot screen id, proven live on the owned disc.

The screen id
-------------
``0x80516303`` is a **u8 boot-screen id**, and ``0x805145F7`` carries the same value (a mirror; both were equal in
every sample, so either can be read and both are exposed). Values proven in a live i9-NUC session
(``7246f3becd6f47b7-ac1aab64c26240b9``, Dolphin 2609, PSO Episode I & II Plus ``GPOE8P``):

======  ==========================================================================
 ``3``   **PRESS START** - the title screen. This is the state the campaign never left.
 ``1``   the title main menu (ONLINE GAME / OFFLINE GAME / OPTIONS / WEBSITE)
 ``9``   the ONLINE GAME submenu (the "Online Game" / "Options" tab pair)
 ``0``   transient: unset, or a fade between screens
 ``4``   the title with its menu closed (the attract/title presentation)
======  ==========================================================================

The proof is a reproducible transition, not a guess: at ``3`` a ``start`` press takes the id to ``1`` (three times in
a row), and at ``1`` the menu stays up until something is confirmed. Confirming ONLINE GAME (``start``/``a`` on the
highlighted item) took it to ``9``; cancelling from there (``b``) reached ``3``.

What this does **not** say: ``0x80516303`` was found by a constancy-filtered whole-RAM diff across a START press (an
animated byte looked like a cursor once and was a logo counter), then confirmed by driving transitions and reading
the result back. The old ROM's ``PHASE`` byte at ``0x804FE120`` does **not** distinguish the title from the menus -
it read 0 in both - which is why the screen id is the variable P1 needs.

The walk
--------
:func:`press_start` is the first step: read the screen, and if it is PRESS START, press START and wait for the main
menu. It takes the read and press functions as arguments so it is testable without an emulator, and it reports what
it saw rather than claiming success.
"""
from __future__ import annotations

import time

from .pso_ram import PHASE, Reader, RamError

# The boot-screen id (u8) and its mirror.
BOOT_SCREEN = 0x80516303
BOOT_SCREEN_MIRROR = 0x805145F7

PRESS_START = 3          # the title screen
MAIN_MENU = 1            # ONLINE GAME / OFFLINE GAME / OPTIONS / WEBSITE
ONLINE_SUBMENU = 9       # the "Online Game" / "Options" tab pair
TRANSIENT = 0            # unset / mid-fade
TITLE_CLOSED = 4         # the title with the menu closed

SCREEN_NAMES = {
    TRANSIENT: "transient",
    MAIN_MENU: "main_menu",
    PRESS_START: "press_start",
    TITLE_CLOSED: "title",
    ONLINE_SUBMENU: "online_submenu",
}

# The title main menu's items, in the order the screen shows them (top to bottom). The cursor index itself is not
# identified yet; this is the order a cursor walks, and it is what the offline walk will index.
MAIN_MENU_ITEMS = ("ONLINE GAME", "OFFLINE GAME", "OPTIONS", "WEBSITE")


class MenuError(RuntimeError):
    pass


def screen(reader: Reader) -> int:
    """The boot-screen id. Raises when the two bytes disagree, which means the read is not the state we think."""
    a = reader.u8(BOOT_SCREEN)
    b = reader.u8(BOOT_SCREEN_MIRROR)
    if a != b:
        raise MenuError(f"boot screen id {a} and its mirror {b} disagree; refusing to act on a torn read")
    return a


def screen_name(value: int) -> str:
    return SCREEN_NAMES.get(value, f"unknown({value})")


def describe(reader: Reader) -> dict:
    """A small status record for telemetry and the round docs."""
    value = screen(reader)
    return {"screen": value, "name": screen_name(value), "phase": reader.u8(PHASE),
            "at_press_start": value == PRESS_START, "in_main_menu": value == MAIN_MENU}


def press_start(reader: Reader, press, *, watcher=None, tries: int = 6, settle: float = 0.6,
                wait: float = 8.0, sleep=time.sleep) -> dict:
    """From PRESS START to the title main menu, by real presses, reporting what is on screen.

    ``press`` takes pad key names (``press("start")``). ``watcher`` is an optional zero-argument callable run
    between attempts (the live driver's frame grab). Returns a dict with the observed trace; ``ok`` is True only
    when the screen really reached the main menu.
    """
    trace = []
    for _ in range(tries):
        value = screen(reader)
        trace.append(value)
        if value == MAIN_MENU:
            return {"ok": True, "from_press_start": trace[0] == PRESS_START, "screen": value,
                    "name": screen_name(value), "trace": trace}
        if value != PRESS_START:
            # Some other screen: PRESS START is not what is up, so pressing START could confirm something.
            raise MenuError(f"expected PRESS START ({PRESS_START}), the screen reads {value} "
                            f"({screen_name(value)}); refusing to press START blind")
        press("start")
        deadline = time.monotonic() + wait
        moved = False
        while time.monotonic() < deadline:
            sleep(settle)
            if watcher is not None:
                watcher()
            now = screen(reader)
            if now != value:
                trace.append(now)
                moved = True
                break
        if not moved:
            trace.append(value)
    final = screen(reader)
    return {"ok": final == MAIN_MENU, "from_press_start": trace[:1] == [PRESS_START],
            "screen": final, "name": screen_name(final), "trace": trace}
