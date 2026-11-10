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
