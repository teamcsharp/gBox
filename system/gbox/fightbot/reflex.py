"""The onset reflex, for titles without a frame clock or attack signatures yet (DOA2 LE: only the opponent's
attack-input edge): on the edge press the guard button with the direction that paid best so far (the book: untried
ones first, then mostly the best), released after hold_s, judged by health dealt minus taken judge_s after the press.
step(now) is one poll; the caller runs it every ~10 ms while a fight is on."""
from __future__ import annotations

import struct

from .book import Book


class OnsetReflex:
    def __init__(self, rd, send, stats: dict, *, warn: int, hp: tuple[int, int], hp_max: int, guard: str,
                 options: tuple, hold_s: float, judge_s: float, explore: float = 0.2, rng=None, hp_fmt: str = "<H",
                 book: Book | None = None, key: str = "warn"):
        self.rd, self.send, self.stats = rd, send, stats
        self.warn, self.hp_at, self.hp_max, self.guard = warn, hp, hp_max, guard
        self.options, self.hold_s, self.judge_s, self.fmt, self.key = options, hold_s, judge_s, hp_fmt, key
        self.names = ["+".join(o) for o in options]
        self.book = book or Book(explore=explore, rng=rng)
        if rng is not None:
            self.book.rng = rng
        self.book.explore = explore
        self.prev, self.down, self.release_at, self.judge = 0, None, None, None
        stats.update(holds=0, hold_dealt=0, hold_taken=0)

    def _hp(self):
        n = struct.calcsize(self.fmt)
        return tuple(struct.unpack(self.fmt, self.rd(a, n))[0] for a in self.hp_at)

    def step(self, now):
        if self.release_at is not None and now >= self.release_at:
            self.send([{"key": k, "down": False} for k in (self.guard, *self.down)])
            self.release_at = None
        if self.judge is not None and now >= self.judge[0]:
            _, name, p1, p2 = self.judge
            n1, n2 = self._hp()
            dealt = max(0, p2 - n2) if n2 <= self.hp_max else 0
            taken = max(0, p1 - n1) if n1 <= self.hp_max else 0
            self.book.record(self.key, None, name, dealt - taken, met=bool(dealt or taken))
            self.stats["hold_dealt"] += dealt
            self.stats["hold_taken"] += taken
            self.stats["hold_best"] = self.book.best(self.key)
            self.judge = None
        w = self.rd(self.warn, 1)[0]
        if w and not self.prev and self.judge is None and self.release_at is None:
            name = self.book.choose(self.key, None, self.names)
            h = self.options[self.names.index(name)]
            p1, p2 = self._hp()
            self.send([{"key": k, "down": True} for k in (self.guard, *h)])
            self.down, self.release_at, self.judge = h, now + self.hold_s, (now + self.judge_s, name, p1, p2)
            self.stats["holds"] += 1
        self.prev = w
