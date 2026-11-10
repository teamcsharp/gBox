"""The universal Mercenaries fight: one aim-and-fire core for RE4, RE5 and RE6 (Switch), the titles' differences in
a profile (docs/research/universal-mercs-architecture.md, section 9: stage A).

The operator, 2026-11-10: "these mercenary titles are all over the shoulder aiming ... I want the same aimbot I am
critiquing in RE4 to improve across 5 and 6 despite their differences. Those should be taken into consideration but
the overall psychology of raising the weapon and aiming and firing to eliminate threats is unchanged ... solve
mercenaries in general so this technology can go across games and be used with other games of the same type with
calibrations and profile adjustments."

The psychology, the same in every title: see the threats (who, where, on his floor, on his line), pick the one that
matters (the one about to hit him, then the one that already did, then the nearest on his level and line), raise the
gun, lay the line on the body, fire while the line is on him, and never stand idle with a threat in range. What is
the title's own is calibration: its units, its sticks, its aim model, how long the gun takes to come up, how wide a
body is at a distance, how tall each enemy class stands, what its specials are. That is TitleProfile; every title's
module builds its own from the constants its bot already uses (combat_profile()), so a knob turned live is the
profile's at the next call.

Five components, each over a small normalized view - positions in cm, angles in radians, the profile converting the
title's own units (RE4's world is in mm):
  (a) bodies     Body / BodyTable / KIND_BODIES, and the body-aware hit tests dot_on / through / line_hits /
                 segment_hits: an enemy class's own heights for the aim and the hit test (a crawler is aimed at its
                 back, not 110 cm over it). A body is per KIND (a dog is a dog in every title); each title maps its
                 classes onto kinds or onto a body of its own.
  (b) NotInControl  shots fired, no effect, unmoved this long: the scene takes no input (an intro card, a death
                 camera): page it with the profile's key, at most page_max_s at a time.
  (c) Threats    gbox.mercs.threat_memory hooked to any title: who hurt him, the motions that came before (lethal
                 wind-ups), the reach they land from, the grudges of this round; the wind-up / grudge priority and
                 the step out of an attack his shots do not stop.
  (d) candidates / rank / pick / priority  the target scorer: a wind-up first (survival), then a boss / dangerous
                 one in reach on his level (prof.tier: gbox.mercs.enemy_identity once it lands, the title's own
                 maximum-health read beside it), then a grudge, then the cheapest by distance x turn x level x line
                 (the current target kept within keep_x) - and one at arm's length is never left for a boss or a
                 grudge.
  (e) IdleGuard  never idle with a threat in range: the gun up this long without a shot is "move" (round to him or
                 close in), neither attacking nor moving this long is "engage".

Nothing here reads or writes the game, and nothing here presses a key: a bot maps each verdict onto its own sticks.
"""
from __future__ import annotations

import importlib
import math
from collections import namedtuple
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .. import threat_memory

try:                                     # per title and enemy class a name and a tier (branch enemy-identity); until
    from .. import enemy_identity as _identity   # it lands every title's own fallback tier stands (identity_tier)
except Exception:                        # noqa: BLE001 - an absent or broken module never costs the fight
    _identity = None


def heading(dx: float, dz: float) -> float:
    """The heading convention of every Switch title (0 = +z, + toward +x)."""
    return math.atan2(dx, dz)


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


# --- (a) bodies -------------------------------------------------------------------------------------------------------
# A body for the shot, in cm above its feet: the head sphere's centre, the aim point (chest), the body capsule from knee
# to shoulder, and its radius. The measures are the PS3 combat layer's (gbox/mercs/titles/re5_combat.py) and the
# RE5 Switch low bodies measured on the models (2026-11-10: the Experimental Facility's crawlers 27 cm tall at the bind
# pose, the dogs 86 cm on four legs).
Body = namedtuple("Body", "head chest knee shoulder r")
HEAD_R_CM = 22.0
FIRE_SLACK_CM = 60.0                     # a ray ending this much short of him ends on something in front of him
HUMAN = Body(160.0, 110.0, 45.0, 145.0, 36.0)
KIND_BODIES = {
    "human": HUMAN,
    "crawler": Body(45.0, 30.0, 0.0, 55.0, 60.0),    # lickers, crawlers: on all fours at his feet
    "dog": Body(75.0, 55.0, 15.0, 80.0, 50.0),       # dogs
}


