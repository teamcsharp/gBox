"""007 Agent Under Fire (GW7E69, GameCube) split-screen multiplayer acceptance helpers.

Used to put a modded character slot (e.g. MP "BOND" -> maps/dm1.ngc bond_combat_l.gcm)
on screen in a private 640x480 Dolphin instance driven by xdotool.  Everything here is
pure Python so it can be unit tested without an emulator.

Findings (request #1362, private flatpak Dolphin 2609, Xvfb 640x480):
- Split screen is horizontal: P1 = top half (y 0..239), P2 = bottom half.
- Radar centres: P1 (559.5, 75.5), P2 (559.5, 302); radius ~31 px; heading-up, so the
  other player's dot angle is the relative bearing.  Own dot red ~0x990000, the other
  player's dot dark teal ~0x006464.
- The other player's floating name tag ("AGENT2") is drawn over the body: when the tag
  is in P1's view, the BOND body is in line of sight (unless far/dark).
- Setup menu: P1 stick/D-pad Right on the Combat Training Map row CHANGES THE MAP.  Never
  send turn keys while a menu is up, or the next match loads a different .ngc.
- Pause menu (P1 Start): Continue Mission, Options, Pause Game, Restart Mission,
  Quit Mission; Restart/Quit ask "Are you sure?" with No highlighted (Left, A = Yes).
  Quit Mission goes to "Combat Training Results" (A continue, X rematch) and then back to
  the per-agent Combat Training Menu (START GAME, PLAYER OPTIONS, PLAYER CHARACTER,
  OPTIONS, WEAPONS, POWERUPS, MODIFIERS, BOTS).
- MULTIPLAYER GAME SELECT is a carousel; it remembers the last mode, so do not assume
  COMBAT TRAINING is selected after a previous session.
"""
from __future__ import annotations

import math
from typing import Callable, Optional, Sequence, Tuple

RGB = Tuple[int, int, int]

RADAR_CENTRES = {1: (559.5, 75.5), 2: (559.5, 302.0)}
RADAR_RADIUS = 31

# xdotool key names bound in the private Dolphin profile (GCPadNew.ini).
KEYS = {
    1: {"A": "x", "B": "z", "START": "Return", "UP": "t", "DOWN": "g", "LEFT": "f",
        "RIGHT": "h", "STICK_UP": "Up", "STICK_DOWN": "Down", "STICK_LEFT": "Left",
        "STICK_RIGHT": "Right"},
    2: {"A": "1", "B": "2", "START": "6", "UP": "9", "DOWN": "0", "LEFT": "u",
        "RIGHT": "o", "STICK_UP": "y", "STICK_DOWN": "n", "STICK_LEFT": "b",
        "STICK_RIGHT": "m"},
}

PAUSE_ITEMS = ("Continue Mission", "Options", "Pause Game", "Restart Mission", "Quit Mission")


def is_other_player_dot(px: RGB) -> bool:
    """Dark-teal radar dot of the other player (thresholds from live frames)."""
    r, g, b = px
    return g > 80 and b > 80 and r < 25 and abs(g - b) < 16


def radar_bearing(pixel: Callable[[int, int], RGB], player: int,
                  radius: int = RADAR_RADIUS) -> Optional[Tuple[float, float, int]]:
    """Return (bearing_deg, distance_px, n_pixels) of the other player's radar dot.

    ``pixel(x, y)`` returns an RGB tuple of the 640x480 frame (e.g. PIL ``getpixel``).
    Bearing is clockwise from straight ahead (heading-up radar); None if no dot.
    """
    cx, cy = RADAR_CENTRES[player]
    xs = ys = n = 0
    for y in range(int(cy - radius), int(cy + radius) + 1):
        for x in range(int(cx - radius), int(cx + radius) + 1):
            if (x - cx) ** 2 + (y - cy) ** 2 >= radius ** 2:
                continue
            if is_other_player_dot(pixel(x, y)):
                xs += x; ys += y; n += 1
    if n < 2:
        return None
    dx, dy = xs / n - cx, ys / n - cy
    return math.degrees(math.atan2(dx, -dy)), math.hypot(dx, dy), n


def pause_select(player: int, item: str, confirm: bool = True) -> Sequence[str]:
    """Key sequence: open pause menu, move to ``item`` and select (confirm Yes if asked)."""
    k = KEYS[player]
    idx = PAUSE_ITEMS.index(item)
    seq = [k["START"]] + [k["DOWN"]] * idx + [k["A"]]
    if confirm and item in ("Restart Mission", "Quit Mission"):
        seq += [k["LEFT"], k["A"]]
    return seq


def turn_key(bearing: float, player: int = 1, dead_zone: float = 12.0) -> Optional[str]:
    """Stick key that turns toward ``bearing``; None when already facing it."""
    if abs(bearing) <= dead_zone:
        return None
    return KEYS[player]["STICK_RIGHT" if bearing > 0 else "STICK_LEFT"]
