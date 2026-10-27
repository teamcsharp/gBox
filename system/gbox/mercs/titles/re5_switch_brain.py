"""RE5 Switch fights with the RE5 PS3 combat core (operator 2026-10-27: "the aiming is just atrocious in this game. I
assume the bot will get the same mind that we trained on the ps5 so it is more effective").

The same game: MT Framework, the same world units (cm, y up), the same Majini and weapons (the inventory's item ids
match: 0x02 the M92F ...). Only the memory layout and the pad differ, so the PS3 combat layer (re5_combat.Combat: its
target choice, laser and dot logic, fire gates, steering, calibration and shot records) runs unchanged on:

    SwitchIO     the title IO (gbox.mercs.brain.io): the player from the snapshot, no action object, the motion byte's
                 shot (29) as the fire signal, the class name as the character, the x80 fire-rate mod as rapid fire
    view()       the Switch snapshot in the fields the combat layer reads (the motion byte as the PS3 action: 26 aimed /
                 29 a shot = aiming, 22 the gun still coming up, the holds = grabbed), the laser as the PS3's {from, at};
                 while the motion byte says the gun is up, the last ray stands in for a laser dropout (FLICKER_S: the
                 Switch laser reads down for a tick in a shot, live 2026-10-27)
    PS3_TO_SWITCH the PS3 pad's keys on Type D (L1 -> ZL, R1 -> ZR, cross -> B, square -> Y, ...)
    Fighter      observe() every tick, fight() when the Switch bot's survival rules hand over

The Switch bot (re5_switch.Bot) keeps its own menus, Continue, mods, heal on Y, break free and escapes; the calibration
and tunables learned here are kept under gbox-data/mercs/learned/010018100CD46000 (not mixed into the PS3's).
"""
from __future__ import annotations

import math

from ..brain.io import NullIO

MAP_ID = "010018100CD46000"
MOTION_AIMED = frozenset({26, 29})       # aimed, a shot: the PS3's action 2 (aiming)
MOTION_RAISING = 22                      # the gun coming up: not ready yet
MOTION_HELD = frozenset({100, 106, 107, 113, 114})   # grabbed, held, strangled: the PS3's action 4
MOTION_MOVING = frozenset({1, 7})        # walking, backing up: the PS3's action 1
MOTION_SHOT = 29
FLICKER_S = 0.6
PS3_TO_SWITCH = {"l1": "zl", "r1": "zr", "cross": "b", "square": "y", "triangle": "x", "circle": "a", "l2": "l",
                 "r2": "r", "start": "plus", "select": "minus"}
DECISIONS = {"fire": "fire", "aim": "aim", "raise the gun": "raise", "swing (gun down)": "turn", "turn": "turn",
             "quick turn": "quick_turn", "reposition": "reposition", "wait": "aim", "hold": "aim"}


def action_of(motion) -> int:
    if motion in MOTION_AIMED:
        return 2
    if motion in MOTION_HELD:
        return 4
    if motion in MOTION_MOVING:
        return 1
    return 0


def switch_keys(keys) -> tuple:
    return tuple(sorted(PS3_TO_SWITCH.get(k, k) for k in keys or ()))


def switch_act(act: dict) -> dict:
    """A combat decision ({"hold": PS3 keys} / {"tap": key}) on the Switch pad."""
    if "tap" in act:
        return {"tap": PS3_TO_SWITCH.get(act["tap"], act["tap"])}
    return {"hold": switch_keys(act.get("hold"))}


class SwitchIO(NullIO):
    """The Switch's answers to the combat layer's RAM questions (bind(view) every tick)."""

    def __init__(self, m=None):
        super().__init__()
        self.m = m
        self._character = None

    def fire_command(self, pl) -> int:
        p = self.snap.get("player") or {}
        return 4 if p.get("motion") == MOTION_SHOT else 0

    def character(self, pl) -> str:
        if self._character is None:
            name = None
            if self.m is not None and pl:
                try:
                    from .re5_switch import class_name
                    name = class_name(self.m, pl)
                except Exception:                            # noqa: BLE001 - a name is a courtesy of the tunables
                    name = None
            self._character = (name or "?").removeprefix("uPl00").lower() if name else "?"
        return self._character

    def rapid_fire(self, wid) -> bool:
        return True                                          # the x80 fire-rate mod (re5_switch_mods) every round


