"""The doctrine's answer to a threat: every threatened tick is a flash, a mine (then away), or fire at the threat -
never nothing (gbox.mercs.core.doctrine's never-stand rule, made specific).

The operator, 2026-11-10: "the bot is just sitting here getting walloped by enemies when really the secret to all
adversarial combat situations is either flashbang, drop a mine, or fire the weapon upon them until there's no longer a
threat. So when I see him just standing there, I'm just puzzled as to what's going on because that's gonna result in
endless combat reports. And this bot is not learning."

Under threat (measured, in cm and seconds: the title's profile converts its units - RE4's world is in mm):
  * his health fell within HURT_S (Rules.hurt_s), with an enemy within threat_memory's REACH_MAX_CM of him; or
  * an enemy on his level within reach (Rules.reach_cm, 2.5 m) that is closing (closing_cm_s), winding up (the title's
    wind-up read or a learned lethal motion), or of a class that has hurt him (a grudge this round, or hits learned
    across rounds in threat memory) - for such a class the reach is its learned reach (threat_memory.reach), so a class
    that hurt him is a threat sooner.

The answer, by what is measured (choose()):
  flash  flash_n or more within flash_r_cm on his level (one that hurt him counts hurt_weight), a wind-up within its
         reach or one at arm's length (the profile's grab_r_cm), or his health at or under low_hp - at most one every
         flash_gap_s; the title's own path (RE5 / RE6: the native flash, no item screen);
  mine   converge_n or more closing within converge_r_cm, none nearer than mine_min_cm (the plant roots him; no mine at
         his feet), and open floor to step to when the title can tell - the title's own mine controller is asked for a
         plant now and runs its own clearance, standoff and retreat;
  fire   otherwise: the title's own fight, on the threats alone (no detour, no run-off), its own line-of-sight / wall
         gates kept (never a wall shot) - the target the wind-up, then the one that hurt him, then the nearest, a
         clear line first.
A title without one of them says so (Kit.flash / Kit.mine None): the next one answers and threat_lacks_flash /
threat_lacks_mine count it. Nothing here presses a key or touches the game: the title's kit does.

What is measured (the stats the round report carries, per round through each driver's round_counters):
  threat_ticks            ticks under threat (outside a hold, a prompt, a heal ...: threat_busy)
  threat_answered_flash   ... answered by a flash (its ask, and the flash_answer_s after it while it goes off)
  threat_answered_mine    ... by the mine cycle (the plant, the run off it)
  threat_answered_fire    ... by fire (the trigger, or the turn / raise / aim toward it within fire_grace_s)
  threat_unanswered       ... by none of the three (target: 0); threat_unanswered_why says the last reason
  hurt_while_idle         hits taken while none of the three ran in the idle_lookback_s before the hit
  threat_forced_fire      ticks the title's own decision answered nothing and the doctrine's fire replaced it
  threat_learned_ticks    threat ticks a class that hurt him (threat memory) made a threat or flash-worthy sooner
  plus threat_hits, hurt_while_busy, threat_busy, threat_flash_asks, threat_mine_asks, threat_lacks_flash,
  threat_lacks_mine, threat_flash_refused, threat_mine_refused, threat_status.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Callable

from .. import threat_memory

ANSWERS = ("flash", "mine", "fire")
COUNTERS = ("threat_ticks", "threat_answered_flash", "threat_answered_mine", "threat_answered_fire",
            "threat_unanswered", "hurt_while_idle", "threat_forced_fire", "threat_learned_ticks", "threat_hits",
            "hurt_while_busy", "threat_busy", "threat_flash_asks", "threat_mine_asks", "threat_lacks_flash",
            "threat_lacks_mine", "threat_flash_refused", "threat_mine_refused", "ring_events",
            "crowd_ticks")
ENFORCE = True                    # False: measured only (the stats above), the title's own action always stands


@dataclass(frozen=True)
class Rules:
    """The doctrine's thresholds, in cm and seconds (the same on every title: the profile converts the units)."""
    hurt_s: float = 1.5
    reach_cm: float = 250.0
    closing_cm_s: float = 40.0
    close_window_s: float = 0.6
    flash_n: int = 3
    flash_r_cm: float = 400.0
    low_hp: float = 0.35
    flash_gap_s: float = 4.0
    flash_answer_s: float = 1.0
    converge_n: int = 2
    converge_r_cm: float = 700.0
    mine_min_cm: float = 250.0
    mine_gap_s: float = 8.0
    fire_grace_s: float = 1.0
    point_blank_cm: float = 150.0
    hurt_weight: int = 2
    idle_lookback_s: float = 0.6
    tick_gap_s: float = 0.5
    crowd_n: int = 3                  # a crowd: this many on his level within crowd_r_cm is a threat before any closes
    crowd_r_cm: float = 600.0
    ring_spread_deg: float = 180.0    # a ring: 3+ within ring_r_cm whose bearings spread over this much (no gap this wide)
    ring_r_cm: float = 700.0     # (the rows end at threat_memory.REACH_MAX_CM)


