"""Title: Resident Evil 4 (Nintendo Switch: title 010099A00BC1E000, v1.0.0+)
- The Mercenaries mode, on Citron NEO (canonical, multi-core) or Eden (single-core): gbox.adapters'
  SwitchLinuxAdapter / CitronLinuxAdapter, NCE, where a guest address is the host address.

This is a skeleton driver prepared for when the operator adds RE4 Switch to the catalog
(operator 2026-10-27: "I am about to add RE4 for switch so our efforts will move there when it is ready").
The RAM map (player, enemies, timer, kills, menus) must be measured live on the Spark before this
driver can play. See gbox.mercs.titles.re5_switch and re6_switch for the measured patterns.

Known from the RE4 GameCube driver (gbox.mercs.titles.re4_gc) and RE4 menus (gbox.re4_menus):
- 5 characters: Leon, Ada, Krauser, Hunk, Wesker
- 4 stages: Village, Castle, Island, Waterworld
- The Mercenaries is a separate mode from the main story
"""
from __future__ import annotations

import math
import struct
import time

from ..driver import Driver

TITLE_ID = "010099A00BC1E000"
MAP_ID = TITLE_ID                       # profiles/gamedata/010099A00BC1E000-ram.json
BUILD_ID = None                         # pending: read from the operator's game once added
SIG_OFF = None                          # pending: 64 read-only bytes of main, unique in the module
SIGNATURE = None                        # pending

# RAM map: pending live measurement on the Spark. The RE4 Switch binary is a port of the
# GameCube / PS2 build (not MT Framework like RE5 / RE6), so the layout will differ from
# re5_switch / re6_switch. Expected structures (from re4_gc and re4_merc_bot):
#   player: position, rotation, health, motion state
#   enemies: Ganados with routine / motion fields (re4_threats)
#   timer: the Mercenaries countdown clock
#   menus: the native menu cursor and screen identifiers
S_MAIN = None                           # pending
S_PLAYER = None                         # pending
S_ENEMY = None                          # pending
S_UNIT = None                           # pending

PHASE_PLAYING, PHASE_OVER = 1, 3


class RE4Switch(Driver):
    map_id = MAP_ID
    solo_p1 = True                              # Mercenaries on Switch is played solo here
    round_counters = ("shots", "hits", "turns", "quick_turns", "backoffs", "holds", "dying", "escapes")

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._timer = (None, 0.0)
        self.stats: dict | None = None

    def snapshot(self, m) -> dict:
        """The round from RAM: pending live measurement. Returns the minimal shape the engine needs."""
        snap: dict = {"player": None, "enemies": [], "timer": None, "timer_start": None, "score": None,
                      "kills": None, "combo": None, "combo_timer": None, "max_combo": None,
                      "mercenaries_phase": None}
        # TODO: measure live on the Spark once the operator adds the game
        return snap

    def screen(self, m, snap: dict | None) -> str:
        """playing / dead / results / loading for the engine. Pending live measurement."""
        snap = self.snapshot(m) if snap is None else snap
        return own_screen(snap)

    def brain(self, m, stats: dict, clock, learn_dir=None, nav=None):
        self.stats = stats
        return Bot(stats=stats, clock=clock)

    def prompt_keys(self, button) -> list:
        return [tuple(str(button).split("+"))]

    def progress(self, snap: dict) -> dict:
        return {"timer": snap.get("timer"), "combo": snap.get("combo"), "score": snap.get("score"),
                "kills": snap.get("kills"), "max_combo": snap.get("max_combo"),
                "mercenaries_phase": snap.get("mercenaries_phase"), "mode": "mercenaries"}


def own_screen(snap: dict) -> str:
    """playing / dead / results / loading from the round's fields alone. Pending live measurement."""
    p, phase = snap.get("player"), snap.get("mercenaries_phase")
    if not p:
        return "results" if phase in (PHASE_PLAYING, PHASE_OVER) else "loading"
    if phase == PHASE_OVER:
        return "results"
    if p.get("hp") is not None and p["hp"] <= 0:
        return "dead"
    return "playing" if phase == PHASE_PLAYING else "loading"


class Bot:
    """One decision per tick from the snapshot. Pending live measurement and combat rules."""

    def __init__(self, stats: dict | None = None, clock=time.monotonic):
        self.stats = stats if stats is not None else {}
        self.clock = clock
        self.target = None

    def tick(self, snap: dict):
        """Pending: the RE4 Switch combat brain (rain fire, mods parity with re4_gc)."""
        return {}

    def prompt_ok(self, button, snap, now):
        return False

    def save(self):
        pass


DRIVER = RE4Switch