class Fighter:
    """The PS3 combat layer on a Switch round: observe() every tick (its shot / hit / kill accounting), fight() for the
    decision when the survival rules let the fight go on. look: the Switch bot's BotLook (the combat layer records its
    shots there, in the shared shape)."""

    def __init__(self, m, stats: dict, clock, look=None, learn_dir=None, lessons=None):
        from . import re5_combat
        self.io = SwitchIO(m)
        self.combat = re5_combat.Combat(m, stats, clock=clock, learn_dir=learn_dir, lessons=lessons, io=self.io,
                                        map_id=MAP_ID)
        self.combat.look = look
        self.stats = stats
        self.last_ray, self.ray_seen = None, None
        self.view_at = None
        self._view = None
        self.flickering = False                              # this tick's laser is the last ray standing in

    def view(self, snap: dict, now: float) -> dict:
        """The Switch snapshot in the PS3 combat layer's fields (built once per tick)."""
        if self._view is not None and self.view_at == now and self._view.get("_src") is snap:
            return self._view
        p = snap.get("player")
        out = {"_src": snap, "player": None, "enemies": [dict(e) for e in snap.get("enemies") or ()],
               "inventory": [dict(s) for s in snap.get("inventory") or ()], "laser": None, "recovery_active": False,
               "prompt": None, "stage_prompt": False, "prompt_target": None, "nav": None, "control_player": 1}
        for k in ("timer", "timer_start", "kills", "combo", "combo_timer", "score", "mercenaries_phase"):
            out[k] = snap.get(k)
        self.flickering = False
        if p:
            motion = p.get("motion")
            out["player"] = {"ptr": p.get("ptr"), "pos": tuple(p["pos"]), "rot": p["rot"], "pitch": None,
                             "action": action_of(motion), "motion": motion, "hp": p.get("hp"), "hp_max": p.get("hp_max")}
            lz = snap.get("laser")
            if lz and lz.get("up"):
                out["laser"] = {"from": tuple(lz["from"]), "at": tuple(lz["at"])}
                self.last_ray, self.ray_seen = out["laser"], now
            elif motion in MOTION_AIMED and self.last_ray is not None and self.ray_seen is not None \
                    and now - self.ray_seen <= FLICKER_S:
                out["laser"] = self.last_ray                  # the dropout in the shot: the gun is up, aim on
                self.flickering = True
            elif motion not in MOTION_AIMED:
                self.last_ray = None
        self._view, self.view_at = out, now
        self.io.bind(out)
        return out

    def observe(self, snap: dict, now: float) -> dict:
        view = self.view(snap, now)
        if view["player"]:
            self.combat.observe(view, now)
        return view

    def fight(self, snap: dict, live: list, now: float) -> tuple[dict, str, str]:
        """(the Switch pad's decision, what (re5_switch.DOINGS), why) for this tick: the combat layer's target (the one
        under the dot, the nearest threat in front, one at arm's length, ...) and its decision, or its seek (no target)."""
        view = self.observe(snap, now)
        p = view["player"]
        keys = {e.get("ptr"): e for e in view["enemies"]}
        mine = [keys[e.get("ptr")] for e in live if e.get("ptr") in keys]
        self.combat.observe_awareness(view, p, now)
        tgt = self.combat.choose_target(view, p, mine, now) if mine else None
        if tgt is None:
            if not mine:
                return {"hold": ()}, "no_foes", "no Majini alive on his level"
            act = self.combat.seek_target(view, p, mine, now)
        else:
            act = self.combat.tick(view, p, tgt, now, observed=True)
        what, why = self.combat.look_decision or ("hold", "")
        doing = DECISIONS.get(what, "aim")
        if tgt is not None and doing == "aim" and "zr" in switch_keys((act or {}).get("hold")):
            doing = "fire"
        return switch_act(act or {"hold": set()}), doing, str(why or self.stats.get("combat") or "")[:160]

    def end_round(self, now: float) -> None:
        try:
            self.combat.end_round(now)
        except Exception as exc:                             # noqa: BLE001 - the round's learning never stops a bot
            self.stats["brain_error"] = f"end_round {type(exc).__name__}: {exc}"[:160]