@dataclass
class Kit:
    """What a title can answer with, this tick. Every callable may raise: an error is an answer it did not give.
      fire(target, pool) -> the title's own fight on these enemies (a pad action), or None;
      flash(why) -> True when a flash was asked (None: the title has none);
      mine(why) -> True when the mine controller took the ask (None: the title has none);
      clear(e) -> True / False / None: the line to him (None: the title cannot tell);
      can_step() -> True / False / None: open floor to step off a mine (None: the controller judges);
      classify(act, doing) -> "flash" / "mine" / "fire" / "aim" / "busy" / None, or "" to use the generic reading."""
    fire: Callable | None = None
    flash: Callable | None = None
    mine: Callable | None = None
    clear: Callable | None = None
    can_step: Callable | None = None
    classify: Callable | None = None
    busy: frozenset = frozenset()          # the title's doings that are not his choice (a hold, a prompt, a heal ...)
    attack: frozenset = frozenset()        # doings that are an attack without the fire button (a kick, a melee)
    aim: frozenset = frozenset()           # doings that bring the gun to bear (turn, raise, aim, reload)
    mine_doings: frozenset = frozenset()   # doings of the title's own mine / bomb cycle
    flash_doings: frozenset = frozenset()  # doings of the title's own flash throw


def _keys(act) -> set:
    act = act or {}
    keys = set(act.get("hold") or ())
    if act.get("tap"):
        keys.add(act["tap"])
    return keys


def classify(prof, kit: Kit, act, doing) -> str | None:
    """What this pad action does about a threat: "flash" / "mine" / "fire" / "aim" (bringing the gun to bear) / "busy"
    (not his choice) / None."""
    if kit.classify is not None:
        try:
            got = kit.classify(act, doing)
        except Exception:                                    # noqa: BLE001 - a classifier error: the generic reading
            got = ""
        if got != "":
            return got
    if doing in kit.busy:
        return "busy"
    if doing in kit.mine_doings:
        return "mine"
    if doing in kit.flash_doings:
        return "flash"
    keys = _keys(act)
    if prof.fire_btn in keys or doing in kit.attack:
        return "fire"
    if prof.aim_btn in keys or doing in kit.aim:
        return "aim"
    return None


class Memory:
    """Threat memory as the doctrine asks it, over a combat.Threats (RE4, RE6) or a threat_memory.ThreatMemory with
    the title's own wind-up read (RE5): reach(e) cm, grudge(e) hits this round, winding(e), hurt_class(e) (his class
    has hurt him before, in any round)."""

    def __init__(self, src, prof=None, winding: Callable | None = None, default_reach_cm: float | None = None):
        self.src, self.prof, self._winding = src, prof, winding
        self.default = default_reach_cm

    def _tm(self):
        return getattr(self.src, "tm", self.src)

    def _cls(self, e):
        key = getattr(self.prof, "class_key", None) if self.prof is not None else None
        return key(e) if key is not None else (e or {}).get("class")

    def reach(self, e) -> float:
        src = self.src
        if hasattr(src, "reach_cm"):
            return float(src.reach_cm(e))
        return float(src.reach(self._cls(e), self.default))

    def grudge(self, e) -> int:
        return int(self.src.grudge(e) or 0)

    def winding(self, e) -> bool:
        if self._winding is not None:
            return bool(self._winding(e))
        w = getattr(self.src, "winding", None)
        return bool(w(e)) if w is not None else False

    def hurt_class(self, e) -> bool:
        cls = self._cls(e)
        c = (self._tm().data.get("classes") or {}).get(str(cls)) if cls is not None else None
        return bool(c) and (c.get("hit_count") or 0) > 0