def scaled(b: Body, k: float) -> Body:
    """The body in another unit (k units per cm)."""
    return b if k == 1.0 else Body(*(float(v) * k for v in b))


@dataclass(frozen=True)
class BodyTable:
    """A title's bodies: its standing enemy (default) and, per enemy class, a Body of its own or a KIND_BODIES name."""
    default: Body = HUMAN
    classes: dict = field(default_factory=dict)

    def body(self, e) -> Body:
        cls = e.get("class") if isinstance(e, dict) else None
        try:
            got = self.classes.get(cls) if cls is not None else None
        except TypeError:                                    # an unhashable class field: the default body
            got = None
        if got is None:
            return self.default
        if isinstance(got, str):
            return KIND_BODIES.get(got, self.default)
        return got

    def low(self, e) -> bool:
        """Whether this enemy's class has a body of its own (not the title's standing one)."""
        return self.body(e) is not self.default


def dot_on(dot, foot, b: Body = HUMAN, head_r: float = HEAD_R_CM) -> str | None:
    """Where an aim's end point sits on a body standing at foot (cm): "head", "body", else None."""
    dx, dy, dz = dot[0] - foot[0], dot[1] - foot[1], dot[2] - foot[2]
    if math.sqrt(dx * dx + (dy - b.head) ** 2 + dz * dz) <= head_r:
        return "head"
    if math.hypot(dx, dz) <= b.r and b.knee - 10 <= dy <= b.shoulder + 20:
        return "body"
    return None


def _probe_heights(b: Body) -> tuple:
    return b.head, b.chest, b.knee + min(30.0, (b.shoulder - b.knee) / 2)


def through(origin, dot, foot, b: Body = HUMAN, slack: float = FIRE_SLACK_CM, head_r: float = HEAD_R_CM) -> bool:
    """Whether the ray origin -> dot runs to him: it reaches his chest's distance (less slack) and passes inside his
    head or body on the way, or ends inside his body's angular width of his chest (close up the body is wide)."""
    chest = (foot[0], foot[1] + b.chest, foot[2])
    want, have = math.dist(origin, chest), math.dist(origin, dot)
    if want < 1.0 or have < 1.0 or have < want - slack:
        return False
    d = tuple((dot[k] - origin[k]) / have for k in range(3))
    cos = sum((chest[k] - origin[k]) * d[k] for k in range(3)) / want
    if math.acos(max(-1.0, min(1.0, cos))) <= math.atan2(b.r, want):
        return True
    for h in _probe_heights(b):
        along = sum((foot[k] + (h if k == 1 else 0.0) - origin[k]) * d[k] for k in range(3))
        if 0.0 < along <= have and dot_on(tuple(origin[k] + along * d[k] for k in range(3)), foot, b, head_r) is not None:
            return True
    return False


def line_hits(origin, toward, foot, reach: float, b: Body = HUMAN, head_r: float = HEAD_R_CM) -> bool:
    """Whether the line from origin through toward, out to reach, passes inside a body standing at foot."""
    have = math.dist(origin, toward)
    if have < 1.0:
        return False
    d = tuple((toward[k] - origin[k]) / have for k in range(3))
    for h in _probe_heights(b):
        along = sum((foot[k] + (h if k == 1 else 0.0) - origin[k]) * d[k] for k in range(3))
        if 0.0 < along <= reach and dot_on(tuple(origin[k] + along * d[k] for k in range(3)), foot, b, head_r) is not None:
            return True
    return False


def segment_hits(origin, dot, foot, b: Body = HUMAN, head_r: float = HEAD_R_CM) -> bool:
    """The measured aim segment ends on the body or crosses it before its end (never extended past a wall)."""
    reach = math.dist(origin, dot)
    return reach >= 1.0 and (dot_on(dot, foot, b, head_r) is not None or line_hits(origin, dot, foot, reach, b, head_r))


def half_angle(b: Body, dist: float) -> float:
    """The angle half his body covers at this distance (the same unit for both): the shot's tolerance."""
    return math.atan2(b.r, max(dist, 1.0))


# --- the profile --------------------------------------------------------------------------------------------------------
def _class_key(e):
    c = (e or {}).get("class")
    return None if c is None else str(c)


def _motion_key(e):
    return (e or {}).get("motion")


