"""RE5 Gold (BLUS30491) Mercenaries: fire while acquiring and tracking nearby living enemies.

The game's own laser sight is the truth about a shot: the bullet goes from the laser's origin (the muzzle) to the laser
dot, the first thing the ray hits (uLaserSight, an FxCore unit: +0x200 origin, +0x30 dot). The camera ray is not the
shot ray (5 deg off, up to 15), and the body's yaw is not either (the upper body aims inside a cone): a loop closed on
anything but the dot misses. So every tick:
  * the dot is read and tested against the target Majini's head (a sphere HEAD_R at HEAD_H above his feet) and his
    body (a capsule BODY_R wide from KNEE_H to SHOULDER_H): on the head = a headshot, on the body = a hit, elsewhere
    = the ray hits something else first (the floor, a wall, a prop) or passes him;
  * the aim approaches a preferred anatomical zone until any body region is exposed, then keeps that exposed
    region under the dot. Stick correction follows the measured shot ray rather than the camera ray;
  * a loaded direct-fire gun holds L1 + R1 during acquisition and tracking, including off-reticle frames. This is
    the operator's later continuous-fire policy, not a claim that every shot will land. Confirmed cover lowers the
    gun for repositioning. Splash weapons still require first-hit overlap and safe impact clearance;
  * every shot the game fires is seen in RAM (the player's current action object, player +0x30B0, entering the
    weapon-fire action 0x0163DFC0 / its frame counter +0x20 starting over) and scored: a hit when any Majini's health
    fell within HIT_S, a headshot when the dot was on the head as it left; a miss is classified by what the dot was on
    (the audit the operator asked for: stats and the run-lessons log);
  * an empty weapon (the in-hand inventory slot's rounds at 0, player +0x22E0 + 0x30 n: +0x8 id, +0xC rounds, +0x20
    in hand) is reloaded (L1 + cross); the weapon switch is the title driver's;
  * a Majini stunned by a headshot (his health fell with the dot on his head; he stands) is closed in on for the
    finisher prompt ("Hook" / "Uppercut": the action button of kind 3 the driver reports as "square", which the
    engine presses at once; each finisher kill is +5 s);
  * what it learns (per character, per weapon id: shots, hits, headshots, finishers, seconds gained, the trigger
    mode, the head tolerance) is kept under gbox-data (TUNABLES_FILE) and adjusted after every round. Historical
    settle-time metadata remains compatible, but it no longer delays a confirmed exposed shot.

This layer's optional RAM write is the player's aim pitch (+0x1AA0) while aiming. The independently enabled mods
health guard owns health maintenance; rapid-fire verification here only reads its global and weapon values.
"""
from __future__ import annotations

import json
import math
import os
import struct
import time
from pathlib import Path

from .. import lessons as L
from ..aim import Shots

MAP_ID = "BLUS30491"

S_PLAYER, S_ENEMY, S_UNIT = 0x017FEB34, 0x017FDB60, 0x0191D700
UNIT_LINES, LINE_STRIDE, LINE_FIRST, UNIT_NEXT = 0x24, 0x20, 0xC, 0x8
FX_LINE, FX_MAX = 18, 200
LASER_VT = 0x015BD958                  # uLaserSight (app 01.01)
LASER_ORIGIN, LASER_DOT = 0x200, 0x30  # the muzzle; the ray's hit point (duplicates at +0xD0, +0x150, +0x210)
P_ACTION, P_PITCH, P_ROT, P_POS = 0x845, 0x1AA0, 0x40, 0x30
P_ACTION_OBJ = 0x1238                  # -> the current cPlAction: the weapon-fire action while a shot runs (a read-only
                                       # scan of the player object for pointers to the action vtables, live 2026-10-21,
                                       # session 3d4f1ba4de924bc3; +0x30B0, named first, is the cNetPlayer)
FIRE_VT, READY_VT, RELOAD_VT = 0x0163DFC0, 0x0163E038, 0x0163DF88   # weapon_fire / weapon_ready_loop / reload
ACT_PHASE, ACT_SECONDS, ACT_FRAMES = 0x14, 0x1C, 0x20                 # on the action: per shot, from 0
P_FIRE_CMD = 0x2F04                    # u32: 4 on the frame a shot leaves (the pad's fire command; live 2026-10-21:
                                       # on every tick the in-hand rounds fell, 0 between), the fallback shot signal
INFINITE_AFTER = 12                    # fire frames with the rounds standing: the no-ammo flag is on (#771)
P_INV, INV_SLOT, INV_SLOTS = 0x22E0, 0x30, 24
INV_ID, INV_ROUNDS, INV_HAND, INV_USED = 0x8, 0xC, 0x20, 0x2D
AIMING = 2

HEAD_H, HEAD_R = 160.0, 22.0           # a Majini's head: a sphere this far above his feet, this wide (cm)
KNEE_H, SHOULDER_H, BODY_R = 45.0, 145.0, 36.0   # his body: a capsule between these heights, this wide
THIGH_LO, THIGH_HI, THIGH_R, THIGH_H = 45.0, 95.0, 26.0, 72.0   # his thighs: the leg-stun zone, aimed at THIGH_H
CHEST_H = 110.0                         # the default aim point: centre mass, past helmets and around shields
DEFAULT_ZONE = "body"                   # zone_for's answer without the strategy's say ("head": the #3046 steady head aim)
THREAT_BLAST = True                     # False: only the sight / dot gates decide (the far-target gate's own tests)
THREAT_BLAST_R = 500.0                  # a Majini this near on the player's level, roughly faced: the trigger stays down
THREAT_BLAST_FACING = math.radians(30)
# The kill policy (docs/mercenaries_re5_meta.md section 1.3: "melee is the clock"): a leg shot until he kneels, then
# the finisher (+5 s, i-frames) - the main kill method; a headshot (a head stun -> Headbutt / Uppercut, or the kill)
# when he is far or the combo window is short; never a second melee on a boss (the wild swing).
FINISHER_SETUP_R = 650.0               # a Majini this near is leg-stunned and finished (the prompt comes at ~1.5 m)
COMBO_SHORT_S = 4.0                    # the combo window under this: a kill now (the head), not a stun setup
BOSS_HP = 2500                         # health above this: a boss (Executioner, Chainsaw ...): one melee, then guns
HEAD_LEAD_S = 0.06                     # the dot is a frame old and the trigger two more: lead his head by this
TAP_DOWN_S, TAP_UP_S = 0.03, 0.03     # fast press/release when the rapid-fire patch is absent
HOLD_NO_SHOT_S = 0.45                  # held on target this long without a shot: this weapon wants taps
TAPS_NO_SHOT = 8                       # ... taps without a shot: it wants a hold (the Gatling)
HOLD_FIRE_IDS = frozenset({0x03, 0x09, 0x13, 0x15, 0x1D})  # verified table IDs; 0x25 was not the Gatling
STEADY_HEAD = True                     # False: the older fire-on-first-overlap policy (tests of that gate)
HEAD_SETTLE_S = 0.10                   # the dot held on his head this long before the trigger (a steady aim, #3046)
HEAD_PATIENCE_S = 0.60                 # the dot on his body (head not reachable) this long: take the body shot
SETTLE_S = 0.08                        # legacy persisted tuning metadata; a first-hit overlap now fires immediately
FRONT_YAW, FRONT_PITCH = math.radians(60), math.radians(45)  # candidate cone, not a visibility claim
WALL_CONE = math.radians(10)           # a first hit this short, within this cone of him: a wall in front (coaching #3002)
BLOCKED_S = 0.8                        # try another candidate after a measured first hit ends before this one
FIRE_TIMER_FPS, FIRE_TIMER_ORIG = 0x0169E098, 60.0
WEAPON_TABLE, WEAPON_STRIDE, WEAPON_INTERVAL = 0x01817530, 0x140, 0x90
AIM_TURN_RAD_S = 0.52                  # the right stick while aiming: ~30 deg/s (the mods agent scales it)
FINE = math.radians(4)                 # closer than this: the stick in pulses (a tick on, a tick off)
STEER_RAY_CM = 50.0                   # near-muzzle endpoints amplify animation/read skew into large angular errors
STEER_REACQUIRE_S, STEER_STEP_S = 0.4, 0.25  # conservative trial bounds, not decoded engine constants
PITCH_WRITE = False                    # the pitch straight into +0x1AA0 (else the stick). Off: the game recomputes
                                       # +0x1AA0 (and +0x31D4, +0x2F3C, the yaw +0x14F4, the quaternion) every frame
                                       # from its own controller - a written value lasted one frame (probe 2026-10-21)
