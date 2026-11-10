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
    from ...re4_merc_bot import CLOCK_MAX_S
    if not 0 < (snap.get("timer") or 0) <= CLOCK_MAX_S:     # at 0, or a word no clock reads (the Result screen)
        return "results"
    if snap.get("hp") is not None and snap["hp"] <= 0:
        return "dead"
    return "playing"


DRIVER = RE4GC

# The GameCube's weapon classes (re_games / re4_merc_bot: the GC item ids) -> the fire pattern's families, the way
# re4_gc_native.Controller.weapon_choices names them ("magnum" the Broken Butterfly, Killer7 and Hand Cannon).
FIRE_FAMILY_BY_KIND = {"magnum": "magnum", "shotgun": "shotgun", "rifle": "rifle", "gun": "handgun", "rocket": None}


def combat_profile():
    """RE4 GameCube described for the universal core (gbox.mercs.core.combat.TitleProfile; the operator 2026-11-10: "I
    want it able to work with even the ps3, and gamecube versions"). Descriptive: this edition's fight is
    re4_merc_bot.Bot and nothing in it consults the profile yet - the core's tank driver can drive it
    (tests/test_mercs_fire_pattern.py). The world is the Switch edition's (mm), the aim the same tank aim (R held, the
    stick fine-turns it, no pitch), the trigger A: pressed a 50 ms tick down, then up, every PRESS_GAP (about 10 a
    second), or held where the round gun auto-repeats at the x80 class interval (re4_merc_bot.TRIGGER_PRIOR, live
    2026-10-26: the shotgun and the rifle repeat only on presses, 3.1 - 4.6 shots a second; the Hand Cannon held
    fires nothing)."""
    from ..core import combat
    from ... import re4_merc_bot as B
    mm = 10.0
    return combat.TitleProfile(
        title="re4_gc", title_id="G4BE08", units_per_cm=mm, aim_model="tank_heading",
        sticks="tank: the stick turns the body; R held raises the gun, left / right fine-turn the aim (no pitch); "
               "A fires (pressed; held only where the class auto-repeats)",
        aim_btn="r", fire_btn="a", turn_sign=1, raise_tol=B.TURN_TOL, fire_tol_min=B.FIRE_TOL,
        engage_cm=B.ENGAGE / mm, level_dy_cm=250.0, max_dy_cm=250.0,
        bodies=combat.BodyTable(default=combat.HUMAN._replace(r=B.BODY_HALF_W / mm)),
        specials=("melee_follow_up", "knife", "time_bonus_route"),
        fire_pattern=False, fire_style="edge", fire_gap_s=B.PRESS_GAP, fire_tick_s=0.05, fire_cap_hz=0.0,
        fire_cap_note="presses ~10/s by design (PRESS_HOLD 0.04 / PRESS_GAP 0.09 at the 20 Hz loop); measured live "
                      "2026-10-26 (TRIGGER_PRIOR): presses 11.2 - 12.2/s gave the shotgun 3.4 - 4.6 and the rifle 3.1 "
                      "shots/s; the magnums' per-class rate not measured",
        family=lambda kind: FIRE_FAMILY_BY_KIND.get(kind, "handgun") if isinstance(kind, str) else "handgun")