# Who is worth dispatching first (the operator 2026-11-10: "have the bot prioritize dispatching boss level foes and
# dangerous opponents"): an enemy's tier, "boss" / "dangerous" / "normal". The source is gbox.mercs.enemy_identity
# (tier(title_id, cls), per title and class) once it is on main, and each title's own fallback beside it (a maximum
# health read: RE6's BIG_HP / BOSS_HP, RE4's HEAVY_HP); the higher of the two counts. IDENTITY off: the fallback only.
TIERS = ("boss", "dangerous", "normal")
TIER_ORDER = {"boss": 0, "dangerous": 1, "normal": 2}
IDENTITY = True


def hp_tier(boss_hp=None, dangerous_hp=None) -> Callable:
    """A fallback tier from the maximum health: at least boss_hp "boss", at least dangerous_hp "dangerous"."""
    def tier_of(e):
        top = (e or {}).get("hp_max")
        if not isinstance(top, (int, float)) or isinstance(top, bool):
            return "normal"
        if boss_hp is not None and top >= boss_hp:
            return "boss"
        if dangerous_hp is not None and top >= dangerous_hp:
            return "dangerous"
        return "normal"
    return tier_of


def identity_tier(title_id: str, fallback: Callable | None = None) -> Callable:
    """e -> its tier: enemy_identity.tier(title_id, class) when that module is there (the class as the census reads it,
    an int class also as hex), else / and the fallback - the higher of the two; "normal" with neither."""
    def tier_of(e):
        best = "normal"
        cls = (e or {}).get("class")
        if IDENTITY and _identity is not None and cls is not None:
            keys = (cls, f"{cls:#x}") if isinstance(cls, int) and not isinstance(cls, bool) else (cls,)
            for k in keys:
                try:
                    t = _identity.tier(title_id, k)
                except Exception:                            # noqa: BLE001 - an identity error is "normal"
                    t = None
                if t in TIER_ORDER and TIER_ORDER[t] < TIER_ORDER[best]:
                    best = t
        if fallback is not None:
            try:
                t = fallback(e)
            except Exception:                                # noqa: BLE001
                t = None
            if t in TIER_ORDER and TIER_ORDER[t] < TIER_ORDER[best]:
                best = t
        return best
    return tier_of


@dataclass(frozen=True)
class TitleProfile:
    """One title's calibration of the universal fight. Distances in cm (the conversions from the title's units:
    units_per_cm), angles in radians, times in seconds. Built by each title's combat_profile() from its own live
    constants."""
    title: str
    title_id: str = ""
    units_per_cm: float = 1.0                # RE4 Switch: 10 (mm); RE5 / RE6 Switch: 1 (cm)
    # how he aims (descriptive: each bot's stick driver owns the keys)
    aim_model: str = "laser_ray"             # "tank_heading" (RE4), "laser_ray" (RE5), "laser_camera_geometry" (RE6)
    sticks: str = ""
    aim_btn: str = "zl"
    fire_btn: str = "zr"
    turn_sign: int = 1                       # +1: an error > 0 turns to the larger heading (left)
    raise_s: float = 0.15                    # the gun up this long before the first shot is believed
    raise_tol: float = math.radians(12)      # the body this close to the target: the gun comes up
    fire_tol_min: float = math.radians(1.0)  # never a tighter shot tolerance than this
    engage_cm: float = 2200.0
    level_dy_cm: float = 120.0               # on his level: within this height of him
    max_dy_cm: float = 300.0                 # in the fight at all: within this height
    bodies: BodyTable = field(default_factory=BodyTable)
    head_r_cm: float = HEAD_R_CM
    fire_slack_cm: float = FIRE_SLACK_CM
    specials: tuple = ()                     # the title's own moves the core leaves to it (melee follow-up, quick shot)
    # (c) who hurt him
    threat_file: Path | None = None
    windup_r_cm: float = 300.0               # a wind-up this near counts (the learned reach widens it per class)
    grudge_r_cm: float = 1000.0
    lethal_keep_x: float = 1.15
    lethal_backoff_max_s: float = 1.8
    hurt_gap_s: float = 0.5                  # health falls closer than this together are one hit (a squeeze)
    class_key: Callable = _class_key         # e -> the class threat memory learns under
    motion_key: Callable = _motion_key       # e -> the motion / action threat memory reads
    attacking: Callable | None = None        # e -> bool: the title's own "an attack is under way" read
    windup: Callable | None = None           # e -> bool: the title's fixed wind-up read (stopped before anyone else)
    # (d) the target scorer
    turn_w: float = 1.0
    level_w: float = 1.5
    keep_x: float = 1.5
    blocked_x: float = 4.0                   # a target with no clear line costs this many times more
    tier: Callable | None = None             # e -> "boss" / "dangerous" / "normal" (identity_tier); None: all normal
    tier_w: dict = field(default_factory=lambda: {"boss": 0.4, "dangerous": 0.7})   # x the distance among them
    priority_r_cm: float = 0.0               # bosses / dangerous ones first within this (0: engage_cm)
    grab_r_cm: float = 120.0                 # one this near on his level is never left for a boss or a grudge
    # (b) not in control
    page_key: str = "a"
    frozen_cm: float = 3.0
    frozen_rad: float = 0.01
    no_effect_s: float = 5.0
    no_effect_shots: int = 8
    no_effect_trigger_s: float = 0.0         # the trigger held this long counts as the shots (0: shots only)
    step_s: float = 0.8
    page_tap_s: float = 0.2
    page_max_s: float = 4.0
    page_clear_cm: float = 0.0               # no paging with a living enemy this near (0: whoever is near)
    # (e) never idle
    idle_aim_s: float = 2.0
    idle_still_s: float = 0.75

    def cm(self, v: float) -> float:
        return float(v) / self.units_per_cm

    def units(self, cm: float) -> float:
        return float(cm) * self.units_per_cm

    def pos_cm(self, pos) -> tuple:
        k = self.units_per_cm
        return tuple(float(v) / k for v in pos[:3])

    def body(self, e) -> Body:
        """His class's body in cm."""
        return self.bodies.body(e)

    def body_units(self, e) -> Body:
        """His class's body in the title's own units."""
        return scaled(self.bodies.body(e), self.units_per_cm)


