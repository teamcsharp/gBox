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
        self.pending_for = None                     # the (mode, keep) the held pick was drawn under (choose)
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

    def choose(self, mode=None, keep=None, last=None):
        """The next round's {"mode", "character", "stage"}, held as pending until a round starts: the DJ's queued pick,
        else the least-played mode/character pair and that pair's least-played stage. mode: only that mode (RE5: a
        MercMode turn never changes mode, a change walks out to the title and in again); keep "stage" / "character":
        that part stays as the last round's (last: the caller's (mode, character, stage), else the last one started),
        so one change at a time is made on its own select screen (re5_ps3.Pace). A DJ pick in another mode stays queued
        for a call without mode (the walk between two turns). A pick held from a call with other constraints is drawn
        again."""
        with self.lock:
            request = self.selection_request
            if request and request["state"] == "queued" and (mode is None or request["selection"]["mode"] == mode):
                self.pending, self.pending_for = dict(request["selection"]), None
                return dict(self.pending)
            last = list(last) if last is not None else self.last
            last = list(last) if isinstance(last, (list, tuple)) and len(last) == 3 \
                and self._valid({"mode": last[0], "character": last[1], "stage": last[2]}) else None
            if keep not in ("stage", "character") or last is None or (mode is not None and last[0] != mode):
                keep = None                                 # nothing of this mode to keep: a free pick in it
            if mode is not None and mode not in self.rosters:
                mode = None
            if self.pending is not None and (getattr(self, "pending_for", None) not in (None, (mode, keep))
                                             or not self._fits(self.pending, mode, keep, last)):
                self.pending = None
            self.pending_for = (mode, keep) if mode is not None or keep is not None else None
            if self.pending is None:
                rosters = {m: chars for m, chars in self.rosters.items() if mode is None or m == mode}
                # Balance mode/character appearances first, then stages for that character.
                totals = {(m, c): sum(self.counts.get(self.key(m, c, s), 0) for s in self.stages)
                          for m, chars in rosters.items() for c in chars}
                if keep == "character":
                    pool = [(last[0], last[1])]
                else:
                    if keep == "stage":                     # a new character on the same stage, in the same mode
                        totals = {x: n for x, n in totals.items() if x != (last[0], last[1])} or totals
                    pool = [x for x, n in totals.items() if n == min(totals.values())]
                    if last and len(pool) > 1:
                        pool = [x for x in pool if list(x) != last[:2]] or pool
                        # the mode just played while it still has a least-played character: a mode change walks back
                        # out to the title and in again (RE5: +13.7 s of menus, and 56% of the gaps between rounds
                        # switched mode on 2026-10-25/26; operator 2026-10-26: "without breaks in between rounds"). Only
                        # least-played pairs are ever chosen, so the balance is the same: the modes take turns in blocks
                        pool = [x for x in pool if x[0] == last[0]] or pool
                chosen_mode, char = self.rng.choice(pool)
                if keep == "stage":
                    stage = last[2]
                else:
                    stages = [s for s in self.stages if keep != "character" or s != last[2]] or list(self.stages)
                    low = min(self.counts.get(self.key(chosen_mode, char, s), 0) for s in stages)
                    stage = self.rng.choice([s for s in stages
                                            if self.counts.get(self.key(chosen_mode, char, s), 0) == low])
                self.pending = {"mode": chosen_mode, "character": char, "stage": stage}
            return dict(self.pending)

    @staticmethod
    def _fits(pending, mode, keep, last) -> bool:
        """Whether a held pick satisfies choose()'s constraints (a status call may have drawn it without them)."""
        if mode is not None and pending.get("mode") != mode:
            return False
        if keep == "stage":
            return pending.get("stage") == last[2] and pending.get("mode") == last[0] \
                and pending.get("character") != last[1]
        if keep == "character":
            return pending.get("character") == last[1] and pending.get("mode") == last[0] \
                and pending.get("stage") != last[2]
        return True

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
