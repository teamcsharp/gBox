"""Player 2's pad for PSO offline multiplayer: the keyboard device Dolphin's GCPad2 binds.

Two measured facts make this module worth having (i9-NUC 2026-11-10):

1. **Each player's character select answers only its own pad.** Pressing P1's virtual pad on "Please select Player 2's
   character." does nothing at all; P2's A opens the "Want to create a new Character?" prompt. Any driver that presses one
   pad and expects the other player's screen to move will sit there forever.
2. **The key names are case-sensitive and uppercase.** `win_send_keys` accepted ``NUMPAD7`` and reported ``sent: 2``, while
   ``numpad7`` reported ``sent: 0`` -- a silent no-op. Dolphin's `GCPad2` in `pso_coop_setup.PAD2_WIN` writes names like
   ``NUMPAD7``, ``SPACE`` and single letters, and those exact strings are what the keyboard path needs.

The mapping below is the one `pso_coop_setup.PAD2_WIN` installs, so a caller can say `PRESS["a"]` and get the key that
Dolphin''s second pad actually holds.
"""
from __future__ import annotations

PRESS = {
    "a": "D",
    "b": "R",
    "x": "M",
    "y": "Y",
    "z": "P",
    "start": "SPACE",
    "up": "NUMPAD8",
    "down": "NUMPAD2",
    "left": "NUMPAD4",
    "right": "NUMPAD6",
    "cup": "C",
    "cdown": "V",
    "cleft": "B",
    "cright": "N",
    "l": "U",
    "r": "O",
    "dup": "NUMPAD7",
    "ddown": "NUMPAD9",
    "dleft": "NUMPAD1",
    "dright": "NUMPAD3",
}

# The names `win_send_keys` accepts are the uppercase spellings above; anything else is silently dropped.
UPPERCASE_ONLY = ("NUMPAD8", "NUMPAD2", "NUMPAD4", "NUMPAD6", "NUMPAD7", "NUMPAD9",
                  "NUMPAD1", "NUMPAD3", "SPACE")


def key(button: str) -> str:
    """The keyboard key for a P2 button name, validated against the uppercase rule."""
    name = PRESS.get(button.lower())
    if name is None:
        raise KeyError(f"unknown player-two button {button!r}; known: {sorted(PRESS)}")
    if name in UPPERCASE_ONLY and not name.isupper():
        raise ValueError(f"{name!r} must be sent uppercase or the keyboard path drops it")
    return name


def events(*buttons: str) -> list[dict]:
    """A down+up event pair per button, in the shape `/api/sessions/{sid}/input` and `win_send_keys` take."""
    out = []
    for button in buttons:
        name = key(button)
        out += [{"key": name, "down": True}, {"key": name, "down": False}]
    return out


def chord(*buttons: str) -> list[dict]:
    """All buttons pressed together, then released in reverse: for prompts whose cursor must move before A lands."""
    names = [key(b) for b in buttons]
    return [{"key": n, "down": True} for n in names] + [{"key": n, "down": False} for n in reversed(names)]

# --- movement: the same keyboard trick applies to BOTH players, and it is the only path that works ---------------
#
# Measured in split-screen co-op in Pioneer 2 (i9-NUC 2026-11-10), with both characters standing free in room 10:
#
#   P1 (virtual pad)    stick `up/down/left/right`, held 1.2 s each    position unchanged
#   P1 (keyboard)       arrow keys `up`/`down`, held 1.4 s each        229,254 -> 175,254 -> 222,234   MOVED
#   P2 (keyboard pad)   `NUMPAD8`/`NUMPAD2`, held 1.4 s each           231,267 -> 181,274 -> 233,274   MOVED
#
# So the virtual pad's buttons reach the game (menus advance) but its **analog stick never does**, while the keyboard
# bindings that both pads carry as fallbacks work perfectly. A driver must therefore move characters through
# `win_send_keys`, not through the virtual pad -- which also means the Dolphin window has to be foreground while moving.
MOVEMENT = {
    1: {"up": "up", "down": "down", "left": "left", "right": "right"},
    2: {"up": "NUMPAD8", "down": "NUMPAD2", "left": "NUMPAD4", "right": "NUMPAD6"},
}


def move_key(player: int, direction: str) -> str:
    """The keyboard key that moves ``player`` (1 or 2) in ``direction``."""
    player = int(player)
    if player not in MOVEMENT:
        raise KeyError(f"player {player} has no movement bindings; known: {sorted(MOVEMENT)}")
    try:
        return MOVEMENT[player][direction.lower()]
    except KeyError:
        raise KeyError(f"unknown direction {direction!r}; known: {sorted(MOVEMENT[player])}") from None


def move_events(player: int, direction: str, *, seconds: float = 1.2) -> list[dict]:
    """A held movement press for the keyboard path: down now, and the caller sends the up after ``seconds``.

    Returned as two batches rather than one so a caller can walk in steps:
    ``move_events(...)[0]`` to start, sleep, ``move_events(...)[1]`` to stop.
    """
    key = move_key(player, direction)
    return [[{"key": key, "down": True}], [{"key": key, "down": False}]]