TITLES = {"re4_switch": "gbox.mercs.titles.re4_switch", "re5_switch": "gbox.mercs.titles.re5_switch",
          "re6_switch": "gbox.mercs.titles.re6_switch"}


def profile(title: str) -> TitleProfile:
    """The title's profile as its module builds it now (its live constants)."""
    return importlib.import_module(TITLES[title]).combat_profile()


# --- (b) not in control -------------------------------------------------------------------------------------------------
Page = namedtuple("Page", "tap cause fresh")     # tap: the key to press this tick (None: between taps)


class NotInControl:
    """Shots fired, no effect, unmoved (RE4 Switch, live 2026-11-10 03:52: Krauser on Waterworld's intro card, "crowd
    fire" for minutes, 620 shots, 0 hits): the scene takes no input - an intro card, a death camera - and the fight is
    not what is wanted: the profile's page key, every page_tap_s.

    Unmoved: his position within frozen_cm and every facing angle given (his heading, a camera yaw, an aim pitch)
    within frozen_rad of where they were when he last moved. Two causes:
      fire  no_effect_shots shots (or no_effect_trigger_s of the trigger held) over no_effect_s, unmoved, with no hit,
            no enemy health falling and no kill since he last moved;
      step  a commanded step (stepped_at, the title's never-stand step) that ran step_s without moving him.
    A spell lasts at most page_max_s: paging that long without a move is not the remedy either, and the fight goes on
    (the rules then need their full time again). No paging with an enemy within page_clear_cm (a title whose grabs
    have their own reading). Stats: <prefix>_spells, _fire_spells, _taps, _releases."""

    def __init__(self, stats: dict | None = None, prefix: str = "frozen"):
        self.stats = stats if stats is not None else {}
        self.prefix = prefix
        self.anchor = None
        self.on, self.on_at, self.tap_at = False, None, -1e9
        self._hp: dict = {}
        self._kills = None
        self.effect_at = -1e9

    def _count(self, k: str) -> None:
        key = f"{self.prefix}_{k}"
        self.stats[key] = self.stats.get(key, 0) + 1

    def effects(self, now: float, enemies=None, kills=None) -> None:
        """An enemy's health falling, or the kill count rising: the game took the shots."""
        if enemies is not None:
            seen = {}
            for e in enemies:
                k = e.get("ptr", e.get("slot")) if isinstance(e, dict) else None
                hp = e.get("hp") if isinstance(e, dict) else None
                if k is None or not isinstance(hp, (int, float)) or isinstance(hp, bool):
                    continue
                if hp < self._hp.get(k, hp):
                    self.effect_at = now
                seen[k] = hp
            self._hp = seen
        if isinstance(kills, int) and not isinstance(kills, bool):
            if isinstance(self._kills, int) and kills > self._kills:
                self.effect_at = now
            self._kills = kills

    def check(self, prof: TitleProfile, now: float, pos, facing=None, shots: int = 0, last_hit_at=None,
              trigger_s=None, stepped_at=None, enemies=None, kills=None, nearest_cm=None) -> Page | None:
        """None while he is in control; else this tick's Page."""
        if enemies is not None or kills is not None:
            self.effects(now, enemies, kills)
        pc = prof.pos_cm(pos)
        fac = tuple(facing) if isinstance(facing, (tuple, list)) else (facing,)
        a = self.anchor
        moved = (a is None or math.hypot(pc[0] - a["pos"][0], pc[2] - a["pos"][2]) > prof.frozen_cm
                 or any(isinstance(f, (int, float)) and isinstance(g, (int, float)) and abs(wrap(f - g)) > prof.frozen_rad
                        for f, g in zip(fac, a["facing"])))
        if moved:
            self.anchor = {"pos": pc, "facing": fac, "at": now, "shots": shots, "trigger": trigger_s}
            self.on = False
            return None
        if self.on and now - self.on_at >= prof.page_max_s:
            a.update(at=now, shots=shots, trigger=trigger_s)    # paged long enough: the fight again, the clocks afresh
            self.on = False
            self._count("releases")
            return None
        at = a["at"]
        hit = max(last_hit_at if isinstance(last_hit_at, (int, float)) else -1e9, self.effect_at)
        effort = (shots - a["shots"] >= prof.no_effect_shots
                  or (prof.no_effect_trigger_s > 0 and isinstance(trigger_s, (int, float))
                      and isinstance(a["trigger"], (int, float)) and trigger_s - a["trigger"] >= prof.no_effect_trigger_s))
        fire_stuck = now - at >= prof.no_effect_s and hit < at and effort
        step_stuck = stepped_at is not None and stepped_at >= at and now - stepped_at >= prof.step_s
        if not (fire_stuck or step_stuck):
            return None
        if prof.page_clear_cm and isinstance(nearest_cm, (int, float)) and nearest_cm < prof.page_clear_cm:
            return None
        fresh = not self.on
        if fresh:
            if fire_stuck:
                self._count("fire_spells")
            self.on, self.on_at = True, now
            self._count("spells")
        tap = None
        if now - self.tap_at >= prof.page_tap_s:
            self.tap_at, tap = now, prof.page_key
            self._count("taps")
        return Page(tap, "fire" if fire_stuck else "step", fresh)