Threat = dict      # {"rows", "target", "why", "hurt", "learned", "crowd", "converging", "nearest_cm", "low"}


class Responder:
    """One bot's doctrine response. Every playing tick: respond() before the title's idle / never-stand rules (the
    verdict and, when the title's own action answered nothing, the doctrine's answer), then settle() with the action
    the tick finally sent (the accounting). The counters are cumulative: the engine takes each round's amount."""

    def __init__(self, stats: dict | None = None, rules: Rules | None = None):
        self.stats = stats if stats is not None else {}
        self.rules = rules or Rules()
        self._track: dict = {}             # enemy key -> deque of (t, d cm)
        self._hp = None                    # (player key, hp)
        self.hurt_at = -1e9
        self.flash_at = self.mine_at = -1e9
        self.fired_at = -1e9
        self.spell_at = None               # the threat's start (None: no threat)
        self.t = None
        self.answers: deque = deque(maxlen=32)     # (t, answer) of the settled ticks
        self.pending = None                # this tick's verdict, until settle()
        self._ringed = False
        for k in COUNTERS:
            self.stats.setdefault(k, 0)

    # --- bookkeeping ---------------------------------------------------------------------------------------------------
    def _count(self, k: str, n: int = 1) -> None:
        self.stats[k] = self.stats.get(k, 0) + n

    def _hurt(self, now: float, player) -> bool:
        """His health fell since the last tick: a hit (hurt_while_idle when none of the three ran just before it)."""
        hp, key = player.get("hp"), player.get("ptr")
        last, self._hp = self._hp, (key, hp)
        if last is None or last[0] != key or type(hp) is not int or type(last[1]) is not int or hp >= last[1]:
            return False
        self.hurt_at = now
        self._count("threat_hits")
        recent = [a for t, a in self.answers if now - t <= self.rules.idle_lookback_s]
        if not any(a in ANSWERS for a in recent):
            self._count("hurt_while_busy" if "busy" in recent else "hurt_while_idle")
        return True

    def _closing(self, key, now: float, d: float) -> float:
        """cm/s his distance is falling at (over close_window_s of his track); 0 with too short a track."""
        h = self._track.setdefault(key, deque(maxlen=16))
        h.append((now, d))
        while len(h) > 2 and now - h[1][0] >= self.rules.close_window_s:
            h.popleft()
        t0, d0 = h[0]
        return (d0 - d) / (now - t0) if now - t0 >= 0.15 else 0.0

    def _crowd(self, rows, me, prof) -> tuple:
        """(crowd, ring): crowd_n or more within crowd_r_cm; ring: crowd_n or more within ring_r_cm whose bearings leave no
        gap of ring_spread_deg or more (they are on all sides, not in front)."""
        r = self.rules
        near = [x for x in rows if x["d"] <= r.ring_r_cm]
        crowd = sum(1 for x in rows if x["d"] <= r.crowd_r_cm) >= r.crowd_n
        ring = False
        if len(near) >= r.crowd_n:
            ang = sorted(math.degrees(math.atan2(*(lambda q: (q[0] - me[0], q[2] - me[2]))(prof.pos_cm(x["e"]["pos"]))))
                         % 360.0 for x in near)
            gaps = [b - a for a, b in zip(ang, ang[1:])] + [ang[0] + 360.0 - ang[-1]]
            ring = (360.0 - max(gaps)) > r.ring_spread_deg
        return crowd, ring

    # --- the verdict ---------------------------------------------------------------------------------------------------
    def assess(self, prof, now: float, player, enemies, memory: Memory | None = None, clear=None) -> Threat | None:
        """The threat this tick, or None. Rows in cm: {"e", "d", "dy", "closing", "windup", "grudge", "hurt_class",
        "reach", "clear", "threat"}."""
        r = self.rules
        gap = self.t is not None and now - self.t > r.tick_gap_s
        self.t = now
        if gap:
            self._track.clear()
            self.spell_at = None
        p = player or {}
        pos = p.get("pos")
        if not pos:
            return None
        hurt_now = self._hurt(now, p)
        me = prof.pos_cm(pos)
        rows, seen = [], set()
        for e in enemies or ():
            if not isinstance(e, dict) or (e.get("hp") or 0) <= 0 or not e.get("pos"):
                continue
            q = prof.pos_cm(e["pos"])
            d, dy = math.hypot(q[0] - me[0], q[2] - me[2]), q[1] - me[1]
            key = e.get("ptr", e.get("slot"))
            seen.add(key)
            closing = self._closing(key, now, d) if key is not None else 0.0
            if abs(dy) > prof.level_dy_cm or d > threat_memory.REACH_MAX_CM:
                continue
            row = {"e": e, "key": key, "d": d, "dy": dy, "closing": closing, "windup": False, "grudge": 0,
                   "hurt_class": False, "reach": r.reach_cm, "clear": None}
            if memory is not None:
                try:
                    row["windup"] = memory.winding(e)
                    row["grudge"] = memory.grudge(e)
                    row["hurt_class"] = memory.hurt_class(e)
                    if row["grudge"] or row["hurt_class"]:
                        row["reach"] = max(r.reach_cm, memory.reach(e))   # a class that hurt him: its learned reach
                    elif row["windup"]:
                        row["reach"] = max(r.reach_cm, min(memory.reach(e), 2 * r.reach_cm))
                except Exception:                            # noqa: BLE001 - a memory error proves nothing
                    pass
            elif prof.windup is not None:
                try:
                    row["windup"] = bool(prof.windup(e))
                except Exception:                            # noqa: BLE001
                    pass
            learned = bool(row["grudge"] or row["hurt_class"])
            row["learned"] = learned
            row["threat"] = row["d"] <= row["reach"] and (row["closing"] >= r.closing_cm_s or row["windup"] or learned)
            rows.append(row)
        for k in [k for k in self._track if k not in seen]:
            del self._track[k]
        hurt = now - self.hurt_at <= r.hurt_s
        crowd_now, ring_now = self._crowd(rows, me, prof)
        if ring_now and not self._ringed:
            self._count("ring_events")      # (RE6 keeps its own surround_events: 3 within 4 m)
        self._ringed = ring_now
        if crowd_now or ring_now:                          # proactive: a crowd / ring is a threat before it closes
            self._count("crowd_ticks")
            for x in rows:
                if prof.grab_r_cm < x["d"] <= (r.ring_r_cm if ring_now else r.crowd_r_cm):   # (arm's length: the title's own escape / flash)
                    x["threat"] = True
        hot = [x for x in rows if x["threat"]]
        if hurt and rows and not hot:
            hot = [min(rows, key=lambda x: x["d"])]            # hurt: the nearest one is the threat
        if not hot:
            self.spell_at = None
            return None
        if self.spell_at is None:
            self.spell_at = now
        line = clear
        for x in rows:
            if line is not None and x in hot:
                try:
                    x["clear"] = line(x["e"])
                except Exception:                            # noqa: BLE001 - a geometry error proves nothing
                    x["clear"] = None
        hp, top = p.get("hp"), p.get("hp_max")
        low = isinstance(hp, (int, float)) and isinstance(top, (int, float)) and top > 0 and hp <= r.low_hp * top
        crowd = sum((r.hurt_weight if x["learned"] else 1) for x in rows if x["d"] <= r.flash_r_cm)
        converging = sum(1 for x in rows if x["d"] <= r.converge_r_cm and x["closing"] >= r.closing_cm_s)
        return {"rows": rows, "hot": hot, "hurt": hurt, "hurt_now": hurt_now, "low": low, "crowd": crowd,
                "converging": converging, "crowd_n": sum(1 for x in rows if x["d"] <= r.ring_r_cm if crowd_now or ring_now), "nearest_cm": min(x["d"] for x in rows),
                "learned": any(x["learned"] for x in hot)}

    def choose(self, prof, threat: Threat) -> tuple:
        """("flash" / "mine" / "fire", why) by what is measured (the module text)."""
        r = self.rules
        grab = any(x["d"] <= prof.grab_r_cm for x in threat["rows"])
        wind = next((x for x in threat["hot"] if x["windup"] and x["d"] <= x["reach"]), None)
        if threat["crowd"] >= r.flash_n:
            return "flash", f"{threat['crowd']} (weighted) within {r.flash_r_cm / 100:.0f} m"
        if wind is not None:
            return "flash", f"a wind-up {wind['d'] / 100:.1f} m off"
        if grab:
            return "flash", f"one at arm's length ({threat['nearest_cm'] / 100:.1f} m)"
        if threat["low"]:
            return "flash", "his health low with a threat on him"
        if threat["crowd_n"] >= r.crowd_n and threat["nearest_cm"] >= r.mine_min_cm and not threat["converging"] >= r.converge_n:
            return "mine", f"a crowd of {threat['crowd_n']} {threat['nearest_cm'] / 100:.1f} m off, past the blast reach"
        if threat["converging"] >= r.converge_n and threat["nearest_cm"] >= r.mine_min_cm:
            return "mine", f"{threat['converging']} converging, the nearest {threat['nearest_cm'] / 100:.1f} m off"
        return "fire", "fire until the threat is gone"

    def target(self, threat: Threat):
        """(row, why) to fire at - a clear line first: the wind-up, the one that hurt him, the nearest; none clear: the
        nearest only at point blank right after a hit (bodies touching: the hit proves the reach), else (None, why)."""
        hot = threat["hot"]
        order = sorted(hot, key=lambda x: (0 if x["windup"] else 1 if x["learned"] else 2, x["d"]))
        for x in order:
            if x["clear"] is not False:
                return x, ""
        x = min(hot, key=lambda x: x["d"])
        if threat["hurt"] and x["d"] <= self.rules.point_blank_cm:
            return x, ""
        return None, "no clear line to any threat (never a wall shot)"

    # --- the tick ------------------------------------------------------------------------------------------------------
    def respond(self, prof, now: float, player, enemies, act, kit: Kit, doing=None, memory: Memory | None = None):
        """This tick's action under the doctrine: the title's own when it answers the threat, else the doctrine's."""
        if self.pending is not None:                         # a tick the title never settled: settled as decided
            self.settle(self.pending.get("act"), self.pending.get("doing"))
        threat = self.assess(prof, now, player, enemies, memory, kit.clear)
        if threat is None:
            self.stats["threat_status"] = ""
            self.pending = {"threat": False, "act": act, "doing": doing, "prof": prof, "kit": kit, "now": now}
            return act
        r = self.rules
        want, why = self.choose(prof, threat)
        seen = classify(prof, kit, act, doing)
        v = {"threat": True, "act": act, "doing": doing, "want": want, "why": why, "asked": None, "forced": False,
             "learned": threat["learned"], "unanswered_why": "", "prof": prof, "kit": kit, "now": now}
        self.pending = v
        if seen == "busy":
            return act
        if not ENFORCE:
            return act
        # the flash: a side effect where the title has a native one (no pad), at most one every flash_gap_s
        if want == "flash":
            if kit.flash is None:
                self._count("threat_lacks_flash")
                want, why = ("mine", why + "; no flash on this title") \
                    if threat["converging"] >= r.converge_n and threat["nearest_cm"] >= r.mine_min_cm \
                    else ("fire", why + "; no flash on this title")
            elif now - self.flash_at >= r.flash_gap_s:
                ok = False
                try:
                    ok = bool(kit.flash(why))
                except Exception:                            # noqa: BLE001
                    ok = False
                if ok:
                    self.flash_at = now
                    self._count("threat_flash_asks")
                    v["asked"] = "flash"
                else:
                    self._count("threat_flash_refused")
        if want == "mine":
            if kit.mine is None:
                self._count("threat_lacks_mine")
            elif now - self.mine_at >= r.mine_gap_s:
                step = None
                if kit.can_step is not None:
                    try:
                        step = kit.can_step()
                    except Exception:                        # noqa: BLE001
                        step = None
                ok = False
                if step is not False:
                    try:
                        ok = bool(kit.mine(why))
                    except Exception:                        # noqa: BLE001
                        ok = False
                if ok:
                    self.mine_at = now
                    self._count("threat_mine_asks")
                else:
                    self._count("threat_mine_refused")
        if v["asked"] == "flash" or now - self.flash_at <= r.flash_answer_s:
            return act                                       # the flash answers; his own action goes on
        if self._answered(prof, now, seen):
            return act
        tgt, no = self.target(threat)
        if tgt is None or kit.fire is None:
            v["unanswered_why"] = no or "no fire path on this title"
            return act
        pool = [tgt["e"]] + [x["e"] for x in threat["hot"] if x is not tgt]
        try:
            forced = kit.fire(tgt["e"], pool)
        except Exception as exc:                             # noqa: BLE001 - the title's own action stands
            self.stats["threat_error"] = f"{type(exc).__name__}: {exc}"[:160]
            forced = None
        if forced is None:
            v["unanswered_why"] = "the fight on the threat gave no action"
            return act
        v.update(act=forced, forced=True, doing=None)
        self._count("threat_forced_fire")
        self.stats["threat_status"] = (f"fire at the threat {tgt['d'] / 100:.1f} m off ({why}): the doctrine's, his "
                                       f"own action ({doing}) answered nothing")[:200]
        return forced

    def _answered(self, prof, now: float, seen) -> bool:
        if seen in ANSWERS:
            return True
        return seen == "aim" and now - max(self.fired_at, self.spell_at or -1e9) <= self.rules.fire_grace_s + prof.raise_s

    def settle(self, act, doing=None) -> str | None:
        """The action this tick finally sent (after the title's idle / stand / wall rules): what he did is remembered
        (hurt_while_idle reads it) and a threat tick's answer counted. -> the answer ("flash" / "mine" / "fire" /
        "busy"; None: unanswered, or no threat this tick)."""
        v, self.pending = self.pending, None
        if v is None:
            return None
        prof, kit, now = v["prof"], v["kit"], v["now"]
        seen = classify(prof, kit, act, doing)
        if seen == "fire":
            self.fired_at = now
        if not v["threat"]:
            self.answers.append((now, seen if seen in ANSWERS or seen == "busy" else None))
            return None
        r = self.rules
        if seen == "busy":
            ans = "busy"
        elif v["asked"] == "flash" or now - self.flash_at <= r.flash_answer_s:
            ans = "flash"
        elif seen in ANSWERS:
            ans = seen
        elif seen == "aim" and prof is not None and self._answered(prof, now, seen):
            ans = "fire"
        else:
            ans = None
        self.answers.append((now, ans))
        if ans == "busy":
            self._count("threat_busy")
            return ans
        self._count("threat_ticks")
        if v["learned"]:
            self._count("threat_learned_ticks")
        if ans is None:
            self._count("threat_unanswered")
            why = v["unanswered_why"] or (f"{doing or 'nothing'}: not one of flash / mine / fire" if seen != "aim"
                                          else "the gun up, no shot past the raise's grace")
            self.stats["threat_unanswered_why"] = why[:160]
            self.stats["threat_status"] = f"UNANSWERED ({v['want']} wanted: {v['why']}): {why}"[:200]
        else:
            self._count("threat_answered_" + ans)
            if not v["forced"]:
                self.stats["threat_status"] = f"{ans} ({v['want']} wanted: {v['why']})"[:200]
        return ans
