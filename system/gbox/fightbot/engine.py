"""The engine tick: one game frame in, the keys to hold this frame out.

    threat  an opponent attack seen in RAM (an attack-tagged move or class, an attack record, a warn edge): its
            onset frame and, when the title can tell, the frames until its first active frame
    answer  the title's answers to it (holds, parries, guards); the book picks one (per move, else per attack class);
            it is pressed `lead` frames (+ the measured input lag) before the first active frame, held `frames`
    judge   the title scores the window after the press as soon as it shows an outcome (health moved, a parry), else
            `judge` frames on (it met nothing): the book learns it, the lessons log it
    punish  after an answer that paid, the title's punish
    latency the frame the game's own input word shows the keys: input latency (frames from sending) and reaction
            (frames from the attack's onset), logged per answer and kept as medians for the watch panel
"""
from __future__ import annotations

import random
import statistics
from collections import deque

from .book import Book
from .title import Answer, Title
from .world import Attack, World

HISTORY = 90                   # frames of worlds kept: the attacker's state before a hit
MIN_GAP = 2                    # frames between the end of one press and the next
OFFENSE = "offense"            # the book's key for the title's attacks (learned by what they dealt)


class Engine:
    def __init__(self, title: Title, book: Book | None = None, lessons=None, stats: dict | None = None,
                 rng: random.Random | None = None):
        self.title, self.book, self.lessons = title, book or Book(), lessons
        self.rng = rng or random.Random()
        self.stats = stats if stats is not None else {}
        self.history: deque[World] = deque(maxlen=HISTORY)
        self.threat = None            # {"key", "cls", "attack", "onset", "answered"}
        self.active = None            # the plan pressing (or waiting to press) now
        self.pending: list[dict] = []  # plans waiting for their judgement
        self.move_start = {}          # "p1" / "p2" -> (move id, frame it began, its move frame then)
        self.free_at = None           # no new press before this frame
        self.attack_at = None         # the frame of the last attack the engine started
        self.lat_input: deque[int] = deque(maxlen=200)
        self.lat_reaction: deque[int] = deque(maxlen=200)
        self.on_judged = None         # callable(answer, label, reward, world): evidence capture, coaching
        for k in ("attacks", "answers", "answered_ok", "parried", "hits_taken", "damage_taken", "damage_dealt",
                  "punishes", "feints_skipped", "out_of_reach"):
            self.stats.setdefault(k, 0)

    # -- bookkeeping --
    def _log(self, kind, frame, **fields):
        if self.lessons is not None:
            self.lessons.log(kind, frame, **fields)

    def _moves(self, w: World):
        for who in ("p1", "p2"):
            f = getattr(w, who)
            cur = self.move_start.get(who)
            restarted = cur and f.move_frame is not None and cur[2] is not None and f.move_frame < cur[2]
            if not cur or cur[0] != f.move or restarted:
                self.move_start[who] = (f.move, w.frame, f.move_frame)
            else:
                self.move_start[who] = (cur[0], cur[1], f.move_frame)

    def in_move(self, who: str, w: World) -> int | None:
        cur = self.move_start.get(who)
        return None if not cur or cur[1] is None or w.frame is None else w.frame - cur[1]

    def _hits(self, prev: World, w: World):
        for me, them, sign in (("p1", "p2", "taken"), ("p2", "p1", "dealt")):
            a, b = getattr(prev, me).hp, getattr(w, me).hp
            if a is None or b is None or b >= a:
                continue
            lost = a - b
            self.stats["damage_" + sign] += lost
            if me != "p1":
                continue
            self.stats["hits_taken"] += 1
            before = self.history[-3] if len(self.history) >= 3 else prev
            att = getattr(before, them)
            if self.threat:
                self.book.hit(self.threat["key"], self.threat["cls"], self.in_move(them, prev))
            self._log("hit_taken", w.frame, hp_lost=lost, hp=b, distance=prev.distance,
                      attacker={"chara": att.chara, "move": att.move, "move_class": att.move_class,
                                "move_frame": att.move_frame, "state": att.state, "tags": att.tags},
                      in_move_frames=self.in_move(them, prev),
                      answered=bool(self.threat and self.threat.get("answered")))

    def _watch_threat(self, prev: World | None, w: World):
        att = w.p2.attack
        t = self.threat
        if att is not None:
            if t is not None and t["attack"].move == att.move and self.in_move("p2", w) != 0:
                t["now"] = att                         # the same attack, one frame on
                return
        elif w.p2.warn and not (prev and prev.p2.warn):
            att = Attack(kind="strike", lead=self.title.warn_lead, tags={"warn": True})
        else:
            if t and t["attack"].tags.get("warn") and w.p2.move != t.get("move0") and t["attack"].move is None:
                t["attack"].move = w.p2.move           # the move the warned input started: learn per move
                t["key"] = f"{w.p2.chara}:{w.p2.move}"
            if t and (not t["attack"].tags.get("warn") or w.frame is None or t["onset"] is None
                      or w.frame - t["onset"] > (t["attack"].lead or 0) + 20):
                self.threat = None                     # the attack is over (a warn: its hit is long past)
            return
        key = f"{w.p2.chara}:{att.move}" if att.move is not None else f"{w.p2.chara}:{att.cls()}"
        self.threat = {"key": key, "cls": att.cls(), "attack": att, "now": att, "onset": w.frame, "answered": False,
                       "move0": w.p2.move}
        self.stats["attacks"] += 1
        self._log("attack", w.frame, key=key, cls=att.cls(), move=att.move, to_active=att.to_active(),
                  distance=w.distance, tags=att.tags)

    def _judge(self, w: World):
        """An answer is judged when its window shows an outcome (health moved either way, a parry), else when the
        window ends (it met nothing): the book has it before the opponent's next attack."""
        if w.frame is None:
            return
        for p in list(self.pending):
            if w.frame <= p["press_at"]:
                continue
            reward, met, label = self.title.outcome(p["before"], w, p["answer"])
            if not met and w.frame < p["judge_at"]:
                continue
            self.pending.remove(p)
            t = p.get("threat")
            if p["answer"].kind == "answer" and t:
                self.book.record(t["key"], t["cls"], p["answer"].name, reward, met)
                self.stats["answered_ok"] += reward > 0
                self.stats["parried"] += label in ("parried", "held")
            elif p["answer"].kind == "punish":
                self.stats["punish_dealt"] = self.stats.get("punish_dealt", 0) + max(0.0, reward)
            elif p["answer"].kind == "attack":
                self.book.record(OFFENSE, None, p["answer"].name, reward, met)
                self.stats["attack_dealt"] = self.stats.get("attack_dealt", 0) + max(0.0, reward)
            self._log(p["answer"].kind, w.frame, answer=p["answer"].name, key=t and t["key"], reward=reward,
                      met=met, outcome=label, sent=p["press_at"], seen=p.get("seen"),
                      input_f=None if p.get("seen") is None else p["seen"] - p["press_at"],
                      reaction_f=None if p.get("seen") is None or not t else p["seen"] - t["onset"])
            if self.on_judged is not None:
                try:
                    self.on_judged(p["answer"], label, reward, w)
                except Exception:                      # noqa: BLE001 - an observer never stops the fight
                    pass
            if p["answer"].kind == "answer" and reward > 0 and self.active is None and w.p1.can_act():
                pun = self.title.punish(w, label)
                if pun is not None:
                    self._start(pun, w, None)

    def _latency(self, w: World):
        p = self.active
        if not p or p.get("seen") is not None or w.frame is None or w.frame <= p["press_at"] or w.p1.input is None:
            return
        bits = self.title.input_bits(p["answer"], w)
        if bits and (w.p1.input & bits) == bits:
            p["seen"] = w.frame
            self.lat_input.append(w.frame - p["press_at"])
            self.stats["lat_input_f"] = statistics.median(self.lat_input)
            self.title.lag_f = int(round(self.stats["lat_input_f"]))
            t = p.get("threat")
            if t and t.get("onset") is not None:
                self.lat_reaction.append(w.frame - t["onset"])
                self.stats["lat_reaction_f"] = statistics.median(self.lat_reaction)

    # -- deciding --
    def _start(self, answer: Answer, w: World, threat, press_at: int | None = None):
        press_at = w.frame if press_at is None else press_at
        plan = {"answer": answer, "press_at": press_at, "until": press_at + answer.length,
                "judge_at": press_at + max(answer.judge, answer.length), "before": w, "threat": threat, "seen": None}
        self.active = plan
        self.pending.append(plan)
        if threat is not None:
            threat["answered"] = True
        counter = {"answer": "answers", "punish": "punishes"}.get(answer.kind, "attacks_made")
        self.stats[counter] = self.stats.get(counter, 0) + 1

    def _offense(self, w: World):
        """Nothing to answer and free: the title's attack (pressure, a throw), at most every title.attack_gap frames."""
        if self.threat is not None or w.frame is None or not w.p1.can_act():
            return
        if self.free_at is not None and w.frame < self.free_at:
            return
        if self.attack_at is not None and w.frame - self.attack_at < getattr(self.title, "attack_gap", 60):
            return
        options = self.title.attacks(w) if hasattr(self.title, "attacks") else []
        name = self.book.choose(OFFENSE, None, [a.name for a in options])
        if name:
            self.attack_at = w.frame
            self._start(next(a for a in options if a.name == name), w, None)

    def _answer(self, w: World):
        t = self.threat
        if not t or t["answered"] is not False or not w.p1.can_act() or w.frame is None:
            return
        if self.free_at is not None and w.frame < self.free_at:
            return
        if self.book.feint(t["key"]):
            t["answered"] = None
            self.stats["feints_skipped"] += 1
            return
        if self.title.reach is not None and w.distance is not None and w.distance > self.title.reach:
            self.stats["out_of_reach"] += 1
            return                                    # it may come into reach later in the move
        since = 0 if t["onset"] is None else w.frame - t["onset"]
        if t["attack"].tags.get("warn") and since < self.title.warn_settle:
            return                                    # an input edge: wait a frame or two for the move it starts
        answers = self.title.answers(t["now"], w)
        name = self.book.choose(t["key"], t["cls"], [a.name for a in answers])
        if not name:
            return
        answer = next(a for a in answers if a.name == name)
        now = t["now"]
        to_active = now.to_active(since)
        seen = self.book.hit_frame(t["key"], t["cls"])                   # frames from the move's start to its hit
        long = now.start is not None and now.end is not None and now.end - now.start > self.title.long_window
        if seen is not None and (to_active is None or long):              # no frames known, or a long window: where
            to_active = seen - (self.in_move("p2", w) or since)          # it landed before (its contact median)
        elif to_active is None:
            to_active = self.title.warn_lead - since                      # nothing known: the title's default
        lag = self.title.lag_f
        press_at = w.frame if to_active is None else w.frame + max(0, to_active - answer.lead - lag)
        self._start(answer, w, t, press_at)

    def _confirm(self, w: World):
        """An answer with confirm_f that hasn't come out by then (P1 wasn't free): its fallback, pressed now."""
        p = self.active
        a = p and p["answer"]
        if not a or not a.confirm_f or p.get("confirmed") or w.frame is None or w.frame <= p["press_at"]:
            return
        if self.title.confirm(a, w):
            p["confirmed"] = True
        elif w.frame >= p["press_at"] + a.confirm_f:
            self.stats["fallbacks"] = self.stats.get("fallbacks", 0) + 1
            if p in self.pending:
                self.pending.remove(p)
            self.active = None
            if a.fallback is not None:
                self._start(a.fallback, w, p.get("threat"))

    def _keys(self, p, w: World) -> tuple:
        keys = p["answer"].at(w.frame - p["press_at"])
        att = w.p1.attack                              # P1's own attack still out: keep hold_off keys up
        if p["answer"].hold_off and att is not None and (att.frame is None or att.end is None or att.frame <= att.end):
            keys = tuple(k for k in keys if k not in p["answer"].hold_off)
        return keys

    def tick(self, w: World) -> tuple:
        prev = self.history[-1] if self.history else None
        self.history.append(w)
        self._moves(w)
        if prev is not None:
            self._hits(prev, w)
        self._watch_threat(prev, w)
        self._judge(w)
        self._latency(w)
        self._confirm(w)
        p = self.active
        a = p and p["answer"]
        if p and w.frame is not None and w.frame >= p["until"] and (
                not a.confirm_f or p.get("confirmed") or w.frame > p["press_at"] + a.confirm_f):
            self.active, self.free_at = None, p["until"] + MIN_GAP
            p = None
        if p is None:
            self._answer(w)
            if self.active is None:
                self._offense(w)
            p = self.active
        if p and w.frame is not None and p["press_at"] <= w.frame < p["until"]:
            return self._keys(p, w)
        return ()