# --- (c) who hurt him ---------------------------------------------------------------------------------------------------
THREAT_COUNTERS = ("lethal_backoffs", "grudge_picks", "windup_picks", "boss_picks", "dangerous_picks", "grab_picks",
                   "tm_hits_attributed", "tm_hits_unattributed", "tm_lethal_starts")


class Threats:
    """gbox.mercs.threat_memory for any title (RE5 Switch's wiring, made title-generic): every tick the living enemies
    (observe), every fall of his health put on the enemy that landed it (hurt), the class's lethal motions and reach
    learned and kept in the profile's threat_file. Rows are normalized to cm and to the profile's class / motion keys
    here, so the memory's distances mean the same on every title. What the bot asks:
      winding(e)    the title's fixed wind-up read, or a motion his class has been learned to hurt with;
      priority()    the target scorer's first bands over these (priority below): a wind-up within its class's
                    reach, a boss / dangerous one in reach, a grudge (one that hurt him this round) - each on his
                    level - the one at arm's length never left for a boss or a grudge;
      step_out()    a learned attack that landed through his shots (unstoppable) under way within lethal_keep_x x its
                    reach: step out of it, for at most lethal_backoff_max_s of one wind-up (then he fights it)."""

    def __init__(self, prof: TitleProfile, stats: dict | None = None, path=None):
        self.prof = prof
        self.stats = stats if stats is not None else {}
        self.tm = threat_memory.ThreatMemory(path if path is not None else prof.threat_file,
                                             default_reach_cm=prof.windup_r_cm, held_needs_flag=True)
        self._hp = None
        self._hit_at = -1e9
        self._bo = None
        for k in THREAT_COUNTERS:
            self.stats.setdefault(k, 0)

    def row(self, e) -> dict:
        pos = e.get("pos")
        return {"ptr": e.get("ptr", e.get("slot")), "class": self.prof.class_key(e), "motion": self.prof.motion_key(e),
                "pos": self.prof.pos_cm(pos) if pos else None, "hp": e.get("hp"), "hp_max": e.get("hp_max"), "raw": e}

    def new_round(self) -> None:
        self.tm.new_round()
        self._hp, self._bo = None, None

    def save(self) -> None:
        self.tm.save(force=True)

    def observe(self, now: float, player, enemies, prof: TitleProfile | None = None) -> dict | None:
        """One tick: the living enemies, then his health (a fall is a hit: attributed). Returns the hit's record."""
        if prof is not None:
            self.prof = prof
        p = player or {}
        pos = p.get("pos")
        if not pos:
            return None
        ppos = self.prof.pos_cm(pos)
        rows = [self.row(e) for e in enemies or () if isinstance(e, dict) and (e.get("hp") or 0) > 0 and e.get("pos")]
        att = self.prof.attacking
        self.tm.observe(now, rows, ppos, attacking=(lambda r: bool(att(r["raw"]))) if att is not None else None)
        hp, key = p.get("hp"), p.get("ptr")
        last, self._hp = self._hp, (key, hp)
        rec = None
        if last is not None and last[0] == key and type(hp) is int and type(last[1]) is int and hp < last[1]:
            if now - self._hit_at > self.prof.hurt_gap_s:
                rec = self.tm.hurt(now, ppos, last[1] - hp)
                self.stats.update(self.tm.stats)
                if rec is not None:
                    self.stats["tm_last_hit"] = {k: rec.get(k) for k in ("class", "motions", "dist_cm", "through")}
                    self.stats["threats"] = self.tm.summary()
            self._hit_at = now
        return rec

    # --- what the bot asks ---
    def learned(self, e) -> bool:
        return self.tm.lethal(self.row(e))

    def winding(self, e) -> bool:
        w = self.prof.windup
        return bool(w is not None and w(e)) or self.learned(e)

    def reach_cm(self, e) -> float:
        return self.tm.reach(self.prof.class_key(e), self.prof.windup_r_cm)

    def grudge(self, e) -> int:
        return self.tm.grudge(self.row(e))

    def unstoppable(self, e) -> bool:
        return self.tm.unstoppable(self.row(e))

    def _flat_dy(self, ppos, e):
        q = self.prof.pos_cm(e["pos"])
        return math.hypot(q[0] - ppos[0], q[2] - ppos[2]), abs(q[1] - ppos[1])

    def priority(self, player, enemies) -> tuple | None:
        """(enemy, kind, why) or None - kind "windup" / "grab" / "boss" / "dangerous" / "grudge": the target scorer's
        priority bands (d) over these enemies."""
        pos = (player or {}).get("pos")
        if not pos:
            return None
        got = priority(self.prof, candidates(self.prof, player, enemies, threats=self))
        if got is None:
            return None
        c, kind, why = got
        return c["e"], kind, why

    def step_out(self, player, enemies, now: float):
        """The nearest unstoppable learned attack under way within reach (see the class text), or None."""
        pos = (player or {}).get("pos")
        if not pos:
            return None
        ppos = self.prof.pos_cm(pos)
        hot = []
        for e in enemies or ():
            if not isinstance(e, dict) or (e.get("hp") or 0) <= 0 or not e.get("pos"):
                continue
            d, dy = self._flat_dy(ppos, e)
            if dy <= self.prof.level_dy_cm and self.learned(e) and self.unstoppable(e) \
                    and d <= self.reach_cm(e) * self.prof.lethal_keep_x:
                hot.append((d, e))
        if not hot:
            self._bo = None
            return None
        d, e = min(hot, key=lambda t: t[0])
        k = (e.get("ptr", e.get("slot")), self.prof.motion_key(e))
        if self._bo is None or self._bo[0] != k:
            self._bo = (k, now)
            self.stats["lethal_backoffs"] = self.stats.get("lethal_backoffs", 0) + 1
        if now - self._bo[1] > self.prof.lethal_backoff_max_s:
            return None                                      # cornered, or a long charge: he fights it
        return e


