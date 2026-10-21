"""Reactions (docs/mercenaries_engine.md, section 3): the prompts the game shows - pressed from RAM first, vision only
when RAM can't tell - with the burst / rest rule that keeps a stuck prompt from owning the pad.

    pp = PromptPresser(source=driver.prompt_source(m, stats), keys=driver.prompt_keys, stats=stats)
    chords = pp.step(now, ok=lambda button: brain.prompt_ok(button, snap, now))   # None, or the chords to press now
"""
from __future__ import annotations

EVERY, BURST, REST = 0.6, 3, 5.0         # press a prompt this often; still up after BURST presses in 3 s: rest REST s
MASH = frozenset({"wiggle", "mash"})     # held by an enemy (RE4 SHAKE OFF: every new stick direction and every new A /
                                         # B counts, 0x8014141C): pressed every step while it shows, never rested - the
                                         # hold drains health until it is shaken off (live 2026-10-21: 10 hp a frame,
                                         # 1.6-2 s a grab at one burst every 0.6 s)


class Unknown(Exception):
    """The RAM source can't tell this prompt (another game, a torn read, a kind not in its tables)."""


class PromptPresser:
    def __init__(self, source=None, vision=None, keys=None, stats: dict | None = None, unknown=(Unknown, LookupError)):
        self.source, self.vision = source, vision
        self.keys = keys or (lambda b: [(b,)])
        self.stats = stats if stats is not None else {}
        self.unknown = unknown
        self.taps: list[float] = []
        self.rest_until = 0.0
        self.mashing = False                 # the last step's chords are a mash (press them fast, no pause after)
        self.stats.setdefault("prompt_presses", 0)

    def ask(self, vision: bool = True):
        """The button the game asks for now: RAM, else vision (unless vision is False), else None."""
        if self.source:
            try:
                b = self.source()
                self.stats["prompt_source"] = "ram"
                return b
            except self.unknown:
                pass
        if vision and self.vision is not None:
            self.stats["prompt_source"] = "vision"
            return self.vision()
        return None

    def step(self, now: float, ok=None):
        """The chords to press now for the prompt on screen, or None (no prompt, held by ok(), resting, or not yet:
        EVERY s between presses). A mash (MASH) is pressed every step, resting or not."""
        resting = now < self.rest_until
        button = self.ask(vision=not resting)              # resting: RAM only (one byte), for a grab
        self.mashing = button in MASH
        if isinstance(button, str) and button.startswith("mash:"):
            # Extended mash requests must resolve through the title's allowlisted chord decoder first.
            chords = self.keys(button)
            if not chords or any(not chord or any(not isinstance(k, str) or ":" in k for k in chord)
                                 for chord in chords):
                self.mashing = False
                return None
            self.mashing = True
            self.stats["prompt_presses"] += 1
            self.stats["mash_presses"] = self.stats.get("mash_presses", 0) + 1
            return chords
        if self.mashing:
            self.stats["prompt_presses"] += 1
            self.stats["mash_presses"] = self.stats.get("mash_presses", 0) + 1
            return self.keys(button)
        if resting:
            return None
        if button and ok is not None and not ok(button):
            button = None
        if not button:
            self.taps = []
            return None
        self.taps = [t for t in self.taps if now - t < 3.0]
        if len(self.taps) >= BURST:
            self.rest_until, self.taps = now + REST, []
            return None
        if self.taps and now - self.taps[-1] < EVERY:
            return None
        self.taps.append(now)
        self.stats["prompt_presses"] += 1
        return self.keys(button)
