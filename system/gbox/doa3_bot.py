"""Dead or Alive 3 (Xbox, USA) autoplay playbook: endless Survival, holding the CPU's strikes and punishing them.

The game is the fighting engine's second title (gbox/fightbot/titles/doa3_xbox.py); this module deploys it:
  * reads: the adapter's verified fast channel (doa3_memory.Channel): one ReadProcessMemory a read, per frame;
  * presses: gBox's virtual pad on the game's 4th port (doa3_pad), never the player's own controller;
  * where the game is: its own RAM (the map's screen signatures), never the picture;
  * between fights: the menus the screen says (Survival, a fighter, continue); in a fight: the frame-synced engine
    (fightbot.runner) holds the attacks the map's signatures (or the move book) say are coming, then punishes;
  * learning: the move book per worker (runtime/fightbot/<map id>/book.json) and the lessons log
    (runtime/fightbot/<map id>/runs/<run>.jsonl): hits taken with the attacker's state just before them.
The same title plays the cast builds (#1976 Sonic, #1977 Sonic vs Mario): characters and attacks are RAM values,
never looks, and the build changes only the disc's assets."""
from __future__ import annotations

import time

from .fightbot import survival
from .fightbot.book import Book
from .fightbot.engine import Engine
from .fightbot.lessons import Run
from .fightbot.runner import Sender, fight
from .fightbot.titles import doa3_xbox

GAME_IDS = doa3_xbox.GAME_IDS


def matches(ad, g: dict) -> bool:
    return getattr(ad, "name", "") == "doa3_native" and g.get("game_id") in GAME_IDS


def setup(ad) -> list[str]:
    """Claim the virtual pad (port 4) before the first press; a failure is reported, not raised."""
    try:
        ad.pad().claim()
        return []
    except Exception as error:                     # noqa: BLE001 - a real 4th pad, a closed channel: say so
        return [f"virtual pad: {error}"]


class Deployment:
    """What fightbot.survival needs from DOA3: where the game is, the menu presses, and the fight itself."""
    STILL_FOR, NUDGE_WAIT = 12.0, 12.0
    NUDGE_KEYS = ("b",)                            # A: confirm (START would join a fight as a challenger)
    MENU_GAP = 0.5

    def __init__(self, ad, title=None, book=None, lessons=None, stats=None):
        self.ad = ad
        self.title = title or doa3_xbox.Doa3()
        root = None
        try:
            root = ad.config.runtime / "fightbot"
        except Exception:                          # noqa: BLE001 - no config (tests): in memory only
            pass
        self.book = book or Book(root / doa3_xbox.MAP_ID / "book.json" if root else None)
        self.lessons = lessons if lessons is not None else Run(root, doa3_xbox.MAP_ID)
        self.engine = Engine(self.title, self.book, self.lessons, stats)
        self.WATCH = doa3_xbox.CLOCK               # the frame clock: still = the game loop stopped

    def reader(self, ad):
        return ad.channel().read

    def state(self, rd) -> dict:
        w = self.title.read(rd)
        return {"screen": w.screen, "fighting": w.screen in self.title.fight_screens, "demo": int(w.screen in ("title", "demo")),
                "p1": w.p1.hp or 0, "p2": w.p2.hp or 0, "world": w}

    def menu_key(self, st) -> str | None:
        return self.title.menu(st["world"])

    def fight(self, ad, rd, send, stopped, stats) -> str:
        self.engine.stats = stats
        sender = Sender(send)
        try:
            return fight(self.title, rd, sender, self.engine, stopped, stats=stats)
        finally:
            sender.close()
            self.book.save()
            stats["book"] = self.book.summary()


def play(ad, send, stopped, clock=time.time, sleep=time.sleep, stats: dict | None = None) -> dict:
    """stats (filled live for the watch panel): the survival loop's (fights_s, menu presses, hung, the screen) and
    the engine's (attacks seen, answers, parried, hits taken, damage both ways, punishes, input and reaction latency
    in frames, frames skipped)."""
    stats = stats if stats is not None else {}
    dep = Deployment(ad, stats=stats)
    try:
        return survival.play(dep, ad, send, stopped, clock=clock, sleep=sleep, stats=stats, holds=False)
    finally:
        dep.book.save()