PITCH_GAIN = 1.0                       # how much of the pitch error one write takes out
HIT_S = 0.35                           # a shot's health drop comes within this
STUN_S, STUN_NEAR, STUN_FAR = 2.2, 110.0, 700.0   # a headshot stuns this long: close in from this far for the finisher
HIT_RATE_WANT = 0.95                   # a round under this tightens the aim
TUNABLES_FILE = "re5_combat.json"      # under the learn dir (gbox-data/mercs/learned/BLUS30491)
EMPTY_RELOAD_EVERY_S = 1.5             # L1 + cross this often while the weapon is empty
ENGAGE_R = 3000.0                     # shared with the driver's existing engagement range; cm, not visibility
# Fire only down a measured line to him (operator 2026-10-22: "Right now he is shooting at nonsense"; live the same day
# 11.6 of 36 s aiming with the dot on no Majini, much of it 1-2 m off the muzzle): the dot on him, or a ray that reaches
# at least his distance within FIRE_CONE of him (tracking a moving Majini). A dot short of him or at the muzzle (a
# wall, the ground, a fence) holds the trigger.
FIRE_CONE, FIRE_SLACK = math.radians(4), 60.0   # the ray this close in angle, ending no more than this short of him
SWING_TURN = math.radians(45)          # a Majini further off the body's heading than this: turn with the gun down
POINT_BLANK = 110.0                   # a Majini this near on the player's level needs no ray (hit recovery, the gun
                                       # coming up): nothing fits between them


def line_to(ray, aim_at, foot=None) -> bool:
    """Whether the laser ray (origin, dot) runs to him: it ends no more than FIRE_SLACK short of the aim point, within
    FIRE_CONE (or his body's half width, close up) of it - or, given his feet, it passes through his head or body on
    the way to a dot beyond him."""
    if ray is None:
        return False
    origin, dot = ray
    want = math.dist(origin, aim_at)
    have = math.dist(origin, dot)
    if want < 1.0 or have < want - FIRE_SLACK:
        return False
    cos = sum((dot[k] - origin[k]) * (aim_at[k] - origin[k]) for k in range(3)) / (have * want)
    if math.acos(max(-1.0, min(1.0, cos))) <= max(FIRE_CONE, math.atan2(BODY_R, want)):
        return True
    if foot is None:
        return False
    direction = tuple((dot[k] - origin[k]) / have for k in range(3))
    for h in (HEAD_H, 110.0, THIGH_H):                         # his head, chest and thighs
        along = sum((foot[k] + (h if k == 1 else 0.0) - origin[k]) * direction[k] for k in range(3))
        if 0.0 < along <= have and dot_on(tuple(origin[k] + along * direction[k] for k in range(3)),
                                                      foot) is not None:
            return True
    return False

CHARACTERS = {0x016172B8: "barry"}     # the player's vtable -> the character (the rest named by their vtable)
ENABLED = True                         # the title driver's Bot hands the fight here (False: its own aim loop)


def ptr_ok(p) -> bool:
    return isinstance(p, int) and 0x30000000 <= p < 0x40000000


def u32(m, a) -> int:
    return struct.unpack(">I", m.rd(a, 4))[0]


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def heading(dx: float, dz: float) -> float:
    return math.atan2(dx, dz)


# --- what the laser says -----------------------------------------------------------------------------------------
def dot_on(dot, foot, head_r: float = HEAD_R, body_r: float = BODY_R) -> str | None:
    """Where the laser dot sits on a Majini standing at foot: "head" (inside the head sphere), "leg" (the thighs),
    "body" (inside the body capsule), else None (the ray ends somewhere else: short of him, past him, beside him)."""
    dx, dy, dz = dot[0] - foot[0], dot[1] - foot[1], dot[2] - foot[2]
    if math.sqrt(dx * dx + (dy - HEAD_H) ** 2 + dz * dz) <= head_r:
        return "head"
    flat = math.hypot(dx, dz)
    if flat <= THIGH_R and THIGH_LO <= dy <= THIGH_HI:
        return "leg"
    if flat <= body_r and KNEE_H - 10 <= dy <= SHOULDER_H + 20:
        return "body"
    return None


def zone_for(tgt: dict, dist: float, combo_timer, combo) -> str:
    """Where to put the shot: "leg" (the stun -> finisher loop) for a Majini within FINISHER_SETUP_R while the combo
    window allows it (over COMBO_SHORT_S, or no combo running), "head" when he is far, the window short, or he is a
    boss. The driver's strategy may say with tgt["zone"]."""
    if tgt.get("zone") in ("leg", "head", "body"):
        return tgt["zone"]
    # Operator 2026-10-22: the head-only aim (#3046) left him "just standing there letting these people devastate him" -
    # "These enemies are wearing helmets, some of them are using shields ... He needs to just hit them wherever he can
    # hit them." The body (chest height, the biggest target) by default, fired on as soon as the dot is anywhere on him;
    # the head and the leg stun only on the strategy's say.
    return DEFAULT_ZONE


def ray_error(origin, dot, target) -> tuple[float, float]:
    """(yaw, pitch) radians to turn the ray origin -> dot onto target (+ yaw = left, + pitch = up)."""
    ox, oy, oz = origin
    want_yaw = heading(target[0] - ox, target[2] - oz)
    have_yaw = heading(dot[0] - ox, dot[2] - oz)
    want_pitch = math.atan2(target[1] - oy, max(math.hypot(target[0] - ox, target[2] - oz), 1.0))
    have_pitch = math.atan2(dot[1] - oy, max(math.hypot(dot[0] - ox, dot[2] - oz), 1.0))
    return wrap(want_yaw - have_yaw), want_pitch - have_pitch


AIM_FIRE_YAW, AIM_FIRE_PITCH = math.radians(7), math.radians(5)   # fire only with the dot this close to the aim point


