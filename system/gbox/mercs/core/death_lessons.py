"""Death lessons: every death makes the Mercenaries bot stronger (request #9525, operator 2026-11-10: "every death needs
to make the bot stronger ... that kill needs to educate the bot as to how to deal with those enemies and the bot needs to
take those enemies more serious in the future").

Three parts, title-generic (RE4 / RE5 / RE6 Switch through gbox.mercs.core.combat.Threats):

  1. RECORD. DeathLessons.observe() keeps the last WINDOW_S seconds of ticks (his health, who is near and how far, what
     he was doing and why, weapon / ammo, flash / mine counts, walls); the tick his health reaches 0 after being above 0
     (or died()) the window is distilled into one lesson - who hurt him (the Threats hit records), the crowd, the health
     curve, the doing / why, the kit - and appended to every path in `paths` (learned/_universal/deaths.jsonl and the
     title's own file).
  2. LEARN. Per enemy class, from the lessons on disk: a class that is BLAMED in at least MIN_DEATHS deaths (the killer
     class: the one that landed the last hit, else the most damage in the window) gets an Adjustment - threat weight,
     keep distance, answer weapon, doctrine multipliers - each bounded (CAPS) and decaying (half-life HALF_LIFE_S, so a
     class that stops killing him fades back to the plain doctrine). No class with fewer deaths gets anything.
  3. USE. Adjustments are read by combat.candidates / band / _order (priority and reach), by the title's doctrine
     (mine_x / flash_x / retreat_x multipliers) and its weapon choice (answer). Nothing here sends a key.

replay() runs recorded deaths in order through the same rules and reports deaths per round before / after the lesson
takes effect; what the records cannot settle (a death with no killer class) is counted and reported "not determined",
never guessed.
"""
from __future__ import annotations

import json
import math
import time
from collections import deque
from pathlib import Path

WINDOW_S = 10.0              # who hurt him in the last this-many seconds
MIN_DEATHS = 2               # evidence: a class must have caused this many deaths before anything changes
HALF_LIFE_S = 7 * 86400.0    # a lesson's weight halves every week
MAX_SAMPLES = 400
# bounds on every adjustment (x the plain value; keep in cm added)
CAPS = {"weight": 3.0, "keep_cm": 400.0, "mine_x": 0.5, "flash_x": 0.5, "retreat_x": 1.5}
STEP = {"weight": 0.5, "keep_cm": 100.0, "mine_x": 0.15, "flash_x": 0.15, "retreat_x": 0.2}
HEAVY_ANSWER = ("magnum", "shotgun", "explosives")
FILE = "deaths.jsonl"


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def data_dir(root=None) -> Path:
    """gbox-data/mercs/learned (the live store: only read here unless a title hands over paths to append to)."""
    base = Path(root) if root else Path(__file__).resolve().parents[3] / "gbox-data" / "mercs" / "learned"
    return base


def default_paths(title_id: str, root=None) -> tuple:
    base = data_dir(root)
    return (base / "_universal" / FILE, base / str(title_id) / FILE)


def _cls(v):
    return None if v is None else str(v)


