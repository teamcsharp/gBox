"""Title #1: Resident Evil 4, GameCube NTSC-U (G4BE08) - the Mercenaries driver.

Its round is read by gbox.re4_merc_bot.snapshot (Leon, the EmMgr Ganados with their routine / motion fields from
gbox.re4_threats, the thrown weapons, the clock); its brain is re4_merc_bot.Bot (the threats-first combat, the time
bonus route on the disc's level map, the learned map); its prompts come from RAM (gbox.re4_ram_prompts: the action
manager's button kind); the screen from gbox.re4_menus when that module is there (the title task's work area), else
from the round's own fields (room 0x04RR, the clock, Leon's pointer and health).
"""
from __future__ import annotations

from ..driver import Driver

try:
    from ... import re4_ram_prompts
except ImportError:                                  # a tree without it: vision only
    re4_ram_prompts = None


class RE4GC(Driver):
    map_id = "G4BE08"

    def __init__(self):
        from ... import re4_merc_bot
        self.B = re4_merc_bot
        try:
            from ... import re4_menus
            self.menus = re4_menus
        except Exception:                            # noqa: BLE001 - not merged yet: the round's own fields
            self.menus = None
        self.prompt_unknown = (re4_ram_prompts.Unknown,) if re4_ram_prompts is not None else (LookupError,)

    def snapshot(self, m) -> dict:
        return self.B.snapshot(m)

    def screen(self, m, snap: dict | None) -> str:
        snap = self.snapshot(m) if snap is None else snap
        if self.menus is not None:
            try:
                where = (self.menus.screen(m, merc=snap) or {}).get("where")
                if where and where != "unknown":
                    return where
            except Exception:                        # noqa: BLE001 - the round's own fields below
                pass
        return own_screen(snap)

    def brain(self, m, stats: dict, clock, learn_dir=None, nav=None):
        bot = self.B.Bot(m, clock=clock, learn_dir=learn_dir, nav=nav)
        stats.update({k: v for k, v in bot.stats.items() if k not in stats})
        bot.stats = stats
        return bot

    def prompt_source(self, m, stats: dict):
        return re4_ram_prompts.source(m, stats) if re4_ram_prompts is not None else None

    def prompt_keys(self, button) -> list:
        if re4_ram_prompts is not None:
            return re4_ram_prompts.KEYS.get(button, [(button,)])
        return super().prompt_keys(button)

    def progress(self, snap: dict) -> dict:
        return {"timer": snap.get("timer"), "combo": snap.get("combo")}

    @property
    def frame(self):
        """The game's frame for the frame-synced tick: the Mercenaries clock (frames, counts down once a game frame
        while the round runs); .vi(m): the VI retrace count (0x802B2D2C, 60 a second: __VIRetraceHandler 0x80078FEC
        increments it, VIWaitForRetrace 0x80079A00 waits on it) for the latency stats."""
        return _Frame()


class _Frame:
    MERC_TIMER, VI_COUNT = 0x80279308, 0x802B2D2C

    def __call__(self, m):
        return int.from_bytes(m.rd(self.MERC_TIMER, 4), "big")

    def vi(self, m):
        return int.from_bytes(m.rd(self.VI_COUNT, 4), "big")


def own_screen(snap: dict) -> str:
    """The screen from the round's fields: no room / no Leon = loading; a room outside stage 4 = story; the clock at
    0 = results; Leon's health at 0 = dead (the "Continue" screen keeps the room and the clock); else playing."""
    room = snap.get("room")
    if room is None or not snap.get("player"):
        return "loading"
    if room >> 8 != 4:
        return "story"
    if (snap.get("timer") or 0) <= 0:
        return "results"
    if snap.get("hp") is not None and snap["hp"] <= 0:
        return "dead"
    return "playing"


DRIVER = RE4GC
