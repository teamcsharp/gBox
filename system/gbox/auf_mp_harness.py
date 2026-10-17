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
- Run r11: Combat Training Setup rows = Number of Players, Time Limit, Point Limit, Map
  Settings, Combat Training Map (4x D-pad Down from the top).  D-pad Right (P1 ``h``) on the
  map row walks MP_MAPS forward; Cooling Station is maps/dm1.ngc (Bond.elf strings).
- Player Character: BOND is skipped while the other agent holds it (MP_CHARACTERS, P2 ``u``
  forward); otherwise MP_CHARACTERS_WITH_BOND applies (P2 ``o`` forward, BOND between
  IDENTICON GUARD and SUPER THUG).  Other characters may be duplicated.
- dm1 has both models/mp_player_bondcombat.men and mp_player_bondtux.men; they differ only
  in two model indices (body 0x1276 vs 0x1294, limb 0x1278 vs 0x1295) and share the head
  index 0x1277 (bond_head_l.gcm), so a head swap is visible whichever body the menu uses.
- Run r12: P1's radar shows P2 as teal, P2's radar shows P1 as RED (each player's own colour
  is its split-screen border).  Name tags are drawn THROUGH walls, so a tag alone is not line
  of sight.  Cooling Station has a raised marble ledge over a lower pillared floor: when the
  radar dots overlap but no body is visible, the other player is on the other level; tilt the
  viewer down with C-stick Down (P2 ``v``) to see him below the ledge.  r12 got the modded
  AGENT1 (BOND) body this way after a radar-biased random walk (home4.py) of ~170 steps.
- Use radar_bearing() for BOTH halves (P2 radar centre y=302, not 75.5+240); ad-hoc
  colour/centre guesses made the r11 homing loop chase noise.
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

# Combat Training Map carousel order (setup screen, D-pad Right = forward), observed r11.
MP_MAPS = ("Dungeon", "Town", "Wine Cellar", "Red Sector", "Castle", "Cooling Station",
           "Abbey", "Arsenal")
MAP_LEVEL = {"Cooling Station": "maps/dm1.ngc"}

# Player Character cycle (P2 D-pad Left = forward), observed r11 on the GW7E69 disc.
MP_CHARACTERS = ("SUPER THUG", "IDENTICON GUARD", "JACKAL", "MALPRAVE", "RIG DIVER",
                 "BLOCH", "GRIFFIN CLONE", "EVIL ZOE CLONE", "TWIN")
MP_CHARACTERS_WITH_BOND = ("SUPER THUG", "TWIN", "EVIL ZOE CLONE", "GRIFFIN CLONE", "BLOCH",
                           "RIG DIVER", "MALPRAVE", "JACKAL", "IDENTICON GUARD", "BOND")


def cycle_keys(order: Sequence[str], current: str, target: str, fwd: str, back: str) -> Sequence[str]:
    """Shortest key list to move a wrap-around menu value from ``current`` to ``target``."""
    n = len(order)
    i, j = order.index(current), order.index(target)
    ahead = (j - i) % n
    return [fwd] * ahead if ahead <= n - ahead else [back] * (n - ahead)


PAUSE_ITEMS = ("Continue Mission", "Options", "Pause Game", "Restart Mission", "Quit Mission")


def is_other_player_dot(px: RGB, player: int = 1) -> bool:
    """Radar dot of the OTHER player as seen in ``player``'s radar (live frames, r11/r12).

    P1's radar draws P2 in P2's colour (dark teal); P2's radar draws P1 in red.
    """
    r, g, b = px
    if player == 2:
        return r > 130 and g < 70 and b < 70
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
            if is_other_player_dot(pixel(x, y), player):
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
