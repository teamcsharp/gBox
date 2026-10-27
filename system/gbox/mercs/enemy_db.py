"""The enemy knowledge database: what the Mercenaries bots learn about each kind of enemy from RAM facts and outcomes,
and the dispatch plan the combat brain asks for (operator 2026-10-27: "i want a universal mercenaries engine"; "the goal
is that the aimbot learns enemy activity and builds a database fof how to dispatch them and the aimbot improves based on
the ram byte information to keep the bot aware of enemies and where and how to aim to dispatch them.").

    from gbox.mercs import enemy_db as K
    cls = K.class_key(enemy)                                  # "uEm10", "em16.0b.hp1400", "hp800" ...
    plan = K.dispatch_plan(title, cls, state, dist_m, weapon) # where to aim, range, fire mode, danger, shots to kill
    K.observe(title, [{"id": ptr, "cls": cls, "state": s, "dist_m": d}, ...])   # 5-20 Hz: exposure and state onsets
    K.record_shot(title, cls, state, dist_m, weapon, (up_m, lateral_m), "hit", hp_delta=-250, enemy_id=ptr)
    K.record_damage(title, cls, state, dist_m, "grab", 120, enemy_id=ptr)

Units are metres and seconds. A title is the driver's map id (BLUS30491, 010018100CD46000, 01002A000CD48000, G4BE08).
Every call is cheap on the bot's thread and never raises: record_* and observe only queue the fact; a background thread
(single flight, started on demand, never a loop that outlives its work) folds the queue into the learned cells and
writes SQLite. Nothing here reads or writes the game.

What is learned, per title and enemy class (and state, distance band, weapon where it matters):
  * aim: where hits land on him - per zone (head / chest / legs) the hit rate and the damage per hit, so the zone with
    the most damage per shot; inside it the centre of the hits as an offset from his reported position (up = height
    above it, lateral = across the line of fire, + to the shooter's right);
  * range: the distance bands whose shots do the most (damage per shot, less what the learned danger there costs);
  * fire mode: tap / hold / burst by damage per second (hit rate x damage per hit / the interval between shots);
  * shots to kill: shots fired at one enemy (by id) until the shot that killed him;
  * danger: damage events per second of exposure (observe) in a class / state / band -> the chance he hurts the player
    within DANGER_WINDOW_S; wind-up: of the onsets of a state, the share followed by damage within WINDUP_WINDOW_S,
    with the lead time (the attack wind-ups, grabs and throws come out of the RAM state bytes this way);
  * attack: what hit us (the brain's word) per class / state.

Every plan field is a Learned(value, confidence, samples, source): source "default" is the title's current constants
(DEFAULTS, copied from the drivers with their names) - with no data dispatch_plan returns exactly those. A field falls
back level by level: the class in this title, his family in this title, his family in every title (CLASS_MAP: an
explicit, evidence-backed table of equivalent classes - generic humanoids, chainsaw types ... - that drivers extend with
extend_classes), every class of this title, then the default. Another title's evidence is shared only where it carries
over: where hits land on such a body (the offset inside the title's own zone) and the danger by distance; the zone, the
range, the fire mode, shots to kill and the hit rate depend on the title's weapons and come from its own shots. A zone
replaces the default only when both were measured at that level and it does SWITCH_ZONE more damage per shot (or kills
more: hit rate alone favours easy zones that don't kill). Numbers age out: every learned weight halves each HALF_LIFE_S
without new evidence and a cell's effective count is capped (CAPS), so newer rounds outweigh old ones.

Storage: <gbox-data>/mercs/knowledge/<title>/enemies.sqlite (lessons.ROOT's data dir): the raw samples (bounded:
MAX_SAMPLES newest, none older than MAX_AGE_S), daily exposure buckets, and the learned cells (JSON per key). rebuild()
replays the samples into fresh cells (gbox.mercs.enemy_db_seed bootstraps them from the bots' older evidence). The live
state sits in _STATE, kept across a bot hot reload (RELOAD_KEEP); a service restart reloads the cells from SQLite.
inspect() is the read-only view behind GET /api/mercs/enemy-knowledge; round_end() puts the round's numbers in stats
(and so in the round report's METRICS that go to sparkDeux).
"""
from __future__ import annotations

import atexit
import fnmatch
import json
import math
import sqlite3
import threading
import time
import uuid
from collections import deque
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

SCHEMA = 1
DB_NAME = "enemies.sqlite"
ANY = "*"
BANDS = ((2.0, "0-2"), (5.0, "2-5"), (10.0, "5-10"), (20.0, "10-20"), (math.inf, "20+"))   # metres (ballistics.BANDS)
BAND_NAMES = tuple(name for _, name in BANDS)
BAND_EDGES = {"0-2": (0.0, 2.0), "2-5": (2.0, 5.0), "5-10": (5.0, 10.0), "10-20": (10.0, 20.0), "20+": (20.0, 40.0)}
ZONES = ("head", "chest", "legs")
ZONE_NAMES = {"head": "head", "headshot": "head", "chest": "chest", "body": "chest", "torso": "chest",
              "legs": "legs", "leg": "legs", "thigh": "legs", "knee": "legs"}
FIRE_MODES = ("tap", "hold", "burst")
DANGER_WINDOW_S = 1.0          # danger: the chance he hurts the player within this
WINDUP_WINDOW_S = 2.0          # damage this soon after a state's onset makes the state its wind-up
DANGER_MAX_M = 15.0            # observe() counts exposure and onsets for enemies this near
OBS_DT_MAX = 0.5               # one observe() adds at most this much exposure (a stalled caller)
FORGET_S = 10.0                # an enemy unseen / unshot this long is forgotten (state history, shots on him)
HIST_MAX = 8                   # state onsets kept per enemy
HALF_LIFE_S = 21 * 86400.0     # a learned weight halves every three weeks without new evidence
CAPS = {"n": 400.0, "e": 7200.0, "on": 600.0}   # a cell's effective counts never exceed these (joint scaling)
MAX_SAMPLES = 100_000          # raw samples kept per title (the newest)
MAX_AGE_S = 90 * 86400.0       # raw samples and exposure days older than this are dropped
MAX_CELLS = 60_000             # learned cells kept per title (the least recently updated go first)
PRUNE_EVERY_S = 600.0
FLUSH_S, FLUSH_N = 2.0, 64     # the learner runs when this long has passed with facts queued, or this many are queued
JOB_MAX = 20_000               # facts folded per pass
PENDING_MAX = 50_000           # facts queued beyond this (the learner stuck): the oldest are dropped and counted
CACHE_MAX = 4096
SUMMARY_MAX = 600              # characters of stats' enemy_db_summary (the round report keeps it)
# the least evidence a level needs before it answers, and the evidence at which its confidence reaches one half
MIN = {"aim": 8.0, "zone": 6.0, "offset": 5.0, "band": 8.0, "mode": 10.0, "interval": 5.0, "kills": 5.0,
       "exposure_s": 20.0, "onsets": 10.0, "leads": 4.0, "attack": 3.0, "hit": 8.0}
HALF = {"aim": 15.0, "range": 40.0, "mode": 30.0, "kills": 10.0, "exposure_s": 60.0, "onsets": 30.0, "leads": 10.0,
        "attack": 10.0, "hit": 30.0}
K_UP, K_LAT = 5.0, 10.0        # the hits' centre is pulled toward the zone's default by this many hits' worth
SWITCH_ZONE, SWITCH_MODE = 1.10, 1.15   # a learned zone / fire mode replaces the default only when this much better
RANGE_KEEP = 0.8               # bands scoring this share of the best join the preferred range

# --- the title's current constants (no data: the plan is exactly these) --------------------------------------------------
DEFAULTS = {
    # RE5 PS3: brain/body.py (re5_combat) HEAD_H 160 / CHEST_H 110 / THIGH_H 72 cm, DEFAULT_ZONE "body" (the chest);
    # re5_ps3 TOO_CLOSE 110 cm and ENGAGE_R 3000 cm; re5_combat.HOLD_FIRE_IDS held, the rest tapped; the immediate
    # radius re5_ps3.BOSS_YIELD_R 350 cm (FIGHT_R the same); a boss (re5_combat.BOSS_HP 2500) kept off BOSS_KEEP_R 450 cm
    "BLUS30491": {"zones": {"head": 1.60, "chest": 1.10, "legs": 0.72}, "zone": "chest", "near_m": 1.1, "far_m": 30.0,
                  "fire_mode": "tap", "hold_weapons": (0x03, 0x09, 0x13, 0x15, 0x1D), "threat_m": 3.5,
                  "boss_hp": 2500, "boss_threat_m": 4.5},
    # RE5 Switch: re5_switch HEAD_H / CHEST_H 110 / THIGH (the PS3's), TOO_CLOSE 150 cm, ENGAGE_R 2200 cm, rain fire
    # (ZR held while a Majini is in front), THREAT_R 250 cm ("he grabs next")
    "010018100CD46000": {"zones": {"head": 1.60, "chest": 1.10, "legs": 0.72}, "zone": "chest", "near_m": 1.5,
                         "far_m": 22.0, "fire_mode": "hold", "threat_m": 2.5},
    # RE6 Switch: re6_switch HEAD_H 160 / CHEST_H 115 / KNEE_H + 30 cm, MELEE_R 140 cm (the kick), ENGAGE_R 1800 cm,
    # AUTO_IDS held (Chris's assault rifle) and the rest tapped, THREAT_R 250 cm
    "01002A000CD48000": {"zones": {"head": 1.60, "chest": 1.15, "legs": 0.75}, "zone": "chest", "near_m": 1.4,
                         "far_m": 18.0, "fire_mode": "tap", "hold_weapons": (0x0F,), "threat_m": 2.5},
    # RE4 GameCube (world units mm): re4_merc_bot HEAD_AIM_H 1520 (aims at heads), CHEST_H 1150, BODY_LO 700,
    # SHOOT_RANGE 2400, RAPID_FIRE (A held) with the shotguns tapped (TRIGGER_PRIOR, SHOTGUNS 0x2C / 0x2D / 0x94),
    # THREAT_R 1600 ("about to strike"); re4_threats: the attack kinds' reach and the bosses (BOSS_HP 3000, CHAINSAW_KEEP)
    "G4BE08": {"zones": {"head": 1.52, "chest": 1.15, "legs": 0.70}, "zone": "head", "near_m": 0.0, "far_m": 2.4,
               "fire_mode": "hold", "tap_weapons": (0x2C, 0x2D, 0x94), "threat_m": 1.6,
               "boss_hp": 3000, "boss_threat_m": 2.0, "family_threat_m": {"chainsaw": 2.0}},
}
GENERIC = {"zones": {"head": 1.60, "chest": 1.10, "legs": 0.72}, "zone": "chest", "near_m": 1.0, "far_m": 20.0,
           "fire_mode": "tap", "threat_m": 2.5}
RE4_ATTACKS = {"swing": (1.2, 0.7), "grab": (1.2, 0.7), "rush": (2.0, 1.0), "throw": (9.0, 0.9),
               "dynamite": (9.0, 1.5), "chainsaw": (1.5, 0.4)}   # re4_threats REACH (m) and the soonest lands (s);
                                                                # read live from re4_threats when it imports
OVERRIDES = {"up_m", "lateral_m", "zone", "near_m", "far_m", "fire_mode", "danger", "lead_s", "shots_to_kill"}

