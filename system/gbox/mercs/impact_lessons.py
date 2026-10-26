"""Every impact the player takes, as a lesson the bot uses (operator 2026-10-26: "I want the autobot trained from every
impact").

Per stage and attacker kind it keeps the hits taken - how far the attacker stood, whether he was in front of, beside or
behind the player, what the bot was doing, the largest single loss - and from them small bounded parameters the title
bots read every tick:

  * RE4 "evade_margin" (per room and attack kind, seconds): how much sooner than the shot can leave an attack must land
    for the bot to run out of it instead of shooting. A melee hit that lands while the bot stood shooting at that very
    attacker (it chose the shot and lost the race) raises it by STEP_EVADE; an attack the bot killed in its wind-up
    lowers it by DECAY_EVADE. Bounded to [the title's base, EVADE_MAX].
  * RE5 "heal_critical" (per stage, share of health): under it a heal starts even with Majini near. The largest single
    hit seen on that stage times HEAL_COVER - one more such hit must not be the one that kills. Bounded to [the title's
    base, HEAL_CRITICAL_MAX].

    lessons = ImpactLessons(path)                        # <learn dir>/impact_lessons.json (None: in memory only)
    lessons.record(stage, kind, dist=..., facing_deg=..., doing=..., loss=..., hp_max=...)   # -> the impact's row
    lessons.adjust(stage, kind, "evade_margin", +0.05, base=0.15, lo=0.15, hi=0.6)
    lessons.value(stage, kind, "evade_margin", base=0.15, lo=0.15, hi=0.6)
    lessons.save()

Nothing here reads or writes the game; a lost file is an empty memory, never an error.
"""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

STEP_EVADE, DECAY_EVADE, EVADE_MAX = 0.05, 0.01, 0.6
HEAL_COVER, HEAL_CRITICAL_MAX = 1.25, 0.35
FRONT_DEG, SIDE_DEG = 45.0, 100.0          # the attacker this far off the player's facing: in front / beside / behind
SAVE_EVERY = 10                            # impacts between saves (the round's end saves too)


def facing_class(deg) -> str | None:
    if deg is None or not isinstance(deg, (int, float)) or not math.isfinite(deg):
        return None
    a = abs(deg)
    return "front" if a < FRONT_DEG else "side" if a < SIDE_DEG else "behind"


class ImpactLessons:
    def __init__(self, path: Path | None = None, clock=time.time):
        self.path = Path(path) if path else None
        self.clock = clock
        self.d: dict = {"v": 1, "stages": {}}
        self.dirty = 0
        if self.path is not None and self.path.is_file():
            try:
                d = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(d, dict) and isinstance(d.get("stages"), dict):
                    self.d = d
            except (OSError, ValueError):
                pass

    def _cell(self, stage, kind) -> dict:
        stages = self.d.setdefault("stages", {})
        row = stages.setdefault(str(stage or "?"), {}).setdefault(str(kind or "unknown"), {})
        for k, v in (("hits", 0), ("front", 0), ("side", 0), ("behind", 0), ("dist_sum", 0.0), ("dist_n", 0),
                     ("max_loss", 0.0), ("doing", {}), ("params", {})):
            row.setdefault(k, v if not isinstance(v, dict) else {})
        return row

    def record(self, stage, kind, *, dist=None, facing_deg=None, doing=None, loss=None, hp_max=None) -> dict:
        """One impact: counted in its stage / kind; the row the round map keeps for it."""
        c = self._cell(stage, kind)
        c["hits"] += 1
        side = facing_class(facing_deg)
        if side:
            c[side] += 1
        if isinstance(dist, (int, float)) and math.isfinite(dist):
            c["dist_sum"] = round(c["dist_sum"] + float(dist), 1)
            c["dist_n"] += 1
        if isinstance(loss, (int, float)) and loss > 0:
            share = float(loss) / float(hp_max) if isinstance(hp_max, (int, float)) and hp_max > 0 else None
            c["max_loss"] = max(c["max_loss"], round(share if share is not None else 0.0, 4))
        if doing:
            key = str(doing)[:40]
            c["doing"][key] = c["doing"].get(key, 0) + 1
            if len(c["doing"]) > 24:                      # the commonest stay
                for k in sorted(c["doing"], key=c["doing"].get)[:len(c["doing"]) - 24]:
                    c["doing"].pop(k, None)
        c["updated"] = int(self.clock())
        self.dirty += 1
        if self.dirty >= SAVE_EVERY:
            self.save()
        return {"stage": str(stage or "?"), "kind": str(kind or "unknown"),
                "dist": round(dist) if isinstance(dist, (int, float)) and math.isfinite(dist) else None,
                "facing_deg": round(facing_deg) if isinstance(facing_deg, (int, float)) and math.isfinite(facing_deg) else None,
                "facing": side, "doing": str(doing)[:60] if doing else None,
                "loss": loss, "hits_here": c["hits"]}

    def value(self, stage, kind, name, base, lo, hi) -> float:
        """The learned parameter, or base; always inside [lo, hi]."""
        stages = self.d.get("stages") or {}
        v = (((stages.get(str(stage or "?")) or {}).get(str(kind or "unknown")) or {}).get("params") or {}).get(name)
        v = base if not isinstance(v, (int, float)) or not math.isfinite(v) else v
        return max(lo, min(hi, float(v)))

    def adjust(self, stage, kind, name, delta, base, lo, hi) -> float:
        """Move the parameter by delta (from base when unset), bounded; the new value."""
        c = self._cell(stage, kind)
        v = max(lo, min(hi, self.value(stage, kind, name, base, lo, hi) + delta))
        c["params"][name] = round(v, 4)
        self.dirty += 1
        return v

    def set_at_least(self, stage, kind, name, want, base, lo, hi) -> float:
        """Raise the parameter to want (never lowers it), bounded; the new value."""
        c = self._cell(stage, kind)
        v = max(lo, min(hi, max(self.value(stage, kind, name, base, lo, hi), want)))
        c["params"][name] = round(v, 4)
        self.dirty += 1
        return v

    def summary(self, stage) -> dict:
        """{kind: {hits, front/side/behind, mean dist, params}} for one stage (stats / the round map)."""
        out = {}
        for kind, c in ((self.d.get("stages") or {}).get(str(stage or "?")) or {}).items():
            out[kind] = {"hits": c.get("hits", 0), "front": c.get("front", 0), "side": c.get("side", 0),
                         "behind": c.get("behind", 0),
                         "mean_dist": round(c["dist_sum"] / c["dist_n"]) if c.get("dist_n") else None,
                         "max_loss": c.get("max_loss"), "params": dict(c.get("params") or {})}
        return out

    def save(self) -> None:
        if self.path is None or not self.dirty:
            self.dirty = 0
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.d, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
            self.dirty = 0
        except OSError:
            pass