class DeathLessons:
    """The recorder + the learned adjustments for one title. `paths`: files the lessons are appended to (the first is
    read for the adjustments, so the universal file teaches every title); `stats`: the bot's live stats dict."""

    def __init__(self, title_id: str, paths=None, stats: dict | None = None, clock=time.time, root=None):
        self.title_id = str(title_id)
        self.paths = [Path(p) for p in (paths if paths is not None else default_paths(title_id, root))]
        self.stats = stats if stats is not None else {}
        self.clock = clock
        self.window: deque = deque(maxlen=MAX_SAMPLES)
        self._hp = None
        self._dead = False
        self._adj: dict | None = None
        self._adj_at = 0.0
        self.stats.setdefault("death_lessons", 0)

    # --- 1. record ---
    def new_round(self) -> None:
        self.window.clear()
        self._hp, self._dead = None, False

    def observe(self, now: float, player, enemies, doing: str = "", why: str = "", hit: dict | None = None,
                kit: dict | None = None, walls=None) -> dict | None:
        """One tick. Returns the lesson on the tick his health first reaches 0."""
        p = player or {}
        hp = _num(p.get("hp"))
        pos = p.get("pos")
        crowd = []
        if pos:
            for e in enemies or ():
                if not isinstance(e, dict) or (_num(e.get("hp")) or 0) <= 0 or not e.get("pos"):
                    continue
                q = e["pos"]
                crowd.append({"class": _cls(e.get("class")), "d": round(math.hypot(q[0] - pos[0], q[2] - pos[2]), 1),
                              "tier": e.get("tier")})
        self.window.append({"t": now, "hp": hp, "crowd": crowd, "doing": doing, "why": why,
                            "hit": dict(hit) if hit else None, "kit": dict(kit) if kit else None,
                            "walls": walls})
        while self.window and now - self.window[0]["t"] > WINDOW_S:
            self.window.popleft()
        last, self._hp = self._hp, hp
        if hp is not None and hp > 0:
            self._dead = False
        if hp is not None and hp <= 0 and last is not None and last > 0 and not self._dead:
            self._dead = True
            return self.died(now)
        return None

    def died(self, now: float | None = None) -> dict | None:
        """Distil the window into a lesson, keep it (every path) and drop the cached adjustments."""
        if not self.window:
            return None
        now = self.window[-1]["t"] if now is None else now
        lesson = distil(self.title_id, list(self.window), now, wall_ts=self.clock())
        for p in self.paths:
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                with p.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(lesson, sort_keys=True) + "\n")
            except OSError as exc:                         # a full disk never stops the bot
                self.stats["death_lesson_error"] = str(exc)
        self.stats["death_lessons"] = self.stats.get("death_lessons", 0) + 1
        self.stats["death_lesson_last"] = {k: lesson.get(k) for k in ("killer", "crowd_n", "doing")}
        self._adj = None
        return lesson

    # --- 2. learn ---
    def adjustments(self, wall_now: float | None = None, refresh_s: float = 30.0) -> dict:
        t = self.clock() if wall_now is None else wall_now
        if self._adj is None or t - self._adj_at > refresh_s:
            self._adj = learn(load(self.paths[:1] if self.paths else []), self.title_id, t)
            self._adj_at = t
        return self._adj

    # --- 3. use ---
    def get(self, cls) -> dict | None:
        return self.adjustments().get(_cls(cls))

    def weight(self, cls) -> float:
        a = self.get(cls)
        return a["weight"] if a else 1.0

    def keep_cm(self, cls) -> float:
        a = self.get(cls)
        return a["keep_cm"] if a else 0.0

    def answer(self, cls):
        a = self.get(cls)
        return a["answer"] if a else None

    def doctrine(self, classes) -> dict:
        """The multipliers (mine_x / flash_x / retreat_x) when any of `classes` is near: the strongest of them."""
        out = {"mine_x": 1.0, "flash_x": 1.0, "retreat_x": 1.0}
        for c in classes or ():
            a = self.get(c)
            if a:
                out["mine_x"] = min(out["mine_x"], a["mine_x"])
                out["flash_x"] = min(out["flash_x"], a["flash_x"])
                out["retreat_x"] = max(out["retreat_x"], a["retreat_x"])
        return out


def distil(title_id: str, window: list, now: float, wall_ts: float | None = None) -> dict:
    """The lesson from the window's samples (oldest first): see the module text."""
    hits = [s["hit"] for s in window if s.get("hit")]
    dmg: dict = {}
    for h in hits:
        c = _cls(h.get("class"))
        if c is not None:
            dmg[c] = dmg.get(c, 0) + (_num(h.get("damage")) or 1)
    last_hit = next((_cls(h.get("class")) for h in reversed(hits) if h.get("class") is not None), None)
    killer = last_hit or (max(dmg, key=lambda k: dmg[k]) if dmg else None)
    final = window[-1]
    near: dict = {}
    for s in window:
        for e in s["crowd"]:
            c = e["class"]
            if c is not None and (c not in near or e["d"] < near[c]):
                near[c] = e["d"]
    hps = [(round(s["t"] - now, 2), s["hp"]) for s in window if s["hp"] is not None]
    kit = next((s["kit"] for s in reversed(window) if s.get("kit")), None) or {}
    return {
        "kind": "death_lesson", "title_id": str(title_id), "ts": wall_ts, "window_s": WINDOW_S,
        "killer": killer, "killer_basis": "last_hit" if last_hit else ("most_damage" if dmg else "not determined"),
        "hurt_by": dmg, "hits": len(hits),
        "crowd_n": len(final["crowd"]), "crowd": sorted(final["crowd"], key=lambda e: e["d"])[:12],
        "nearest_cm": near, "hp_curve": hps[-40:],
        "doing": next((s["doing"] for s in reversed(window) if s.get("doing")), ""),
        "why": next((s["why"] for s in reversed(window) if s.get("why")), ""),
        "kit": kit, "walls": final.get("walls"),
    }