# --- (d) the target scorer ----------------------------------------------------------------------------------------------
# Bands, best first (the operator's order: survival, then the ones worth dispatching first, then the ones that already
# hurt him, then the cheapest):
#   0  WINDUP  a wind-up within its class's reach on his level (the title's own read, or a learned lethal motion);
#   1  TIERED  a boss / dangerous one (prof.tier) within priority_r on his level - a boss before a dangerous one at the
#              same distance (the distance x tier_w);
#   2  GRUDGE  one that hurt him this round within grudge_r on his level;
#   3  REST    the cheapest by distance x turn x level x line (cost), the current one kept within keep_x.
# Whichever of bands 1-2 wins, one on his level within grab_r (at arm's length: about to grab him) is never left for it.
WINDUP, TIERED, GRUDGE, REST = 0, 1, 2, 3


def candidates(prof: TitleProfile, player, enemies, facing=None, threats: Threats | None = None, clear=None) -> list:
    """The living enemies as the scorer sees them: [{"e", "key", "d", "err", "dy", "windup", "grudge", "reach",
    "tier", "clear"}] - d and dy in cm, err the bearing off `facing` (rad; his heading when None), tier the enemy's
    ("boss" / "dangerous" / "normal": prof.tier), clear(e) -> True / False / None (the line to him, when the title can
    tell)."""
    p = player or {}
    pos = p.get("pos")
    if not pos:
        return []
    ppos = prof.pos_cm(pos)
    face = facing if isinstance(facing, (int, float)) else (p.get("rot") or 0.0)
    out = []
    for e in enemies or ():
        if not isinstance(e, dict) or (e.get("hp") or 0) <= 0 or not e.get("pos"):
            continue
        q = prof.pos_cm(e["pos"])
        dx, dz = q[0] - ppos[0], q[2] - ppos[2]
        line = None
        if clear is not None:
            try:
                line = clear(e)
            except Exception:                                # noqa: BLE001 - a geometry error proves nothing
                line = None
        t = "normal"
        if prof.tier is not None:
            try:
                t = prof.tier(e) or "normal"
            except Exception:                                # noqa: BLE001 - an identity error: an ordinary one
                t = "normal"
        out.append({"e": e, "key": e.get("ptr", e.get("slot")), "d": math.hypot(dx, dz),
                    "err": wrap(heading(dx, dz) - face), "dy": q[1] - ppos[1],
                    "windup": threats.winding(e) if threats is not None else bool(prof.windup and prof.windup(e)),
                    "grudge": threats.grudge(e) if threats is not None else 0,
                    "reach": threats.reach_cm(e) if threats is not None else prof.windup_r_cm,
                    "tier": t if t in TIER_ORDER else "normal", "clear": line})
    return out


