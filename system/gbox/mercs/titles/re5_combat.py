"""RE5 Gold (BLUS30491) Mercenaries: the combat layer - only landed shots (operator 2026-10-21: "i am absolutely tired
of seeing missed shots in mercenaries ... I want only landed shots happening"; "I need him doing only headshots").

The game's own laser sight is the truth about a shot: the bullet goes from the laser's origin (the muzzle) to the laser
dot, the first thing the ray hits (uLaserSight, an FxCore unit: +0x200 origin, +0x30 dot). The camera ray is not the
shot ray (5 deg off, up to 15), and the body's yaw is not either (the upper body aims inside a cone): a loop closed on
anything but the dot misses. So every tick:
  * the dot is read and tested against the target Majini's head (a sphere HEAD_R at HEAD_H above his feet) and his
    body (a capsule BODY_R wide from KNEE_H to SHOULDER_H): on the head = a headshot, on the body = a hit, elsewhere
    = the ray hits something else first (the floor, a wall, a prop) or passes him;
  * the aim approaches a preferred anatomical zone until any body region is exposed, then keeps that exposed
    region under the dot. Stick correction follows the measured shot ray rather than the camera ray;
  * the trigger is pulled immediately while the first-hit dot overlaps his head, body or leg. A verified rapid-fire
    patch holds R1 continuously on exposed targets; otherwise weapon-specific taps/holds are learned. Front-camera
    geometry only chooses candidates: it never establishes visibility or authorizes a shot;
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
SETTLE_S = 0.08                        # legacy persisted tuning metadata; a first-hit overlap now fires immediately
FRONT_YAW, FRONT_PITCH = math.radians(60), math.radians(45)  # candidate cone, not a visibility claim
BLOCKED_S = 0.8                        # try another candidate after a measured first hit ends before this one
FIRE_TIMER_FPS, FIRE_TIMER_ORIG = 0x0169E098, 60.0
WEAPON_TABLE, WEAPON_STRIDE, WEAPON_INTERVAL = 0x01817530, 0x140, 0x90
AIM_TURN_RAD_S = 0.52                  # the right stick while aiming: ~30 deg/s (the mods agent scales it)
FINE = math.radians(4)                 # closer than this: the stick in pulses (a tick on, a tick off)
PITCH_WRITE = False                    # the pitch straight into +0x1AA0 (else the stick). Off: the game recomputes
                                       # +0x1AA0 (and +0x31D4, +0x2F3C, the yaw +0x14F4, the quaternion) every frame
                                       # from its own controller - a written value lasted one frame (probe 2026-10-21)
PITCH_GAIN = 1.0                       # how much of the pitch error one write takes out
HIT_S = 0.35                           # a shot's health drop comes within this
STUN_S, STUN_NEAR, STUN_FAR = 2.2, 110.0, 700.0   # a headshot stuns this long: close in from this far for the finisher
HIT_RATE_WANT = 0.95                   # a round under this tightens the aim
TUNABLES_FILE = "re5_combat.json"      # under the learn dir (gbox-data/mercs/learned/BLUS30491)
EMPTY_RELOAD_EVERY_S = 1.5             # L1 + cross this often while the weapon is empty

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
    if tgt.get("zone") in ("leg", "head"):
        return tgt["zone"]
    if (tgt.get("hp_max") or 0) > BOSS_HP:
        return "head"
    window_ok = not combo or combo_timer is None or combo_timer > COMBO_SHORT_S
    return "leg" if dist <= FINISHER_SETUP_R and window_ok else "head"


def ray_error(origin, dot, target) -> tuple[float, float]:
    """(yaw, pitch) radians to turn the ray origin -> dot onto target (+ yaw = left, + pitch = up)."""
    ox, oy, oz = origin
    want_yaw = heading(target[0] - ox, target[2] - oz)
    have_yaw = heading(dot[0] - ox, dot[2] - oz)
    want_pitch = math.atan2(target[1] - oy, max(math.hypot(target[0] - ox, target[2] - oz), 1.0))
    have_pitch = math.atan2(dot[1] - oy, max(math.hypot(dot[0] - ox, dot[2] - oz), 1.0))
    return wrap(want_yaw - have_yaw), want_pitch - have_pitch


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
        if not any(o) or math.dist(o, d) < 5.0:
            return None
        return o, d


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
        self.triggers: dict = {}
        self.act_seen = None                  # (vtable, frames) of the action object last tick
        self.pulse = 0
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
        origin, dot = tuple(sl["from"]), tuple(sl["at"])
        return (origin, dot) if math.dist(origin, dot) >= 5.0 else None

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
        return along > length + BODY_R + 25.0 and dot_on(projected, foot) is not None

    def choose_target(self, snap, p, enemies, now):
        self.target_exposed = False
        enemies = [e for e in enemies if (e.get("hp") or 0) > 0]
        ray = self._ray(snap, now) if self._ready(p) else None
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
            if now >= self.step_until:
                self.step_until = now + 0.25
                self.step_side = "lright" if self.step_side == "lleft" else "lleft"
            self.stats["combat"] = "reposition: measured obstruction"
            return {"hold": {self.step_side}}    # release aim so RE5 can move; never fire through cover
        target = min(enemies, key=lambda e: math.dist(p["pos"], e["pos"]))
        self.stats["combat"] = "turning toward a front candidate"
        return {"hold": self._face(p, target["pos"])}

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
        if not observed:
            # Standalone callers own a new decision, and may reuse a mutable snapshot fixture between ticks.
            self._observed_snap = None
        pl, wid, rounds, shot = self.observe(snap, now)
        # the laser dot against him (the driver's snapshot carries it as {"from", "at"} when it read it)
        lz = self._ray(snap, now)
        foot = tgt["pos"]
        lead = self._lead(tgt, now)
        dist = math.hypot(foot[0] - p["pos"][0], foot[2] - p["pos"][2])
        zone = zone_for(tgt, dist, snap.get("combo_timer"), snap.get("combo"))
        self.zone = zone
        aim_at = (foot[0] + lead[0], foot[1] + (HEAD_H if zone == "head" else THIGH_H), foot[2] + lead[1])
        tune = self.tun.weapon(self.character, wid or 0)
        where = None
        if lz is not None:
            where = dot_on(lz[1], foot, head_r=tune["head_r"])
            if where is not None:
                aim_at = (foot[0] + lead[0], lz[1][1], foot[2] + lead[1])  # keep the exposed region under the dot
        self.last_dot = (where, tgt.get("ptr"), lz, foot, now)
        if not self._ready(p) or lz is None:
            self.dot_head_since = self.dot_body_since = None
            self.stats["combat"] = f"readying: action={p.get('action')} laser={'yes' if lz else 'no'}"
            return {"hold": {"l1"} | self._face(p, foot)}
        # steer the dot onto the zone (his head, or his thighs for the stun)
        yaw_err, pitch_err = ray_error(lz[0], lz[1], aim_at)
        keys = {"l1"}
        keys |= self._yaw(yaw_err)
        keys |= self._pitch(pl, p, pitch_err, now)
        # A current first-hit overlap authorizes the shot immediately; a preferred anatomical zone does not delay it.
        on_target = where in ("head", "body", "leg") and (rounds is None or rounds > 0)
        from .re5_weapons import fire_policy
        permitted, policy = fire_policy(wid, snap, tgt, lz[1])
        on_target = on_target and permitted
        self.stats["weapon_policy"] = policy
        if rounds == 0:
            if now - self.reload_at > EMPTY_RELOAD_EVERY_S:   # empty: reload (the driver switches weapons)
                self.reload_at = now
                self.stats["reloads"] += 1
                return {"hold": {"l1", "cross"}}
            return {"hold": {"l1"}}
        trig = self.triggers.get(wid)
        if trig is None:
            trig = self.triggers[wid] = Trigger(tune["mode"])
        rapid = self._rapid_fire(wid, now)
        keys |= ({"r1"} if on_target else set()) if rapid else trig.keys(now, on_target, shot)
        tune["mode"] = trig.mode
        weapon_label = hex(wid) if isinstance(wid, int) else "unknown"
        self.stats["combat"] = (f"{self.character} w{weapon_label} {zone} dot {where} yaw {math.degrees(yaw_err):+.1f} "
                                f"pitch {math.degrees(pitch_err):+.1f} {'rapid hold' if rapid else trig.mode} {'FIRE' if on_target else ''}")
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
            self.pulse ^= 1
            if not self.pulse:
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
            self.pulse ^= 1
            if not self.pulse:
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
