"""Title: Resident Evil 4 (Nintendo Switch: title 010099A00BC1E000, v1.0.0+)
- The Mercenaries mode, on Citron NEO (canonical, multi-core) or Eden (single-core): gbox.adapters'
  SwitchLinuxAdapter / CitronLinuxAdapter, NCE, where a guest address is the host address.

Measured live 2026-11-04 on the Spark (Citron NEO d3df71e55): the round loads and then waits - timer,
spawns and locomotion all gated - until the round intro is paged with A (INTRO_PRESSES below). That is
input, not a setting: every renderer/CPU-backend/async combination behaves identically
(docs/research/re4-switch-round-gate.md).

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
# Static identity of the Switch build, from Citron's dump_nso (2026-11-05, docs/research/re4-switch-ram.md):
# the file is the 0x100-byte NSO header plus the image at vaddr 0, so a pattern at vaddr V is at base + V
# in the guest (NCE: guest address == host address). Verified live twice on the same boot: the signature was
# found once, at base 0x3ca7c04000, which is also where Citron maps RE6's main.
BUILD_ID = "82C2A04A21D3E0B850F273D4149C9003"     # the dumped main-*.nso name
MAIN_NSO_SHA256 = "98ca897f07b2c864a0cabfb9dd8ca46a54b88c565ba629da3b7a4b6a57a57441"
SIG_OFF = 0x100000                      # deep in the image, away from the load stubs at vaddr 0
SIGNATURE = bytes.fromhex(
    "fd7b07a9fdc30191355100b0b5c646f9a90240f928514439f30300aa88080035"
    "285544391f0d007121080054285100b008bd46f9080140f98a018a5208696a38")


def module_base(m) -> int | None:
    """main's load address this boot (SIG_OFF/SIGNATURE), cached on m and re-checked with one 64-byte read."""
    base = getattr(m, "module_base", None)
    if isinstance(base, int):
        try:
            if bytes(m.rd(base + SIG_OFF, len(SIGNATURE))) == SIGNATURE:
                return base
        except (ValueError, OSError):
            pass
    rows = getattr(m, "rows", None)
    rows = list(rows() if callable(rows) else rows or [])
    for s, e, p in rows:
        if not str(p).startswith("r") or "w" in str(p):
            continue
        step = 1 << 24
        for off in range(s, e, step):
            n = min(step + len(SIGNATURE), e - off)
            try:
                chunk = bytes(m.rd(off, n))
            except (ValueError, OSError):
                break
            at = chunk.find(SIGNATURE)
            if at >= 0:
                m.module_base = off + at - SIG_OFF
                return m.module_base
    return None

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

# Round entry (measured live 2026-11-04 on the Spark: Citron NEO nightly d3df71e55, GB10, NCE, Vulkan;
# docs/research/re4-switch-round-gate.md). THE MERCENARIES loads its stage with the round-intro tips on
# screen and holds the whole round behind them: banner up indefinitely, no HUD timer, no spawns, no
# locomotion, no aim. A is the only button that pages them; one press is not enough and three start the
# clock (timer counting down, Ganados walking in, movement and aim live, verified on screen). No emulator
# setting changes this (multi-core true/false, NCE/Dynarmic, async shaders and presentation on/off were
# all identical), so a round is entered by pressing, the way the GameCube bot walks its menus
# (gbox.re4_menus) - never by waiting for the clock.
INTRO_PRESSES, INTRO_GAP_S = 3, 0.9


def round_entry_events() -> list[dict]:
    """One A press in the shape SwitchLinuxAdapter.send_input takes. Send it INTRO_PRESSES times,
    INTRO_GAP_S apart, once the stage has drawn: the Mercenaries clock starts on the last one."""
    return [{"key": "a", "down": True}, {"key": "a", "down": False}]


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
