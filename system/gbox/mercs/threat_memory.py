"""Who hurt him, and what they were doing first: a Mercenaries bot's memory of the enemies that land hits.

Operator, 2026-11-10: "the enemies that hurt the bot ... the bot needs to take note of them and seek to resolve them
quickly to avoid being hurt by them again. The bot needs to be able to know via the ram signatures that an enemy is
trying a lethal attack and the bot seeks to dispatch them or stop the attack ... He should not be standing under a
hammer who is charging up over and over in the same match."

Title-generic: a bot hands it, every tick, the living enemies as rows ({ptr|slot, class, motion, pos, hp, hp_max})
and whether each one's own attack flag is up, and tells it when his health fell. It keeps:

  * each nearby enemy's recent motions (the RAM motion byte the title's driver reads), so a hit can be put on the one
    that landed it: the candidates within REACH_MAX_CM at the hit, scored by an attack flag up or a motion begun in the
    WINDOW_S before it (the swing), by a signature already learned, then by distance.
  * per enemy class, learned and saved across rounds and sessions (`path`, JSON): how often each motion began near him
    (`starts`) and how often a hit followed it (`hits`); the farthest reach a hit came from; how many hits landed
    although his shots were hurting the attacker during the wind-up (`through`: an attack shooting does not stop).
    A (class, motion) is a LETHAL signature once LEARN_HITS hits followed it and they are at least LEARN_RATE of its
    starts near him - or at once, for the rest of the round, after it hurt him once in this round.
  * grudges: the enemies that hurt him in this round (by unit), so the bot can deal with them first.

Nothing here presses a button. The bot decides: a lethal signature under way within the class's learned reach is a
wind-up to stop (shoot it) or, for a class whose attack lands through his shots, to step out of.
"""
from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path

WINDOW_S = 1.6           # the motions an enemy began this long before a hit are its attack's signature
REACH_MAX_CM = 700.0     # an enemy farther than this at the hit did not land it (melee reach, a swing's arc)
LEARN_HITS = 2           # a (class, motion) is lethal after this many hits followed it ...
LEARN_RATE = 0.2         # ... and they are at least this share of its starts near him
REACH_MARGIN = 1.15      # a learned reach is used with this margin (and REACH_PAD_CM more)
REACH_PAD_CM = 60.0
GRUDGE_S = 90.0          # an enemy that hurt him stays a grudge this long within the round
SAVE_S = 20.0            # the file is written at most this often (and at each round's start)
VERSION = 1


def _key(e):
    return e.get("ptr", e.get("slot"))