# --- equivalent classes across titles: explicit rows, each with its evidence. Drivers add theirs with extend_classes.
# A class key matches a row exactly or as an fnmatch pattern; the first matching row wins (specific rows first).
# "basis hp_max" rows key a class the driver can't name yet by its full health, from the measurements cited.
CLASS_MAP = [
    ("G4BE08", "em16.*.hp6500", "chainsaw", "re4_threats: the Village ESL (omake01.esl) has six em 0x16 entries at hp 6500, "
     "types 0xb / 0xc - Dr. Salvador, the chainsaw man (one hit kills)"),
    ("G4BE08", "em20.16.hp3500", "chainsaw", "re4_threats: Waterworld (omake02.esl, a chainsaw stage) type 0x16 at 3500 - "
     "the Bella sisters"),
    ("G4BE08", "em20.16.hp5000", "chainsaw", "re4_threats: Waterworld type 0x16 at 5000 - Super Salvador"),
    ("G4BE08", "em16.*", "humanoid", "re4_threats: every other Village Ganado is em 0x16 at 1200-1800 (omake01.esl)"),
    ("G4BE08", "em20.*", "humanoid", "re4_threats: Waterworld soldiers are em 0x20, types 0xe-0x16, at 400-1000 (omake02.esl)"),
    ("BLUS30491", "uEm10", "humanoid", "re5_ps3: sEnemy holds uEm10 / uEm11 Majini"),
    ("BLUS30491", "uEm11", "humanoid", "re5_ps3: sEnemy holds uEm10 / uEm11 Majini"),
    ("BLUS30491", "uEm32", "crawler", "re5_aim_geometry: uEm32 is the Licker, a low model (no humanoid chest)"),
    ("BLUS30491", "hp800", "humanoid", "basis hp_max: re5_ps3 sEnemy, Majini maximum health 800 / 700"),
    ("BLUS30491", "hp700", "humanoid", "basis hp_max: re5_ps3 sEnemy, Majini maximum health 800 / 700"),
    ("BLUS30491", "hp1", "critter", "basis hp_max: re5_ps3, crows are enemies with 1 health"),
    ("010018100CD46000", "uEm10", "humanoid", "docs/research/re5-switch-ram.md: uEm10 / uEm11 Majini"),
    ("010018100CD46000", "uEm11", "humanoid", "docs/research/re5-switch-ram.md: uEm10 / uEm11 Majini"),
    ("010018100CD46000", "uEm62", "critter", "docs/research/re5-switch-ram.md: uEm62 has 1 health"),
    ("010018100CD46000", "hp800", "humanoid", "basis hp_max: re5-switch-ram.md, Majini 800 or 700"),
    ("010018100CD46000", "hp700", "humanoid", "basis hp_max: re5-switch-ram.md, Majini 800 or 700"),
    ("010018100CD46000", "hp1", "critter", "basis hp_max: re5-switch-ram.md, uEm62 has 1 health (re5_ps3: crows)"),
    ("01002A000CD48000", "uEm5200", "humanoid", "docs/research/re6-switch-ram.md: uEm5200 / uEm5210 zombies (Urban Chaos); "
     "re6_switch: RE6's are human-sized like RE5's Majini"),
    ("01002A000CD48000", "uEm5210", "humanoid", "docs/research/re6-switch-ram.md: uEm5200 / uEm5210 zombies (Urban Chaos)"),
    ("01002A000CD48000", "hp700", "humanoid", "basis hp_max: re6-switch-ram.md, the Urban Chaos zombies have 700 or 400 "
     "(other stages unverified)"),
    ("01002A000CD48000", "hp400", "humanoid", "basis hp_max: re6-switch-ram.md, the Urban Chaos zombies have 700 or 400 "
     "(other stages unverified)"),
]
FAMILIES = ("humanoid", "chainsaw", "heavy", "crawler", "critter")   # documented names; heavy has no verified rows yet


# --- the plan --------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Learned:
    """One plan field: its value, how sure (0..1), the effective samples behind it, and which level answered."""
    value: object
    confidence: float = 0.0
    samples: int = 0
    source: str = "default"
    detail: dict | None = None

    def to_dict(self) -> dict:
        out = {"value": _plain(self.value), "confidence": round(float(self.confidence), 3),
               "samples": int(self.samples), "source": self.source}
        if self.detail:
            out["detail"] = _plain(self.detail)
        return out


@dataclass(frozen=True)
class Aim:
    """Where to aim on him: up_m above his reported position (his feet), lateral_m across the line of fire (+ the
    shooter's right), in the zone named."""
    up_m: float
    lateral_m: float
    zone: str

    def world_offset(self, shooter_pos, enemy_pos, units_per_m: float = 100.0) -> tuple:
        """(dx, dy, dz) in the title's world units from his position to the aim point (y up; a heading's convention is
        atan2(dx, dz), a larger heading turning left, so the shooter's right is (-fz, fx))."""
        up = self.up_m * units_per_m
        lat = (self.lateral_m or 0.0) * units_per_m
        try:
            fx, fz = enemy_pos[0] - shooter_pos[0], enemy_pos[2] - shooter_pos[2]
            length = math.hypot(fx, fz)
        except (TypeError, IndexError):
            return (0.0, up, 0.0)
        if not lat or length < 1e-6:
            return (0.0, up, 0.0)
        fx, fz = fx / length, fz / length
        return (-fz * lat, up, fx * lat)


@dataclass(frozen=True)
class Plan:
    title: str
    enemy_class: str
    state: str | None
    band: str | None
    family: str | None
    aim: Learned            # Aim
    range: Learned          # (near_m, far_m)
    fire_mode: Learned      # "tap" | "hold" | "burst"
    danger: Learned         # 0..1 within DANGER_WINDOW_S
    windup: Learned         # 0..1 or None: an onset of this state followed by damage within WINDUP_WINDOW_S
    lead_s: Learned         # seconds from this state's onset to the hit, or None
    attack: Learned         # the commonest what_hit_us, or None
    shots_to_kill: Learned  # float or None
    hit_rate: Learned       # 0..1 or None at this band (and weapon)

    def to_dict(self) -> dict:
        head = {"title": self.title, "enemy_class": self.enemy_class, "state": self.state, "band": self.band,
                "family": self.family}
        return head | {k: getattr(self, k).to_dict() for k in ("aim", "range", "fire_mode", "danger", "windup",
                                                                 "lead_s", "attack", "shots_to_kill", "hit_rate")}


def _plain(v):
    if isinstance(v, Aim):
        return {"up_m": round(v.up_m, 3), "lateral_m": round(v.lateral_m, 3), "zone": v.zone}
    if isinstance(v, float):
        return round(v, 4) if math.isfinite(v) else None
    if isinstance(v, (tuple, list)):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    return v


# --- the live state (kept across a bot hot reload) ---------------------------------------------------------------------
_STATE: dict = {}
RELOAD_KEEP = ("_STATE",)                 # gbox.hot_reload: the learned cells, the queue and the learner survive a reload


def _state() -> dict:
    s = _STATE
    if s.get("v") != 1:
        s.setdefault("lock", threading.RLock())
        for key, make in (("models", dict), ("titles", dict), ("pending", deque), ("px", dict), ("pon", dict),
                          ("hist", dict), ("seen", dict), ("obs_t", dict), ("ctx", lambda: {"kills": {}, "last": {}}),
                          ("round", dict), ("cache", dict), ("classes", list), ("states", list), ("fam_cache", dict),
                          ("need_load", set), ("errors", lambda: deque(maxlen=10))):
            s.setdefault(key, make())
        for key, value in (("root", None), ("busy", False), ("last_job", 0.0), ("version", 0), ("dropped", 0),
                           ("discovered", False), ("atexit", False), ("gc_at", 0.0)):
            s.setdefault(key, value)
        s["v"] = 1
    if not s["atexit"]:
        s["atexit"] = True
        atexit.register(_at_exit)
    if s.get("plan_cls") is not Plan:                   # a hot reload redefined the plan: no cached plan of the old one
        s["cache"].clear()
        s["fam_cache"].clear()
        s["plan_cls"] = Plan
    return s


def root() -> Path:
    """Where the database lives: configure()'s directory, else <lessons data dir>/knowledge (gbox-data/mercs/knowledge)."""
    s = _state()
    if s["root"] is not None:
        return Path(s["root"])
    from . import lessons
    return Path(lessons.ROOT).parent / "knowledge"


def configure(path) -> Path:
    """Put the database under path (a deployment's data dir, tests); None: back to the default. Pending facts are
    written first; the in-memory cells are dropped and load again from the new place."""
    flush(wait=True)
    s = _state()
    with s["lock"]:
        s["root"] = Path(path) if path is not None else None
        _forget(s)
    return root()


def reset() -> None:
    """Drop the in-memory state (tests). Files stay; unwritten facts are lost (flush first to keep them)."""
    s = _state()
    with s["lock"]:
        _forget(s)
        s["pending"].clear()
        s["round"].clear()
        s["classes"].clear()
        s["states"].clear()
        s["errors"].clear()
        s["dropped"] = 0


def _forget(s) -> None:
    for key in ("models", "titles", "px", "pon", "hist", "seen", "obs_t", "cache", "fam_cache"):
        s[key].clear()
    s["ctx"] = {"kills": {}, "last": {}}
    s["need_load"].clear()
    s["discovered"] = False
    s["version"] += 1


# --- keys -------------------------------------------------------------------------------------------------------------
def _safe(text, limit: int) -> str:
    return str(text).strip().replace("|", "/")[:limit]


def _title(title) -> str | None:
    if title is None:
        return None
    t = "".join(c for c in str(title) if c.isalnum() or c in "-_")[:40]
    return t or None


def _cls(enemy_class) -> str:
    if enemy_class is None or (isinstance(enemy_class, str) and not enemy_class.strip()):
        return "unknown"
    if isinstance(enemy_class, bool):
        return str(int(enemy_class))
    if isinstance(enemy_class, int):
        return f"{enemy_class:#x}"
    c = _safe(enemy_class, 60)
    return "_" + c if c in (ANY, "?") or c.startswith(("@", "~")) else c


def class_key(enemy, title=None) -> str:
    """The class key of a snapshot enemy, from what its driver reads: an explicit class ("class_id", "cls", "class": a
    class name from the vtable's DTI such as "uEm10", or the adapter's own id) > RE4's EmMgr id / type bytes with the
    full health ("em16.0b.hp1400": one em id holds ordinary Ganados and the chainsaw man, told apart by their ESL health)
    > the verified native model kind ("uEm32") > the full health alone ("hp800") > "unknown"."""
    try:
        if not isinstance(enemy, dict):
            return "unknown"
        for key in ("class_id", "cls", "class"):
            v = enemy.get(key)
            if v is not None and v != "":
                return _cls(v)
        eid, etype, hp_max = enemy.get("id"), enemy.get("type"), enemy.get("hp_max")
        if type(eid) is int and type(etype) is int and 0 <= eid < 0x100 and 0 <= etype < 0x100:
            return f"em{eid:02x}.{etype:02x}" + (f".hp{hp_max}" if type(hp_max) is int and hp_max > 0 else "")
        native = enemy.get("native_aim")
        if isinstance(native, dict) and native.get("kind") not in (None, "", "unknown"):
            return _cls(native["kind"])
        if isinstance(hp_max, (int, float)) and not isinstance(hp_max, bool) and math.isfinite(hp_max) and hp_max > 0:
            return f"hp{int(hp_max)}"
    except Exception:                                   # noqa: BLE001 - a key is never worth an error
        pass
    return "unknown"


def state_key(state) -> str | None:
    """A RAM state as a key: an int -> "0x1a", bytes like RE4's routine (r0, r1) -> "01:26", text kept (40 chars)."""
    if state is None:
        return None
    if isinstance(state, bool):
        return str(int(state))
    if isinstance(state, int):
        return f"{state:#x}" if state >= 0 else str(state)
    if isinstance(state, float):
        return f"{state:g}" if math.isfinite(state) else None
    if isinstance(state, (bytes, bytearray)):
        state = tuple(state)
    if isinstance(state, (tuple, list)):
        parts = [f"{v:02x}" if type(v) is int and 0 <= v < 0x100 else _safe(v, 12) for v in state[:6]]
        return ":".join(parts)[:40] or None
    s = _safe(state, 40)
    if not s:
        return None
    return "_" + s if s == ANY or s.startswith(("~", "@")) else s


def _kind_key(kind) -> str | None:
    return "~" + _safe(kind, 30) if kind else None


def _weapon(weapon) -> str:
    if weapon is None or weapon == "":
        return ANY
    if isinstance(weapon, bool):
        return str(int(weapon))
    if isinstance(weapon, int):
        return f"{weapon:#x}"
    w = _safe(weapon, 40)
    return w if w and w != ANY else ANY


def _weapon_int(weapon) -> int | None:
    if isinstance(weapon, int) and not isinstance(weapon, bool):
        return weapon
    if isinstance(weapon, str):
        try:
            return int(weapon.strip(), 0)
        except ValueError:
            return None
    return None