def cost(prof: TitleProfile, c: dict) -> float:
    """Near, in front, on his level and on a clear line is cheap."""
    turn = 1.0 + prof.turn_w * abs(c["err"]) / math.pi
    level = 1.0 + prof.level_w * min(abs(c["dy"]), prof.max_dy_cm) / max(prof.max_dy_cm, 1.0)
    line = prof.blocked_x if c.get("clear") is False else 1.0
    return c["d"] * turn * level * line


def band(prof: TitleProfile, c: dict) -> int:
    """The candidate's band (WINDUP / TIERED / GRUDGE / REST, above)."""
    level = abs(c["dy"]) <= prof.level_dy_cm
    if level and c["windup"] and c["d"] <= c["reach"]:
        return WINDUP
    if level and c.get("tier", "normal") != "normal" and c["d"] <= (prof.priority_r_cm or prof.engage_cm):
        return TIERED
    if level and c["grudge"] and c["d"] <= prof.grudge_r_cm:
        return GRUDGE
    return REST


def _order(prof: TitleProfile, b: int, c: dict) -> float:
    if b == TIERED:
        return c["d"] * float(prof.tier_w.get(c.get("tier"), 1.0))
    return c["d"] if b < REST else cost(prof, c)


def rank(prof: TitleProfile, cands: list) -> list:
    """[(band, order, c)] best first: the nearest of each priority band (a tiered one's distance x tier_w), the
    cheapest of the rest."""
    out = []
    for c in cands:
        b = band(prof, c)
        out.append((b, _order(prof, b, c), c))
    return sorted(out, key=lambda r: (r[0], r[1]))


def _grab(prof: TitleProfile, cands: list, best: dict):
    """The nearest other one on his level at arm's length (grab_r), or None."""
    near = [c for c in cands if c is not best and c["d"] <= prof.grab_r_cm and abs(c["dy"]) <= prof.level_dy_cm]
    return min(near, key=lambda c: c["d"]) if near else None