class ThreatMemory:
    def __init__(self, path: Path | None = None, *, default_reach_cm: float = 300.0):
        self.path = Path(path) if path else None
        self.default_reach = float(default_reach_cm)
        self.data = self._load()
        self.hist: dict = {}          # enemy key -> deque of (t, motion, attacking, dist, hp)
        self.rows: dict = {}          # enemy key -> its row at the last observe
        self.round_hits: dict = {}    # (class, motion) -> hits this round
        self.grudges: dict = {}       # enemy key -> {"t", "hits", "class"}
        self.last_hit: dict | None = None
        self.stats = {"tm_hits_attributed": 0, "tm_hits_unattributed": 0, "tm_lethal_starts": 0}
        self._dirty, self._saved_at = False, time.monotonic()

    # --- the file ----------------------------------------------------------------------------------------------
    def _load(self) -> dict:
        if self.path is None:
            return {"version": VERSION, "classes": {}}
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"version": VERSION, "classes": {}}
        if not isinstance(d, dict) or not isinstance(d.get("classes"), dict):
            return {"version": VERSION, "classes": {}}
        return d

    def save(self, force: bool = False) -> None:
        if self.path is None or not self._dirty:
            return
        if not force and time.monotonic() - self._saved_at < SAVE_S:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=1, sort_keys=True), encoding="utf-8")
            tmp.replace(self.path)
            self._dirty, self._saved_at = False, time.monotonic()
        except OSError:
            pass

    def _cls(self, cls) -> dict:
        c = self.data["classes"].setdefault(str(cls), {})
        c.setdefault("starts", {})
        c.setdefault("hits", {})
        c.setdefault("through", 0)
        c.setdefault("hit_count", 0)
        c.setdefault("reach_cm", 0.0)
        return c

    # --- the round ---------------------------------------------------------------------------------------------
    def new_round(self) -> None:
        self.hist.clear()
        self.rows.clear()
        self.round_hits.clear()
        self.grudges.clear()
        self.last_hit = None
        self.save(force=True)

    # --- every tick --------------------------------------------------------------------------------------------
    def observe(self, now: float, enemies, ppos, attacking=None) -> None:
        """The living enemies this tick. `attacking(e)` -> bool: the title's own attack flag (None: none)."""
        px, pz = ppos[0], ppos[2]
        seen = set()
        for e in enemies or ():
            k = _key(e)
            if k is None or not e.get("pos"):
                continue
            seen.add(k)
            d = ((e["pos"][0] - px) ** 2 + (e["pos"][2] - pz) ** 2) ** 0.5
            self.rows[k] = e
            if d > REACH_MAX_CM * 1.5 and k not in self.hist:
                continue
            h = self.hist.setdefault(k, deque(maxlen=64))
            m = e.get("motion")
            att = bool(attacking(e)) if attacking else False
            if h and h[-1][1] != m:                                    # (a first sighting began nothing)
                cls = e.get("class")
                if cls is not None and m is not None and d <= self.reach(cls):
                    c = self._cls(cls)
                    c["starts"][str(m)] = c["starts"].get(str(m), 0) + 1   # a motion begun within his reach
                    self._dirty = True
                    if self.lethal_motion(cls, m):
                        self.stats["tm_lethal_starts"] += 1
            h.append((now, m, att, d, e.get("hp")))
            while h and now - h[0][0] > 2 * WINDOW_S and len(h) > 1:
                h.popleft()
        for k in [k for k in self.hist if k not in seen]:              # dead or gone
            del self.hist[k]
            self.rows.pop(k, None)
        for k, g in list(self.grudges.items()):
            if k not in seen or now - g["t"] > GRUDGE_S:
                del self.grudges[k]

    @staticmethod
    def _window(h, now):
        """(the entries of the last WINDOW_S, the motions begun in it) of one enemy's history."""
        win = [x for x in h if now - x[0] <= WINDOW_S]
        seen_before = len(h) > len(win)
        prior = h[len(h) - len(win) - 1][1] if seen_before else None
        began = []
        for i, x in enumerate(win):
            if not i and not seen_before:
                continue                                               # his first sighting: nothing began
            prev = win[i - 1][1] if i else prior
            if x[1] is not None and x[1] != prev and x[1] not in began:
                began.append(x[1])
        return win, began

    def hurt(self, now: float, ppos, amount=None) -> dict | None:
        """His health fell: the enemy that landed it (or None), its signature counted. Returns the record."""
        best, best_s = None, None
        for k, h in self.hist.items():
            if not h or h[-1][3] > REACH_MAX_CM:
                continue
            win, began = self._window(h, now)
            score = (3.0 if any(x[2] for x in win) else 0.0) + (2.0 if began else 0.0)
            if self.lethal(self.rows.get(k) or {}):
                score += 2.0
            score -= h[-1][3] / 250.0
            if best_s is None or score > best_s:
                best, best_s = k, score
        if best is None:
            self.stats["tm_hits_unattributed"] += 1
            self.last_hit = {"t": now, "attacker": None, "amount": amount}
            return None
        h, e = self.hist[best], self.rows.get(best) or {}
        cls = e.get("class")
        win, motions = self._window(h, now)                            # the motions begun in the window ...
        if win and win[-1][1] is not None and win[-1][1] not in motions:
            motions.append(win[-1][1])                                 # ... and the one it is in (a long charge)
        hp_seen = [x[4] for x in win if isinstance(x[4], (int, float))]
        through = len(hp_seen) >= 2 and hp_seen[-1] < hp_seen[0]       # his shots hurt it during the wind-up
        d = h[-1][3]
        if cls is not None:
            c = self._cls(cls)
            for m in motions:
                c["hits"][str(m)] = c["hits"].get(str(m), 0) + 1
                self.round_hits[(str(cls), str(m))] = self.round_hits.get((str(cls), str(m)), 0) + 1
            c["hit_count"] += 1
            c["through"] += 1 if through else 0
            c["reach_cm"] = round(max(c["reach_cm"], min(d, REACH_MAX_CM)), 1)
            c["last_hit_at"] = round(time.time())
            self._dirty = True
        g = self.grudges.setdefault(best, {"t": now, "hits": 0, "class": cls})
        g["t"], g["hits"] = now, g["hits"] + 1
        self.stats["tm_hits_attributed"] += 1
        self.last_hit = {"t": now, "attacker": best, "class": cls, "motions": motions, "dist_cm": round(d),
                         "through": through, "amount": amount}
        self.save()
        return self.last_hit

    # --- what the bot asks ---------------------------------------------------------------------------------------
    def lethal_motion(self, cls, motion) -> bool:
        if cls is None or motion is None:
            return False
        if self.round_hits.get((str(cls), str(motion)), 0) >= 1:
            return True                                                # it hurt him in this round: at once
        c = self.data["classes"].get(str(cls))
        if not c:
            return False
        hits = c["hits"].get(str(motion), 0)
        starts = c["starts"].get(str(motion), 0)
        return hits >= LEARN_HITS and hits >= LEARN_RATE * max(starts, hits)

    def lethal(self, e) -> bool:
        """This enemy's motion now is a learned lethal signature of its class."""
        return bool(e) and self.lethal_motion(e.get("class"), e.get("motion"))

    def reach(self, cls, default: float | None = None) -> float:
        """The class's learned reach (with the margin), never under `default` / the title's default."""
        base = self.default_reach if default is None else float(default)
        c = self.data["classes"].get(str(cls)) if cls is not None else None
        r = (c or {}).get("reach_cm") or 0.0
        return max(base, r * REACH_MARGIN + REACH_PAD_CM) if r else base

    def unstoppable(self, e) -> bool:
        """The class's attack has landed although his shots were hurting it: step out of it, do not stand and shoot."""
        c = self.data["classes"].get(str((e or {}).get("class")))
        return bool(c) and c.get("through", 0) >= 1

    def grudge(self, e) -> int:
        g = self.grudges.get(_key(e or {}))
        return g["hits"] if g else 0

    def summary(self, limit: int = 6) -> dict:
        """The classes that hurt him most, with their lethal motions and reach (for the stats / the live map)."""
        out = {}
        ranked = sorted(self.data["classes"].items(), key=lambda kv: -kv[1].get("hit_count", 0))
        for cls, c in ranked[:limit]:
            if not c.get("hit_count"):
                continue
            lethal = sorted((m for m in c["hits"] if self.lethal_motion(cls, m)), key=lambda m: (len(m), m))
            out[cls] = {"hits": c["hit_count"], "lethal_motions": lethal, "reach_m": round(c["reach_cm"] / 100, 1),
                        "through": c.get("through", 0)}
        return out