def _num(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _dist(distance) -> float | None:
    d = _num(distance)
    return d if d is not None and 0.0 <= d < 400.0 else None


def band(distance) -> str | None:
    """The distance band of a ground distance in metres ("0-2" ... "20+"), None when unknown."""
    d = _dist(distance)
    if d is None:
        return None
    return next(name for edge, name in BANDS if d < edge)


def _k(*parts) -> str:
    return "|".join(parts)


def _clock(t) -> float:
    f = _num(t)
    return f if f is not None else time.time()


def _wall(t) -> float:
    f = _num(t)
    return f if f is not None and 1e9 < f < 1e10 else time.time()


def _zone(zone) -> str | None:
    return ZONE_NAMES.get(str(zone).strip().lower()) if zone else None


def _zone_of(title, up) -> str | None:
    if up is None:
        return None
    z = (DEFAULTS.get(title) or GENERIC)["zones"]
    if up >= (z["head"] + z["chest"]) / 2:
        return "head"
    if up < (z["chest"] + z["legs"]) / 2:
        return "legs"
    return "chest"


def _offset(aim_point, enemy_pos=None, shooter_pos=None, units_per_m=None) -> tuple:
    """(up_m, lateral_m) of where the shot went, from (up_m, lateral_m), {"up_m", "lateral_m"} or a world point with
    the enemy's and the shooter's positions and the title's units per metre."""
    if aim_point is None:
        return None, None
    if isinstance(aim_point, dict):
        aim_point = (aim_point.get("up_m"), aim_point.get("lateral_m"))
    if not isinstance(aim_point, (tuple, list)):
        return None, None
    if len(aim_point) == 2:
        up, lat = _num(aim_point[0]), _num(aim_point[1])
        up = up if up is not None and -5.0 <= up <= 10.0 else None
        lat = lat if lat is not None and abs(lat) <= 10.0 and up is not None else None
        return up, lat
    upm = _num(units_per_m)
    if len(aim_point) != 3 or not upm or upm <= 0 or not isinstance(enemy_pos, (tuple, list)) or len(enemy_pos) != 3:
        return None, None
    a, e = [_num(v) for v in aim_point], [_num(v) for v in enemy_pos]
    if None in a or None in e:
        return None, None
    up = (a[1] - e[1]) / upm
    if not -5.0 <= up <= 10.0:
        return None, None
    lat = None
    if isinstance(shooter_pos, (tuple, list)) and len(shooter_pos) == 3:
        sp = [_num(v) for v in shooter_pos]
        if None not in sp:
            fx, fz = e[0] - sp[0], e[2] - sp[2]
            length = math.hypot(fx, fz)
            if length > 1e-6:
                fx, fz = fx / length, fz / length
                lat = ((a[0] - e[0]) * -fz + (a[2] - e[2]) * fx) / upm
                lat = lat if abs(lat) <= 10.0 else None
    return up, lat


def _outcome(outcome) -> str | None:
    o = str(outcome or "").strip().lower()
    if o in ("hit", "kill", "miss"):
        return o
    if o in ("headshot", "legshot") or o.startswith("hit:") or o.startswith("hit "):
        return "hit"
    if o.startswith("miss"):
        return "miss"
    if o in ("killed", "dead", "dispatched"):
        return "kill"
    return None


def _eid(enemy_id) -> str | None:
    if enemy_id is None or isinstance(enemy_id, bool):
        return None
    return _safe(enemy_id, 40) or None


# --- the class map and the state kinds --------------------------------------------------------------------------------
def extend_classes(title, mapping: dict, evidence: str = "") -> int:
    """Add rows to the class map for a title ({class key or pattern: family}); a driver's rows come before the built-in
    ones and replace its earlier rows for the same key. Returns the rows taken."""
    s = _state()
    ti = _title(title)
    if not ti or not isinstance(mapping, dict):
        return 0
    n = 0
    with s["lock"]:
        for pattern, fam in mapping.items():
            if not pattern or not fam:
                continue
            pattern, fam = _safe(pattern, 60), _safe(fam, 30)
            s["classes"][:] = [r for r in s["classes"] if (r[0], r[1]) != (ti, pattern)]
            s["classes"].insert(0, (ti, pattern, fam, _safe(evidence, 300)))
            n += 1
        s["fam_cache"].clear()
        s["version"] += 1
    return n


def extend_states(title, mapping: dict, evidence: str = "") -> int:
    """Name what a title's raw states are ({state key or pattern: attack kind such as "grab"}): learning then also
    pools each kind across the raw states that share it, and the defaults know its kind."""
    s = _state()
    ti = _title(title)
    if not ti or not isinstance(mapping, dict):
        return 0
    n = 0
    with s["lock"]:
        for pattern, kind in mapping.items():
            if not pattern or not kind:
                continue
            pattern, kind = _safe(pattern, 40), _safe(kind, 30)
            s["states"][:] = [r for r in s["states"] if (r[0], r[1]) != (ti, pattern)]
            s["states"].insert(0, (ti, pattern, kind, _safe(evidence, 300)))
            n += 1
        s["version"] += 1
    return n


def family(title, cls) -> str | None:
    """The cross-title family of a class (CLASS_MAP and the drivers' rows), None when no row says."""
    if not cls or cls in (ANY, "unknown", "?") or cls.startswith("@"):
        return None
    s = _state()
    key = (title, cls)
    hit = s["fam_cache"].get(key, False)
    if hit is not False:
        return hit
    found = None
    for t, pattern, fam, _ in [*s["classes"], *CLASS_MAP]:
        if t in (title, ANY) and (pattern == cls or fnmatch.fnmatchcase(cls, pattern)):
            found = fam
            break
    if len(s["fam_cache"]) > CACHE_MAX:
        s["fam_cache"].clear()
    s["fam_cache"][key] = found
    return found


def class_rows(title=None) -> list:
    """The class map's rows (the drivers' first), for humans: [{title, match, family, evidence}]."""
    s = _state()
    return [{"title": t, "match": p, "family": f, "evidence": e} for t, p, f, e in [*s["classes"], *CLASS_MAP]
            if title is None or t in (title, ANY)]


_RE4: dict = {}


def _re4_tables():
    """re4_threats' attack table (r_no_1 -> kind, reach, lands) and holds, read once; {} when it does not import."""
    if "attacks" not in _RE4:
        try:
            from .. import re4_threats as T
            _RE4.update(attacks={k: (v[0], v[1] / 1000.0, v[2]) for k, v in T.ATTACKS.items()},
                        holds=frozenset(T.HOLDS), act=T.R_ACT,
                        reach={k: v / 1000.0 for k, v in T.REACH.items()})
        except Exception:                               # noqa: BLE001 - a tree without it: the static copy
            _RE4.update(attacks={}, holds=frozenset(), act=1, reach={k: v[0] for k, v in RE4_ATTACKS.items()})
    return _RE4


def _re4_state(st):
    try:
        r0, r1 = (int(x, 16) for x in st.split(":")[:2])
    except (ValueError, AttributeError):
        return None, None
    return r0, r1


def state_kind(title, st) -> str | None:
    """The attack kind a raw state stands for (the drivers' rows; RE4: its routine's r_no_1 by re4_threats.ATTACKS and
    HOLDS), None when nothing says."""
    if not st:
        return None
    if st.startswith("~"):
        return st[1:]
    s = _state()
    for t, pattern, kind, _ in s["states"]:
        if t == title and (pattern == st or fnmatch.fnmatchcase(st, pattern)):
            return kind
    if title == "G4BE08":
        r0, r1 = _re4_state(st)
        tables = _re4_tables()
        if r0 is not None and r0 == tables["act"]:
            if r1 in tables["attacks"]:
                return tables["attacks"][r1][0]
            if r1 in tables["holds"]:
                return "hold"
    return None


# --- defaults ---------------------------------------------------------------------------------------------------------
def _defaults(title, weapon, st, kind, dist, hp_max, fam, overrides) -> dict:
    base = DEFAULTS.get(title) or GENERIC
    zones = dict(base["zones"])
    zone = base["zone"]
    fire = base["fire_mode"]
    w = _weapon_int(weapon)
    if w is not None:
        if w in base.get("hold_weapons", ()):
            fire = "hold"
        if w in base.get("tap_weapons", ()):
            fire = "tap"
    danger, rule = _default_danger(title, base, dist, kind, fam, hp_max)
    lead = None
    if title == "G4BE08":
        tables = _re4_tables()
        r0, r1 = _re4_state(st) if st and not st.startswith("~") else (None, None)
        if r0 == tables["act"] and r1 in tables["attacks"]:
            lead = tables["attacks"][r1][2]
        elif kind in RE4_ATTACKS:
            lead = RE4_ATTACKS[kind][1]
    d = {"zones": zones, "zone": zone, "up_m": zones[zone], "lateral_m": 0.0, "near_m": base["near_m"],
         "far_m": base["far_m"], "fire_mode": fire, "danger": danger, "danger_rule": rule, "lead_s": lead,
         "shots_to_kill": None}
    if isinstance(overrides, dict):
        zone_v = _zone(overrides.get("zone"))
        if zone_v:                                      # the zone first: an up_m given with it is that zone's height
            d["zone"], d["up_m"] = zone_v, zones.get(zone_v, d["up_m"])
        fire_v = overrides.get("fire_mode")
        if fire_v in FIRE_MODES:
            d["fire_mode"] = fire_v
        for key, v in overrides.items():
            if key not in OVERRIDES or key in ("zone", "fire_mode"):
                continue
            if key in ("lead_s", "shots_to_kill") and v is None:
                d[key] = None
                continue
            v = _num(v)
            if v is None:
                continue
            if key == "danger":
                v = max(0.0, min(1.0, v))
            d[key] = v
            if key == "up_m":
                zones[d["zone"]] = v
    return d


def _default_danger(title, base, dist, kind, fam, hp_max) -> tuple:
    if kind == "hold":
        return 1.0, "holding the player"
    if dist is None:
        return 0.0, "distance unknown"
    r, why = base["threat_m"], f"threat radius {base['threat_m']:g} m"
    fr = (base.get("family_threat_m") or {}).get(fam)
    if fr is not None and fr > r:
        r, why = fr, f"{fam} threat radius {fr:g} m"
    hp = _num(hp_max)
    if hp is not None and base.get("boss_hp") and hp >= base["boss_hp"] and base.get("boss_threat_m", 0) > r:
        r, why = base["boss_threat_m"], f"boss threat radius {base['boss_threat_m']:g} m"
    if title == "G4BE08" and kind:
        reach = _re4_tables()["reach"].get(kind)
        if reach is not None and dist <= reach:
            return 1.0, f"{kind} within its reach {reach:g} m"
    return (1.0 if dist <= r else 0.0), why


# --- recording (the bot's thread: queue only) --------------------------------------------------------------------------
def record_shot(title, enemy_class, state, distance, weapon, aim_point, outcome, hp_delta=None, *, enemy_id=None,
                zone=None, fire_mode=None, enemy_pos=None, shooter_pos=None, units_per_m=None, hp_max=None,
                round_id=None, t=None, source: str = "live") -> None:
    """One resolved shot. outcome "hit" | "miss" | "kill" (bot_look's "hit:<kind>" / "miss:<cause>" too); hp_delta the
    target's health change (negative). aim_point: where the shot went (the laser dot at the trigger, else the aim
    point) as (up_m, lateral_m) from his reported position, or a world point with enemy_pos, shooter_pos and
    units_per_m. zone if known (the dot on head / body / leg). enemy_id (his pointer / slot) counts shots to kill."""
    try:
        ti, out = _title(title), _outcome(outcome)
        if ti is None or out is None:
            return
        up, lat = _offset(aim_point, enemy_pos, shooter_pos, units_per_m)
        z = _zone(zone) or _zone_of(ti, up)
        hd = _num(hp_delta)
        ev = {"k": "shot", "ti": ti, "t": _wall(t), "c": _cls(enemy_class), "s": state_key(state), "w": _weapon(weapon),
              "d": _dist(distance), "o": out, "hd": hd, "u": up, "l": lat, "z": z,
              "m": fire_mode if fire_mode in FIRE_MODES else None, "e": _eid(enemy_id), "hm": _num(hp_max),
              "r": _safe(round_id, 40) if round_id else None, "src": _safe(source, 40) or "live"}
        _push(ev)
        r = _round(ti)
        r["shots"] += 1
        r["hits"] += out in ("hit", "kill")
        r["kills"] += out == "kill"
        _seen_class(r, ev["c"])
    except Exception as exc:                            # noqa: BLE001 - a lost fact never costs the tick
        _error(_state(), exc)


def record_damage(title, enemy_class, state, distance, what_hit_us, hp_loss, *, enemy_id=None, in_state_s=None,
                  hp_max=None, player_state=None, round_id=None, t=None, source: str = "live") -> None:
    """One player health loss, blamed on enemy_class (None: unattributed) in state at distance. what_hit_us: "melee",
    "grab", "hold", "thrown", "projectile", "explosive" ... or the title's word. in_state_s: how long he had been in
    that state (when the brain tracks it; observe() gives it otherwise)."""
    try:
        ti = _title(title)
        if ti is None:
            return
        s = _state()
        now = _clock(t)
        cls = _cls(enemy_class) if enemy_class not in (None, "") else None
        st = state_key(state)
        dist = _dist(distance)
        eid = _eid(enemy_id)
        pre = []
        if cls is not None and eid is not None:
            with s["lock"]:
                for entry in s["hist"].get((ti, eid)) or ():
                    if not entry[4] and now - WINDUP_WINDOW_S <= entry[0] <= now + 0.05:
                        entry[4] = True                 # one onset is the wind-up of one hit at most
                        pre.append([entry[1], entry[3], round(max(0.0, now - entry[0]), 3)])
        lead = _num(in_state_s)
        if not pre and cls is not None and st and lead is not None and 0.0 <= lead <= 30.0:
            pre.append([st, band(dist), round(lead, 3)])
        loss = _num(hp_loss)
        ev = {"k": "damage", "ti": ti, "t": _wall(t), "c": cls, "s": st, "d": dist,
              "a": _safe(what_hit_us, 30) if what_hit_us else None, "loss": abs(loss) if loss is not None else None,
              "e": eid, "pre": pre, "hm": _num(hp_max), "ps": state_key(player_state),
              "r": _safe(round_id, 40) if round_id else None, "src": _safe(source, 40) or "live"}
        _push(ev)
        r = _round(ti)
        r["damage"] += 1
        r["loss"] += ev["loss"] or 0.0
        if cls is not None:
            _seen_class(r, cls)
    except Exception as exc:                            # noqa: BLE001
        _error(_state(), exc)


def observe(title, enemies, t=None) -> None:
    """The live enemies (within ~DANGER_MAX_M), 5-20 times a second: dicts {"id", "cls", "state", "dist_m"} (or
    "enemy_class" / "distance"), or (cls, state, dist_m, id) tuples. Adds the exposure each class / state / band had
    (danger is damage per second of it) and the state onsets (wind-ups)."""
    try:
        ti = _title(title)
        if ti is None:
            return
        s = _state()
        now = _clock(t)
        with s["lock"]:
            last = s["obs_t"].get(ti)
            dt = 0.0 if last is None else max(0.0, min(now - last, OBS_DT_MAX))
            s["obs_t"][ti] = now
            px, pon, hist, seen = s["px"], s["pon"], s["hist"], s["seen"]
            for item in enemies or ():
                parsed = _enemy_item(item)
                if parsed is None:
                    continue
                cls, st, dist, eid = parsed
                if dist is None or dist > DANGER_MAX_M:
                    continue
                b = band(dist)
                key = (ti, cls, st, b)
                if dt > 0.0:
                    px[key] = px.get(key, 0.0) + dt
                if eid is None:
                    continue
                prev = seen.get((ti, eid))
                if prev is not None and (prev[1] != st or prev[2] != cls) and st is not None:
                    pon[key] = pon.get(key, 0) + 1
                    h = hist.setdefault((ti, eid), [])
                    h.append([now, st, cls, b, False])
                    del h[:-HIST_MAX]
                seen[(ti, eid)] = (now, st, cls)
            if now - s["gc_at"] > 2.0 or now < s["gc_at"]:
                s["gc_at"] = now
                for key in [k for k, v in seen.items() if not 0.0 <= now - v[0] <= FORGET_S]:
                    seen.pop(key, None)
                    hist.pop(key, None)
                for key in [k for k, h in hist.items() if not h or not 0.0 <= now - h[-1][0] <= FORGET_S * 3]:
                    hist.pop(key, None)
        _kick()
    except Exception as exc:                            # noqa: BLE001
        _error(_state(), exc)


def _enemy_item(item):
    if isinstance(item, dict):
        cls = item.get("cls", item.get("enemy_class"))
        if cls is None:
            cls = class_key(item)
        dist = item.get("dist_m", item.get("distance"))
        return _cls(cls), state_key(item.get("state")), _dist(dist), _eid(item.get("id", item.get("enemy_id")))
    if isinstance(item, (tuple, list)) and len(item) >= 3:
        return _cls(item[0]), state_key(item[1]), _dist(item[2]), _eid(item[3]) if len(item) > 3 else None
    return None


def record_outcome(outcome: dict) -> None:
    """The universal brain's outcome dict (gbox.mercs.brain.knowledge.record): kind "shot" | "damage", title, t,
    enemy_id, enemy_class, state, distance (cm on the ground, or units_per_m), weapon, aim_offset (cm: x, y up, z from
    his position), hit, kill, where (the dot: head / body / leg / wall / floor / none), hp_delta (the enemy's, or the
    player's for damage), attack / what_hit_us, fire_mode, round_id."""
    try:
        if not isinstance(outcome, dict):
            return
        upm = _num(outcome.get("units_per_m")) or 100.0
        dist = _num(outcome.get("distance"))
        dist = dist / upm if dist is not None else None
        if outcome.get("kind") == "damage":
            hd = _num(outcome.get("hp_delta"))
            loss = _num(outcome.get("hp_loss"))
            loss = loss if loss is not None else (-hd if hd is not None else None)
            record_damage(outcome.get("title"), outcome.get("enemy_class"), outcome.get("state"), dist,
                          outcome.get("attack") or outcome.get("what_hit_us"), loss, enemy_id=outcome.get("enemy_id"),
                          in_state_s=outcome.get("in_state_s"), hp_max=outcome.get("hp_max"),
                          player_state=outcome.get("player_state"), round_id=outcome.get("round_id"),
                          t=outcome.get("t"))
            return
        if outcome.get("kind") not in (None, "shot"):
            return
        hit = outcome.get("hit")
        result = "kill" if outcome.get("kill") is True else "hit" if hit is True else "miss" if hit is False \
            else outcome.get("outcome")
        dot = outcome.get("dot_offset")                 # where the laser dot sat on him (cm), when the brain has it
        aim = dot if dot is not None else outcome.get("aim_offset")
        aim_point = None
        if isinstance(aim, (tuple, list)) and len(aim) == 3 and _num(aim[1]) is not None:
            side = [_num(aim[0]), _num(aim[2])]
            aim_point = (_num(aim[1]) / upm, 0.0 if side == [0.0, 0.0] else None)
        where = outcome.get("where")
        zone = _zone(where)
        title = _title(outcome.get("title"))
        if dot is None and zone and aim_point and _zone_of(title, aim_point[0]) != zone:
            aim_point = None                            # the intended point, but the dot was on another zone: zone only
        record_shot(outcome.get("title"), outcome.get("enemy_class"), outcome.get("state"), dist,
                    outcome.get("weapon"), aim_point, result, outcome.get("hp_delta"), enemy_id=outcome.get("enemy_id"),
                    zone=zone, fire_mode=outcome.get("fire_mode"),
                    hp_max=outcome.get("hp_max"), round_id=outcome.get("round_id"), t=outcome.get("t"))
    except Exception as exc:                            # noqa: BLE001
        _error(_state(), exc)


def _push(ev) -> None:
    s = _state()
    q = s["pending"]
    q.append(ev)
    if len(q) > PENDING_MAX:
        with s["lock"]:
            while len(q) > PENDING_MAX:
                q.popleft()
                s["dropped"] += 1
    _kick()


def _round(ti) -> dict:
    s = _state()
    r = s["round"].get(ti)
    if r is None:
        r = s["round"][ti] = {"shots": 0, "hits": 0, "kills": 0, "damage": 0, "loss": 0.0, "classes": set(),
                              "since": time.time()}
    return r


def _seen_class(r, cls) -> None:
    if cls and len(r["classes"]) < 256:
        r["classes"].add(cls)


def _error(s, exc) -> None:
    try:
        s["errors"].append({"at": round(time.time(), 1), "error": f"{type(exc).__name__}: {exc}"[:200]})
    except Exception:                                   # noqa: BLE001
        pass


# --- the learner (background) ------------------------------------------------------------------------------------------
def _kick(force: bool = False) -> None:
    s = _state()
    now = time.monotonic()
    with s["lock"]:
        if s["busy"]:
            return
        queued = bool(s["pending"] or s["px"] or s["pon"])
        if not (force or s["need_load"] or len(s["pending"]) >= FLUSH_N
                or (queued and now - s["last_job"] >= FLUSH_S)):
            return
        s["busy"] = True
    try:
        threading.Thread(target=_job, name="mercs-enemy-db", daemon=True).start()
    except RuntimeError:                                # interpreter shutting down: no new threads
        with s["lock"]:
            s["busy"] = False


def flush(wait: bool = False, timeout: float = 5.0) -> bool:
    """Fold and write the queued facts now (a round's end); wait: until done or timeout. True when nothing is left."""
    s = _state()
    _kick(force=True)
    if not wait:
        return True
    deadline = time.monotonic() + timeout
    while True:
        with s["lock"]:
            idle = not s["busy"] and not s["pending"] and not s["px"] and not s["pon"] and not s["need_load"]
            busy = s["busy"]
        if idle:
            return True
        if time.monotonic() >= deadline:
            return False
        if not busy:
            _kick(force=True)
        time.sleep(0.01)


def _at_exit() -> None:
    """The process ends: the queued facts written on this thread (no new thread can start at interpreter shutdown)."""
    try:
        s = _state()
        deadline = time.monotonic() + 2.0
        while s["busy"] and time.monotonic() < deadline:
            time.sleep(0.01)
        with s["lock"]:
            if s["busy"] or not (s["pending"] or s["px"] or s["pon"]):
                return                                  # still busy, or nothing to write
            s["busy"] = True
        _job()
    except Exception:                                   # noqa: BLE001
        pass


def status() -> dict:
    """The live learner, for humans: titles loaded (and their write errors), facts queued, facts dropped, recent errors."""
    s = _state()
    return {"root": str(root()), "titles": {t: {k: m.get(k) for k in ("generation", "writable", "error")}
                                            for t, m in list(s["titles"].items())},
            "pending": len(s["pending"]), "busy": s["busy"], "dropped": s["dropped"], "version": s["version"],
            "errors": list(s["errors"])}


def _job() -> None:
    s = _state()
    try:
        for _ in range(32):
            if not _job_once(s):
                break
    except Exception as exc:                            # noqa: BLE001 - the learner never takes the bot down
        _error(s, exc)
    finally:
        with s["lock"]:
            s["busy"] = False
            s["last_job"] = time.monotonic()


def _job_once(s) -> bool:
    base = root()
    if not s["discovered"]:
        s["discovered"] = True
        try:
            names = sorted(d.name for d in base.iterdir() if (d / DB_NAME).is_file()) if base.is_dir() else []
        except OSError:
            names = []
        for name in names:
            if not (s["titles"].get(name) or {}).get("loaded"):
                _load(s, name, base)
    with s["lock"]:
        events = []
        while s["pending"] and len(events) < JOB_MAX:
            events.append(s["pending"].popleft())
        px, s["px"] = s["px"], {}
        pon, s["pon"] = s["pon"], {}
        need = set(s["need_load"])
        s["need_load"].clear()
    titles = {e["ti"] for e in events} | {k[0] for k in px} | {k[0] for k in pon} | need
    for ti in sorted(titles):
        meta = s["titles"].get(ti) or {}
        if not meta.get("loaded"):
            _load(s, ti, base)
        elif events or px or pon:
            _check_generation(s, ti, base)
    if not events and not px and not pon:
        return bool(need)
    now = time.time()
    batch: dict = {}
    rows: dict = {}
    exposure: dict = {}
    models = s["models"]
    for ev in events:
        try:
            _apply(models, batch, s["ctx"], ev)
            rows.setdefault(ev["ti"], []).append(_row_of(ev))
        except Exception as exc:                        # noqa: BLE001 - one bad fact never stops the rest
            _error(s, exc)
    day = int(now // 86400)
    for (ti, cls, st, b), secs in px.items():
        _apply_exposure(models, batch, ti, cls, st, b, now, secs, 0.0)
        acc = exposure.setdefault(ti, {}).setdefault((day, cls, st or "", b), [0.0, 0.0])
        acc[0] += secs
    for (ti, cls, st, b), n in pon.items():
        _apply_exposure(models, batch, ti, cls, st, b, now, 0.0, float(n))
        acc = exposure.setdefault(ti, {}).setdefault((day, cls, st or "", b), [0.0, 0.0])
        acc[1] += n
    _gc_ctx(s["ctx"], now)
    with s["lock"]:
        for (ti, key), cell in batch.items():
            models.setdefault(ti, {})[key] = cell
        s["version"] += 1
    by_title: dict = {}
    for (ti, key), cell in batch.items():
        by_title.setdefault(ti, {})[key] = cell
    for ti in sorted(titles):
        _write(s, ti, base, rows.get(ti, ()), exposure.get(ti, {}), by_title.get(ti, {}), now)
    return True


def _gc_ctx(ctx, now) -> None:
    kills = ctx["kills"]
    if len(kills) > 64:
        for key in [k for k, v in kills.items() if not 0.0 <= now - v[1] <= FORGET_S * 6]:
            kills.pop(key, None)
    last = ctx["last"]
    if len(last) > 256:
        for key in sorted(last, key=last.get)[:len(last) - 128]:
            last.pop(key, None)


# --- folding facts into cells (the same code for the live learner, rebuild() and the seed) -----------------------------
def _decay(dt: float) -> float:
    return 0.5 ** (dt / HALF_LIFE_S) if dt > 0 else 1.0


RAW = ("t", "lossmax", "N")    # cell fields never aged or capped: the last update, the worst loss, the raw sample total


def _scale(cell: dict, f: float) -> None:
    for key, v in cell.items():
        if key in RAW:
            continue
        if isinstance(v, dict):
            for k2 in v:
                v[k2] *= f
        elif isinstance(v, float):
            cell[key] = v * f


def _cap(cell: dict) -> None:
    f = 1.0
    for key, cap in CAPS.items():
        v = cell.get(key)
        if isinstance(v, float) and v > cap:
            f = min(f, cap / v)
    if f < 1.0:
        _scale(cell, f)


def _add(models, batch, ti, key, t, fields, att=None, lossmax=None) -> None:
    cell = batch.get((ti, key))
    if cell is None:
        old = (models.get(ti) or {}).get(key)
        cell = dict(old) if old else {"t": t}
        if old and isinstance(old.get("att"), dict):
            cell["att"] = dict(old["att"])
        batch[(ti, key)] = cell
    ct = cell.get("t", t)
    if t >= ct:
        f = _decay(t - ct)
        if f < 1.0:
            _scale(cell, f)
        cell["t"] = t
        w = 1.0
    else:
        w = _decay(ct - t)                              # an older fact (a seed, a replay) weighs what it would by now
    for k, v in fields.items():
        cell[k] = float(cell.get(k, 0.0)) + w * v
    if "n" in fields:
        cell["N"] = float(cell.get("N", 0.0)) + fields["n"]   # every sample ever folded here, for humans
    if att:
        a = cell.setdefault("att", {})
        a[att] = a.get(att, 0.0) + w
        if len(a) > 8:
            for k in sorted(a, key=a.get)[:len(a) - 8]:
                a.pop(k, None)
    if lossmax is not None:
        cell["lossmax"] = max(float(cell.get("lossmax", 0.0)), lossmax)
    _cap(cell)


def _levels(ti, cls) -> list:
    """The class levels a fact teaches: the class, his family in this title ("@family"), every class ("*")."""
    out = [cls]
    fam = family(ti, cls)
    if fam:
        out.append("@" + fam)
    if cls != ANY:
        out.append(ANY)
    return out


def _apply(models, batch, ctx, ev) -> None:
    if ev["k"] == "shot":
        _apply_shot(models, batch, ctx, ev)
    elif ev["k"] == "damage":
        _apply_damage(models, batch, ev)


def _apply_shot(models, batch, ctx, ev) -> None:
    ti, t, cls, w = ev["ti"], ev["t"], ev["c"], ev["w"]
    b, z = band(ev["d"]) or ANY, ev["z"] or ANY
    hit, kill = ev["o"] in ("hit", "kill"), ev["o"] == "kill"
    fields = {"n": 1.0, "h": float(hit), "k": float(kill)}
    hd = ev.get("hd")
    if hit and hd:
        fields.update(d=abs(hd), dn=1.0)
    if hit and ev.get("u") is not None:
        fields.update(aw=1.0, au=ev["u"], au2=ev["u"] * ev["u"])
        if ev.get("l") is not None:
            fields.update(lw=1.0, al=ev["l"], al2=ev["l"] * ev["l"])
    levels = _levels(ti, cls)
    for cl in levels:
        for pw, pb, pz in {(w, b, z), (ANY, b, z), (ANY, ANY, z), (w, b, ANY), (ANY, b, ANY), (ANY, ANY, ANY),
                           (w, ANY, ANY)}:
            _add(models, batch, ti, _k("shot", cl, pw, pb, pz), t, fields)
    eid = ev.get("e")
    if eid:
        rec = ctx["kills"].setdefault((ti, eid), [0, t])
        rec[0] += 1
        rec[1] = t
        if kill:
            shots = float(rec[0])
            ctx["kills"].pop((ti, eid), None)
            for cl in levels:
                for pw in {w, ANY}:
                    _add(models, batch, ti, _k("kill", cl, pw), t, {"n": 1.0, "s": shots, "s2": shots * shots})
    mode = ev.get("m")
    if mode:
        last_key = (ti, w, mode)
        last = ctx["last"].get(last_key)
        ctx["last"][last_key] = t
        mf = {"n": 1.0, "h": float(hit)}
        if hit and hd:
            mf.update(d=abs(hd), dn=1.0)
        if last is not None and 0.0 < t - last <= 1.0:
            mf.update(iw=1.0, isum=t - last)
        for cl in levels:
            for pw, pb in {(w, b), (w, ANY), (ANY, b), (ANY, ANY)}:
                _add(models, batch, ti, _k("mode", cl, pw, pb, mode), t, mf)


def _apply_damage(models, batch, ev) -> None:
    ti, t, cls = ev["ti"], ev["t"], ev["c"]
    b = band(ev["d"]) or ANY
    loss = ev.get("loss") or 0.0
    if cls is None:
        _add(models, batch, ti, _k("danger", "?", ANY, ANY), t, {"n": 1.0, "loss": loss}, att=ev.get("a"))
        return
    st = ev.get("s")
    states = [x for x in dict.fromkeys((st, _kind_key(state_kind(ti, st)), ANY)) if x]
    for cl in _levels(ti, cls):
        for x in states:
            for pb in {b, ANY}:
                _add(models, batch, ti, _k("danger", cl, x, pb), t, {"n": 1.0, "loss": loss}, att=ev.get("a"),
                     lossmax=loss)
    for entry in ev.get("pre") or ():
        try:
            pst, pband, lead = entry[0], entry[1], float(entry[2])
        except (TypeError, ValueError, IndexError):
            continue
        for cl in (cls, ANY):
            for x in [y for y in dict.fromkeys((pst, _kind_key(state_kind(ti, pst)))) if y]:
                for pb in {pband or ANY, ANY}:
                    _add(models, batch, ti, _k("pre", cl, x, pb), t,
                         {"n": 1.0, "ln": 1.0, "ls": lead, "ls2": lead * lead})


def _apply_exposure(models, batch, ti, cls, st, b, t, secs, onsets) -> None:
    kind = _kind_key(state_kind(ti, st))
    if secs > 0.0:
        for cl in _levels(ti, cls):
            for x in [y for y in dict.fromkeys((st, kind, ANY)) if y]:
                for pb in {b or ANY, ANY}:
                    _add(models, batch, ti, _k("danger", cl, x, pb), t, {"e": secs})
    if onsets > 0.0 and st:
        for cl in (cls, ANY):
            for x in [y for y in dict.fromkeys((st, kind)) if y]:
                for pb in {b or ANY, ANY}:
                    _add(models, batch, ti, _k("pre", cl, x, pb), t, {"on": onsets})


# --- SQLite ------------------------------------------------------------------------------------------------------------
DDL = (
    "create table if not exists meta(key text primary key, value text)",
    "create table if not exists samples(id integer primary key autoincrement, ts real not null, kind text not null, "
    "cls text, state text, weapon text, dist_m real, outcome text, hp_delta real, up_m real, lateral_m real, zone text, "
    "fire_mode text, attack text, enemy text, round_id text, source text, extra text)",
    "create index if not exists samples_ts on samples(ts)",
    "create index if not exists samples_cls on samples(cls, ts)",
    "create table if not exists exposure(day integer not null, cls text not null, state text not null, band text not null, "
    "seconds real not null default 0, onsets real not null default 0, primary key(day, cls, state, band))",
    "create table if not exists cells(key text primary key, data text not null, updated real not null)",
)
SAMPLE_COLS = ("ts", "kind", "cls", "state", "weapon", "dist_m", "outcome", "hp_delta", "up_m", "lateral_m", "zone",
               "fire_mode", "attack", "enemy", "round_id", "source", "extra")


def db_path(title, base=None) -> Path:
    ti = _title(title)
    if not ti:
        raise ValueError(f"bad title {title!r}")
    return Path(base if base is not None else root()) / ti / DB_NAME


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5.0)
    db.execute("pragma journal_mode=WAL")
    db.execute("pragma synchronous=NORMAL")
    for stmt in DDL:
        db.execute(stmt)
    if db.execute("select value from meta where key='schema'").fetchone() is None:
        db.execute("insert or replace into meta values('schema', ?)", (str(SCHEMA),))
    return db


def _ro(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=5.0)
    db.execute("pragma query_only=ON")
    return db


def _read_cells(db) -> dict:
    out = {}
    for key, data in db.execute("select key, data from cells"):
        try:
            cell = json.loads(data)
        except ValueError:
            continue
        if isinstance(cell, dict):
            out[key] = {k: (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
                        for k, v in cell.items()}
    return out


def _meta(db, key):
    row = db.execute("select value from meta where key=?", (key,)).fetchone()
    return row[0] if row else None


def _load(s, ti, base) -> None:
    path = Path(base) / ti / DB_NAME
    meta = {"loaded": True, "generation": None, "writable": True, "error": None, "pruned": 0.0}
    cells: dict = {}
    if path.is_file():
        try:
            with closing(_connect(path)) as db:
                cells = _read_cells(db)
                meta["generation"] = _meta(db, "generation")
        except (sqlite3.Error, OSError) as exc:
            meta.update(writable=False, error=f"{type(exc).__name__}: {exc}"[:200])
    with s["lock"]:
        old = s["models"].get(ti) or {}
        merged = dict(cells)
        merged.update({k: v for k, v in old.items() if k not in cells})   # in-memory facts not on disk yet stay
        s["models"][ti] = merged
        s["titles"][ti] = meta
        s["version"] += 1


def _check_generation(s, ti, base) -> None:
    path = Path(base) / ti / DB_NAME
    meta = s["titles"].get(ti) or {}
    if not path.is_file() or not meta.get("writable", True):
        return
    try:
        with closing(_ro(path)) as db:
            gen = _meta(db, "generation")
    except (sqlite3.Error, OSError):
        return
    if gen != meta.get("generation"):                   # rebuilt (a seed): its cells replace the ones in memory
        try:
            with closing(_ro(path)) as db:
                cells = _read_cells(db)
        except (sqlite3.Error, OSError):
            return
        with s["lock"]:
            s["models"][ti] = cells
            meta["generation"] = gen
            s["version"] += 1


def _cell_json(cell: dict) -> str:
    out = {}
    for k, v in cell.items():
        if isinstance(v, float):
            out[k] = round(v, 6)
        elif isinstance(v, dict):
            out[k] = {k2: round(v2, 6) for k2, v2 in v.items()}
        else:
            out[k] = v
    return json.dumps(out, separators=(",", ":"))


def _write(s, ti, base, rows, exposure, cells, now) -> None:
    meta = s["titles"].setdefault(ti, {"loaded": True, "generation": None, "writable": True, "error": None,
                                       "pruned": 0.0})
    if not meta.get("writable", True) or not (rows or exposure or cells):
        return
    try:
        with closing(_connect(Path(base) / ti / DB_NAME)) as db:
            with db:
                if rows:
                    db.executemany(f"insert into samples({','.join(SAMPLE_COLS)}) values "
                                   f"({','.join('?' * len(SAMPLE_COLS))})", rows)
                for (day, cls, st, b), (secs, ons) in exposure.items():
                    db.execute("insert into exposure values(?,?,?,?,?,?) on conflict(day, cls, state, band) do update "
                               "set seconds=seconds+excluded.seconds, onsets=onsets+excluded.onsets",
                               (day, cls, st, b, secs, ons))
                db.executemany("insert into cells values(?,?,?) on conflict(key) do update set data=excluded.data, "
                               "updated=excluded.updated", [(k, _cell_json(c), c.get("t", now)) for k, c in cells.items()])
            if now - meta.get("pruned", 0.0) >= PRUNE_EVERY_S:
                meta["pruned"] = now
                _prune(s, ti, db, now)
        meta["error"] = None
    except (sqlite3.Error, OSError) as exc:
        meta["error"] = f"{type(exc).__name__}: {exc}"[:200]
        _error(s, exc)


def _prune(s, ti, db, now) -> None:
    """Bound the store: samples older than MAX_AGE_S or past the newest MAX_SAMPLES, old exposure days, and cells whose
    weight has aged to nothing (or the least recently updated past MAX_CELLS)."""
    with db:
        db.execute("delete from samples where ts < ?", (now - MAX_AGE_S,))
        row = db.execute("select id from samples order by id desc limit 1 offset ?", (MAX_SAMPLES,)).fetchone()
        if row:
            db.execute("delete from samples where id <= ?", (row[0],))
        db.execute("delete from exposure where day < ?", (int((now - MAX_AGE_S) // 86400),))
    cells = s["models"].get(ti) or {}
    drop = [k for k, c in list(cells.items())
            if now - c.get("t", now) > MAX_AGE_S and max(c.get("n", 0.0), c.get("e", 0.0) / 60.0, c.get("on", 0.0))
            * _decay(now - c.get("t", now)) < 0.05]
    if len(cells) - len(drop) > MAX_CELLS:
        dropped = set(drop)
        keep = sorted((k for k in list(cells) if k not in dropped), key=lambda k: cells[k].get("t", 0.0))
        drop += keep[:len(keep) - int(MAX_CELLS * 0.9)]
    if drop:
        with s["lock"]:
            for k in drop:
                cells.pop(k, None)
            s["version"] += 1
        with db:
            db.executemany("delete from cells where key=?", [(k,) for k in drop])


def _row_of(ev) -> tuple:
    if ev["k"] == "shot":
        extra = {k: ev[k] for k in ("hm",) if ev.get(k) is not None}
        return (ev["t"], "shot", ev["c"], ev["s"], ev["w"], ev["d"], ev["o"], ev.get("hd"), ev.get("u"), ev.get("l"),
                ev.get("z"), ev.get("m"), None, ev.get("e"), ev.get("r"), ev.get("src"),
                json.dumps(extra, separators=(",", ":")) if extra else None)
    extra = {k: ev[k] for k in ("pre", "hm", "ps") if ev.get(k)}
    return (ev["t"], "damage", ev["c"], ev["s"], None, ev["d"], None, ev.get("loss"), None, None, None, None,
            ev.get("a"), ev.get("e"), ev.get("r"), ev.get("src"),
            json.dumps(extra, separators=(",", ":")) if extra else None)


def _ev_of(ti, row) -> dict | None:
    r = dict(zip(SAMPLE_COLS, row))
    try:
        extra = json.loads(r["extra"]) if r["extra"] else {}
    except ValueError:
        extra = {}
    if r["kind"] == "shot":
        if r["outcome"] not in ("hit", "kill", "miss"):
            return None
        return {"k": "shot", "ti": ti, "t": r["ts"], "c": r["cls"] or "unknown", "s": r["state"], "w": r["weapon"] or ANY,
                "d": r["dist_m"], "o": r["outcome"], "hd": r["hp_delta"], "u": r["up_m"], "l": r["lateral_m"],
                "z": r["zone"], "m": r["fire_mode"], "e": r["enemy"], "hm": extra.get("hm"), "r": r["round_id"],
                "src": r["source"]}
    if r["kind"] == "damage":
        return {"k": "damage", "ti": ti, "t": r["ts"], "c": r["cls"], "s": r["state"], "d": r["dist_m"],
                "a": r["attack"], "loss": r["hp_delta"], "e": r["enemy"], "pre": extra.get("pre") or [],
                "hm": extra.get("hm"), "ps": extra.get("ps"), "r": r["round_id"], "src": r["source"]}
    return None


def rebuild(title, base=None, *, now=None) -> dict:
    """Fold every stored sample and exposure day of a title into fresh cells, replacing the stored ones (after a seed,
    or a change to the learning rules). A running bot reloads them (the generation changes). Returns counts."""
    path = db_path(title, base)
    ti = path.parent.name
    now = time.time() if now is None else now
    models: dict = {ti: {}}
    batch: dict = {}
    ctx = {"kills": {}, "last": {}}
    counts = {"shots": 0, "damage": 0, "exposure_days": 0}
    with closing(_connect(path)) as db:
        for row in db.execute(f"select {','.join(SAMPLE_COLS)} from samples order by ts, id"):
            ev = _ev_of(ti, row)
            if ev is None:
                continue
            _apply(models, batch, ctx, ev)
            counts["shots" if ev["k"] == "shot" else "damage"] += 1
        for day, cls, st, b, secs, ons in db.execute("select day, cls, state, band, seconds, onsets from exposure"):
            _apply_exposure(models, batch, ti, cls, st or None, b, min(day * 86400.0 + 43200.0, now), secs or 0.0,
                            ons or 0.0)
            counts["exposure_days"] += 1
        cells = {key: cell for (t2, key), cell in batch.items() if t2 == ti}
        gen = uuid.uuid4().hex
        with db:
            db.execute("delete from cells")
            db.executemany("insert into cells values(?,?,?)",
                           [(k, _cell_json(c), c.get("t", now)) for k, c in cells.items()])
            db.execute("insert or replace into meta values('generation', ?)", (gen,))
            db.execute("insert or replace into meta values('rebuilt_at', ?)", (str(round(now, 3)),))
    counts.update(cells=len(cells), generation=gen)
    return counts


# --- the plan ----------------------------------------------------------------------------------------------------------
def dispatch_plan(title, enemy_class, state=None, distance=None, weapon=None, *, hp=None, hp_max=None,
                  defaults=None) -> Plan:
    """How to dispatch this enemy now (see the module docstring). Cheap: in memory, cached until the next learning
    pass. Before any data - or for a title not loaded yet - every field is the title's current constants."""
    s = _state()
    ti = _title(title) or "unknown"
    cls, st, dist, w = _cls(enemy_class), state_key(state), _dist(distance), _weapon(weapon)
    b = band(dist)
    try:
        kind = state_kind(ti, st)
        fam = family(ti, cls)
        d = _defaults(ti, weapon, st, kind, dist, hp_max, fam, defaults)
    except Exception as exc:                            # noqa: BLE001
        _error(s, exc)
        kind, fam = None, None
        d = _defaults(ti, None, None, None, dist, None, None, None)
    try:
        meta = s["titles"].get(ti)
        if meta is None or not meta.get("loaded"):
            with s["lock"]:
                s["need_load"].add(ti)
            _kick()
        else:
            _kick()
        # learned values depend on the band; the defaults (in the key) carry every exact-distance rule
        key = (ti, cls, st, b, w, _num(hp), _num(hp_max),
               tuple(sorted((k, v) for k, v in d.items() if k != "zones" and not isinstance(v, dict))))
        version = s["version"]
        cached = s["cache"].get(key)
        if cached is not None and cached[0] == version:
            return cached[1]
        plan = _plan(s["models"], ti, cls, st, kind, fam, dist, b, w, _num(hp), _num(hp_max), d, time.time())
        if len(s["cache"]) > CACHE_MAX:
            s["cache"].clear()
        s["cache"][key] = (version, plan)
        return plan
    except Exception as exc:                            # noqa: BLE001 - a plan error answers with the constants
        _error(s, exc)
        return _default_plan(ti, cls, st, b, fam, d)


def _default_plan(ti, cls, st, b, fam, d) -> Plan:
    return Plan(ti, cls, st, b, fam, aim=Learned(Aim(d["up_m"], d["lateral_m"], d["zone"])),
                range=Learned((d["near_m"], d["far_m"])), fire_mode=Learned(d["fire_mode"]),
                danger=Learned(d["danger"], detail={"rule": d.get("danger_rule")}), windup=Learned(None),
                lead_s=Learned(d["lead_s"]), attack=Learned(None), shots_to_kill=Learned(d["shots_to_kill"]),
                hit_rate=Learned(None))


def _view(cell, now) -> dict:
    f = _decay(now - cell.get("t", now))
    out = {}
    for k, v in cell.items():
        if k in RAW:
            out[k] = v
        elif isinstance(v, dict):
            out[k] = {k2: v2 * f for k2, v2 in v.items()}
        elif isinstance(v, float):
            out[k] = v * f
    return out


def _merge(a, b) -> dict:
    if a is None:
        return b
    out = dict(a)
    for k, v in b.items():
        if k == "t":
            out[k] = max(out.get(k, v), v)
        elif k == "lossmax":
            out[k] = max(out.get(k, 0.0), v)
        elif isinstance(v, dict):
            att = dict(out.get(k) or {})
            for k2, v2 in v.items():
                att[k2] = att.get(k2, 0.0) + v2
            out[k] = att
        elif isinstance(v, float):
            out[k] = out.get(k, 0.0) + v
    return out


def _cell(models, lt, key, now) -> dict | None:
    """The cell at key in title lt (every title summed for "*"), aged to now."""
    if lt == ANY:
        out = None
        for cells in list(models.values()):
            c = cells.get(key)
            if c:
                out = _merge(out, _view(c, now))
        return out
    c = (models.get(lt) or {}).get(key)
    return _view(c, now) if c else None


def _class_levels(ti, cls, fam, cross: bool = True) -> list:
    out = [("class", ti, cls)]
    if fam:
        out.append(("title_family", ti, "@" + fam))
        if cross:
            out.append(("family", ANY, "@" + fam))
    if cls != ANY:
        out.append(("title", ti, ANY))
    return out


def _conf(n, half) -> float:
    return n / (n + half) if n > 0 else 0.0


def _plan(models, ti, cls, st, kind, fam, dist, b, w, hp, hp_max, d, now) -> Plan:
    pb = b or ANY
    danger = _plan_danger(models, ti, cls, fam, st, kind, pb, d, now)
    windup, lead = _plan_windup(models, ti, cls, st, kind, pb, d, now)

    def risk(band_name):
        learned = _plan_danger(models, ti, cls, fam, None, None, band_name, {"danger": 0.0}, now)
        return (learned.detail or {}).get("p", 0.0) * learned.confidence
    return Plan(ti, cls, st, b, fam,
                aim=_plan_aim(models, ti, cls, fam, w, pb, d, now),
                range=_plan_range(models, ti, cls, fam, w, d, now, risk),
                fire_mode=_plan_fire(models, ti, cls, fam, w, pb, d, now),
                danger=danger, windup=windup, lead_s=lead,
                attack=_plan_attack(models, ti, cls, st, kind, now),
                shots_to_kill=_plan_stk(models, ti, cls, fam, w, hp, hp_max, d, now),
                hit_rate=_plan_hit(models, ti, cls, fam, w, pb, now))


def _plan_aim(models, ti, cls, fam, w, b, d, now) -> Learned:
    probes = []
    for src, lt, cl in _class_levels(ti, cls, fam):
        if w != ANY and b != ANY:
            probes.append((src, lt, cl, w, b))
        if b != ANY:
            probes.append((src, lt, cl, ANY, b))
        probes.append((src, lt, cl, ANY, ANY))
    for src, lt, cl, pw, pb in probes:
        zs = {z: _cell(models, lt, _k("shot", cl, pw, pb, z), now) for z in ZONES}
        hits = sum((c or {}).get("h", 0.0) for c in zs.values())
        if hits < MIN["aim"]:
            continue
        n_all = sum((c or {}).get("n", 0.0) for c in zs.values())
        p_bar = hits / n_all if n_all else 0.0
        dn_all = sum((c or {}).get("dn", 0.0) for c in zs.values())
        m_bar = sum((c or {}).get("d", 0.0) for c in zs.values()) / dn_all if dn_all >= 1.0 else None
        k_bar = sum((c or {}).get("k", 0.0) for c in zs.values()) / hits
        values = {}
        for z, c in zs.items():
            if not c or c.get("n", 0.0) < MIN["zone"]:
                continue
            p = (c.get("h", 0.0) + 4.0 * p_bar) / (c["n"] + 4.0)
            if m_bar:                                   # damage per shot where the health change is known ...
                m = (c.get("d", 0.0) + 3.0 * m_bar) / (c.get("dn", 0.0) + 3.0)
            else:                                       # ... else hits, a kill counting double
                m = 1.0 + (c.get("k", 0.0) + 3.0 * k_bar) / (c.get("h", 0.0) + 3.0)
            values[z] = p * m
        dz = d["zone"]
        if src == "family":
            # Another title's evidence says where hits land on such a body (the offset in the title's own zone), never
            # which zone or range this title's weapons should take: that needs this title's own shots.
            zone = dz
            if (zs.get(dz) or {}).get("aw", 0.0) < MIN["offset"]:
                continue
        else:
            if dz not in values:                        # the default zone unmeasured at this level: nothing to beat
                continue
            best = max(values, key=values.get)
            # a zone replaces the default only on damage or kills (hit rate alone favours easy zones that don't kill)
            zone = best if best != dz and (m_bar is not None or k_bar > 0) \
                and values[best] >= SWITCH_ZONE * values[dz] else dz
        c = zs.get(zone) or {}
        default_up = d["up_m"] if zone == dz else d["zones"].get(zone, d["up_m"])
        aw, lw = c.get("aw", 0.0), c.get("lw", 0.0)
        up = (c.get("au", 0.0) + K_UP * default_up) / (aw + K_UP) if aw >= MIN["offset"] else default_up
        lat = (c.get("al", 0.0) + K_LAT * d["lateral_m"]) / (lw + K_LAT) if lw >= MIN["offset"] else d["lateral_m"]
        hz = c.get("h", 0.0)
        detail = {"probe": f"{pw}/{pb}", "zones": {z: {"shots": round(v.get("n", 0.0), 1), "hits": round(v.get("h", 0.0), 1),
                                                       "value": round(values[z], 3) if z in values else None}
                                                   for z, v in zs.items() if v}}
        if aw >= 2.0:
            sd = math.sqrt(max(0.0, c.get("au2", 0.0) / aw - (c.get("au", 0.0) / aw) ** 2))
            detail["up_sd_m"] = round(sd, 3)
        return Learned(Aim(round(up, 3), round(lat, 3), zone), _conf(hz, HALF["aim"]), int(round(hz)), src, detail)
    return Learned(Aim(d["up_m"], d["lateral_m"], d["zone"]))


def _rate(c, p_bar, m_bar) -> float:
    p = (c.get("h", 0.0) + 4.0 * p_bar) / (c.get("n", 0.0) + 4.0)
    m = (c.get("d", 0.0) + 3.0 * m_bar) / (c.get("dn", 0.0) + 3.0) if m_bar else 1.0
    return p * m


def _plan_range(models, ti, cls, fam, w, d, now, risk) -> Learned:
    for src, lt, cl in _class_levels(ti, cls, fam, cross=False):      # the title's own weapons decide its range
        for pw in ((w, ANY) if w != ANY else (ANY,)):
            rows = {}
            for name in BAND_NAMES:
                c = _cell(models, lt, _k("shot", cl, pw, name, ANY), now)
                if c and c.get("n", 0.0) >= MIN["band"]:
                    rows[name] = c
            total = sum(c["n"] for c in rows.values())
            if not rows or total < 2 * MIN["band"]:
                continue
            p_bar = sum(c.get("h", 0.0) for c in rows.values()) / total
            dn = sum(c.get("dn", 0.0) for c in rows.values())
            m_bar = sum(c.get("d", 0.0) for c in rows.values()) / dn if dn >= 1.0 else None
            score = {name: _rate(c, p_bar, m_bar) * (1.0 - min(0.95, risk(name))) for name, c in rows.items()}
            best = max(score, key=score.get)
            keep = {best}
            i = BAND_NAMES.index(best)
            for step in (-1, 1):
                j = i + step
                while 0 <= j < len(BAND_NAMES) and BAND_NAMES[j] in score and score[BAND_NAMES[j]] >= RANGE_KEEP * score[best]:
                    keep.add(BAND_NAMES[j])
                    j += step
            names = [n for n in BAND_NAMES if n in keep]
            near = max(BAND_EDGES[names[0]][0], d["near_m"])
            far = BAND_EDGES[names[-1]][1] if names[-1] != "20+" else max(BAND_EDGES["20+"][1], d["far_m"])
            if far <= near:
                continue
            n_sel = sum(rows[n]["n"] for n in names)
            detail = {"weapon": pw, "bands": {n: {"shots": round(c["n"], 1), "hits": round(c.get("h", 0.0), 1),
                                                  "score": round(score[n], 3)} for n, c in rows.items()}}
            return Learned((round(near, 2), round(far, 2)), _conf(n_sel, HALF["range"]), int(round(n_sel)), src, detail)
    return Learned((d["near_m"], d["far_m"]))


def _plan_fire(models, ti, cls, fam, w, b, d, now) -> Learned:
    dm = d["fire_mode"]
    for src, lt, cl in _class_levels(ti, cls, fam, cross=False):
        probes = [(w, b), (w, ANY)] if w != ANY else [(ANY, b), (ANY, ANY)]
        for pw, pb in dict.fromkeys(probes):
            ms = {m: _cell(models, lt, _k("mode", cl, pw, pb, m), now) for m in FIRE_MODES}
            values = {}
            for m, c in ms.items():
                if c and c.get("n", 0.0) >= MIN["mode"] and c.get("iw", 0.0) >= MIN["interval"]:
                    rate = c["iw"] / max(c.get("isum", 0.0), 1e-3)
                    p = c.get("h", 0.0) / c["n"]
                    dmg = c["d"] / c["dn"] if c.get("dn", 0.0) >= 1.0 else 1.0
                    values[m] = rate * p * dmg
            if dm not in values or len(values) < 2:
                continue
            best = max(values, key=values.get)
            chosen = best if best != dm and values[best] >= SWITCH_MODE * values[dm] else dm
            n = min(ms[chosen]["n"], ms[dm]["n"])
            detail = {"probe": f"{pw}/{pb}", "per_s": {m: round(v, 3) for m, v in values.items()}}
            return Learned(chosen, _conf(n, HALF["mode"]), int(round(n)), src, detail)
    return Learned(dm)


def _plan_stk(models, ti, cls, fam, w, hp, hp_max, d, now) -> Learned:
    share = hp / hp_max if hp is not None and hp_max and hp_max > 0 and 0 < hp <= hp_max else 1.0
    for src, lt, cl in _class_levels(ti, cls, fam, cross=False):
        for pw in dict.fromkeys((w, ANY)):
            c = _cell(models, lt, _k("kill", cl, pw), now)
            if c and c.get("n", 0.0) >= MIN["kills"]:
                v = c["s"] / c["n"] * share
                return Learned(round(v, 2), _conf(c["n"], HALF["kills"]), int(round(c["n"])), src,
                               {"weapon": pw, "full_health_shots": round(c["s"] / c["n"], 2)})
    full = hp_max if hp_max and hp_max > 0 else None
    if full is not None:
        target = hp if hp is not None and 0 < hp <= full else full
        for src, lt, cl in _class_levels(ti, cls, fam, cross=False):
            c = _cell(models, lt, _k("shot", cl, w, ANY, ANY), now) if w != ANY else None
            c = c if c and c.get("n", 0.0) >= 10.0 else _cell(models, lt, _k("shot", cl, ANY, ANY, ANY), now)
            if c and c.get("n", 0.0) >= 10.0 and c.get("dn", 0.0) >= 5.0 and c.get("h", 0.0) > 0.0:
                per_shot = (c["h"] / c["n"]) * (c["d"] / c["dn"])
                if per_shot > 0:
                    v = max(1.0, min(500.0, target / per_shot))
                    return Learned(round(v, 2), 0.5 * _conf(c["n"], 20.0), int(round(c["n"])), "estimate",
                                   {"level": src, "damage_per_shot": round(per_shot, 1)})
    return Learned(d["shots_to_kill"])


def _plan_danger(models, ti, cls, fam, st, kind, b, d, now) -> Learned:
    states = [x for x in dict.fromkeys((st, _kind_key(kind))) if x] + [ANY]
    probes = [("class", ti, cls, x, b) for x in states]
    if fam:
        probes += [("title_family", ti, "@" + fam, ANY, b), ("family", ANY, "@" + fam, ANY, b)]
    if cls != ANY:
        probes.append(("title", ti, ANY, ANY, b))
    for src, lt, cl, x, pb in probes:
        c = _cell(models, lt, _k("danger", cl, x, pb), now)
        if c and c.get("e", 0.0) >= MIN["exposure_s"]:
            lam = c.get("n", 0.0) / c["e"]
            p = 1.0 - math.exp(-lam * DANGER_WINDOW_S)
            conf = _conf(c["e"], HALF["exposure_s"])
            value = conf * p + (1.0 - conf) * d["danger"]
            return Learned(round(value, 3), conf, int(round(c.get("n", 0.0))), src,
                           {"p": round(p, 4), "exposure_s": round(c["e"], 1), "events": round(c.get("n", 0.0), 1),
                            "state": x, "band": pb})
    return Learned(d["danger"], detail={"rule": d.get("danger_rule")})


def _plan_windup(models, ti, cls, st, kind, b, d, now) -> tuple:
    lead_default = Learned(d["lead_s"])
    if not st and not kind:
        return Learned(None), lead_default
    probes = [(src, cl, x, pb) for src, cl in (("class", cls), ("title", ANY))
              for x in dict.fromkeys((st, _kind_key(kind))) if x for pb in dict.fromkeys((b, ANY))]
    windup = lead = None
    for src, cl, x, pb in probes:
        c = _cell(models, ti, _k("pre", cl, x, pb), now)
        if not c:
            continue
        if windup is None and c.get("on", 0.0) >= MIN["onsets"]:
            v = min(1.0, c.get("n", 0.0) / c["on"])
            windup = Learned(round(v, 3), _conf(c["on"], HALF["onsets"]), int(round(c["on"])), src,
                             {"state": x, "band": pb, "followed": round(c.get("n", 0.0), 1)})
        if lead is None and c.get("ln", 0.0) >= MIN["leads"]:
            mean = c["ls"] / c["ln"]
            sd = math.sqrt(max(0.0, c.get("ls2", 0.0) / c["ln"] - mean * mean))
            lead = Learned(round(mean, 3), _conf(c["ln"], HALF["leads"]), int(round(c["ln"])), src,
                           {"state": x, "band": pb, "sd_s": round(sd, 3)})
        if windup is not None and lead is not None:
            break
    return windup or Learned(None), lead or lead_default


def _plan_attack(models, ti, cls, st, kind, now) -> Learned:
    for src, cl, x in [("class", cls, y) for y in dict.fromkeys((st, _kind_key(kind), ANY)) if y]:
        c = _cell(models, ti, _k("danger", cl, x, ANY), now)
        att = (c or {}).get("att") or {}
        total = sum(att.values())
        if total >= MIN["attack"]:
            best = max(att, key=att.get)
            share = att[best] / total
            return Learned(best, share * _conf(total, HALF["attack"]), int(round(total)), src,
                           {"state": x, "kinds": {k: round(v, 1) for k, v in att.items()}})
    return Learned(None)


def _plan_hit(models, ti, cls, fam, w, b, now) -> Learned:
    for src, lt, cl in _class_levels(ti, cls, fam, cross=False):
        probes = []
        if w != ANY:
            probes.append((w, b))
        probes += [(ANY, b)] if b != ANY else []
        if b == ANY:
            probes.append((ANY, ANY))
        for pw, pb in dict.fromkeys(probes):
            c = _cell(models, lt, _k("shot", cl, pw, pb, ANY), now)
            if c and c.get("n", 0.0) >= MIN["hit"]:
                return Learned(round(c.get("h", 0.0) / c["n"], 3), _conf(c["n"], HALF["hit"]), int(round(c["n"])), src,
                               {"probe": f"{pw}/{pb}"})
    return Learned(None)


# --- the round's numbers (stats, the round report) ----------------------------------------------------------------------
def round_begin(title) -> None:
    """A round starts: its counters start over (the engine calls this when it opens the round's evidence)."""
    ti = _title(title)
    if ti:
        s = _state()
        s["round"][ti] = {"shots": 0, "hits": 0, "kills": 0, "damage": 0, "loss": 0.0, "classes": set(),
                          "since": time.time()}
        if not (s["titles"].get(ti) or {}).get("loaded"):
            with s["lock"]:
                s["need_load"].add(ti)
            _kick()


def round_stats(title) -> dict:
    """The round's facts and what the database knows for the title, as stats keys (numbers, and one bounded line):
    enemy_db_shots / _hits / _kills / _damage (recorded this round), enemy_db_classes_seen (classes this round),
    enemy_db_classes (classes the title has learned anything about), enemy_db_samples (the shots and hits taken
    behind them, every one folded in), enemy_db_learned (classes whose own aim or danger is learned with confidence
    >= 0.5), enemy_db_summary (the top classes' plans)."""
    s = _state()
    ti = _title(title) or "unknown"
    r = s["round"].get(ti) or {}
    view = summary(ti, s["models"], time.time())
    return {"enemy_db_shots": int(r.get("shots", 0)), "enemy_db_hits": int(r.get("hits", 0)),
            "enemy_db_kills": int(r.get("kills", 0)), "enemy_db_damage": int(r.get("damage", 0)),
            "enemy_db_classes_seen": len(r.get("classes") or ()), "enemy_db_classes": view["classes"],
            "enemy_db_samples": view["samples"], "enemy_db_learned": view["learned"],
            "enemy_db_summary": view["text"]}


ROUND_END_WAIT_S = 0.3         # round_end lets the learner fold the round's last facts this long (between rounds, off
                               # the fight: the engine's evidence close writes its Notebook row synchronously too)


def round_end(title, stats: dict | None = None) -> dict:
    """A round ends: the queued facts folded and written (waiting ROUND_END_WAIT_S at most), then its numbers into
    stats (the Notebook row and the round report take them from there). Returns the numbers."""
    flush(wait=True, timeout=ROUND_END_WAIT_S)
    out = round_stats(title)
    if isinstance(stats, dict):
        stats.update(out)
    return out


def _classes(cells: dict) -> dict:
    """{class: (shots, damage events)} of one title's cells: every sample folded in (the raw totals)."""
    out: dict = {}
    for key, cell in list(cells.items()):
        parts = key.split("|")
        if parts[0] == "shot" and len(parts) == 5 and parts[2:] == [ANY, ANY, ANY]:
            cls = parts[1]
            idx = 0
        elif parts[0] == "danger" and len(parts) == 4 and parts[2:] == [ANY, ANY]:
            cls = parts[1]
            idx = 1
        else:
            continue
        if cls in (ANY, "?") or cls.startswith("@"):
            continue
        row = out.setdefault(cls, [0.0, 0.0])
        row[idx] = float(cell.get("N", cell.get("n", 0.0)))
    return {k: (v[0], v[1]) for k, v in out.items()}


def summary(title, models=None, now=None) -> dict:
    """{classes, samples, learned, text, top: [...]}: the title's top classes' plans in one bounded line."""
    s = _state()
    models = s["models"] if models is None else models
    now = time.time() if now is None else now
    ti = _title(title) or "unknown"
    cells = models.get(ti) or {}
    classes = _classes(cells)
    ranked = sorted(classes.items(), key=lambda kv: -(kv[1][0] + kv[1][1]))
    own = ("class", "title_family")                     # what the class itself (or his family in this title) taught
    learned, parts, top = 0, [], []
    for cls, (shots, hurt) in ranked:
        fam = family(ti, cls)
        d = _defaults(ti, None, None, None, None, None, fam, None)
        plan = _plan(models, ti, cls, None, None, fam, None, None, ANY, None, None, d, now)
        near = _plan_danger(models, ti, cls, fam, None, None, "0-2", {"danger": 0.0}, now)
        if (plan.aim.source in own and plan.aim.confidence >= 0.5) or (near.source in own and near.confidence >= 0.5):
            learned += 1
        if len(top) < 3:
            a = plan.aim.value
            bits = [f"{cls}{'(' + fam + ')' if fam else ''}: {shots:.0f} shots"]
            if plan.hit_rate.value is not None and plan.hit_rate.source in own:
                bits[-1] += f" {plan.hit_rate.value:.0%} hit"
            if plan.aim.source in own:
                bits.append(f"aim {a.zone} {a.up_m:.2f}m c{plan.aim.confidence:.1f}")
            if plan.range.source in own:
                bits.append(f"range {plan.range.value[0]:g}-{plan.range.value[1]:g}m")
            if plan.shots_to_kill.value is not None and plan.shots_to_kill.source in own:
                bits.append(f"{plan.shots_to_kill.value:.1f} shots/kill")
            if hurt:
                bits.append(f"hurt us {hurt:.0f}x" + (f", danger 0-2m {near.value:.2f}"
                                                       if near.confidence and near.source in own else ""))
            parts.append(", ".join(bits))
            top.append({"class": cls, "family": fam, "shots": round(shots, 1), "damage": round(hurt, 1),
                        "plan": plan.to_dict()})
    worst = _worst_state(models, ti, now)
    if worst:
        parts.append(worst)
    text = "; ".join(parts)
    if len(text) > SUMMARY_MAX:
        text = text[:SUMMARY_MAX - 3] + "..."
    return {"classes": len(classes), "samples": int(round(sum(a + b for a, b in classes.values()))),
            "learned": learned, "text": text, "top": top}


def _worst_state(models, ti, now) -> str:
    best = None
    for key, cell in list((models.get(ti) or {}).items()):
        parts = key.split("|")
        if parts[0] != "pre" or len(parts) != 4 or parts[1] in (ANY,) or parts[3] != ANY:
            continue
        c = _view(cell, now)
        if c.get("on", 0.0) < MIN["onsets"]:
            continue
        v = c.get("n", 0.0) / c["on"]
        if best is None or v > best[0]:
            lead = c["ls"] / c["ln"] if c.get("ln", 0.0) >= 1.0 else None
            best = (v, parts[1], parts[2], lead, c["on"])
    if best is None:
        return ""
    v, cls, st, lead, on = best
    return f"wind-up: {cls} {st} hurts {min(1.0, v):.0%} of {on:.0f} onsets" + (f", {lead:.1f}s lead" if lead else "")


# --- the read-only view (GET /api/mercs/enemy-knowledge) ---------------------------------------------------------------
def inspect(title=None, *, root_dir=None, enemy_class=None, recent: int = 20, now=None) -> dict:
    """For humans and sparkDeux: without a title, the titles the database holds; with one, per class the learned plan
    (aim, range, fire mode, shots to kill, danger by band), the states that come before damage, the sample counts and
    the recent outcomes. Reads the stored database only (a running bot's last FLUSH_S of facts may not be in yet)."""
    base = Path(root_dir) if root_dir is not None else root()
    now = time.time() if now is None else now
    recent = max(0, min(100, int(recent or 0)))
    names = sorted(d.name for d in base.iterdir() if (d / DB_NAME).is_file()) if base.is_dir() else []
    if not title:
        titles = []
        for name in names:
            with closing(_ro(base / name / DB_NAME)) as db:
                counts = dict(db.execute("select kind, count(*) from samples group by kind").fetchall())
                sources = dict(db.execute("select coalesce(source,''), count(*) from samples group by source").fetchall())
                last = db.execute("select max(ts) from samples").fetchone()[0]
                cells = _read_cells(db)
            titles.append({"title": name, "shots": counts.get("shot", 0), "damage": counts.get("damage", 0),
                           "sources": sources, "last_sample_at": last, "classes": len(_classes(cells)),
                           "cells": len(cells)})
        return {"schema": "gbox.mercs.enemy-db/1", "root": str(base), "titles": titles}
    ti = _title(title)
    if not ti:
        raise ValueError(f"bad title {title!r}")
    if ti not in names:
        raise FileNotFoundError(f"no enemy knowledge for {ti}")
    models = {}
    for name in names:
        with closing(_ro(base / name / DB_NAME)) as db:
            models[name] = _read_cells(db)
    classes = _classes(models[ti])
    wanted = _cls(enemy_class) if enemy_class else None
    ranked = [c for c, _ in sorted(classes.items(), key=lambda kv: -(kv[1][0] + kv[1][1]))
              if wanted is None or c == wanted][:60]
    if wanted is not None and wanted not in classes:
        raise FileNotFoundError(f"no samples of {wanted} in {ti}")
    out_classes = []
    with closing(_ro(base / ti / DB_NAME)) as db:
        meta = dict(db.execute("select key, value from meta").fetchall())
        for cls in ranked:
            fam = family(ti, cls)
            d = _defaults(ti, None, None, None, None, None, fam, None)
            plan = _plan(models, ti, cls, None, None, fam, None, None, ANY, None, None, d, now)
            danger = {}
            for name in BAND_NAMES:
                lo, hi = BAND_EDGES[name]
                dd = _defaults(ti, None, None, None, (lo + min(hi, lo + 5.0)) / 2.0, None, fam, None)
                danger[name] = _plan_danger(models, ti, cls, fam, None, None, name, dd, now).to_dict()
            whole = _cell(models, ti, _k("shot", cls, ANY, ANY, ANY), now) or {}
            hurt = _cell(models, ti, _k("danger", cls, ANY, ANY), now) or {}
            rows = db.execute(f"select {','.join(SAMPLE_COLS)} from samples where cls=? order by ts desc limit ?",
                              (cls, recent)).fetchall() if recent else []
            out_classes.append({
                "class": cls, "family": fam, "plan": plan.to_dict(), "danger_by_band": danger,
                "states": _class_states(models, ti, cls, now),
                "samples": {"shots": round(whole.get("n", 0.0), 1), "hits": round(whole.get("h", 0.0), 1),
                            "kills": round(whole.get("k", 0.0), 1), "damage": round(hurt.get("n", 0.0), 1),
                            "exposure_s": round(hurt.get("e", 0.0), 1),     # effective (aged, capped) - and
                            "shots_total": int(whole.get("N", 0.0)), "damage_total": int(hurt.get("N", 0.0))},   # all
                "recent": [_sample_view(r) for r in rows]})
    return {"schema": "gbox.mercs.enemy-db/1", "title": ti, "meta": meta, "classes": out_classes,
            "class_map": class_rows(ti), "units": "metres, seconds; danger within %gs" % DANGER_WINDOW_S}


def _class_states(models, ti, cls, now) -> list:
    rows = []
    cells = models.get(ti) or {}
    for key, cell in list(cells.items()):
        parts = key.split("|")
        if parts[0] != "danger" or len(parts) != 4 or parts[1] != cls or parts[2] == ANY or parts[3] != ANY:
            continue
        c = _view(cell, now)
        pre = _cell(models, ti, _k("pre", cls, parts[2], ANY), now) or {}
        rows.append({"state": parts[2], "kind": state_kind(ti, parts[2]) if not parts[2].startswith("~") else parts[2][1:],
                     "damage": round(c.get("n", 0.0), 1), "exposure_s": round(c.get("e", 0.0), 1),
                     "onsets": round(pre.get("on", 0.0), 1), "followed": round(pre.get("n", 0.0), 1),
                     "lead_s": round(pre["ls"] / pre["ln"], 3) if pre.get("ln", 0.0) >= 1.0 else None,
                     "attack": max(c["att"], key=c["att"].get) if c.get("att") else None})
    rows.sort(key=lambda r: -(r["damage"] + r["followed"]))
    return rows[:12]


def _sample_view(row) -> dict:
    r = dict(zip(SAMPLE_COLS, row))
    out = {k: r[k] for k in ("ts", "kind", "state", "weapon", "dist_m", "outcome", "hp_delta", "zone", "up_m",
                             "attack", "source") if r[k] is not None}
    return out