def line_of_sight_aim(ray, aim_at, where, foot) -> bool:
    """Whether the shot may leave the gun: the dot sits on him, or the ray points at the aim point within a few
    degrees and does not end on the floor short of him. Coaching note 3: R1 held while the dot was on the ground
    (turning toward him, or aimed below him) fired the magazine into the floor and lost time."""
    if where is not None:
        return True
    if ray is None:
        return False
    origin, dot = ray
    yaw, pitch = ray_error(origin, dot, aim_at)
    if abs(yaw) > AIM_FIRE_YAW or abs(pitch) > AIM_FIRE_PITCH:
        return False
    flat_dot, flat_tgt = math.hypot(dot[0] - origin[0], dot[2] - origin[2]), math.hypot(foot[0] - origin[0], foot[2] - origin[2])
    short_on_floor = flat_dot < flat_tgt - BODY_R * 2 and dot[1] < foot[1] + KNEE_H
    return not short_on_floor


def valid_ray(origin, dot):
    """Keep endpoint evidence separate from whether its short baseline can guide the stick."""
    try:
        origin, dot = tuple(origin), tuple(dot)
        if (len(origin) == len(dot) == 3 and any(origin)
                and all(math.isfinite(v) for v in (*origin, *dot)) and math.dist(origin, dot) >= 5.0):
            return origin, dot
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def steering_ray(ray, target):
    """A defensive direction baseline, reduced for genuinely close targets; not a visibility test.

    Run9 contains 6 cm rays reversing elevation by 139 degrees while the player's reported pitch barely changes.
    Endpoints can still prove an overlap/obstruction, but a tiny muzzle-to-dot vector must not drive full stick.
    """
    return math.dist(*ray) >= min(STEER_RAY_CM, math.dist(ray[0], target) * 0.5)


class Laser:
    """uLaserSight in sUnit's FxCore line: found once, checked by its vtable every read, looked for again when gone."""

    def __init__(self, m):
        self.m = m
        self.unit = None
        self.looked = -1e9

    def find(self, now: float):
        m = self.m
        if self.unit is not None:
            try:
                if u32(m, self.unit) == LASER_VT:
                    return self.unit
            except (ValueError, OSError, struct.error):
                pass
            self.unit = None
        if now - self.looked < 1.0:
            return None
        self.looked = now
        su = u32(m, S_UNIT)
        if not ptr_ok(su):
            return None
        u, n = u32(m, su + UNIT_LINES + LINE_STRIDE * FX_LINE + LINE_FIRST), 0
        while ptr_ok(u) and n < FX_MAX:
            if u32(m, u) == LASER_VT:
                self.unit = u
                return u
            u, n = u32(m, u + UNIT_NEXT), n + 1
        return None

    def read(self, now: float):
        """(origin, dot) or None (no laser: the gun is down)."""
        u = self.find(now)
        if u is None:
            return None
        o = struct.unpack(">3f", self.m.rd(u + LASER_ORIGIN, 12))
        d = struct.unpack(">3f", self.m.rd(u + LASER_DOT, 12))
        return valid_ray(o, d)


class Writer:
    """Writes into the guest: through the memory view's own write() when it has one that works, else a second
    handle on /proc/<pid>/mem (r5mem.Guest keeps pid and base). ok is False when nothing can write (then the stick)."""

    def __init__(self, m):
        self.m, self.f, self.base, self.ok = m, None, None, False
        pid, base = getattr(m, "pid", None), getattr(m, "base", None)
        if callable(getattr(m, "write", None)) and getattr(m, "writable", False):
            self.ok = True
        elif pid and base is not None:
            try:
                self.f = open(f"/proc/{pid}/mem", "r+b", 0)
                self.base, self.ok = base, True
            except OSError:
                self.ok = False

    def write(self, addr: int, data: bytes) -> bool:
        if not self.ok:
            return False
        try:
            if self.f is not None:
                self.f.seek(self.base + addr)
                self.f.write(data)
            else:
                self.m.write(addr, data)
            return True
        except OSError:
            return False


class Trigger:
    """R1 for one weapon: a hold (the Gatling) or taps; learned from whether shots come."""

    def __init__(self, mode: str = "tap"):
        self.mode = mode
        self.down_at = None
        self.up_at = -1e9
        self.on_since = None
        self.taps_without = 0
        self.last_shot = -1e9

    def keys(self, now: float, on_target: bool, shot: bool) -> set:
        if shot:
            self.last_shot, self.taps_without = now, 0
        if not on_target:
            self.on_since, self.down_at = None, None
            return set()
        self.on_since = self.on_since or now
        if self.mode == "hold":
            if now - self.on_since > HOLD_NO_SHOT_S and now - self.last_shot > HOLD_NO_SHOT_S:
                self.mode, self.on_since = "tap", now        # a held R1 fired once (or not at all): taps
            return {"r1"}
        if self.down_at is not None:
            if now - self.down_at < TAP_DOWN_S:
                return {"r1"}
            self.down_at, self.up_at = None, now
            self.taps_without += 1
            if self.taps_without >= TAPS_NO_SHOT:            # taps fire nothing: it wants a hold
                self.mode, self.taps_without = "hold", 0
            return set()
        if now - self.up_at >= TAP_UP_S:
            self.down_at = now
            return {"r1"}
        return set()


class Tunables:
    """Per character, per weapon id: the counts and the knobs, kept in learn_dir / TUNABLES_FILE."""

    def __init__(self, learn_dir: Path | None):
        self.path = Path(learn_dir) / TUNABLES_FILE if learn_dir else None
        self.d: dict = {"weapons": {}, "rounds": []}
        if self.path and self.path.is_file():
            try:
                self.d = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass

    def weapon(self, character: str, wid: int) -> dict:
        key = f"{character}:{wid:#x}"
        w = self.d["weapons"].setdefault(key, {"mode": "hold" if wid in HOLD_FIRE_IDS else "tap", "head_r": HEAD_R,
                                               "settle_s": SETTLE_S, "shots": 0, "hits": 0, "headshots": 0,
                                               "finishers": 0, "time_gained_s": 0.0, "rounds": 0})
        return w

    def save(self):
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.d, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass


