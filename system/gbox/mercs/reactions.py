"""Reactions (docs/mercenaries_engine.md, section 3): the prompts the game shows - pressed from RAM first, vision only
when RAM can't tell - with the burst / rest rule that keeps a stuck prompt from owning the pad.

    pp = PromptPresser(source=driver.prompt_source(m, stats), keys=driver.prompt_keys, stats=stats)
    chords = pp.step(now, ok=lambda button: brain.prompt_ok(button, snap, now))   # None, or the chords to press now
"""
from __future__ import annotations

EVERY, BURST, REST = 0.6, 3, 5.0         # press a prompt this often; still up after BURST presses in 3 s: rest REST s


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
        self.stats.setdefault("prompt_presses", 0)

    def ask(self):
        """The button the game asks for now: RAM, else vision, else None."""
        if self.source:
            try:
                b = self.source()
                self.stats["prompt_source"] = "ram"
                return b
            except self.unknown:
                pass
        if self.vision is not None:
            self.stats["prompt_source"] = "vision"
            return self.vision()
        return None

    def step(self, now: float, ok=None):
        """The chords to press now for the prompt on screen, or None (no prompt, held by ok(), resting, or not yet:
        EVERY s between presses)."""
        if now < self.rest_until:
            return None
        button = self.ask()
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