def _kind(b: int, c: dict) -> str:
    return {WINDUP: "windup", GRUDGE: "grudge", REST: "rest"}.get(b) or c.get("tier", "boss")


def priority(prof: TitleProfile, cands: list) -> tuple | None:
    """(candidate, kind, why) of the priority bands, or None (nothing pressing: the title's own choice stands). kind:
    "windup", "boss" / "dangerous", "grudge", or "grab" - the one at arm's length that a boss or a grudge must not
    cost him."""
    ranked = rank(prof, cands)
    if not ranked or ranked[0][0] >= REST:
        return None
    b, _k, best = ranked[0]
    if b in (TIERED, GRUDGE):
        g = _grab(prof, cands, best)
        if g is not None:
            return g, "grab", (f"one {g['d'] / 100:.1f} m off, about to grab him: before the {_kind(b, best)} "
                               f"{best['d'] / 100:.1f} m off")
    return best, _kind(b, best), _why(prof, b, best)


def pick(prof: TitleProfile, cands: list, current=None) -> tuple:
    """(candidate, why) - (None, "") with none: the priority bands first (priority), else the cheapest, the current
    target (its key) kept while it costs within keep_x of the best."""
    got = priority(prof, cands)
    if got is not None:
        return got[0], got[2]
    ranked = rank(prof, cands)
    if not ranked:
        return None, ""
    b, k, best = ranked[0]
    if current is not None:
        cur = next((r for r in ranked if r[2]["key"] == current), None)
        if cur is not None and cur[1] <= prof.keep_x * k:
            best = cur[2]
    return best, _why(prof, b, best)


def _why(prof: TitleProfile, b: int, c: dict) -> str:
    m = c["d"] / 100.0
    if b == WINDUP:
        return f"winding up {m:.1f} m off (inside his reach {c['reach'] / 100:.1f} m): stopped first"
    if b == TIERED:
        return f"a {c.get('tier')} foe {m:.1f} m off, in reach on his level: dispatched first"
    if b == GRUDGE:
        return f"he hurt him this round ({c['grudge']} hits), {m:.1f} m off: resolved next"
    return f"the cheapest by distance, turn, level and line: {m:.1f} m"


# --- (e) never idle -----------------------------------------------------------------------------------------------------
class IdleGuard:
    """Never idle with a threat in range (gbox.mercs.core.doctrine "engage": on sight, shoot, always shoot; the
    operator 2026-11-03: "the bot is raising their weapon and NOT firing"). Every tick, with a threat in range:
      the gun up idle_aim_s without a shot -> "move" (he rounds the target or closes in: the line he holds fires no
                                               shot - a gate, a wall, an aim that does not converge);
      neither attacking nor moving idle_still_s -> "engage" (the gun up at him, or the turn to him).
    One verdict per spell; the clocks start again from it, and after any gap between ticks longer than GAP_S (a page,
    a loading screen: no decision was his). Stats: idle_aim_breaks, idle_still_breaks."""

    GAP_S = 0.5

    def __init__(self, stats: dict | None = None):
        self.stats = stats if stats is not None else {}
        self.aim_at = None
        self.still_at = None
        self.t = None
        for k in ("idle_aim_breaks", "idle_still_breaks"):
            self.stats.setdefault(k, 0)

    def tick(self, prof: TitleProfile, now: float, threat: bool, aiming: bool, fired: bool, moving: bool) -> str | None:
        gap, self.t = (self.t is not None and now - self.t > self.GAP_S), now
        if gap:
            self.aim_at = self.still_at = None
        if not threat:
            self.aim_at = self.still_at = None
            return None
        if fired:
            self.aim_at = now if aiming else None            # the gun's clock from this shot
            self.still_at = None
            return None
        if aiming:
            self.still_at = None
            self.aim_at = now if self.aim_at is None else self.aim_at
            if now - self.aim_at >= prof.idle_aim_s:
                self.aim_at = now
                self.stats["idle_aim_breaks"] = self.stats.get("idle_aim_breaks", 0) + 1
                return "move"
            return None
        self.aim_at = None
        if moving:
            self.still_at = None
            return None
        self.still_at = now if self.still_at is None else self.still_at
        if now - self.still_at >= prof.idle_still_s:
            self.still_at = now
            self.stats["idle_still_breaks"] = self.stats.get("idle_still_breaks", 0) + 1
            return "engage"
        return None