class Combat:
    """The fight with one Majini, one tick at a time (the title driver's Bot hands over the target it chose):
    tick(snap, p, tgt, now) -> {"hold": keys} | {"tap": key}. Reads the laser and the action object itself (m);
    the inventory from snap["inventory"] when the driver read it, else from RAM."""

    def __init__(self, m, stats: dict, clock=time.time, learn_dir=None, lessons=None):
        self.m, self.stats, self.clock = m, stats, clock
        if learn_dir is None:                 # the deployment: beside the lessons under gbox-data
            learn_dir = L.ROOT.parent / "learned" / MAP_ID
        self.run_id = time.strftime("%Y%m%d-%H%M%S", time.localtime()) + "-combat"
        self.lessons = lessons or (lambda e: L.append(MAP_ID, e, run=self.run_id))
        self.laser = Laser(m)
        self.writer = Writer(m)
        self.tun = Tunables(learn_dir)
        self.shots = Shots(gun_gap_s=0.0)
        self.shots.HIT_S = HIT_S
        self._scored_hits = self._scored_misses = 0
        self._observed_snap = None
        self._observation = None
        self.blocked_until = {}
        self.rapid_checked = -1e9
        self.rapid_fire = False
        self.step_until = 0.0
        self.step_side = "lleft"
        self.near_ray_since = self.near_ray_key = None
        self.near_ray_move_until = 0.0
        self.triggers: dict = {}
        self.act_seen = None                  # (vtable, frames) of the action object last tick
        self.yaw_pulse = self.pitch_pulse = 0
        self.dot_head_since = None
        self.dot_body_since = None
        self.last_dot = None                  # (where, tgt ptr, t) the dot at the last tick: what a shot left on
        self.stunned: dict = {}               # Majini ptr -> until
        self.melees: dict = {}                # Majini ptr -> finishers pressed on him (a boss gets one)
        self.zone = "head"
        self.reload_at = -1e9
        self.character = "?"
        self.wid = None
        self.round_t0 = None
        self.round_counts = {"shots": 0, "hits": 0, "headshots": 0, "finishers": 0, "time_gained_s": 0.0}
        self.last_timer = None
        self.finishers_seen = 0
        self.infinite = False                 # the rounds don't count (the no-ammo flag): shots from the fire command
        self._fire_cmd_seen = 0
        self._cmd_shot_at = -1e9
        for k in ("shots", "hits", "misses", "headshots", "accuracy", "miss_short", "miss_past", "miss_beside",
                  "miss_moved", "finishers", "reloads", "pitch_writes", "stun_runs"):
            self.stats.setdefault(k, 0)
        for k in ("shots", "hits", "misses", "headshots", "legshots", "miss_short", "miss_past", "miss_beside",
                  "miss_moved"):
            self.stats[k] = 0
        self.stats["accuracy"] = 0.0

    # --- RAM ---
    def _action(self):
        try:
            pl = self._player_ptr()
            ap = u32(self.m, pl + P_ACTION_OBJ) if pl else 0
            if not ptr_ok(ap):
                return None
            vt = u32(self.m, ap)
            fr = struct.unpack(">f", self.m.rd(ap + ACT_FRAMES, 4))[0]
            return vt, fr
        except (ValueError, OSError, struct.error):
            return None

    def _player_ptr(self) -> int:
        sp = u32(self.m, S_PLAYER)
        pl = u32(self.m, sp + 0x28) if ptr_ok(sp) else 0
        return pl if ptr_ok(pl) else 0

    def _in_hand(self, snap, pl):
        """(weapon id, rounds) of the slot in hand."""
        inv = snap.get("inventory")
        if inv:
            s = next((x for x in inv if x.get("hand")), None)
            if s:
                return s.get("item", s.get("id", 0) & 0xFF), s.get("rounds")
        try:
            raw = self.m.rd(pl + P_INV, INV_SLOT * INV_SLOTS)
        except (ValueError, OSError):
            return None, None
        for k in range(INV_SLOTS):
            o = k * INV_SLOT
            if struct.unpack_from(">I", raw, o + INV_HAND)[0] == 1 and raw[o + INV_USED]:
                return struct.unpack_from(">I", raw, o + INV_ID)[0] & 0xFF, struct.unpack_from(">i", raw, o + INV_ROUNDS)[0]
        return None, None

    def _shot(self, pl: int, rounds, aiming: bool, now: float) -> bool:
        """A shot the game fired since the last tick: the in-hand rounds fell (the surest, until infinite ammo), else
        the action entering weapon_fire / its frames starting over (where the action pointer is one), else the fire
        command word (one frame) on a tick while aiming with a loaded gun. Infinite ammo (the package's no-ammo flag:
        the rounds stand while the fire command keeps coming) is noticed after INFINITE_AFTER such frames."""
        was_rounds, self.rounds_seen = getattr(self, "rounds_seen", None), rounds
        if rounds is not None and was_rounds is not None and 0 < was_rounds - rounds <= 3:
            self.act_seen = self._action()
            self._fire_cmd_seen = 0
            return True
        a = self._action()
        was, self.act_seen = self.act_seen, a
        if a is not None and was is not None and a[0] in (FIRE_VT, READY_VT, RELOAD_VT):
            return a[0] == FIRE_VT and (was[0] != FIRE_VT or a[1] < was[1] - 0.5)
        try:
            cmd = u32(self.m, pl + P_FIRE_CMD) if pl else 0
        except (ValueError, OSError, struct.error):
            return False
        fire_frame = aiming and cmd == 4 and (rounds is None or rounds > 0) and now - self._cmd_shot_at > 0.025
        if not fire_frame:
            return False
        self._cmd_shot_at = now
        if rounds is not None and not self.infinite:        # a counting gun fires and its rounds stand: not yet a
            self._fire_cmd_seen += 1                        # shot - unless that goes on: infinite ammo
            if self._fire_cmd_seen >= INFINITE_AFTER:
                self.infinite = True
                self.stats["infinite_ammo"] = True
            return False
        return True

    def observe(self, snap, now, *, active=True):
        """Account for a snapshot even while a prompt or the walker owns the pad. Same snapshot: once only."""
        if self._observed_snap is snap:
            return self._observation
        self._observed_snap = snap
        if active:
            self.start_round(now)
        p = snap.get("player") or {}
        pl = p.get("ptr") or self._player_ptr()
        wid, rounds = self._in_hand(snap, pl)
        if active:
            self.character = CHARACTERS.get(u32(self.m, pl), f"vt{u32(self.m, pl):#x}") if pl else "?"
            self.wid = wid
        shot = active and self._shot(pl, rounds, p.get("action") == AIMING, now)
        if shot:
            self._on_shot(now)
        self.shots.update(snap.get("enemies") or [], now)
        self._score(now)
        if active:
            self._count_kills(snap)
            self._clock(snap, now)
        self._observation = (pl, wid, rounds, shot)
        return self._observation

    def suspend_observation(self, now):
        """A missing/loading snapshot cannot establish damage or time gained across its gap."""
        self.last_timer = None
        self.act_seen = self.rounds_seen = self.last_dot = None
        self._observed_snap = self._observation = None
        self.shots.update([], now)
        self._score(now)

    def _ray(self, snap, now):
        if "laser" not in snap:
            return self.laser.read(now)
        sl = snap.get("laser")
        if not sl or not sl.get("from") or not sl.get("at") or not any(sl["from"]):
            return None
        return valid_ray(sl["from"], sl["at"])

    def _ready(self, p):
        action = self.act_seen
        return p.get("action") == AIMING or (p.get("action") not in (4, 5) and action is not None
                                             and action[0] in (READY_VT, FIRE_VT))

    @staticmethod
    def front_candidate(snap, p, e):
        """A conservative front-camera sector. Cover and actual screen projection remain unknown."""
        cam = snap.get("camera")
        if cam and cam.get("eye") and cam.get("at") and math.dist(cam["eye"], cam["at"]) > 1.0:
            origin, at = cam["eye"], cam["at"]
            yaw = heading(at[0] - origin[0], at[2] - origin[2])
            pitch = math.atan2(at[1] - origin[1], max(math.hypot(at[0] - origin[0], at[2] - origin[2]), 1.0))
        else:
            origin = (p["pos"][0], p["pos"][1] + 140.0, p["pos"][2])
            yaw, pitch = p["rot"], 0.0
        dx, dy, dz = e["pos"][0] - origin[0], e["pos"][1] + 110.0 - origin[1], e["pos"][2] - origin[2]
        return abs(wrap(heading(dx, dz) - yaw)) <= FRONT_YAW and \
            abs(math.atan2(dy, max(math.hypot(dx, dz), 1.0)) - pitch) <= FRONT_PITCH

    @staticmethod
    def ray_blocked(ray, foot):
        """Only an aligned first-hit ray ending well before the target establishes an obstruction."""
        origin, dot = ray
        length = math.dist(origin, dot)
        if length < 5.0:
            return False
        direction = tuple((dot[k] - origin[k]) / length for k in range(3))
        centre = (foot[0], foot[1] + 110.0, foot[2])
        along = sum((centre[k] - origin[k]) * direction[k] for k in range(3))
        projected = tuple(origin[k] + along * direction[k] for k in range(3))
        if along <= length + BODY_R + 25.0:
            return False
        if dot_on(projected, foot) is not None:
            return True
        # A wall straight ahead: the first hit is a solid surface well short of him and the aim is only a few degrees
        # off him, so the shot would hit the wall (the ray may miss his capsule by a hand's width at range).
        # Rays shorter than STEER_RAY_CM carry too little direction to claim this; a wide miss stays "unknown".
        if length < STEER_RAY_CM:
            return False
        to_c = tuple(centre[k] - origin[k] for k in range(3))
        norm = math.sqrt(sum(v * v for v in to_c))
        cos = sum(to_c[k] * direction[k] for k in range(3)) / max(norm, 1.0)
        return math.acos(max(-1.0, min(1.0, cos))) <= WALL_CONE

    def observe_awareness(self, snap, p, now):
        if getattr(self, "_awareness_tick", None) == (id(snap), now):
            return self._awareness_ray
        self._awareness_tick = (id(snap), now)
        ray = self._ray(snap, now) if self._ready(p) else None
        self._awareness_ray = ray
        awareness = []
        for enemy in snap.get("enemies") or ():
            key = enemy.get("ptr", enemy.get("slot"))
            hit = ray is not None and dot_on(ray[1], enemy["pos"]) is not None
            if hit:
                self.blocked_until.pop(key, None)
            elif ray is not None and self.ray_blocked(ray, enemy["pos"]):
                self.blocked_until[key] = now + BLOCKED_S
            blocked = self.blocked_until.get(key, 0) > now
            awareness.append({"id": key, "hp": enemy.get("hp"), "hp_max": enemy.get("hp_max"),
                              "distance_cm": round(math.dist(p["pos"], enemy["pos"]), 1),
                              "visibility": "clear" if hit else "blocked" if blocked else "unknown"})
        self.awareness = sorted(awareness, key=lambda row: row["distance_cm"])
        self.stats["nearby_enemies"] = sum(row["distance_cm"] <= 350 for row in awareness)
        self.stats["enemy_awareness_count"] = len(awareness)
        return ray

    def choose_target(self, snap, p, enemies, now):
        self.target_exposed = False
        enemies = [e for e in enemies if (e.get("hp") or 0) > 0]
        ray = self.observe_awareness(snap, p, now)
        # Immediate threats outrank distant crosshair targets, bonus routes and score optimizations.
        # Unknown sight lines remain explicitly unknown; direct-fire guns fire during acquisition by operator policy.
        close = [e for e in enemies if math.dist(p["pos"], e["pos"]) <= 350
                 and self.blocked_until.get(e.get("ptr", e.get("slot")), 0) <= now]
        if close:
            exposed_close = [e for e in close if ray is not None and dot_on(ray[1], e["pos"]) is not None]
            target = min(exposed_close or close, key=lambda e: math.dist(p["pos"], e["pos"]))
            self.target_exposed = ray is not None and dot_on(ray[1], target["pos"]) is not None
            self.stats["target_evidence"] = "nearest immediate threat; " + (
                "laser first hit on enemy" if self.target_exposed else "acquiring clear shot")
            return target
        if ray is not None:
            # A current first hit is stronger evidence than the conservative camera-sector estimate, especially
            # when aiming down at a nearby enemy whose centre lies outside that estimate.
            exposed = [e for e in enemies if dot_on(ray[1], e["pos"]) is not None]
            if exposed:
                target = min(exposed, key=lambda e: math.dist(p["pos"], e["pos"]))
                self.blocked_until.pop(target.get("ptr", target.get("slot")), None)
                self.stats["target_evidence"] = "laser first hit on enemy"
                self.target_exposed = True
                return target
        candidates = [e for e in enemies if self.front_candidate(snap, p, e)]
        if ray is not None:
            for e in candidates:
                if self.ray_blocked(ray, e["pos"]):
                    self.blocked_until[e.get("ptr", e.get("slot"))] = now + BLOCKED_S
        candidates = [e for e in candidates if self.blocked_until.get(e.get("ptr", e.get("slot")), 0) <= now]
        self.stats["target_evidence"] = "front candidate; visibility unconfirmed" if candidates else "no exposed candidate"
        return min(candidates, key=lambda e: math.dist(p["pos"], e["pos"]), default=None)

    def seek_target(self, snap, p, enemies, now):
        if any(self.blocked_until.get(e.get("ptr", e.get("slot")), 0) > now for e in enemies):
            return self._reposition(now, "reposition: measured obstruction")
        target = min(enemies, key=lambda e: math.dist(p["pos"], e["pos"]))
        self.stats["combat"] = "turning toward a front candidate"
        return {"hold": self._face(p, target["pos"])}

    def _reposition(self, now, reason):
        if now >= self.step_until:
            self.step_until = now + STEER_STEP_S
            self.step_side = "lright" if self.step_side == "lleft" else "lleft"
        self.stats["combat"] = reason
        return {"hold": {self.step_side}}       # lower the gun so the game can move

    def _rapid_fire(self, wid, now):
        if now - self.rapid_checked < 1.0 and wid == getattr(self, "rapid_weapon", None):
            return self.rapid_fire
        self.rapid_checked, self.rapid_weapon = now, wid
        try:
            fps = struct.unpack(">f", self.m.rd(FIRE_TIMER_FPS, 4))[0]
            interval = struct.unpack(">f", self.m.rd(WEAPON_TABLE + wid * WEAPON_STRIDE + WEAPON_INTERVAL, 4))[0]
            self.rapid_fire = 120.0 <= fps <= 60000.0 and interval == 0.0
        except (TypeError, ValueError, OSError, struct.error):
            self.rapid_fire = False
        self.stats["rapid_fire_verified"] = self.rapid_fire
        return self.rapid_fire

    # --- the tick ---
    def tick(self, snap: dict, p: dict, tgt: dict, now: float, *, observed=False) -> dict:
        if (not p or (p.get("hp") or 0) <= 0 or not tgt or (tgt.get("hp") or 0) <= 0
                or snap.get("recovery_active")
                or (snap.get("prompt") and not self.optional_prompt_blocked(snap))):
            self.near_ray_since = self.near_ray_key = None
            self.near_ray_move_until = 0.0
            self.stats["combat"] = "waiting: no living target or priority prompt/recovery"
            return {"hold": set()}
        if not observed:
            # Standalone callers own a new decision, and may reuse a mutable snapshot fixture between ticks.
            self._observed_snap = None
        pl, wid, rounds, shot = self.observe(snap, now)
        # the laser dot against him (the driver's snapshot carries it as {"from", "at"} when it read it)
        lz = self._ray(snap, now)
        foot = tgt["pos"]
        lead = self._lead(tgt, now)
        dist = math.hypot(foot[0] - p["pos"][0], foot[2] - p["pos"][2])
        if dist > ENGAGE_R:
            self.stats["combat"] = "target outside engagement range"
            return {"hold": set()}
        zone = zone_for(tgt, dist, snap.get("combo_timer"), snap.get("combo"))
        self.zone = zone
        aim_at = (foot[0] + lead[0], foot[1] + {"head": HEAD_H, "leg": THIGH_H}.get(zone, CHEST_H), foot[2] + lead[1])
        tune = self.tun.weapon(self.character, wid or 0)
        where = None
        if lz is not None:
            where = dot_on(lz[1], foot, head_r=tune["head_r"])
            if where is not None:
                aim_at = (foot[0] + lead[0], lz[1][1], foot[2] + lead[1])  # keep the exposed region under the dot
        self.last_dot = (where, tgt.get("ptr"), lz, foot, now)
        head_key = (tgt.get("ptr"), tgt.get("slot"))
        if getattr(self, "_head_key", None) != head_key:
            self._head_key = head_key
            self.dot_head_since = self.dot_body_since = None
        if where == "head":
            self.dot_head_since = self.dot_head_since if self.dot_head_since is not None else now
            self.dot_body_since = None
        elif where in ("body", "leg"):
            self.dot_body_since = self.dot_body_since if self.dot_body_since is not None else now
            self.dot_head_since = None
        else:
            self.dot_head_since = self.dot_body_since = None
        key = tgt.get("ptr", tgt.get("slot"))
        if self._ready(p) and lz is not None:
            if where is not None:
                self.blocked_until.pop(key, None)
            elif self.ray_blocked(lz, foot):
                self.blocked_until[key] = now + BLOCKED_S
        if self.blocked_until.get(key, 0) > now:
            return self.seek_target(snap, p, [tgt], now)
        from .re5_weapons import DIRECT, WEAPONS, fire_policy
        weapon = WEAPONS.get(wid)
        direct = weapon is not None and weapon.family in DIRECT
        permitted, policy = fire_policy(wid, snap, tgt, lz[1] if lz else None)
        self.stats["weapon_policy"] = policy
        loaded = rounds is not None and rounds > 0
        point_blank = dist < POINT_BLANK and abs(foot[1] - p["pos"][1]) < 150.0   # nothing fits between: fire
        sighted = where is not None or point_blank or line_to(lz, aim_at, foot)     # through hit recovery too
        # and the laser has to stop on him (#881): a ray off the aim point - the ground, beside him, or on past him (the
        # game's dot stops on the first body it meets, so a dot beyond him is a miss) - holds fire while the stick
        # brings the dot onto him; no ray yet, or one too short to judge, leaves it to the sight check
        on_line = lz is None or not steering_ray(lz, aim_at) or line_of_sight_aim(lz, aim_at, where, foot)
        tracking_fire = direct and permitted and loaded and sighted and on_line
        steady = True
        if STEADY_HEAD and zone == "head" and direct and not point_blank:   # a steady aim: settled on the head, else patience
            head_ok = self.dot_head_since is not None and now - self.dot_head_since >= HEAD_SETTLE_S
            body_ok = self.dot_body_since is not None and now - self.dot_body_since >= HEAD_PATIENCE_S
            steady = head_ok or body_ok
            tracking_fire = tracking_fire and steady
        self.stats["fire_gate"] = ("settling on the head: hold fire" if sighted and on_line and not steady
                                   else "no line: hold fire" if not sighted else "dot off him: hold fire" if not on_line
                                   else "on him" if where is not None else "line to him")
        # A threat on top of him: blast. Operator 2026-10-22: "I need them blasting like a lunatic on a threat. They are
        # just eating blows ... The gun is being raised. It needs to be blasting. Rapid fire. There is no preparing the
        # aim. There's only blasting and aiming while blasting." Within THREAT_BLAST_R on his level and roughly faced, the
        # trigger stays down from the moment the gun comes up and the stick keeps correcting; the sight / dot gates above
        # are for Majini further off (no shooting walls from across the map).
        to_him = wrap(heading(foot[0] - p["pos"][0], foot[2] - p["pos"][2]) - p["rot"])
        if (THREAT_BLAST and direct and permitted and loaded and dist < THREAT_BLAST_R
                and abs(foot[1] - p["pos"][1]) < 150.0 and abs(to_him) < THREAT_BLAST_FACING):
            tracking_fire = True
            self.stats["fire_gate"] = "threat: blasting"
            self.stats["threat_blasts"] = self.stats.get("threat_blasts", 0) + 1
        rapid = self._rapid_fire(wid, now)              # observed package status, independent of fire intent
        if p.get("action") == 4:                      # prompts own escape from a grab
            self.stats["combat"] = "waiting: grab animation"
            return {"hold": set()}
        if rounds == 0:
            if now - self.reload_at > EMPTY_RELOAD_EVERY_S:
                self.reload_at = now
                self.stats["reloads"] += 1
                return {"hold": {"l1", "cross"}}
            return {"hold": {"l1"}}
        facing = wrap(heading(foot[0] - p["pos"][0], foot[2] - p["pos"][2]) - p["rot"])
        if abs(facing) > SWING_TURN and p.get("action") != 4:
            # He is well off to the side or behind: the gun down, the body turned at ~150 deg/s (aiming turns ~30 deg/s:
            # live 2026-10-22 the gun stayed up through yaw errors of 90-160 deg, seconds of aiming at walls)
            self.near_ray_since = None
            self.stats["combat"] = f"swinging round to him (gun down): {math.degrees(facing):+.0f} deg"
            return {"hold": self._face(p, foot)}
        steer = lz is not None and steering_ray(lz, aim_at)
        feedback_key = (p.get("ptr"), key)
        if feedback_key != self.near_ray_key or (self._ready(p) and (steer or where is not None)):
            self.near_ray_since, self.near_ray_key = None, feedback_key
            self.near_ray_move_until = 0.0
        if now < self.near_ray_move_until:
            return self._reposition(now, "reacquire: near-origin ray")
        if self.near_ray_move_until:
            self.near_ray_move_until = 0.0
            self.near_ray_since = None
        if not self._ready(p) or lz is None:
            # Queue aim/fire through hit recovery too; waiting for the pose byte to clear can perpetuate stunlock.
            # The game decides when the gun can fire, and only its RAM shot events enter the counters.
            self.dot_head_since = self.dot_body_since = None
            self.stats["combat"] = (f"readying: action={p.get('action')} laser={'yes' if lz else 'no'} "
                                    f"{'tracking FIRE' if tracking_fire else policy}")
            self.stats["aim_feedback"] = "waiting for ready ray"
            return {"hold": {"l1"} | ({"r1"} if tracking_fire else set()) | self._face(p, foot)}
        if not steer and where is None:
            if self.near_ray_since is None:
                self.near_ray_since = now
            elif now - self.near_ray_since >= STEER_REACQUIRE_S:
                self.near_ray_move_until = now + STEER_STEP_S
                return self._reposition(now, "reacquire: near-origin ray")
        # steer the dot onto the zone (his head, or his thighs for the stun)
        yaw_err, pitch_err = ray_error(lz[0], lz[1], aim_at)
        keys = {"l1"}
        self.stats["aim_feedback"] = "ray direction" if steer else "near-origin ray; correction paused"
        if steer:
            keys |= self._yaw(yaw_err)
            keys |= self._pitch(pl, p, pitch_err, now)
        # Direct fire continues while the stick corrects aim. Splash/unknown policies remain separate.
        firing = tracking_fire or (where in ("head", "body", "leg") and loaded and permitted and steady)
        self.stats["los_held_fire"] = self.stats.get("los_held_fire", 0) + (0 if firing or not (direct and permitted and loaded) else 1)
        trig = self.triggers.get(wid)
        if trig is None:
            trig = self.triggers[wid] = Trigger(tune["mode"])
        if direct:
            trig.mode = "hold"
        keys |= ({"r1"} if firing else set()) if direct or rapid else trig.keys(now, firing, shot)
        tune["mode"] = trig.mode
        weapon_label = hex(wid) if isinstance(wid, int) else "unknown"
        self.stats["combat"] = (f"{self.character} w{weapon_label} {zone} dot {where} yaw {math.degrees(yaw_err):+.1f} "
                                f"pitch {math.degrees(pitch_err):+.1f} {'rapid hold' if rapid else trig.mode} {'FIRE' if firing else ''}")
        return {"hold": keys}

    def _lead(self, tgt, now) -> tuple:
        """Where his feet will be in HEAD_LEAD_S (his velocity from the last ticks)."""
        hist = getattr(self, "_hist", {})
        self._hist = hist
        ptr = tgt.get("ptr") or tgt.get("slot")
        prev = hist.get(ptr)
        hist[ptr] = (now, tgt["pos"])
        if not prev or now - prev[0] <= 0.01 or now - prev[0] > 0.5:
            return (0.0, 0.0)
        dt = now - prev[0]
        return ((tgt["pos"][0] - prev[1][0]) / dt * HEAD_LEAD_S, (tgt["pos"][2] - prev[1][2]) / dt * HEAD_LEAD_S)

    def _face(self, p, foot) -> set:
        err = wrap(heading(foot[0] - p["pos"][0], foot[2] - p["pos"][2]) - p["rot"])
        if abs(err) < math.radians(10):
            return set()
        return {"rleft"} if err > 0 else {"rright"}

    def _yaw(self, err: float) -> set:
        if abs(err) <= math.radians(0.6):
            return set()
        if abs(err) < FINE:
            self.yaw_pulse ^= 1
            if not self.yaw_pulse:
                return set()
        return {"rleft"} if err > 0 else {"rright"}

    def _pitch(self, pl: int, p: dict, err: float, now: float) -> set:
        """The aim pitch: written into the player (+0x1AA0, + = down) by the dot's own error, else the stick."""
        if abs(err) <= math.radians(0.5):
            return set()
        if PITCH_WRITE and self.writer.ok and pl:
            try:
                cur = struct.unpack(">f", self.m.rd(pl + P_PITCH, 4))[0]
                new = max(-1.3, min(1.3, cur - PITCH_GAIN * err))
                if self.writer.write(pl + P_PITCH, struct.pack(">f", new)):
                    self.stats["pitch_writes"] += 1
                    return set()
            except (ValueError, OSError, struct.error):
                pass
        if abs(err) < FINE:
            self.pitch_pulse ^= 1
            if not self.pitch_pulse:
                return set()
        return {"rup"} if err > 0 else {"rdown"}

    # --- scoring and learning ---
    def _on_shot(self, now):
        """A shot left: remember what the dot was on (the class the hit / miss gets scored with)."""
        self.shots.fired(now)
        self.round_counts["shots"] += 1
        where, ptr, lz, foot = (self.last_dot or (None, None, None, None))[:4]
        reach = None
        if lz is not None and foot is not None:            # the dot short of him (a wall, a prop) or past him
            d_dot = math.dist(lz[0], lz[1])
            d_him = math.dist(lz[0], (foot[0], foot[1] + HEAD_H, foot[2]))
            reach = "short" if d_dot < d_him - 60 else ("past" if d_dot > d_him + 60 else "beside")
        self._pending_where = getattr(self, "_pending_where", [])
        self._pending_where.append((now, where, ptr, reach, round(d_him) if foot is not None and lz is not None else None))
        w = self.tun.weapon(self.character, self.wid or 0)
        w["shots"] += 1

    def _score(self, now):
        st = self.shots.stats
        hits, misses = st["hits"], st["misses"]
        new_hits, new_misses = hits - self._scored_hits, misses - self._scored_misses
        self._scored_hits, self._scored_misses = hits, misses
        pend = getattr(self, "_pending_where", [])
        for _ in range(new_hits):
            t, where, ptr, reach, dist = pend.pop(0) if pend else (now, None, None, None, None)
            self.round_counts["hits"] += 1
            w = self.tun.weapon(self.character, self.wid or 0)
            w["hits"] += 1
            if where == "head":
                self.stats["headshots"] += 1
                self.round_counts["headshots"] += 1
                w["headshots"] += 1
            if where == "leg":
                self.stats["legshots"] = self.stats.get("legshots", 0) + 1
            if where in ("head", "leg") and ptr:          # a stun (the kneel / the head reel): in for the finisher
                self.stunned[ptr] = now + STUN_S
            self._log_shot(t, "headshot" if where == "head" else "hit", where, reach, dist, ptr)
        for _ in range(new_misses):
            t, where, ptr, reach, dist = pend.pop(0) if pend else (now, None, None, None, None)
            if where in ("head", "body"):              # the dot was on him and nothing fell: he moved / a frame late
                cls, key = "miss: dot on him, he moved", "miss_moved"
            elif reach == "short":
                cls, key = "miss: line of sight blocked (the dot short of him)", "miss_short"
            elif reach == "past":
                cls, key = "miss: the ray passed him (aim)", "miss_past"
            else:
                cls, key = "miss: the dot beside him (aim)", "miss_beside"
            self.stats[key] = self.stats.get(key, 0) + 1
            self._log_shot(t, cls, where, reach, dist, ptr)
        self.stats["shots"], self.stats["hits"], self.stats["misses"] = st["shots"], hits, misses
        self.stats["accuracy"] = st["accuracy"]
        self.stats.update(round_shots=self.round_counts["shots"], round_hits=self.round_counts["hits"],
                          round_accuracy=(round(self.round_counts["hits"] / self.round_counts["shots"], 3)
                                          if self.round_counts["shots"] else None))

    def _log_shot(self, t, cls, where, reach, dist, ptr):
        """Every shot into the title's run-lessons log (operator: "why did he miss" -> its class)."""
        self.stats["last_shot"] = cls
        try:
            self.lessons({"kind": "shot", "t": round(t, 2), "result": cls, "dot": where, "reach": reach,
                          "dist_cm": dist, "target": ptr, "weapon": self.wid, "character": self.character,
                          "trigger": (self.triggers.get(self.wid).mode if self.wid in self.triggers else None)})
        except Exception:                              # noqa: BLE001 - a lesson lost never stops the fight
            pass

    def _count_kills(self, snap):
        """Kills from the game's own counter; headshot % and shots per kill follow (the #3046 measures)."""
        k = snap.get("kills")
        if type(k) is int:
            last = getattr(self, "_kills_last", None)
            if last is not None and 0 < k - last < 20:
                self.stats["kills_seen_by_combat"] = self.stats.get("kills_seen_by_combat", 0) + k - last
            self._kills_last = k
        self._headshot_metrics()

    def _headshot_metrics(self):
        shots, kills = self.stats.get("shots") or 0, self.stats.get("kills_seen_by_combat") or 0
        self.stats["headshot_pct"] = (round(100.0 * (self.stats.get("headshots") or 0) / shots, 1) if shots else None)
        self.stats["shots_per_kill"] = round(shots / kills, 2) if kills else None

    def start_round(self, now):
        """Called on an observed playing transition, never inferred from a clock bonus."""
        if self.round_t0 is not None:
            return
        self.round_t0 = now
        self.round_counts = {"shots": 0, "hits": 0, "headshots": 0, "finishers": 0, "time_gained_s": 0.0}
        self.last_timer = None
        self.act_seen = self.rounds_seen = self.last_dot = None
        self.dot_head_since = self.dot_body_since = None
        self.shots.hp.clear()
        self.stunned.clear()
        self.melees.clear()
        self.blocked_until.clear()
        self.finishers_seen = self.stats.get("presses_square", 0)
        self.stats.update(round_shots=0, round_hits=0, round_accuracy=None)

    def end_round(self, now):
        if self.round_t0 is None:
            return
        # A pending shot must be resolved before the next spawn can change enemy health or reuse its slots.
        self.shots.update([], now + HIT_S + 1)
        self._score(now)
        self._round_over()
        self.round_t0 = None
        self.last_timer = None

    def _clock(self, snap, now):
        """Record time gained inside the current round, including ordinary hourglasses."""
        t = snap.get("timer")
        if t is None:
            return
        if self.round_t0 is None:
            self.start_round(now)
        if self.last_timer is not None and 3 < t - self.last_timer:
            self.round_counts["time_gained_s"] += t - self.last_timer
        self.last_timer = t
        sq = self.stats.get("presses_square", 0)
        if sq > self.finishers_seen:
            self.round_counts["finishers"] += sq - self.finishers_seen
            self.stats["finishers"] += sq - self.finishers_seen
            self.finishers_seen = sq

    def _round_over(self):
        rc = self.round_counts
        w = self.tun.weapon(self.character, self.wid or 0)
        w["rounds"] += 1
        w["finishers"] += rc["finishers"]
        w["time_gained_s"] = round(w["time_gained_s"] + rc["time_gained_s"], 1)
        rate = rc["hits"] / rc["shots"] if rc["shots"] else None
        if rate is not None:
            if rate < HIT_RATE_WANT:                       # tighten: a smaller head, a longer settle
                w["head_r"] = round(max(12.0, w["head_r"] * 0.85), 1)
                w["settle_s"] = round(min(0.3, w["settle_s"] + 0.04), 3)
            elif rate >= 0.999 and rc["shots"] >= 10:      # perfect: a notch looser (more shots)
                w["head_r"] = round(min(HEAD_R, w["head_r"] * 1.1), 1)
                w["settle_s"] = round(max(0.03, w["settle_s"] - 0.02), 3)
        self.tun.d["rounds"].append({"character": self.character, "weapon": self.wid, "at": round(time.time()),
                                     **rc, "hit_rate": round(rate, 3) if rate is not None else None})
        self.tun.d["rounds"] = self.tun.d["rounds"][-200:]
        self.tun.save()
        if self.lessons:
            try:
                self.lessons({"kind": "combat_round", "character": self.character, "weapon": self.wid, **rc,
                              "hit_rate": rate})
            except Exception:                              # noqa: BLE001
                pass

    def prompt_ok(self, button, snap, now) -> bool:
        """Press the prompt? A finisher (square) on a boss only once (a second melee is the wild swing); the finisher
        prompt itself means he is stunned: he is marked so."""
        if button != "square":
            return True
        if self.optional_prompt_blocked(snap):
            self.stats["melee_deferred_for_threat"] = self.stats.get("melee_deferred_for_threat", 0) + 1
            return False
        tgt = snap.get("prompt_target")
        if tgt:
            self.stunned[tgt] = now + STUN_S
        e = next((x for x in snap.get("enemies") or () if x.get("ptr") == tgt), None) if tgt else None
        if e is not None and (e.get("hp_max") or 0) > BOSS_HP:
            n = self.melees.get(tgt, 0)
            if n >= 1:
                self.stats["boss_melee_held"] = self.stats.get("boss_melee_held", 0) + 1
                return False
            self.melees[tgt] = n + 1
        return True

    def optional_prompt_blocked(self, snap):
        """Escape/recovery chords stay mandatory; ordinary square melee may yield to another close attacker."""
        if snap.get("prompt") != "square":
            return False
        player, target = snap.get("player") or {}, snap.get("prompt_target")
        if not player.get("pos"):
            return False
        for enemy in snap.get("enemies") or ():
            if enemy.get("ptr") == target or (enemy.get("hp") or 0) <= 0:
                continue
            if math.dist(player["pos"], enemy["pos"]) <= 350 \
                    and self.blocked_until.get(enemy.get("ptr", enemy.get("slot")), 0) <= self.clock():
                return True
        return False

    def stunned_target(self, enemies, p, now):
        """A Majini stunned by a head or leg shot, in finisher reach: close in on him (the prompt comes at ~1.5 m);
        never a boss already meleed once."""
        for e in enemies:
            until = self.stunned.get(e.get("ptr"))
            if not until or now > until or (e.get("hp") or 0) <= 0:
                continue
            if (e.get("hp_max") or 0) > BOSS_HP and self.melees.get(e.get("ptr"), 0) >= 1:
                continue
            d = math.hypot(e["pos"][0] - p["pos"][0], e["pos"][2] - p["pos"][2])
            if STUN_NEAR < d < STUN_FAR:
                return e
        return None

    def run_to(self, p, e) -> dict:
        self.stats["stun_runs"] += 1
        err = wrap(heading(e["pos"][0] - p["pos"][0], e["pos"][2] - p["pos"][2]) - p["rot"])
        keys = set()
        if abs(err) > math.radians(10):
            keys.add("rleft" if err > 0 else "rright")
        if abs(err) < math.radians(50):
            keys |= {"lup", "cross"}
        return {"hold": keys}

    def save(self):
        if self.round_t0 is not None and self.round_counts["shots"]:
            self.end_round(self.clock())
        else:
            self.tun.save()
