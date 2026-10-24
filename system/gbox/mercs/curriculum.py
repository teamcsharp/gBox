"""Persistent, randomized coverage of a title's mode/character/stage combinations.

Adapters supply actual selectable identifiers. A request is counted only after the adapter
confirms a round began; menu attempts never count as play or as a successful result.
"""
from __future__ import annotations

import json
import random
import threading
import time
import uuid
from pathlib import Path


class Coverage:
    def __init__(self, path, rosters, stages, rng=None):
        self.path = Path(path) if path else None
        self.rosters, self.stages = rosters, tuple(stages)
        self.rng = rng or random.SystemRandom()
        self.counts, self.pending, self.last, self.selection_request = {}, None, None, None
        self.lock = threading.RLock()
        if self.path:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.counts = {k: v for k, v in data.get("counts", {}).items()
                               if type(v) is int and 0 <= v < 1_000_000}
                self.last = data.get("last")
                request = data.get("selection_request")
                if isinstance(request, dict) and request.get("state") in ("queued", "started") \
                        and isinstance(request.get("id"), str) and len(request["id"]) == 32 \
                        and self._valid(request.get("selection")):
                    self.selection_request = request
            except (OSError, ValueError, TypeError):
                pass

    @staticmethod
    def key(mode, character, stage):
        return f"{mode}/{character}/{stage}"

    def _valid(self, selection):
        return isinstance(selection, dict) and isinstance(selection.get("mode"), str) \
            and selection["mode"] in self.rosters \
            and selection.get("character") in self.rosters[selection["mode"]] \
            and type(selection.get("stage")) is int and selection["stage"] in self.stages

    def choose(self):
        with self.lock:
            if self.selection_request and self.selection_request["state"] == "queued":
                self.pending = dict(self.selection_request["selection"])
            if self.pending is None:
                # Balance mode/character appearances first, then stages for that character.
                totals = {(m, c): sum(self.counts.get(self.key(m, c, s), 0) for s in self.stages)
                          for m, chars in self.rosters.items() for c in chars}
                pool = [x for x, n in totals.items() if n == min(totals.values())]
                if self.last and len(pool) > 1:
                    pool = [x for x in pool if list(x) != self.last[:2]] or pool
                mode, char = self.rng.choice(pool)
                low = min(self.counts.get(self.key(mode, char, s), 0) for s in self.stages)
                stage = self.rng.choice([s for s in self.stages
                                        if self.counts.get(self.key(mode, char, s), 0) == low])
                self.pending = {"mode": mode, "character": char, "stage": stage}
            return dict(self.pending)

    def request(self, mode, character, stage):
        selected = {"mode": mode, "character": character, "stage": stage}
        if not self._valid(selected):
            raise ValueError("selection is outside the verified roster/stage catalog")
        with self.lock:
            if self.selection_request and self.selection_request["state"] == "queued" \
                    and self.selection_request["selection"] == selected:
                return dict(selected)
            previous = self.pending, self.selection_request
            self.pending = selected
            self.selection_request = {"id": uuid.uuid4().hex, "state": "queued",
                                      "selection": dict(selected), "requested_at": time.time()}
            try:
                self.save()
            except OSError:
                self.pending, self.selection_request = previous
                raise
            return dict(self.pending)

    def started(self, mode, character, stage):
        """The caller must pass observed selections, rather than the requested target."""
        with self.lock:
            observed = {"mode": mode, "character": character, "stage": stage}
            if not self._valid(observed):
                return False
            key = self.key(mode, character, stage)
            self.counts[key] = self.counts.get(key, 0) + 1
            self.last = [mode, character, stage]
            request = self.selection_request
            if request and request["state"] == "queued":
                request["last_observed"] = dict(observed)
                if request["selection"] == observed:
                    request.update(state="started", confirmed_at=time.time(), confirmation="native_round_start")
                    self.pending = None
                else:
                    self.pending = dict(request["selection"])
            else:
                self.pending = None
            self.save()
            return True

    def save(self):
        with self.lock:
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temp = self.path.with_suffix(".tmp")
                temp.write_text(json.dumps({"version": 2, "counts": self.counts, "last": self.last,
                                            "selection_request": self.selection_request}), encoding="utf-8")
                temp.replace(self.path)

    def status(self):
        with self.lock:
            return {"combinations_played": len(self.counts), "total_rounds": sum(self.counts.values()),
                    "combinations_total": sum(map(len, self.rosters.values())) * len(self.stages),
                    "next": self.choose(), "counts": dict(self.counts),
                    "selection_request": json.loads(json.dumps(self.selection_request))}
