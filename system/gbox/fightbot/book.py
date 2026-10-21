"""The move book: what each answer earned against each attack, learned as the bot plays and kept per title.

Two levels: the move itself (the attacker's character and move id: "chara:move") and its attack class
("strike:mid:kick"), the fallback for a move not met yet. An answer's reward is the title's judgement of the window
after it (damage dealt minus damage taken, a parry landed, ...). Feints: a move answered MISS_LIMIT times that never
met anything (no hit either way, SC2's stance cancels and edge-of-reach whiffs) is left alone until it hits."""
from __future__ import annotations

import json
import random
import threading
from pathlib import Path

MISS_LIMIT = 2
EXPLORE = 0.2
TRUST = 2                       # a class-level answer is used for a new move once it was tried this often and paid
HIT_FRAMES = 15                 # the last this many start-to-hit frame counts kept per move


class Book:
    def __init__(self, path: Path | str | None = None, explore: float = EXPLORE, rng: random.Random | None = None):
        self.path = Path(path) if path else None
        self.explore, self.rng = explore, rng or random.Random()
        self.moves: dict[str, dict] = {}      # key -> {"answers": {name: [tries, reward, misses]}, "hits": n}
        self.classes: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.dirty = 0
        if self.path and self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.moves, self.classes = data.get("moves") or {}, data.get("classes") or {}
            except (OSError, ValueError):
                pass

    @staticmethod
    def _mean(row):
        return row[1] / row[0] if row[0] else 0.0

    def _row(self, table, key):
        return table.setdefault(key, {"answers": {}, "hits": 0})

    def best(self, key: str, cls: str | None = None) -> str | None:
        """The answer that paid best for this move (else its class), or None."""
        for table, k in ((self.moves, key), (self.classes, cls)):
            ans = (table.get(k) or {}).get("answers") or {}
            tried = {a: r for a, r in ans.items() if r[0]}
            if tried:
                return max(tried, key=lambda a: self._mean(tried[a]))
        return None

    def choose(self, key: str, cls: str | None, answers: list[str]) -> str | None:
        """Untried answers first for a new move, unless its class already has a paying answer; then mostly the best
        (EXPLORE of the time another)."""
        if not answers:
            return None
        with self.lock:
            mine = (self.moves.get(key) or {}).get("answers") or {}
            tried = {a: mine[a] for a in answers if a in mine and mine[a][0]}
            if not tried:
                theirs = (self.classes.get(cls) or {}).get("answers") or {}
                good = [a for a in answers if a in theirs and theirs[a][0] >= TRUST and self._mean(theirs[a]) > 0]
                if good:
                    return max(good, key=lambda a: self._mean(theirs[a]))
            untried = [a for a in answers if a not in tried]
            if untried:
                return untried[0]
            if self.rng.random() < self.explore:
                return self.rng.choice(answers)
            return max(answers, key=lambda a: self._mean(tried[a]))

    def record(self, key: str, cls: str | None, answer: str, reward: float, met: bool | None = True):
        """met: the answer met something (a hit either way, a parry, a guard); False = it whiffed into nothing;
        None = the title can't tell (counted as a try, never as a whiff)."""
        with self.lock:
            for table, k in ((self.moves, key), (self.classes, cls)):
                if k is None:
                    continue
                row = self._row(table, k)["answers"].setdefault(answer, [0, 0.0, 0])
                row[0] += 1
                row[1] += float(reward)
                row[2] += 1 if met is False else 0
            self.dirty += 1

    def hit(self, key: str, cls: str | None = None, frames: int | None = None):
        """The move hit the player (unanswered or answered wrong): it is real, never a feint. frames: frames from the
        move's start to the hit; their median times the answers to a move whose signature has no active frames."""
        with self.lock:
            for table, k in ((self.moves, key), (self.classes, cls)):
                if k is not None:
                    row = self._row(table, k)
                    row["hits"] += 1
                    if isinstance(frames, int) and 0 <= frames < 600:
                        row["hit_f"] = (row.get("hit_f") or [])[-(HIT_FRAMES - 1):] + [frames]
            self.dirty += 1

    def hit_frame(self, key: str, cls: str | None = None) -> int | None:
        """Frames from the move's start to its hit, as seen (the move, else its class), or None."""
        for table, k in ((self.moves, key), (self.classes, cls)):
            seen = sorted((table.get(k) or {}).get("hit_f") or [])
            if seen:
                return seen[len(seen) // 2]
        return None

    def feint(self, key: str) -> bool:
        row = self.moves.get(key) or {}
        ans = row.get("answers") or {}
        tries = sum(r[0] for r in ans.values())
        misses = sum(r[2] for r in ans.values())
        return not row.get("hits") and tries >= MISS_LIMIT and misses == tries

    def summary(self, top: int = 8) -> dict:
        """For the watch panel: the classes and their best answers."""
        out = {}
        for cls, row in sorted(self.classes.items()):
            ans = row.get("answers") or {}
            if ans:
                best = max(ans, key=lambda a: self._mean(ans[a]))
                out[cls] = {"best": best, "mean": round(self._mean(ans[best]), 1), "tries": sum(r[0] for r in ans.values())}
        return dict(list(out.items())[:top])

    def save(self, force: bool = False):
        if not self.path or not (self.dirty or force):
            return
        with self.lock:
            data = json.dumps({"moves": self.moves, "classes": self.classes}, separators=(",", ":"))
            self.dirty = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(data, encoding="utf-8")
        tmp.replace(self.path)