def load(paths) -> list:
    out = []
    for p in paths:
        try:
            for line in Path(p).read_text(encoding="utf-8").splitlines():
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict) and d.get("kind") == "death_lesson":
                    out.append(d)
        except OSError:
            continue
    return out


def _decay(age_s: float) -> float:
    return 0.5 ** (max(age_s, 0.0) / HALF_LIFE_S)


def learn(lessons: list, title_id: str | None = None, now: float | None = None) -> dict:
    """{class: adjustment} from the lessons (all titles' when title_id is None; with one, that title's count must
    reach MIN_DEATHS only through lessons of any title - the universal file teaches every title, but a class's own
    title lessons count fully, other titles' half). Needs MIN_DEATHS blamed deaths; bounded by CAPS; decayed."""
    now = time.time() if now is None else now
    score: dict = {}
    count: dict = {}
    for d in lessons:
        c = d.get("killer")
        if c is None:
            continue
        w = _decay(now - (_num(d.get("ts")) or now))
        if title_id is not None and d.get("title_id") != str(title_id):
            w *= 0.5
        score[c] = score.get(c, 0.0) + w
        count[c] = count.get(c, 0) + 1
    out = {}
    for c, n in count.items():
        if n < MIN_DEATHS:
            continue
        steps = max(score[c] - (MIN_DEATHS - 1), 0.0)         # the MIN_DEATHS-th death is the first step, then one each

        def b(name, sign=1):
            return round(min(steps * STEP[name], CAPS[name]) * sign, 3)
        if score[c] < 0.25:                                    # faded away
            continue
        out[c] = {"deaths": n, "score": round(score[c], 3), "weight": round(1.0 + min(steps * STEP["weight"], CAPS["weight"] - 1.0), 3),
                  "keep_cm": b("keep_cm"), "answer": list(HEAVY_ANSWER),
                  "mine_x": round(1.0 - b("mine_x"), 3), "flash_x": round(1.0 - b("flash_x"), 3),
                  "retreat_x": round(1.0 + b("retreat_x"), 3)}
    return out


def replay(lessons: list, rounds_key: str = "round") -> dict:
    """Deaths per round before / after the first adjustment, over recorded lessons in order. Each lesson is a
    death_lesson (or a record with `killer`); `round` (an id) groups deaths into rounds, a lesson with no round id counts
    as its own round. The adjustment for a death is learned only from the deaths BEFORE it (no look-ahead). Reports the
    deaths whose killer class an adjustment already covered (what the lesson would have been used against) and those with
    no killer class (not determined)."""
    seen: list = []
    before_rounds, after_rounds = set(), set()
    covered = uncovered = undetermined = 0
    first_at = None
    for i, d in enumerate(lessons):
        rid = d.get(rounds_key, f"#{i}")
        k = d.get("killer")
        adj = learn(seen, None, _num(d.get("ts")) or time.time())
        if k is None:
            undetermined += 1
        elif k in adj:
            covered += 1
            after_rounds.add(rid)
        elif first_at is not None or adj:
            uncovered += 1
        if adj and first_at is None:
            first_at = i
        if first_at is None or i < first_at:
            before_rounds.add(rid)
        seen.append(d)
    n_before = sum(1 for i in range(len(lessons)) if first_at is None or i < first_at)
    n_after = len(lessons) - n_before
    return {"deaths": len(lessons), "first_adjustment_at_death": first_at,
            "deaths_before": n_before, "rounds_before": len(before_rounds),
            "deaths_after": n_after, "rounds_after": len(after_rounds) if first_at is not None else 0,
            "after_deaths_by_class_already_learned": covered, "after_deaths_by_unlearned_class": uncovered,
            "killer_not_determined": undetermined,
            "note": "per-round rates need the rounds played between deaths (not in the death records): not determined"}
