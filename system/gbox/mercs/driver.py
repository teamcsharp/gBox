"""The per-title driver (docs/mercenaries_engine.md, section 4): what is specific to one Mercenaries - how to read its
round, which screen is up, its prompts' buttons, the brain that plays it - behind one small interface.

A title's map names its driver in its mercs block ("driver": "gbox.mercs.titles.re4_gc"); load(prof) imports it.
"""
from __future__ import annotations

import importlib

PLAYING, DEAD = "playing", "dead"
IN_ROUND = (PLAYING, DEAD, "paused")


class Driver:
    map_id = ""
    # True for a driver with no teamplay (one pad, no SessionRuntime): every round is the bot alone on P1, scored for
    # P1 alone, and the engine records team_role "solo_p1" and scoring_scope "solo" for it (round_reports, MercMode).
    solo_p1 = False
    # Stats the driver's brain counts across a whole turn (they keep growing from round to round): the engine also
    # records each one's amount for the round as "round_<key>" in the round's Notebook row.
    round_counters: tuple = ()

    def snapshot(self, m) -> dict:
        """The round as the brain reads it (the title's own snapshot)."""
        raise NotImplementedError

    def screen(self, m, snap: dict | None) -> str:
        """Where the game is: one of vocab.SCREENS (playing / dead / results / loading / menu / story ...); snap None:
        the driver reads what it needs itself."""
        raise NotImplementedError

    def brain(self, m, stats: dict, clock, learn_dir=None, nav=None):
        """The object that plays a round: tick(snap) -> {"hold": keys} | {"tap": key}, prompt_ok(button, snap, now),
        save(), and stats / _threats for the engine's logs."""
        raise NotImplementedError

    def prompt_source(self, m, stats: dict):
        """() -> the button the game asks for (RAM), raising reactions.Unknown when RAM can't tell; None: none."""
        return None

    def prompt_keys(self, button) -> list:
        """A prompt's button -> the chords to press ("a+b" -> [("a", "b")])."""
        return [tuple(str(button).split("+"))]

    def progress(self, snap: dict) -> dict:
        """Live stats that show the round moving (the deployment's black-screen watch reads timer / ram_progress)."""
        return {}

    def learning_stage(self, snap: dict) -> str | None:
        """The round evidence/recall key. A title may return None until its native identity is readable;
        gameplay continues and the engine tries again on the next playing sample."""
        return getattr(snap.get("nav"), "learning_sig", None) or str(getattr(snap.get("stage"), "key", "unknown"))


def load(prof) -> Driver:
    """The driver a profile names: its mercs block's "driver" module, whose DRIVER is the class (or the instance)."""
    name = (prof.get("driver") if isinstance(prof, dict) else (getattr(prof, "mercs", {}) or {}).get("driver"))
    if not name:
        raise LookupError("the profile's mercs block names no driver")
    mod = importlib.import_module(name)
    d = getattr(mod, "DRIVER")
    return d() if isinstance(d, type) else d
