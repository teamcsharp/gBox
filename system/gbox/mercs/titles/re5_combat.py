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
  * one straight sequence per Majini (operator 2026-10-26: "raise his gun, aim it at the target, and shoot the target";
    re5_engage): the gun comes up, the aim slews onto him with a deadband inside his body's window, the trigger is down
    while the dot is on any Majini or (within re5_engage.CLOSE_R) the aim is inside his window - with 80x fire that is
    the operator's "blasting" - and up while the dot is on a wall or the floor short of him or the gun is still coming
    up (a Majini at arm's length in front excepted); the gun comes down to turn only with nothing threatening in front.
    A laser read that cannot be the gun's (re5_engage.plausible) never steers or fires. Measured cover turns to another
    Majini in sight, else one sidestep. Splash weapons still require first-hit overlap and safe impact clearance;
  * direct-gun firing is observed in RAM (the player's current action object, player +0x1238, entering the
    weapon-fire action 0x0163DFC0 / its frame counter +0x20 starting over) and scored: a hit when any Majini's health
    fell within HIT_S, a headshot when the dot was on the head as it left; a miss is classified by what the dot was on
    (the audit the operator asked for: stats and the run-lessons log). Accelerated bow action observations can
    undercount arrows; bow outcomes remain unknown/confounded without native collision ownership and never tune aim;
  * an empty weapon (the in-hand inventory slot's rounds at 0, player +0x22E0 + 0x30 n: +0x8 id, +0xC rounds, +0x20
    in hand) is reloaded (L1 + cross); the weapon switch is the title driver's;
  * a Majini stunned by a headshot (his health fell with the dot on his head; he stands) is closed in on for the
    finisher prompt ("Hook" / "Uppercut": the action button of kind 3 the driver reports as "square", which the
    engine presses at once; each finisher kill is +5 s);
  * what it learns (per character, per weapon id: shots, hits, headshots, finishers, seconds gained, the trigger
    mode, the head tolerance) is kept under gbox-data (TUNABLES_FILE) and adjusted after every round. Historical
    settle-time metadata remains compatible, but it no longer delays a confirmed exposed shot;
  * every shot gets a record (gbox.mercs.ballistics: the aim decided at the tick before it left - distance, height,
    zone, aim point, where the dot sat, the yaw / pitch error, the body's turn rate, his speed, the gate - and the
    result with its time to hit), kept for the round (round_shots, the driver's round map) and summed up in the
    round's ballistic report; the solo, attributed ones train a per character / weapon / distance band calibration
    (ballistics.CALIBRATION_FILE, beside TUNABLES_FILE): the hits' centre corrects the aim point, the band's last
    shots widen or tighten the trigger, and the hits' 90th-percentile error holds swing-then-fire shots (CAL_*);
  * a rifle or magnum that has shown its laser aims at a Majini beyond ENGAGE_R up to re5_weapons.longshot_reach and
    fires there only with the dot on him (a longshot).

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

from .. import ballistics as B
from .. import lessons as L
from ..aim import Shots
from ..brain.body import (AIM_FIRE_PITCH, AIM_FIRE_YAW, BODY_R, BOW_TOL_MAX, BOW_TOL_MIN, CHEST_H, FIRE_CONE,  # noqa: F401
                          FIRE_SLACK, HEAD_H, HEAD_R, KNEE_H, SHOULDER_H, STEER_RAY_CM, THIGH_H, THIGH_HI, THIGH_LO,
                          THIGH_R, bow_tolerance, dot_on, heading, line_of_sight_aim, line_to, ray_error, steering_ray,
                          valid_ray, wrap)
from . import re5_aim_geometry
from . import re5_engage as E

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

# The anatomy (HEAD_H / HEAD_R, KNEE_H / SHOULDER_H / BODY_R, the thighs, CHEST_H) and the ray's geometry (dot_on,
# ray_error, line_to, line_of_sight_aim, valid_ray, steering_ray, bow_tolerance; FIRE_CONE / FIRE_SLACK, STEER_RAY_CM,
# AIM_FIRE_YAW / _PITCH, BOW_TOL_*) live in gbox.mercs.brain.body, the universal brain's, imported above.
DEFAULT_ZONE = "body"                   # zone_for's answer without the strategy's say ("head": the #3046 steady head aim)
THREAT_BLAST = True                     # False: only the sight / dot gates decide (the far-target gate's own tests)
THREAT_BLAST_R = 500.0                  # a Majini this near on the player's level, roughly faced: the trigger stays down
THREAT_BLAST_FACING = math.radians(30)
# The same for a gun without a laser ray (operator 2026-10-26: "the laserless path must fire while turning toward a target
# within ~3 m instead of lowering the gun"; 16:36 Missile Area: 100 s of 157 s fighting turning gun-down, hit 5 of 6
# times): this near and inside this cone the gun stays up and fires while the aim corrects - no corridor, no alignment
LASERLESS_BLAST_R, LASERLESS_BLAST_CONE = 300.0, math.radians(60)
BLAST_GATE_LASERLESS = "threat: blasting (laserless)"   # its gate in the shot records (the ballistic report's by_gate)
LASERLESS_SWITCH_S = 2.0                # a gun up this long without a laser ray is laserless (Combat.laserless_now)
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
# Calibration (gbox.mercs.ballistics.Calibration, per character / weapon / distance band, learned from every resolved
# shot; operator 2026-10-26: "Every landed shot should better inform and train the system on how to aim"): the hits'
# centre corrects the aim point; a band hitting >= 90 % of its last 20 gate-able shots fires inside a CAL_WIDEN wider
# cone, one under 50 % fires only with the dot on him; and no line-only shot leaves while the ray is further off the aim
# point than the band's hits' 90th percentile ("the aimbot will aim at a person then aim away and begin firing"),
# except point blank and the close-threat blast. Beyond ENGAGE_R a weapon that has shown its laser and can reach
# (re5_weapons.longshot_reach: rifle, magnum) is aimed, and fired only with the dot on him: a longshot.
CAL_WIDEN = 1.25
CAL_P90_FLOOR = math.radians(1.0)      # the p90 gate never asks for an aim closer than this
AIM_STALE_S = 0.5                      # a shot this long after the last aim decision: its record says "stale"
SHOTS_PER_ROUND = 3000                 # shot records kept per round (the round map's "shots")
SWING_TURN = math.radians(45)          # a Majini further off the body's heading than this: turn with the gun down
# A Majini behind: the quick turn (left stick down + cross, the run button; docs/mercenaries_re5_meta.md item 21, marked
# "verify live") instead of ~1 s of body turning with the gun down. Self-verifying: the heading must swing at least
# QUICK_TURN_SEEN within QUICK_TURN_CHECK_S, else after QUICK_TURN_TRIES presses without one it is off for the session
QUICK_TURN_ERR, QUICK_TURN_SEEN = math.radians(100), math.radians(90)   # verified live 2026-10-26 15:39 (128 deg)
QUICK_TURN_CHECK_S, QUICK_TURN_GAP_S, QUICK_TURN_TRIES = 0.7, 0.8, 2
# Target choice: a Majini off the body's heading costs his distance times (1 + FRONT_WEIGHT * angle / pi), so the one in
# front is shot while the one behind closes in; the current target is kept unless another costs under TARGET_SWITCH of
# his (live 2026-10-26 15:39: 19.6 s of a 30 s life turning with the gun down between the nearest Majini, hit 3 of 3 times)
FRONT_WEIGHT, TARGET_SWITCH = 1.5, 0.7
POINT_BLANK = 110.0                   # a Majini this near on the player's level needs no ray (hit recovery, the gun
                                       # coming up): nothing fits between them
WILD_YAW, WILD_PITCH = math.radians(30), math.radians(25)   # a ray error past this is not a turn to make: a torn read
                                       # (operator 2026-10-26: "looking down and to the side while dispatching the foes")
LEVEL_PITCH = math.radians(15)         # the guard levels a gun pitched further than this
BOW_RANGE = 2000.0                    # controller tuning, not a decoded projectile range
BOW_YAW, BOW_PITCH = math.radians(6), math.radians(7)
BOW_BURST_S = 3.0                     # observed target HP progress, never trigger/FIRE activity, renews this lease
BOW_OUTCOME_S = 2.0                   # observation retention only; expiry is unknown, never a confirmed miss
BOW_TRACK = .25                       # the aim keeps correcting inside this share of the release window
BOW_STAND_R = 800.0                   # a Majini this near: the longbow stands and shoots, never leaves to reposition
BOW_TURN_ENTER, BOW_TURN_EXIT = math.radians(60), math.radians(25)
BOW_TURN_IDLE_S, BOW_TURN_MAX_S = .75, 2.0
BOW_READY_WAIT_S = 1.0
BOW_TARGET_SLACK = 75.0              # keep a living target through nearby distance ties (world cm)
# One straight sequence (operator 2026-10-26: "he should basically raise his gun, aim it at the target, and shoot the
# target"; re5_engage): the gun up, the stick slewing onto him with a deadband, the trigger down only while the aim is on
# him (his body's window) or the dot on any Majini, the gun down to turn only with nothing threatening in front.
READY_FIRE_R = 150.0                 # the gun still coming up: the trigger only for a Majini this near (on his level) ...
READY_FIRE_FACING = math.radians(25)  # ... faced within this (2026-10-26: shots while the gun came up hit 13 of 141 -
                                      # "shot at his feet")
REPOSITION_S = 0.7                   # a blocked line: one sidestep this long, the next one the other way (was 0.25 s
                                     # each way: standing among foes jittering left / right)
WINDOW_GATES = frozenset({"on him", "on another Majini", "point blank", "threat: blasting", "line to him"})
                                     # the gates that fire inside the target's window (behavior_metrics: on target)


CHARACTERS = {0x016172B8: "barry"}     # the player's vtable -> the character (the rest named by their vtable)
ENABLED = True                         # the title driver's Bot hands the fight here (False: its own aim loop)


def ptr_ok(p) -> bool:
    return isinstance(p, int) and 0x30000000 <= p < 0x40000000


def u32(m, a) -> int:
    return struct.unpack(">I", m.rd(a, 4))[0]


# --- what the laser says (dot_on: gbox.mercs.brain.body) ---------------------------------------------------------
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


class PS3IO:
    """The RE5 PS3 RAM behind the combat layer (gbox.mercs.brain.io.TitleIO): the player chain, the action object,
    the fire command word, the second player's slot, the character's vtable, the inventory record in hand, the FX
    line's laser, the fire timer and the pitch writer. Combat reads RAM only through its io (this, by default), so
    another title runs the same combat core with its own."""

    def __init__(self, m):
        self.m = m
        self.laser = Laser(m)
        self.writer = Writer(m)

    def player_index(self):
        from . import re5_ps3 as R
        return R.player_index(self.m)

    def player_ptr(self) -> int:
        from . import re5_ps3 as R
        pl = R.player_pointer(self.m)
        return pl if ptr_ok(pl) else 0

    def action(self, pl):
        """(vtable, frames) of the player's current action object, or None (re-checked against a swap mid-read)."""
        ap = u32(self.m, pl + P_ACTION_OBJ) if pl else 0
        if not ptr_ok(ap):
            return None
        index = self.player_index()
        if index != 0 and u32(self.m, ap + 0x18) != pl:
            return None
        vt = u32(self.m, ap)
        fr = struct.unpack(">f", self.m.rd(ap + ACT_FRAMES, 4))[0]
        if not math.isfinite(fr) or self.player_ptr() != pl \
                or u32(self.m, pl + P_ACTION_OBJ) != ap \
                or (index != 0 and u32(self.m, ap + 0x18) != pl):
            return None
        return vt, fr

    def in_hand(self, pl):
        """(weapon id, rounds, an item in hand) from the inventory records, or None when nothing is in hand."""
        raw = self.m.rd(pl + P_INV, INV_SLOT * INV_SLOTS)
        for k in range(INV_SLOTS):
            o = k * INV_SLOT
            if struct.unpack_from(">I", raw, o + INV_HAND)[0] == 1 and raw[o + INV_USED]:
                word = struct.unpack_from(">I", raw, o + INV_ID)[0]
                if word >> 8 != 1:
                    return None, None, True
                return word & 0xFF, struct.unpack_from(">i", raw, o + INV_ROUNDS)[0], False
        return None

    def fire_command(self, pl) -> int:
        return u32(self.m, pl + P_FIRE_CMD) if pl else 0

    def second_player(self) -> bool:
        manager = u32(self.m, S_PLAYER)
        return ptr_ok(manager) and ptr_ok(u32(self.m, manager + 0x2C))

    def character(self, pl) -> str:
        return CHARACTERS.get(u32(self.m, pl), f"vt{u32(self.m, pl):#x}")

    def read_laser(self, now):
        return self.laser.read(now)

    def rapid_fire(self, wid):
        fps = struct.unpack(">f", self.m.rd(FIRE_TIMER_FPS, 4))[0]
        interval = struct.unpack(">f", self.m.rd(WEAPON_TABLE + wid * WEAPON_STRIDE + WEAPON_INTERVAL, 4))[0]
        return 120.0 <= fps <= 60000.0 and interval == 0.0

    def read_pitch(self, pl):
        return struct.unpack(">f", self.m.rd(pl + P_PITCH, 4))[0]

    def write_pitch(self, pl, value) -> bool:
        return self.writer.write(pl + P_PITCH, struct.pack(">f", value))


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

    def __init__(self, m, stats: dict, clock=time.time, learn_dir=None, lessons=None, io=None, map_id=None):
        self.m, self.stats, self.clock = m, stats, clock
        self.io = io if io is not None else PS3IO(m)      # every RAM read (another title brings its own)
        self.map_id = map_id or MAP_ID
        if learn_dir is None:                 # the deployment: beside the lessons under gbox-data
            learn_dir = L.ROOT.parent / "learned" / self.map_id
        self.run_id = time.strftime("%Y%m%d-%H%M%S", time.localtime()) + "-combat"
        self.lessons = lessons or (lambda e: L.append(self.map_id, e, run=self.run_id))
        self.laser = self.io.laser
        self.writer = self.io.writer
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
        self.qturn, self.qturn_at = None, -math.inf   # the quick turn under way {at, rot}; the last one pressed
        self.qturn_ok = self.qturn_failed = 0
        self.qturn_off = False                # QUICK_TURN_TRIES presses without a turn: not this game's chord
        self.zone = "head"
        self.reload_at = -1e9
        self.character = "?"
        self.wid = None
        self.round_t0 = None
        self.round_counts = {"shots": 0, "hits": 0, "headshots": 0, "finishers": 0, "time_gained_s": 0.0}
        self.round_weapons = {}
        self.last_timer = None
        self.finishers_seen = 0
        self.damage_unattributed = False
        self.mine_damage_confounded = False
        self.mine_confounded_until = -math.inf
        self._mine_release_sample = False
        self.round_unattributed_shots = 0
        self._unattributed_hp = {}
        self.infinite = False                 # the rounds don't count (the no-ammo flag): shots from the fire command
        self._fire_cmd_seen = 0
        self._cmd_shot_at = -1e9
        self.bow_down_at = None
        self.bow_up_at = -1e9
        self.bow_turn_key, self.bow_turning = None, False
        self.bow_turn_started = self.bow_turn_progress_at = 0.
        self.bow_turn_best, self.bow_turn_direction = math.inf, 0
        self.bow_ready_key, self.bow_ready_since = None, None
        self.bow_target_key = None
        self.laserless_feedback_since = None
        self.needs_firing_position = False
        self.laserless_progress = None
        self.bow_pending = []
        self.bow_aim = None
        self.bow_hp = {}
        self.bow_hp_at = None
        self.bow_target_damage = {}
        self.bow_round_observations = 0
        self.shot_evidence = None
        self.cal = B.Calibration(learn_dir)   # per character / weapon / band aim corrections (ballistics.CALIBRATION_FILE)
        self.round_shots: list = []           # this round's shot records (the ballistic report)
        self.shot_sink = None                 # called with each resolved record (the driver's round map)
        self.last_aim = None                  # the aim decided at the last tick: a shot seen next tick is credited with it
        self.last_report = None               # the last round's ballistic report (records only)
        self.laser_weapons: set = set()       # weapon ids that have shown a laser ray in hand (the longshot rule)
        self._rot_seen = None
        self._pos_seen: dict = {}
        self.look = None                      # gbox.mercs.bot_look.BotLook (the driver's Bot sets it): "look at the bot"
        self.metrics = None                   # gbox.mercs.behavior_metrics.BehaviorMetrics (the Bot's): the shots' lines
        self._look_pending: dict = {}         # id(shot record) -> (its look entry, target ptr, enemy hp at the shot)
        self.round_dots: dict = {}            # this round's shots by what the dot was on (re5_engage.dot_class)
        self.decisions_n = 0                  # one more per decision (the Bot tells this tick's decision from a stale one)
        self.look_decision = None             # (decision, reason) of the last decision, for the look
        self.swing_key = None                 # the Majini a gun-down swing is turning to (it ends at re5_engage.SWING_DONE)
        self.target_key = None
        self._enemy_hp: dict = {}             # this snapshot's enemy health (the look's hp_delta)
        self._obs_snap = None
        self._ray_checked = None              # (snap, now, ray): a snapshot's laser is checked once
        self.ray_rejected = None              # why this tick's laser read was dropped (re5_engage.plausible), or None
        self.decision_target = None
        self._err_seen = None                 # (target, t, yaw, pitch) of the last laser aim error (the jump guard)
        self.stats.update(bow_confirmed_hits=0,bow_confirmed_misses=0,
                          bow_ballistic_calibration='unavailable; no native projectile impact ownership')
        for k in ("shots", "hits", "misses", "headshots", "accuracy", "miss_short", "miss_past", "miss_beside",
                  "miss_moved", "finishers", "reloads", "pitch_writes", "stun_runs"):
            self.stats.setdefault(k, 0)
        for k in ("shots", "hits", "misses", "headshots", "legshots", "miss_short", "miss_past", "miss_beside",
                  "miss_moved"):
            self.stats[k] = 0
        self.stats["accuracy"] = 0.0

    # --- RAM ---
    def _action(self, pl=None):
        try:
            scoped = self._player_ptr()
            pl = scoped if pl is None else pl
            if not pl or pl != scoped:
                return None
            return self.io.action(pl)
        except (ValueError, OSError, struct.error):
            return None

    def _player_ptr(self) -> int:
        return self.io.player_ptr()

    def _in_hand(self, snap, pl):
        """(weapon id, rounds) of the slot in hand; (None, None) with a non-weapon in hand (self.item_in_hand): the
        First Aid Spray is {id 0x304, type 3, item 4} - read as item 4 it was the Ithaca M37, its use a "shot" that
        missed (2026-10-26: 85 shot rows as 0x4, 6 of 45 hits; 69 hits taken with the spray in hand)."""
        self.item_in_hand = False
        inv = snap.get("inventory")
        if inv:
            s = next((x for x in inv if x.get("hand")), None)
            if s:
                if s.get("type", 1) != 1:
                    self.item_in_hand = True
                    return None, None
                return s.get("item", s.get("id", 0) & 0xFF), s.get("rounds")
        try:
            held = self.io.in_hand(pl)
        except (ValueError, OSError):
            return None, None
        if held is None:
            return None, None
        if held[2]:
            self.item_in_hand = True
            return None, None
        return held[0], held[1]

    def _shot(self, pl: int, rounds, aiming: bool, now: float) -> bool:
        """A shot the game fired since the last tick: the in-hand rounds fell (the surest, until infinite ammo), else
        the action entering weapon_fire / its frames starting over (where the action pointer is one), else the fire
        command word (one frame) on a tick while aiming with a loaded gun. Infinite ammo (the package's no-ammo flag:
        the rounds stand while the fire command keeps coming) is noticed after INFINITE_AFTER such frames."""
        self.shot_evidence = None
        was_rounds, self.rounds_seen = getattr(self, "rounds_seen", None), rounds
        if rounds is not None and was_rounds is not None and 0 < was_rounds - rounds <= 3:
            self.act_seen = self._action(pl)
            self._fire_cmd_seen = 0
            self.shot_evidence = 'native_ammo_decrease'
            return True
        a = self._action(pl)
        was, self.act_seen = self.act_seen, a
        if a is not None and was is not None and a[0] in (FIRE_VT, READY_VT, RELOAD_VT):
            fired = a[0] == FIRE_VT and (was[0] != FIRE_VT or a[1] < was[1] - 0.5)
            if fired:self.shot_evidence = 'native_fire_action_entry_or_reset'
            return fired
        try:
            cmd = self.io.fire_command(pl) if pl else 0
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
        self.shot_evidence = 'native_fire_command_inferred_infinite'
        return True

    def _update_attribution(self, snap, index, now):
        """Shared enemy HP/counters cannot establish which local player hit it."""
        other_player = index != 0 or any(row.get('slot') == 2 and row.get('native_actor_verified') is True
            for row in snap.get('players') or () if isinstance(row, dict))
        try:
            other_player = other_player or self.io.second_player()
        except (OSError, ValueError, struct.error):
            other_player = True  # missing participant evidence cannot prove solo attribution
        if other_player and not self.damage_unattributed:
            self.damage_unattributed = True
            self._unattributed_hp = {}
            # Discard unresolved solo correlation when a second player appears.
            self.shots.hp.clear()
            self.stunned.clear()
        ground = snap.get('ground_mines')
        active_setting = snap.get('mines_enabled', self.stats.get('mines_enabled')) is True
        unreadable_active = active_setting and (ground is None or not getattr(ground, 'verified', True))
        if ground or unreadable_active:
            # Match the mine observer's two-second damage window. Presence itself also makes a gun/HP correlation
            # ambiguous: the sampled list can miss the exact detonation frame between two observations.
            self.mine_confounded_until = now + 2.
        was_confounded = self.mine_damage_confounded
        self.mine_damage_confounded = now <= self.mine_confounded_until
        self._mine_release_sample = was_confounded and not self.mine_damage_confounded
        self.stats['combat_mine_damage_confounded'] = self.mine_damage_confounded
        self.stats['combat_damage_attribution'] = ('unattributed_multiple_players' if self.damage_unattributed
            else 'unattributed_mine_window' if self.mine_damage_confounded or self._mine_release_sample
            else 'solo_temporal_correlation')
        self.stats['combat_player_index'] = index

    def _observe_impacts(self, enemies, now):
        mine_window = self.mine_damage_confounded or self._mine_release_sample
        if not self.damage_unattributed and not mine_window:
            self._unattributed_hp = {}
            # Score expired records before a newer shot receives this tick's HP loss. Otherwise the two counts
            # can assign the hit to the old head shot and the miss to the newer body shot.
            self.shots.expire(now)
            self._score(now)
            return self.shots.update(enemies, now)
        previous, current, losses, deaths = self._unattributed_hp, {}, 0., 0
        if mine_window and not previous:
            previous = {e.get('ptr', e.get('slot')): self.shots.hp[e.get('slot')][0]
                        for e in enemies if e.get('slot') in self.shots.hp}
        for enemy in enemies:
            key = enemy.get('ptr', enemy.get('slot'))
            hp = enemy.get('hp')
            if not isinstance(hp, (int, float)) or isinstance(hp, bool) or not math.isfinite(hp):
                continue
            current[key] = hp
            if key in previous and hp < previous[key]:
                losses += previous[key] - hp
                deaths += int(previous[key] > 0 and hp <= 0)
        self._unattributed_hp = current
        self.stats['enemy_hp_loss_unattributed'] = self.stats.get('enemy_hp_loss_unattributed', 0) + losses
        self.stats['enemy_deaths_unattributed'] = self.stats.get('enemy_deaths_unattributed', 0) + deaths
        while self.shots.pending and (mine_window or now - self.shots.pending[0] > self.shots.HIT_S):
            at = self.shots.pending.pop(0)
            pending = getattr(self, '_pending_where', [])
            record = pending.pop(0) if pending else (at, None, None, None, None)
            self.stats['shot_impacts_unattributed'] = self.stats.get('shot_impacts_unattributed', 0) + 1
            self.round_unattributed_shots += 1
            why = ('impact unattributed: mine presence or recent detonation' if mine_window
                   else 'impact unattributed: multiple players can damage enemies')
            self._resolve(record[7] if len(record) > 7 else None, "unattributed", now, record[0], cls=why)
            self._log_shot(record[0], why, record[1], record[3], record[4], record[2],
                           weapon=record[5] if len(record) > 5 else self.wid,
                           character=record[6] if len(record) > 6 else self.character)
        if mine_window:
            self.stats['mine_window_enemy_hp_loss_unattributed'] = self.stats.get('mine_window_enemy_hp_loss_unattributed', 0) + losses
            # Rebase on every ambiguous sample so damage during the window cannot become a later gun hit.
            self.shots.hp = {e.get('slot', e.get('id')): (e.get('hp'), (e.get('hp') or 0) <= 0) for e in enemies}
            self._mine_release_sample = False
        return []

    def observe(self, snap, now, *, active=True):
        """Account for a snapshot even while a prompt or the walker owns the pad. Same snapshot: once only."""
        if self._observed_snap is snap:
            return self._observation
        self._observed_snap = snap
        if active:
            self.start_round(now)
        p = snap.get("player") or {}
        index = self.io.player_index()
        scoped = self._player_ptr()
        if index is None or (index != 0 and (not scoped or p.get('ptr') != scoped)):
            self.suspend_observation(now)
            self.stats['combat'] = 'scoped player identity unavailable; no Player 1 fallback'
            self._observed_snap, self._observation = snap, (0, None, None, False)
            return self._observation
        pl = p.get("ptr") or scoped
        self._update_attribution(snap, index, now)
        wid, rounds = self._in_hand(snap, pl)
        if active:
            self.character = self.io.character(pl) if pl else "?"
            self.wid = wid
        shot = active and not getattr(self, "item_in_hand", False) and self._shot(pl, rounds, p.get("action") == AIMING, now)
        if active and getattr(self, "item_in_hand", False):
            self.rounds_seen = None                       # a spray's count falling is no round fired
        self._obs_snap = snap
        if shot:
            self._on_shot(now)
        self._observe_bow(snap, now)
        self._observe_impacts(snap.get("enemies") or [], now)
        self._enemy_hp = {e.get("ptr", e.get("slot")): e.get("hp") for e in snap.get("enemies") or ()
                          if isinstance(e, dict) and isinstance(e.get("hp"), (int, float))}
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
        self.bow_hp.clear()
        self.bow_hp_at = None
        self.bow_target_damage.clear()
        self.bow_aim = None
        self._observe_bow({},now)
        self._observed_snap = self._observation = None
        self._observe_impacts([], now)
        self._score(now)

    def _ray(self, snap, now):
        """The laser ray (origin, dot) when it can be his gun's (re5_engage.plausible), else None. A torn read - an origin
        metres from him, a ray behind him or straight into the ground (2026-10-26 19:25: "yaw +172.6 pitch -79.7") - never
        steers or gates a shot; stats laser_rejected counts them (once per snapshot)."""
        checked = self._ray_checked
        if checked is not None and checked[0] is snap and checked[1] == now and checked[3] is snap.get("laser") \
                and "laser" in snap:
            return checked[2]
        ray = self._raw_ray(snap, now)
        if ray is not None:
            ok, why = E.plausible(ray, snap.get("player") or {},
                                  on_majini=E.under_dot(ray, snap.get("enemies") or (), dot_on) is not None)
            if not ok:
                self.stats["laser_rejected"] = self.stats.get("laser_rejected", 0) + 1
                self.stats["laser_rejected_why"] = why
                self.ray_rejected = why
                ray = None
            else:
                self.ray_rejected = None
        else:                                   # no read this tick - or one the driver dropped from the snapshot
            self.ray_rejected = snap.get("laser_dropped")
        self._ray_checked = (snap, now, ray, snap.get("laser"))
        return ray

    def _raw_ray(self, snap, now):
        if "laser" not in snap:
            if self.io.player_index() != 0:
                return None  # the global first-laser scan has no verified P2 owner
            return self.io.read_laser(now)
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
        # a Majini under the dot is a target, not cover: the ones behind him are not "blocked" by him (the old rule marked
        # them, and the bot sidestepped among foes instead of shooting the one in front)
        under = E.under_dot(ray, snap.get("enemies") or (), dot_on)
        for enemy in snap.get("enemies") or ():
            key = enemy.get("ptr", enemy.get("slot"))
            hit = ray is not None and dot_on(ray[1], enemy["pos"]) is not None
            if hit:
                self.blocked_until.pop(key, None)
            elif ray is not None and under is None and self.ray_blocked(ray, enemy["pos"]):
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
        """The Majini to fight (re5_engage.pick): the one under the laser dot; else the nearest threat in front within
        FRONT_CLEAR_R (the gun stays up); else one at arm's length anywhere (turned to); else the nearest in front within
        FRONT_R; else near and in front first. The held target stays while he is still that kind of choice. Measured cover
        (the dot on a wall short of him) leaves a Majini out for BLOCKED_S; a Majini under the dot is never cover.
        2026-10-26 16:00-19:30: at 94 of 162 hits taken during a gun-down swing a Majini stood within 4 m and 35 deg in
        front - the old cost (distance x (1 + 1.5 x angle / pi), the held one kept unless another cost under 0.7 of him,
        anyone within 1.1 m always first) kept the one off to the side. The longbow keeps its own lock
        (_choose_bow_target)."""
        self.target_exposed = False
        enemies = [e for e in enemies if (e.get("hp") or 0) > 0]
        if any(w.get('hand') and w.get('id') == 0x10F for w in snap.get('inventory') or ()):
            return self._choose_bow_target(snap, p, enemies, now)
        self.bow_target_key = None
        ray = self.observe_awareness(snap, p, now)
        dotted = E.under_dot(ray, enemies, dot_on)
        if dotted is not None:
            self.blocked_until.pop(E.key(dotted), None)
        pool = [e for e in enemies if self.blocked_until.get(E.key(e), 0) <= now]
        target, why = E.pick(p, pool, held=self.target_key, dotted=dotted,
                             extra_ok=lambda e: self.front_candidate(snap, p, e))
        self.target_key = E.key(target) if target is not None else None
        self.target_exposed = target is not None and ray is not None and dot_on(ray[1], target["pos"]) is not None
        close = target is not None and math.dist(p["pos"], target["pos"]) <= 350
        evidence = ("laser first hit on enemy" if self.target_exposed else "acquiring clear shot" if close
                    else "front candidate; visibility unconfirmed" if target is not None else "no exposed candidate")
        self.stats["target_evidence"] = ("nearest immediate threat; " + evidence) if close else evidence
        self.stats["target_rule"] = why
        return target

    def _choose_bow_target(self, snap, p, enemies, now):
        """The longbow's target: the nearest supported one, locked through distance ties (its own controller's rules)."""
        bow = True
        def cost(e):
            off = abs(wrap(heading(e['pos'][0] - p['pos'][0], e['pos'][2] - p['pos'][2]) - (p.get('rot') or 0.0)))
            return math.dist(p['pos'], e['pos']) * (1.0 + FRONT_WEIGHT * off / math.pi)
        def nearest(pool):
            contact = [e for e in pool if math.dist(p['pos'], e['pos']) < POINT_BLANK]
            target = min(contact or pool, key=(lambda e: math.dist(p['pos'], e['pos'])) if contact else cost, default=None)
            held = next((e for e in pool if e.get('ptr', e.get('slot')) == getattr(self, 'target_key', None)), None)
            if not contact and held is not None and target is not None and held is not target                     and cost(target) > TARGET_SWITCH * cost(held):
                target = held                              # no swing for a slightly better one (one in contact: always)
            self.target_key = target.get('ptr', target.get('slot')) if target is not None else None
            if not bow or target is None:
                return target
            locked = next((e for e in pool if self.bow_target_key ==
                           (p.get('ptr'), e.get('ptr', e.get('slot')))), None)
            reason = 'nearest supported target'
            if locked is not None:
                distance = math.dist(p['pos'], target['pos'])
                locked_distance = math.dist(p['pos'], locked['pos'])
                contact_preemption = distance < POINT_BLANK and locked_distance > max(150., 1.5*distance)
                if not contact_preemption and locked_distance <= distance+BOW_TARGET_SLACK:
                    target = locked
                    reason = 'retain living bow target through a nearby distance tie'
                elif contact_preemption:
                    reason = 'closer contact threat takes priority'
            key = (p.get('ptr'), target.get('ptr', target.get('slot')))
            if self.bow_target_key is not None and self.bow_target_key != key:
                self.stats['bow_target_changes'] = self.stats.get('bow_target_changes',0)+1
            self.bow_target_key = key
            self.stats.update(bow_target_id=key[1], bow_target_policy=reason)
            return target
        ray = self.observe_awareness(snap, p, now)
        # Immediate threats outrank distant crosshair targets, bonus routes and score optimizations.
        # Unknown sight lines remain explicitly unknown; direct-fire guns fire during acquisition by operator policy.
        close = [e for e in enemies if math.dist(p["pos"], e["pos"]) <= 350
                 and self.blocked_until.get(e.get("ptr", e.get("slot")), 0) <= now]
        if close:
            exposed_close = [e for e in close if ray is not None and dot_on(ray[1], e["pos"]) is not None]
            target = nearest(exposed_close or close)
            self.target_exposed = ray is not None and dot_on(ray[1], target["pos"]) is not None
            self.stats["target_evidence"] = "nearest immediate threat; " + (
                "laser first hit on enemy" if self.target_exposed else "acquiring clear shot")
            return target
        if ray is not None:
            # A current first hit is stronger evidence than the conservative camera-sector estimate, especially
            # when aiming down at a nearby enemy whose centre lies outside that estimate.
            exposed = [e for e in enemies if dot_on(ray[1], e["pos"]) is not None]
            if exposed:
                target = nearest(exposed)
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
        return nearest(candidates)

    def seek_target(self, snap, p, enemies, now, *, depth=0):
        """No target to fight here. A measured obstruction (the dot on a wall short of him): another Majini in sight is
        fought at once - never a stand among foes - else one sidestep (REPOSITION_S). Nobody chosen at all: the body turns
        to the nearest and, once he is in the gun's sector, the gun comes up (its laser confirms or blocks the line; the
        old turn without L1 stood facing a Majini with the gun down - 484 s of "turning toward a front candidate"
        standstills on 2026-10-26)."""
        if any(self.blocked_until.get(e.get("ptr", e.get("slot")), 0) > now for e in enemies):
            others = [e for e in snap.get("enemies") or () if E.living(e) and E.on_level(p, e)
                      and self.blocked_until.get(E.key(e), 0) <= now and E.flat(p["pos"], e["pos"]) <= E.FRONT_R]
            nxt, _ = E.pick(p, others, held=None) if others and depth == 0 else (None, None)
            if nxt is not None:
                self.target_key = E.key(nxt)
                self.stats["blocked_switches"] = self.stats.get("blocked_switches", 0) + 1
                return self._decide(snap, p, nxt, now, observed=True, depth=1)
            act = self._reposition(now, "reposition: measured obstruction")
            self._decided(act, (enemies or [None])[0], p)
            return act
        target = min(enemies, key=lambda e: math.dist(p["pos"], e["pos"]))
        self.stats["combat"] = "turning toward a front candidate"
        keys = self._face(p, target["pos"])
        if abs(E.bearing(p, target["pos"])) <= E.FRONT_CONE:
            keys = keys | {"l1"}
        act = {"hold": keys}
        self._decided(act, target, p)
        return act

    def _quick_turn(self, p, facing, now):
        """A Majini more than QUICK_TURN_ERR off the heading, the gun down (stand / move): the quick turn (operator
        2026-10-26: "turning around nonsensically ignoring threats"; live the same day: killed by a Majini 119 deg behind
        while the body swung round at ~150 deg/s with the gun down). None: not now (off, recently used, aiming)."""
        if (self.qturn_off or self.qturn is not None or abs(facing) < QUICK_TURN_ERR or p.get("action") not in (0, 1)
                or now - self.qturn_at < QUICK_TURN_GAP_S or p.get("rot") is None):
            return None
        self.qturn, self.qturn_at = {"at": now, "rot": p["rot"]}, now
        self.stats["quick_turns"] = self.stats.get("quick_turns", 0) + 1
        self.stats["combat"] = f"quick turn: {math.degrees(facing):+.0f} deg behind"
        return {"hold": {"ldown", "cross"}}

    def _quick_turn_watch(self, p, now):
        """The quick turn pressed: hands off while the heading swings (QUICK_TURN_CHECK_S at most), then judged - a swing
        of QUICK_TURN_SEEN is a turn; none after QUICK_TURN_TRIES presses (and never one seen) switches it off for the
        session, stats quick_turn says so. A stale press (no target ticks since) is dropped unjudged."""
        q = self.qturn
        if q is None or p.get("rot") is None:
            return None
        turned = abs(wrap(p["rot"] - q["rot"]))
        if turned >= QUICK_TURN_SEEN:
            self.qturn, self.qturn_ok = None, self.qturn_ok + 1
            self.stats["quick_turn"] = f"works: {self.qturn_ok} turn(s), last {math.degrees(turned):.0f} deg"
            return None
        age = now - q["at"]
        if age < QUICK_TURN_CHECK_S:
            self.stats["combat"] = f"quick turn: {math.degrees(turned):.0f} deg so far"
            return {"hold": set()}
        self.qturn = None
        if age > 3 * QUICK_TURN_CHECK_S:
            return None                           # no target ticks in between: nothing to judge
        self.qturn_failed += 1
        if self.qturn_failed >= QUICK_TURN_TRIES and not self.qturn_ok:
            self.qturn_off = True
            self.stats["quick_turn"] = (f"no effect ({math.degrees(turned):.0f} deg in {QUICK_TURN_CHECK_S:g} s, "
                                        f"{self.qturn_failed} presses): off, the body turns")
        return None

    def _reposition(self, now, reason):
        """One sidestep REPOSITION_S long in one direction; the next sidestep goes the other way (the gun comes down so
        the game moves him)."""
        if now >= self.step_until:
            self.step_until = now + REPOSITION_S
            self.step_side = "lright" if self.step_side == "lleft" else "lleft"
        self.stats["combat"] = reason
        return {"hold": {self.step_side}}       # lower the gun so the game can move

    def _rapid_fire(self, wid, now):
        if now - self.rapid_checked < 1.0 and wid == getattr(self, "rapid_weapon", None):
            return self.rapid_fire
        self.rapid_checked, self.rapid_weapon = now, wid
        try:
            self.rapid_fire = bool(self.io.rapid_fire(wid))
        except (TypeError, ValueError, OSError, struct.error):
            self.rapid_fire = False
        self.stats["rapid_fire_verified"] = self.rapid_fire
        return self.rapid_fire

    # --- the tick ---
    def tick(self, snap: dict, p: dict, tgt: dict, now: float, *, observed=False) -> dict:
        """One decision (_decide); the aim it took is kept for the record of a shot the next tick sees leave."""
        self.decision_target = tgt
        act = self._decide(snap, p, tgt, now, observed=observed)
        aim = self.last_aim
        if aim is not None and aim.get("at") == now:
            aim["fire"] = "r1" in (act.get("hold") or ())
            aim.setdefault("gate", self.stats.get("fire_gate"))
        self._decided(act, self.decision_target, p)
        return act

    def _decided(self, act, tgt, p) -> None:
        """This tick's decision for the look (gbox.mercs.bot_look): what (fire / aim / raise / swing / quick turn /
        reposition / turn / wait) and why (the target, the fire gate, the combat line)."""
        self.decisions_n += 1
        held = set((act or {}).get("hold") or ())
        c = str(self.stats.get("combat") or "")
        if c.startswith("quick turn"):
            what = "quick turn"
        elif c.startswith("swinging round") or "lower weapon and turn" in c or "finish committed body turn" in c:
            what = "swing (gun down)"
        elif c.startswith(("reposition", "reacquire")) or "route to" in c or "use supported route" in c:
            what = "reposition"
        elif c.startswith("waiting"):
            what = "wait"
        elif "r1" in held:
            what = "fire"
        elif c.startswith("readying"):
            what = "raise the gun"
        elif "l1" in held:
            what = "aim"
        elif c.startswith("turning toward"):
            what = "turn"
        else:
            what = "hold"
        who = ""
        if isinstance(tgt, dict) and tgt.get("pos") and p and p.get("pos"):
            kind = "boss" if (tgt.get("hp_max") or 0) > BOSS_HP else "Majini"
            k = tgt.get("ptr", tgt.get("slot"))
            who = (f"{kind} {k:#x}" if isinstance(k, int) else f"{kind} {k}") + \
                f" {E.flat(p['pos'], tgt['pos']) / 100.0:.1f} m {round(E.bearing_right_deg(p, tgt['pos'])):+d} deg; "
        gate = str(self.stats.get("fire_gate") or "")
        self.look_decision = (what, (who + (gate + "; " if gate and what in ("fire", "aim", "raise the gun") else "")
                                     + c)[:160])

    def _note_ray(self, wid, ray: bool, ready: bool, now: float) -> None:
        """Gun-up seconds without a laser ray, per weapon (a ray resets it): laserless_now() tells the driver to take a
        laser gun from a quick slot at close range (re5_weapons.best_quick_slot laserless=)."""
        last = getattr(self, "_ray_note_at", None)
        dt = max(0.0, min(0.5, now - last)) if last is not None else 0.0
        self._ray_note_at = now
        if not isinstance(wid, int):
            return
        no_ray = self.__dict__.setdefault("no_ray_s", {})
        if ray:
            no_ray[wid] = 0.0
        elif ready:
            no_ray[wid] = no_ray.get(wid, 0.0) + dt

    def laserless_now(self, wid) -> bool:
        """This gun has been up LASERLESS_SWITCH_S without a laser ray (the bow always counts)."""
        if wid == 0x0F:
            return True
        return (getattr(self, "no_ray_s", None) or {}).get(wid, 0.0) >= LASERLESS_SWITCH_S

    def _aim_begin(self, now, p, tgt, wid) -> dict:
        """This tick's aim record: the geometry and motion at the decision; the paths below add the aim and the gate."""
        foot, pos = tgt["pos"], p["pos"]
        rot, turn = p.get("rot"), None
        if isinstance(rot, (int, float)) and math.isfinite(rot):
            if self._rot_seen is not None and 0.01 < now - self._rot_seen[0] <= 0.5:
                turn = abs(wrap(rot - self._rot_seen[1])) / (now - self._rot_seen[0])
            self._rot_seen = (now, rot)
        key = tgt.get("ptr", tgt.get("slot"))
        seen, speed = self._pos_seen.get(key), None
        if seen is not None and 0.01 < now - seen[0] <= 0.5:
            speed = math.hypot(foot[0] - seen[1][0], foot[2] - seen[1][2]) / (now - seen[0])
        if len(self._pos_seen) > 64:
            self._pos_seen.clear()
        self._pos_seen[key] = (now, tuple(foot))
        facing = wrap(heading(foot[0] - pos[0], foot[2] - pos[2]) - (rot if isinstance(rot, (int, float)) else 0.0))
        pitch = p.get("pitch")
        self.last_aim = {"at": now, "state": None, "wid": wid, "target": key,
                         "dist": round(math.hypot(foot[0] - pos[0], foot[2] - pos[2])), "dy": round(foot[1] - pos[1]),
                         "facing": round(math.degrees(facing), 1),
                         "turn": round(math.degrees(turn), 1) if turn is not None else None,
                         "speed": round(speed) if speed is not None else None,
                         "pitch": round(math.degrees(pitch), 1) if isinstance(pitch, (int, float)) else None}
        return self.last_aim

    def _decide(self, snap: dict, p: dict, tgt: dict, now: float, *, observed=False, depth=0) -> dict:
        """One decision for one Majini - one straight sequence (operator 2026-10-26: "he should basically raise his gun, aim
        it at the target, and shoot the target"; re5_engage):
          1. the gun comes up (L1) facing him; while it is still coming up the trigger waits (a Majini at arm's length in
             front excepted): those shots went into the floor - 13 hits in 141 on 2026-10-26;
          2. the aim slews onto him with a deadband inside his body's window (no waving): by the laser ray when it can be
             the gun's (re5_engage.plausible), else the camera's look ray, else his heading and the gun's pitch;
          3. the trigger is down while the dot is on any Majini (another one under the dot is shot - he is no "cover"
             for the target) or, within CLOSE_R, while the aim is inside the target's window; never with the dot on a wall
             or the floor short of him; beyond CLOSE_R the laser line gate decides as before;
          4. the target is kept (choose_target); a gun-down swing goes on until he is within SWING_DONE, and it starts
             only when nothing threatening stands within FRONT_CLEAR_R in front - that one is fought instead.
        depth: a decision handed to another Majini this tick (the one in front, or the next one in sight when this one's
        line is measured blocked) is not handed on again."""
        if (not p or (p.get("hp") or 0) <= 0 or not tgt or (tgt.get("hp") or 0) <= 0
                or snap.get("recovery_active")
                or (snap.get("prompt") and not self.optional_prompt_blocked(snap))):
            self.near_ray_since = self.near_ray_key = None
            self.near_ray_move_until = 0.0
            self.swing_key = None
            self.stats["combat"] = "waiting: no living target or priority prompt/recovery"
            return {"hold": set()}
        self.decision_target = tgt
        if not observed:
            # Standalone callers own a new decision, and may reuse a mutable snapshot fixture between ticks.
            self._observed_snap = None
        pl, wid, rounds, shot = self.observe(snap, now)
        if not pl:
            return {'hold':set()}
        turning = self._quick_turn_watch(p, now)
        if turning is not None:
            return turning                        # the turn's animation plays out untouched
        if snap.get('rotten_egg_only') and wid!=0x36:
            self.stats['combat']='eggs only: awaiting native egg equip; gun trigger withheld'
            return {'hold':set()}
        if snap.get('rotten_egg_only') and not snap.get('rotten_egg_native_equipped'):
            self.stats['combat']='eggs only: native in-hand weapon ownership unverified; trigger withheld'
            return {'hold':set()}
        from .re5_weapons import DIRECT, WEAPONS, fire_policy, longshot_reach
        weapon = WEAPONS.get(wid)
        direct = weapon is not None and weapon.family in DIRECT
        self.needs_firing_position = False
        self.stats.pop("aim_guard", None)                  # set again below while a guard holds (never last round's)
        aim = self._aim_begin(now, p, tgt, wid)
        lz = self._ray(snap, now)                          # the gun's ray only (a torn read is None)
        ready = self._ready(p)
        self._note_ray(wid, lz is not None, ready, now)
        # The laserless controller: the bow and the egg always; a direct gun only once it has been up LASERLESS_SWITCH_S
        # without a ray. Until then its ray may simply not be up yet (2026-10-26 19:16: the MP5 lowered its gun to turn as
        # "laserless" in the frames before its ray showed, and was hit; 19:19 the P8 fired "laserless" 25 deg off him).
        if wid in (0x0F, 0x36) or (direct and lz is None and ready and self.laserless_now(wid)):
            act = self._laserless_tick(snap, p, tgt, now, pl, wid, rounds, shot, depth=depth)
            said = str(self.stats.get("combat") or "")          # its own lowered-weapon turns are the gun-down swing
            aim["state"] = "swing" if "lower weapon and turn" in said or "finish committed body turn" in said \
                else "laserless"
            return act
        self.stats.pop("laserless_visibility", None)
        self.laserless_feedback_since = None
        self.laserless_progress = None
        if lz is not None and isinstance(wid, int):
            self.laser_weapons.add(wid)
        foot = tgt["pos"]
        lead = self._lead(tgt, now)
        dist = math.hypot(foot[0] - p["pos"][0], foot[2] - p["pos"][2])
        level = abs(foot[1] - p["pos"][1]) < 150.0
        reach = max(ENGAGE_R, longshot_reach(wid)) if wid in self.laser_weapons else ENGAGE_R
        if dist > reach and (lz is None or dot_on(lz[1], foot) is None):
            self.stats["combat"] = "target outside engagement range"
            aim.update(state="out of range", gate="out of range")
            return {"hold": set()}
        longshot = dist > ENGAGE_R           # a laser weapon that reaches: aimed, and fired with the dot on him only
        zone = zone_for(tgt, dist, snap.get("combo_timer"), snap.get("combo"))
        self.zone = zone
        nominal = (foot[0] + lead[0], foot[1] + {"head": HEAD_H, "leg": THIGH_H}.get(zone, CHEST_H), foot[2] + lead[1])
        cal_yaw, cal_pitch = self.cal.correction(self.character, wid or 0, dist)     # degrees, learned from the hits
        origin = lz[0] if lz is not None else (p["pos"][0], p["pos"][1] + 140.0, p["pos"][2])
        aim_at = B.turn_point(origin, nominal, math.radians(cal_yaw), math.radians(cal_pitch))
        tune = self.tun.weapon(self.character, wid or 0)
        where = None
        if lz is not None:
            where = dot_on(lz[1], foot, head_r=tune["head_r"])
            if where is not None:            # keep the exposed region under the dot (the learned yaw still applies)
                axis = B.turn_point(origin, (foot[0] + lead[0], lz[1][1], foot[2] + lead[1]), math.radians(cal_yaw), 0.0)
                aim_at = (axis[0], lz[1][1], axis[2])
        aim.update(character=self.character, zone=zone, where=where, longshot=longshot or None,
                   aim=[round(v) for v in aim_at], corr=[cal_yaw, cal_pitch] if cal_yaw or cal_pitch else None)
        if lz is not None:
            ye, pe = ray_error(lz[0], lz[1], aim_at)          # the steering error (to the corrected aim point)
            ny, npi = ray_error(lz[0], lz[1], nominal)       # ... and to the zone's nominal point (what calibration learns)
            aim.update(yaw_err=round(math.degrees(ye), 2), pitch_err=round(math.degrees(pe), 2),
                       nom_yaw=round(math.degrees(ny), 2), nom_pitch=round(math.degrees(npi), 2),
                       steer=steering_ray(lz, aim_at))
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
        enemies = snap.get("enemies") or ()
        # the dot on another Majini: a measured line to him - he is shot now and becomes the target (the old gate held
        # the trigger: "no line" to the target, while the bot stood among foes with its gun on one of them)
        other = E.under_dot(lz, enemies, dot_on, exclude=key) if ready and lz is not None and where is None else None
        if ready and lz is not None:
            if where is not None or other is not None:
                self.blocked_until.pop(key, None)
            elif self.ray_blocked(lz, foot):
                self.blocked_until[key] = now + BLOCKED_S
        if self.blocked_until.get(key, 0) > now:
            aim.update(state="blocked", gate="measured cover: reposition")
            self.swing_key = None
            return self.seek_target(snap, p, [tgt], now, depth=depth)
        if other is not None:
            self.target_key = E.key(other)
            aim.update(other=E.key(other))
        if lz is None and dist > E.FRONT_CLEAR_R and snap.get("nav") is not None \
                and not self.firing_corridor(snap, p, tgt, wid):
            # no ray to measure the line, and the stage's floor says a wall stands between: no aiming at the wall - a
            # firing position (the driver walks the floor route; a Majini within FRONT_CLEAR_R is always faced)
            self.needs_firing_position = True
            self.swing_key = None
            aim.update(state="walled", gate="known wall: reposition")
            self.stats.update(fire_gate="no laser ray: known-wall veto / unknown corridor; hold fire",
                              combat="route to a firing position: a known wall between", aim_feedback="no laser ray")
            return {"hold": set()}
        permitted, policy = fire_policy(wid, snap, tgt, lz[1] if lz else None)
        self.stats["weapon_policy"] = policy
        loaded = rounds is not None and rounds > 0
        point_blank = dist < POINT_BLANK and level   # nothing fits between
        close = dist <= E.CLOSE_R and level            # the fire window rules here (the laser line gate beyond)
        facing = wrap(heading(foot[0] - p["pos"][0], foot[2] - p["pos"][2]) - p["rot"])
        est = self._aim_estimate(snap, p, lz, aim_at, ready)
        if est is not None and est[0] in ("camera", "body") and est[1] is not None:
            aim.update(est=est[0], est_yaw=round(math.degrees(est[1]), 2),
                       est_pitch=round(math.degrees(est[2]), 2) if est[2] is not None else None)
        laser_est = est is not None and est[0] == "laser"
        win_y, win_p = E.window(max(50.0, dist - E.MUZZLE_CM),   # seen from the gun, half a metre ahead of his feet
                                pad=E.LASER_PAD_CM if laser_est else E.WINDOW_PAD_CM)
        on_window = (est is not None and est[1] is not None and abs(est[1]) <= win_y
                     and (abs(est[2]) <= win_p if est[2] is not None else point_blank))
        if laser_est and not on_window:
            on_window = E.through_body(lz, foot)            # the ray runs through his torso / head on its way
        short = (lz is not None and where is None and other is None
                 and math.dist(lz[0], lz[1]) < math.dist(lz[0], aim_at) - FIRE_SLACK)
        # a torn read: the ray's own direction jumped further in one tick than the stick can turn the aim (Ship_Deck
        # 11:37: yaw -5 / pitch +1, 0.26 s later -55 / -56): no steering and no line-only shot on it until it holds a
        # second tick (the dot leaving his shoulder for the wall behind him moves the dot, not the direction: no jump)
        jump = None
        if lz is not None and steering_ray(lz, aim_at):
            ray_yaw = heading(lz[1][0] - lz[0][0], lz[1][2] - lz[0][2])
            ray_pitch = math.atan2(lz[1][1] - lz[0][1], max(math.hypot(lz[1][0] - lz[0][0], lz[1][2] - lz[0][2]), 1.0))
            last = getattr(self, "_err_seen", None)
            if last is not None and last[0] == key and 0 < now - last[1] <= 0.5 and \
                    (abs(wrap(ray_yaw - last[2])) > WILD_YAW or abs(ray_pitch - last[3]) > WILD_PITCH):
                jump = f"jump: ray yaw {math.degrees(last[2]):+.0f} -> {math.degrees(ray_yaw):+.0f}, pitch " \
                       f"{math.degrees(last[3]):+.0f} -> {math.degrees(ray_pitch):+.0f} in {now - last[1]:.2f} s"
            self._err_seen = (key, now, ray_yaw, ray_pitch)
        mode, window_rate = self.cal.mode(self.character, wid or 0, dist)
        widen = CAL_WIDEN if mode == "wide" else 1.0
        dot_required = mode == "strict" or longshot
        line_ok = line_to(lz, aim_at, foot, cone=FIRE_CONE * widen)
        p90 = self.cal.p90(self.character, wid or 0, dist)
        steady = True
        if STEADY_HEAD and zone == "head" and direct and not point_blank:   # a steady aim: settled on the head, else patience
            head_ok = self.dot_head_since is not None and now - self.dot_head_since >= HEAD_SETTLE_S
            body_ok = self.dot_body_since is not None and now - self.dot_body_since >= HEAD_PATIENCE_S
            steady = head_ok or body_ok
        able = direct and permitted and loaded
        if not able:
            fire = where is not None and loaded and permitted and steady    # splash: the dot on him (its own policy)
            gate = "on him" if fire else "no line: hold fire" if where is None else "dot off him: hold fire"
        elif where is not None:
            fire, gate = True, "on him"
        elif other is not None:
            fire, gate = True, "on another Majini"
        elif point_blank and (on_window or ((lz is None or short or not steering_ray(lz, aim_at))
                                            and abs(facing) <= READY_FIRE_FACING)
                             or (lz is None and abs(facing) <= READY_FIRE_FACING)):
            fire, gate = True, "point blank"
        elif not ready and level and dist < READY_FIRE_R and abs(facing) <= READY_FIRE_FACING:
            # a Majini at arm's length in front while the gun comes up (or through hit recovery): the trigger is queued -
            # waiting for the pose to clear perpetuates the stunlock
            fire, gate = True, "point blank"
        elif short and jump is None:
            fire, gate = False, ("floor short of him: hold fire"
                                 if E.dot_class(lz, foot, p, enemies, dot_on) == "floor" else "wall in front: hold fire")
        elif close:
            if not ready:
                fire, gate = False, "gun coming up: hold fire"
            elif on_window and jump is None:
                fire, gate = True, "threat: blasting" if THREAT_BLAST and dist < THREAT_BLAST_R else "line to him"
            else:
                off = math.degrees(math.hypot(est[1] or 0.0, est[2] or 0.0)) if est is not None and est[1] is not None else None
                fire, gate = False, (f"slewing {off:.0f} deg off him: hold fire" if off is not None else "no line: hold fire")
        else:
            sighted = line_ok and not dot_required
            # the laser has to stop on him (#881): a ray off the aim point - the ground, beside him, or on past him - holds
            # fire while the stick brings the dot onto him
            on_line = lz is None or not steering_ray(lz, aim_at) or line_of_sight_aim(lz, aim_at, where, foot, scale=widen)
            fire = lz is not None and sighted and on_line and jump is None
            gate = ("no line: hold fire" if not sighted else "dot off him: hold fire" if not on_line or jump
                    else "line to him")
            if line_ok and not sighted:
                gate = ("longshot: the dot must be on him: hold fire" if longshot else
                        f"calibration: {B.band(dist)} m hits {window_rate:.0%}, the dot must be on him: hold fire")
            # the swing-then-fire case: a line-only shot while the ray is further off the aim point than the band's hits
            # ever were (their 90th percentile) is held
            if fire and p90 is not None and steering_ray(lz, aim_at):
                limit = max(math.radians(p90) * widen, CAL_P90_FLOOR)
                error = math.hypot(*ray_error(lz[0], lz[1], aim_at))
                if error > limit:
                    fire = False
                    gate = (f"calibration: error {math.degrees(error):.1f} > the hits' p90 "
                            f"{math.degrees(limit):.1f} deg: hold fire")
        if able and fire and not steady and gate not in ("on another Majini", "point blank"):
            fire, gate = False, "settling on the head: hold fire"
        if gate == "threat: blasting":
            self.stats["threat_blasts"] = self.stats.get("threat_blasts", 0) + 1
        self.stats["fire_gate"] = gate
        described = self.cal.describe(self.character, wid or 0, dist)
        if described:
            self.stats["aim_calibration"] = described
        else:
            self.stats.pop("aim_calibration", None)
        aim.update(gate=gate, mode=mode if mode != "normal" else None, p90=p90, pb=point_blank or None)
        rapid = self._rapid_fire(wid, now)              # observed package status, independent of fire intent
        if p.get("action") == 4:                      # prompts own escape from a grab
            self.stats["combat"] = "waiting: grab animation"
            aim["state"] = "grab"
            return {"hold": set()}
        if rounds == 0:
            aim["state"] = "reload"
            if now - self.reload_at > EMPTY_RELOAD_EVERY_S:
                self.reload_at = now
                self.stats["reloads"] += 1
                return {"hold": {"l1", "cross"}}
            return {"hold": {"l1"}}
        # The swing: he is well off the heading (or a swing under way has not brought him within SWING_DONE) and the gun
        # is not already on him: the gun comes down and the body turns at ~150 deg/s (aiming turns ~30 deg/s) - unless a
        # threat stands within FRONT_CLEAR_R in front: then that one is fought now, the gun up.
        aimed = ready and (where is not None or other is not None or (on_window and jump is None))
        swinging = self.swing_key == key and abs(facing) > E.SWING_DONE
        if (abs(facing) > E.SWING_TURN or swinging) and not aimed:
            threat = E.front_threat(p, enemies, exclude=key) if depth == 0 else None
            if threat is not None:
                self.target_key = E.key(threat)
                self.swing_key = None
                self.stats["front_first"] = self.stats.get("front_first", 0) + 1
                return self._decide(snap, p, threat, now, observed=True, depth=depth + 1)
            self.near_ray_since = None
            self.swing_key = key
            aim["state"] = "swing"                     # the quick turn too: the gun is down while the body turns
            quick = self._quick_turn(p, facing, now)
            if quick is not None:
                return quick
            self.stats["combat"] = f"swinging round to him (gun down): {math.degrees(facing):+.0f} deg"
            return {"hold": self._face(p, foot, tol=E.SWING_DONE * 0.6)}
        self.swing_key = None
        steer = lz is not None and steering_ray(lz, aim_at) and jump is None
        feedback_key = (p.get("ptr"), key)
        if feedback_key != self.near_ray_key or lz is None or (ready and (steer or where is not None or other is not None)):
            self.near_ray_since, self.near_ray_key = None, feedback_key   # (no ray at all: no near-origin sidestep either)
            self.near_ray_move_until = 0.0
        if now < self.near_ray_move_until:
            aim["state"] = "reacquire"
            return self._reposition(now, "reacquire: near-origin ray")
        if self.near_ray_move_until:
            self.near_ray_move_until = 0.0
            self.near_ray_since = None
        trig = self.triggers.get(wid)
        if trig is None:
            trig = self.triggers[wid] = Trigger(tune["mode"])
        if direct:
            trig.mode = "hold"
        self.stats["los_held_fire"] = self.stats.get("los_held_fire", 0) + (0 if fire or not able else 1)

        def trigger(keys):
            keys |= ({"r1"} if fire else set()) if direct or rapid else trig.keys(now, fire, shot)
            tune["mode"] = trig.mode
            return keys
        if not ready:
            # The gun coming up (L1) facing him. Queue aim/fire through hit recovery too; waiting for the pose byte to clear
            # can perpetuate stunlock. The game decides when the gun can fire; only its RAM shot events enter the counters.
            self.dot_head_since = self.dot_body_since = None
            self.stats["combat"] = (f"readying: action={p.get('action')} laser={'yes' if lz else 'no'} "
                                    f"{'tracking FIRE' if fire else policy}")
            self.stats["aim_feedback"] = "waiting for ready ray"
            aim["state"] = "readying"
            return {"hold": {"l1"} | ({"r1"} if fire else set()) | self._face(p, foot)}
        if lz is None:
            # The gun is up and its ray has not shown (yet, or a torn read was dropped): the aim by the camera's look ray,
            # else his heading and the gun's pitch - slewed with a deadband, fired inside his window.
            self.dot_head_since = self.dot_body_since = None
            src = est[0] if est is not None else "body"
            keys = {"l1"}
            yaw_e = est[1] if est is not None else None
            pitch_e = est[2] if est is not None else None
            if yaw_e is not None:
                dby, dbp = E.deadband(dist)
                keys |= self._yaw(yaw_e, deadzone=dby)
                if pitch_e is not None:
                    keys |= self._pitch(pl, p, pitch_e, now, deadzone=dbp)
            guard = None
            if getattr(self, "ray_rejected", None):
                guard = "wild"
                self.stats["aim_guard"] = f"wild: ray dropped ({self.ray_rejected}): face him, level the gun"
                self.stats["aim_guards"] = self.stats.get("aim_guards", 0) + 1
            aim.update(state=src, guard=guard)
            keys = trigger(keys)
            self.stats["aim_feedback"] = f"no laser ray yet; {src} direction"
            self.stats["combat"] = (f"aim by the {src}: yaw {math.degrees(yaw_e or 0.0):+.1f} pitch "
                                    f"{math.degrees(pitch_e or 0.0):+.1f} {'FIRE' if fire else ''}"
                                    f"{' guard ' + guard if guard else ''}")
            return {"hold": keys}
        if not steer and where is None and other is None and jump is None:
            if self.near_ray_since is None:
                self.near_ray_since = now
            elif now - self.near_ray_since >= STEER_REACQUIRE_S:
                self.near_ray_move_until = now + STEER_STEP_S
                aim["state"] = "reacquire"
                return self._reposition(now, "reacquire: near-origin ray")
        # steer the dot onto the zone, a deadband inside his window: on him, the stick is left alone
        yaw_err, pitch_err = ray_error(lz[0], lz[1], aim_at)
        keys = {"l1"}
        self.stats["aim_feedback"] = "ray direction" if steer else "near-origin ray; correction paused"
        guard = "jump" if jump else None
        aim.update(state="aim", guard=guard)
        if guard:
            self.stats["aim_guard"] = jump + ": steering paused"
            self.stats["aim_guards"] = self.stats.get("aim_guards", 0) + 1
        if steer and other is None:
            dby, dbp = E.deadband(dist)
            keys |= self._yaw(yaw_err, deadzone=dby if abs(yaw_err) <= win_y else None)
            keys |= self._pitch(pl, p, pitch_err, now, deadzone=dbp if abs(pitch_err) <= win_p else None)
        keys = trigger(keys)
        weapon_label = hex(wid) if isinstance(wid, int) else "unknown"
        dot = where if where is not None else "other" if other is not None else None
        self.stats["combat"] = (f"{self.character} w{weapon_label} {zone} dot {dot} yaw {math.degrees(yaw_err):+.1f} "
                                f"pitch {math.degrees(pitch_err):+.1f} {'rapid hold' if rapid else trig.mode} "
                                f"{'FIRE' if fire else ''}{' guard ' + guard if guard else ''}")
        return {"hold": keys}

    def _aim_estimate(self, snap, p, lz, aim_at, ready):
        """(source, yaw error, pitch error) from where the gun points to aim_at (+ = left / up): the laser ray when it can
        steer ("laser"; a ray too short to give a direction is ("laser-near", None, None)); else, the gun up, the camera's
        look ray ("camera": it runs through the crosshair, where the shot goes); else his heading and the gun's pitch
        ("body"; the pitch error None when the snapshot has no pitch)."""
        if lz is not None:
            if steering_ray(lz, aim_at):
                y, pch = ray_error(lz[0], lz[1], aim_at)
                return "laser", y, pch
            return "laser-near", None, None
        if ready:
            cam = snap.get("camera") or {}
            try:
                eye, at = tuple(cam["eye"]), tuple(cam["at"])
                if len(eye) == len(at) == 3 and all(math.isfinite(v) for v in (*eye, *at)) and math.dist(eye, at) > 1.0:
                    y, pch = ray_error(eye, at, aim_at)
                    return "camera", y, pch
            except (KeyError, TypeError, ValueError, OverflowError):
                pass
        pos, rot = p["pos"], p.get("rot") or 0.0
        y = wrap(heading(aim_at[0] - pos[0], aim_at[2] - pos[2]) - rot)
        pitch = p.get("pitch")
        if isinstance(pitch, (int, float)) and not isinstance(pitch, bool) and math.isfinite(pitch):
            want = math.atan2(aim_at[1] - (pos[1] + 140.0), max(math.hypot(aim_at[0] - pos[0], aim_at[2] - pos[2]), 1.0))
            return "body", y, want - pitch
        return "body", y, None

    @staticmethod
    def firing_corridor(snap, p, tgt, wid=0x0F):
        """A known-wall veto only. A navmesh is not an arrow collision ray."""
        mesh = snap.get("nav")
        try:
            return (mesh is not None and math.dist(p["pos"], tgt["pos"]) <= (1000. if wid==0x36 else BOW_RANGE if wid == 0x0F else ENGAGE_R)
                    and bool(mesh.floor_segment(p["pos"], tgt["pos"])))
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
            return False

    def _laserless_tick(self, snap, p, tgt, now, pl, wid, rounds, shot, depth=0):
        """Aim without laser feedback using the camera or native body/pitch.

        A direct gun with a Majini within LASERLESS_BLAST_R on his level needs no floor corridor, and fires once the aim
        (the camera, else his heading) is inside the target's window (re5_engage.window) - never while still turning
        toward him (2026-10-26: the old close-threat blast fired 60 deg off him: "shooting at walls"). Further off the
        heading than SWING_TURN, the gun comes down to turn only with no threat in front (re5_engage.front_threat).

        Trigger intent never counts as an arrow. The ordinary RAM observation path alone records shots/hits;
        native refire-table verification does not establish the bow animation's achievable firing rate.
        """
        from .re5_weapons import laserless_fire_policy
        label = 'rotten egg' if wid==0x36 else "longbow" if wid == 0x0F else "laserless gun"
        self._rapid_fire(wid, now)
        self.last_dot = (None, tgt.get("ptr"), None, tgt["pos"], now)
        self.stats["laserless_visibility"] = ("ordinary aligned throw; ballistic calibration and cover unverified"
                                             if wid==0x36 else "corridor only; projectile cover unconfirmed")
        corridor = self.firing_corridor(snap, p, tgt,wid)
        if self.blocked_until.get(tgt.get("ptr",tgt.get("slot")),0) > now:
            corridor = False
        ray = None if wid==0x36 else self._ray(snap, now)
        if ray is not None and self.ray_blocked(ray, tgt["pos"]):
            corridor = False
        foot = tgt["pos"]
        facing = wrap(heading(foot[0]-p["pos"][0], foot[2]-p["pos"][2])-p["rot"])
        blast = (wid not in (0x0F, 0x36) and rounds is not None and rounds > 0 and p.get("action") != 4
                 and math.hypot(foot[0]-p["pos"][0], foot[2]-p["pos"][2]) < LASERLESS_BLAST_R
                 and abs(foot[1]-p["pos"][1]) < 150.0)          # near: no corridor needed; fired once aligned
        if not corridor and not blast:
            self.bow_down_at = None
            self.needs_firing_position = True
            self.stats.update(weapon_policy=label+": blocked or unknown floor corridor",
                              fire_gate=label+": known-wall veto / unknown corridor; hold fire",
                              combat=label+": route to a supported firing position",
                              aim_feedback="no projectile ray; no blind reposition")
            return {"hold": set()}
        foot = tgt["pos"]
        facing = wrap(heading(foot[0]-p["pos"][0], foot[2]-p["pos"][2])-p["rot"])
        if wid == 0x0F:
            key = (p.get('ptr'), tgt.get('ptr', tgt.get('slot')))
            if self.bow_turn_key != key:
                self.bow_turn_key, self.bow_turning = key, False
            if self.bow_turning:
                # Deliberately lowering L1 leaves the ready pose. Finish that
                # committed body turn before requesting aim again; the orbit
                # camera is not aim feedback while the weapon is lowered.
                if p.get('action') in (4, 5):
                    self.bow_turning = False
                    return {'hold': set()}
                if abs(facing) <= BOW_TURN_EXIT or facing*self.bow_turn_direction <= 0:
                    self.bow_turning, self.bow_ready_since = False, None
                    self.laserless_progress = None  # a completed turn begins a fresh bounded aim/shot attempt
                else:
                    if self.bow_turn_best-abs(facing) >= math.radians(3):
                        self.bow_turn_best, self.bow_turn_progress_at = abs(facing), now
                    if now-self.bow_turn_started >= BOW_TURN_MAX_S \
                            or now-self.bow_turn_progress_at >= BOW_TURN_IDLE_S:
                        self.bow_turning = False
                        self.laserless_progress = None
                        self.needs_firing_position = True
                        self.stats.update(bow_aim_phase='body turn stalled',
                            combat='longbow: bounded body turn stalled; use supported route',
                            fire_gate='longbow: body turn unconfirmed; release and reacquire')
                        return {'hold': set()}
                    self.stats.update(bow_aim_phase='finishing body turn',
                        bow_body_error_deg=round(math.degrees(facing),3),
                        combat='longbow: finish committed body turn before raising aim',
                        fire_gate='longbow: body turn; trigger released',
                        aim_feedback='current body heading; orbit camera withheld')
                    return {'hold': self._face(p, foot)}
            if self.bow_ready_key != key:
                self.bow_ready_key, self.bow_ready_since = key, None
            if not self._ready(p):
                self.bow_down_at = None
                if self.bow_ready_since is None:
                    self.bow_ready_since = now
                waiting = now-self.bow_ready_since < BOW_READY_WAIT_S
                self.needs_firing_position = not waiting
                if not waiting:
                    self.bow_ready_since = None  # the next supported position gets a fresh bounded aim attempt
                self.stats.update(bow_aim_phase='waiting for native aim pose' if waiting else 'native aim pose unavailable',
                    combat='longbow: holding aim while the native pose settles' if waiting
                        else 'longbow: native pose unavailable; reacquire supported position',
                    fire_gate='longbow: aim pose unconfirmed; no camera correction or trigger',
                    aim_feedback='third-person camera withheld until native aim pose')
                return {'hold': {'l1'} if waiting else set()}
            self.bow_ready_since = None
        aim = (foot[0], foot[1] + CHEST_H, foot[2])
        aim_source = "humanoid chest estimate"
        geometry = tgt.get("native_aim") or {}
        if wid == 0x0F and (geometry.get("kind") == "uEm32" or geometry.get("requires_native_center") is True):
            native_point = re5_aim_geometry.point(tgt)
            if native_point is None:
                self.bow_down_at = None
                self.bow_aim = None
                self.stats.pop("bow_aim_point", None)
                if self.laserless_feedback_since is None:
                    self.laserless_feedback_since = now
                self.needs_firing_position = now-self.laserless_feedback_since >= STEER_REACQUIRE_S
                self.stats.update(bow_aim_point_source="native creature center unavailable",
                                  combat="longbow: waiting for verified creature geometry",
                                  fire_gate="longbow: creature aim point unverified; trigger withheld")
                return {"hold": set() if self.needs_firing_position else {"l1"}}
            aim, aim_source = native_point, re5_aim_geometry.SOURCE
        if wid == 0x0F:
            self.stats.update(bow_aim_point=list(aim), bow_aim_point_source=aim_source)
        cam = snap.get("camera") or {}
        camera_direction = None
        try:
            origin, at = tuple(cam["eye"]), tuple(cam["at"])
            if len(origin) != 3 or len(at) != 3 or not all(math.isfinite(v) for v in (*origin, *at)) \
                    or math.dist(origin, at) <= 1.0:
                raise ValueError("invalid camera direction")
            yaw, pitch = ray_error(origin, at, aim)
            camera_direction = list(at)
            self.stats["aim_feedback"] = label+" camera direction; no projectile ray"
        except (KeyError, TypeError, ValueError, OverflowError):
            origin = (p["pos"][0], p["pos"][1]+140., p["pos"][2])
            pitch_now = p.get("pitch")
            if not isinstance(pitch_now, (float, int)) or not math.isfinite(pitch_now):
                self.bow_down_at = None
                if self.laserless_feedback_since is None:
                    self.laserless_feedback_since = now
                self.needs_firing_position = now-self.laserless_feedback_since >= STEER_REACQUIRE_S
                self.stats.update(fire_gate=label+": aim feedback unavailable; hold fire",
                                  combat=label+": route to reacquire native camera/pitch" if self.needs_firing_position
                                  else label+": waiting briefly for native camera/pitch")
                return {"hold":set() if self.needs_firing_position else {"l1"}}
            yaw = facing
            pitch = math.atan2(aim[1]-origin[1], max(math.hypot(aim[0]-origin[0], aim[2]-origin[2]),1.))-pitch_now
            self.stats["aim_feedback"] = label+" body/pitch estimate; no projectile ray"
        self.laserless_feedback_since = None
        distance = math.dist(origin,aim)
        if wid == 0x0F:
            yaw_tol, pitch_tol = bow_tolerance(distance)
        else:                       # a gun: his body's window at this range (wider than BOW_YAW / BOW_PITCH up close)
            win_y, win_p = E.window(math.hypot(foot[0]-p["pos"][0], foot[2]-p["pos"][2]))
            yaw_tol, pitch_tol = max(BOW_YAW, win_y), max(BOW_PITCH, win_p)
        aligned = abs(yaw) <= yaw_tol and abs(pitch) <= pitch_tol
        if wid == 0x0F:
            self.stats.update(bow_aim_tolerance_deg=[round(math.degrees(yaw_tol),3),round(math.degrees(pitch_tol),3)],
                              bow_aim_error_deg=[round(math.degrees(yaw),3),round(math.degrees(pitch),3)],
                              bow_body_error_deg=round(math.degrees(facing),3))
            self.bow_turning = abs(facing) > SWING_TURN and abs(yaw) > BOW_TURN_ENTER
            if self.bow_turning:
                self.bow_turn_started = self.bow_turn_progress_at = now
                self.bow_turn_best = abs(facing)
                self.bow_turn_direction = 1 if facing > 0 else -1
            swing = self.bow_turning
            self.stats['bow_aim_phase'] = 'turning to target' if swing else 'tracking with aim held'
        else:
            swing = abs(facing) > E.SWING_TURN and not aligned
            threat = None
            if swing and depth == 0 and p.get("action") != 4:
                threat = E.front_threat(p, snap.get("enemies") or (), exclude=tgt.get("ptr", tgt.get("slot")))
            if threat is not None:            # a threat in front: he is fought now, the gun stays up
                self.target_key = E.key(threat)
                self.stats["front_first"] = self.stats.get("front_first", 0) + 1
                return self._decide(snap, p, threat, now, observed=True, depth=depth + 1)
        # An on-target aim (camera ray already on his chest) supersedes the whole-body swing: if the aim line is
        # already on him, fire now instead of lowering the gun to turn the body. Only a genuinely off-axis aim for a
        # far-off heading turns first. Never swing mid-grab (action 4).
        # For the bow, a vertical correction or small camera yaw error must never
        # drop aim and turn by the body's heading. The shoulder aim can already
        # face the target while the body remains off-axis. Separate enter/exit
        # angles prevent the aim-camera transition from repeatedly toggling L1.
        if swing and p.get("action") != 4:
            self.bow_down_at = None
            if self._laserless_stalled(p,tgt,wid,abs(facing),shot,now):
                return {"hold":set()}
            self.stats.update(weapon_policy=label+": turn before aiming", fire_gate=label+": turning; hold fire",
                              combat=label+": lower weapon and turn toward target")
            return {"hold": self._face(p, foot)}
        if not (blast and aligned) and self._laserless_stalled(p,tgt,wid,math.hypot(yaw,pitch),shot,now,aligned=aligned):
            return {"hold":set()}
        if wid==0x0F:
            self.bow_aim = {'at':now,'target':tgt.get('ptr'),'player':p.get('ptr'),
                'player_pos':list(p['pos']),'target_pos':list(foot),'origin':list(origin),
                'aim_point':list(aim),'aim_point_source':aim_source,
                'camera_at':camera_direction,
                'distance_cm':round(distance,1),'yaw_error_rad':yaw,'pitch_error_rad':pitch,
                'yaw_tolerance_rad':yaw_tol,'pitch_tolerance_rad':pitch_tol,
                'corridor_supported':bool(corridor),'cover':'projectile collision unverified',
                'ballistic_calibration':'unavailable; no owned impact/flight model'}
        if wid not in (0x0F,0x36) and math.dist(p["pos"],foot) < POINT_BLANK and abs(yaw) <= BOW_YAW:
            aligned = True  # Supported corridor, contact distance: continue firing while correcting elevation.
        fire, policy = laserless_fire_policy(wid, corridor=corridor or blast, aligned=aligned,
                                      loaded=rounds is not None and rounds > 0)
        if blast and fire:
            policy = "laserless gun: close-threat blast"
            self.stats["laserless_blasts"] = self.stats.get("laserless_blasts", 0) + 1
        self.stats["weapon_policy"] = policy
        keys = {"l1"} | self._yaw(yaw,deadzone=yaw_tol*BOW_TRACK if wid==0x0F else None) \
            | self._pitch(pl,p,pitch,now,deadzone=pitch_tol*BOW_TRACK if wid==0x0F else None)
        # Always release between arrows, even when the separate global refire table is accelerated.
        if not fire:
            self.bow_down_at = None
        elif wid not in (0x0F,0x36):
            keys.add("r1")
        elif self.bow_down_at is not None:
            if now-self.bow_down_at < TAP_DOWN_S:
                keys.add("r1")
            else:
                self.bow_down_at, self.bow_up_at = None, now
        elif now-self.bow_up_at >= TAP_UP_S:
            self.bow_down_at = now
            keys.add("r1")
        self.stats["fire_gate"] = (BLAST_GATE_LASERLESS if blast and fire and policy.endswith("blast") else
                                   label+": aimed "+("press/release" if wid in (0x0F,0x36) else "hold") if fire else policy+"; hold fire")
        self.stats["combat"] = (f"{label} yaw {math.degrees(yaw):+.1f} pitch {math.degrees(pitch):+.1f} "
                                f"{'TRIGGER' if 'r1' in keys else 'release / tracking'}")
        return {"hold": keys}

    def _laserless_stalled(self,p,tgt,wid,error,shot,now,*,aligned=False):
        """Finite but static camera/heading feedback must not hold aim or turn in place forever."""
        key = (p.get("ptr"),tgt.get("ptr",tgt.get("slot")),wid)
        progress = self.laserless_progress
        if progress is None or progress["key"] != key:
            self.laserless_progress = {"key":key,"best":error,"improved":now,"started":now}
        elif wid in (0x0F,0x36) and aligned and math.dist(p["pos"],tgt["pos"]) < BOW_STAND_R:
            # Keep firing at an aligned nearby threat. Proximity alone cannot renew this lease: a static,
            # off-target camera otherwise leaves the gun raised forever without a single trigger press.
            progress.update(improved=now,started=now)
        elif wid==0x0F and now-max(progress['started'],self.bow_target_damage.get(tgt.get('ptr'),-math.inf)) >= BOW_BURST_S:
            self.laserless_progress = None
            self.bow_down_at = None
            self.needs_firing_position = True
            self.stats['bow_ineffective_bursts'] = self.stats.get('bow_ineffective_bursts',0)+1
            self.stats.update(combat='longbow: no measured target HP progress; resume supported route',
                              fire_gate='longbow: bounded burst ended; reposition / checkpoint routing')
            return True
        elif wid==0x0F and self.bow_target_damage.get(tgt.get('ptr'),-math.inf)>progress.get('damage',-math.inf):
            progress.update(improved=now,damage=self.bow_target_damage[tgt.get('ptr')])
        elif (shot and wid!=0x0F) or progress["best"]-error >= math.radians(3):
            progress.update(best=error,improved=now)
        elif now-progress["improved"] >= 2.5:
            self.laserless_progress = None
            self.bow_down_at = None
            self.needs_firing_position = True
            self.stats["laserless_reacquisitions"] = self.stats.get("laserless_reacquisitions",0)+1
            self.stats.update(combat="laserless: no shot or aim progress; use supported route",
                              fire_gate="laserless: unproductive aim; release and reacquire")
            return True
        return False

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

    def _face(self, p, foot, tol=math.radians(10)) -> set:
        err = wrap(heading(foot[0] - p["pos"][0], foot[2] - p["pos"][2]) - p["rot"])
        if abs(err) < tol:
            return set()
        return {"rleft"} if err > 0 else {"rright"}

    def _yaw(self, err: float, *, deadzone=None) -> set:
        if abs(err) <= (math.radians(0.6) if deadzone is None else deadzone):
            return set()
        if abs(err) < FINE:
            self.yaw_pulse ^= 1
            if not self.yaw_pulse:
                return set()
        return {"rleft"} if err > 0 else {"rright"}

    def _pitch(self, pl: int, p: dict, err: float, now: float, *, deadzone=None) -> set:
        """The aim pitch: written into the player (+0x1AA0, + = down) by the dot's own error, else the stick."""
        if abs(err) <= (math.radians(0.5) if deadzone is None else deadzone):
            return set()
        if PITCH_WRITE and self.writer.ok and pl:
            try:
                cur = self.io.read_pitch(pl)
                new = max(-1.3, min(1.3, cur - PITCH_GAIN * err))
                if self.io.write_pitch(pl, new):
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
    def _bow_event(self, event):
        try:self.lessons(event)
        except Exception:pass  # lost analytics never blocks control

    def _observe_bow(self, snap, now):
        """HP changes are progress/correlation, not proof of an individual arrow hit or miss."""
        current = {e.get('ptr'):e['hp'] for e in snap.get('enemies') or ()
                   if e.get('ptr') and type(e.get('hp')) in (int,float) and math.isfinite(e['hp'])}
        continuous = self.bow_hp_at is not None and 0 <= now-self.bow_hp_at <= .5
        losses = {ptr:self.bow_hp[ptr]-hp for ptr,hp in current.items()
                  if continuous and ptr in self.bow_hp and hp<self.bow_hp[ptr]}
        self.bow_hp,self.bow_hp_at = current,now
        self.bow_target_damage = {ptr:at for ptr,at in self.bow_target_damage.items() if now-at<=BOW_BURST_S}
        for ptr,loss in losses.items():
            if self.wid!=0x0F:continue
            self.bow_target_damage[ptr] = now
            candidates = [row for row in self.bow_pending if row.get('target')==ptr and 0<=now-row['t']<=BOW_OUTCOME_S]
            if candidates:
                row = candidates[0]
                row['damage_correlation'] = True
                self.stats['bow_damage_correlations'] = self.stats.get('bow_damage_correlations',0)+1
                self._bow_event({'kind':'bow_damage_observation','t':now,'target':ptr,'hp_loss':loss,
                    'firing_observations_in_window':len(candidates),
                    'attribution':'unconfirmed; native projectile collision/source unavailable',
                    'multiple_players':self.damage_unattributed,'ground_mines_present':bool(snap.get('ground_mines')),
                    'calibration_applied':False})
        for row in list(self.bow_pending):
            if now-row['t']<BOW_OUTCOME_S:continue
            self.bow_pending.remove(row)
            correlated = bool(row.get('damage_correlation'))
            key = 'bow_confounded_outcomes' if correlated else 'bow_unconfirmed_impacts'
            self.stats[key] = self.stats.get(key,0)+1
            self._bow_event({'kind':'shot','weapon':0x0F,'character':row['character'],**row,
                'outcome':'confounded' if correlated else 'unknown',
                'result':'bow damage correlated; source unconfirmed' if correlated else 'bow impact unconfirmed: no attributable impact',
                'confirmed_hit':False,'confirmed_miss':False,'calibration_applied':False})
        self.stats['bow_pending_observations'] = len(self.bow_pending)

    def _on_shot(self, now):
        """A shot left: remember what the dot was on (the class the hit / miss gets scored with)."""
        if self.wid==0x0F:
            # Accelerated bow spawns can outnumber action transitions. Preserve this
            # legacy count as observations, never claim it is an arrow/impact count.
            self.shots.stats['shots'] += 1
            self.round_counts['shots'] += 1
            self.bow_round_observations += 1
            self.stats['bow_firing_observations'] = self.stats.get('bow_firing_observations',0)+1
            self.stats['bow_count_basis'] = 'native firing observations; individual arrow count unknown'
            aim = self.bow_aim if self.bow_aim and 0<=now-self.bow_aim['at']<=.5 else {}
            row = {**aim,'t':now,'character':self.character,'native_evidence':self.shot_evidence,
                   'individual_arrow_count':None,'outcome':'pending_unattributed'}
            self.bow_pending.append(row)
            if len(self.bow_pending)>32:
                old = self.bow_pending.pop(0)
                self.stats['bow_unconfirmed_impacts'] = self.stats.get('bow_unconfirmed_impacts',0)+1
                self._bow_event({'kind':'shot','weapon':0x0F,**old,'outcome':'unknown',
                    'result':'bow observation capacity reached; impact unknown',
                    'confirmed_hit':False,'confirmed_miss':False,'calibration_applied':False})
            self._bow_event({'kind':'bow_firing_observation',**row})
            if self.look is not None:                  # an arrow's impact is never attributed: its outcome stays unknown
                try:
                    p = (self._obs_snap or {}).get("player") or {}
                    tgt = aim.get("target_pos")
                    target = {"id": f"{aim['target']:#x}" if isinstance(aim.get("target"), int) else aim.get("target"),
                              "kind": "majini", "dist_m": E.flat(p["pos"], tgt) / 100.0,
                              "bearing_deg": E.bearing_right_deg(p, tgt)} if tgt and p.get("pos") else None
                    yaw = aim.get("yaw_error_rad")
                    self.look.record_shot("longbow (0xf)", self.stats.get("fire_gate"), target,
                                          aim_err_deg=-math.degrees(yaw) if isinstance(yaw, (int, float)) else None,
                                          dot_on="off", t=now)
                except Exception:                      # noqa: BLE001 - the look never stops the fight
                    pass
            return
        self.shots.fired(now)
        self.round_counts["shots"] += 1
        where, ptr, lz, foot = (self.last_dot or (None, None, None, None))[:4]
        if self.wid in (0x0F,0x36) and where is None:
            where = 'egg_projectile' if self.wid==0x36 else "projectile"
        reach = None
        if lz is not None and foot is not None:            # the dot short of him (a wall, a prop) or past him
            d_dot = math.dist(lz[0], lz[1])
            d_him = math.dist(lz[0], (foot[0], foot[1] + HEAD_H, foot[2]))
            reach = "short" if d_dot < d_him - 60 else ("past" if d_dot > d_him + 60 else "beside")
        self._pending_where = getattr(self, "_pending_where", [])
        rec = self._shot_record(now, where, reach)
        self._pending_where.append((now, where, ptr, reach, round(d_him) if foot is not None and lz is not None else None,
                                    self.wid, self.character, rec))
        try:
            self._look_shot(now, rec, lz, foot, ptr)
        except Exception as exc:                     # noqa: BLE001 - the look never stops the fight
            self.stats["look_error"] = f"{type(exc).__name__}: {exc}"[:160]
        # Native shots are counted above; learned weapon samples enter only when their outcome is resolvable.

    def _look_shot(self, now, rec, lz, foot, ptr) -> None:
        """The shot into the look (gbox.mercs.bot_look): the weapon, the fire gate, the target (id, kind, distance,
        bearing + = right), the aim error at the trigger (+ = he was right of the aim; the laser's, else the camera / body
        estimate's), what the dot was on (re5_engage.dot_class: also the record's "dot_on", and this round's round_dots).
        Its outcome follows in _look_resolve."""
        snap = self._obs_snap or {}
        p = snap.get("player") or {}
        enemies = snap.get("enemies") or ()
        dot = E.dot_class(lz, foot, p, enemies, dot_on) if p.get("pos") else ("off" if lz is None else "none")
        rec["dot_on"] = dot
        self.round_dots[dot] = self.round_dots.get(dot, 0) + 1
        if self.metrics is not None:                # the round's behaviour block: what the line met, on the window or not
            self.metrics.shot_line(dot)
            self.metrics.shot(now, dot == "target" or rec.get("gate") in WINDOW_GATES)
        if self.look is None:
            return
        tgt = next((e for e in enemies if e.get("ptr", e.get("slot")) == ptr), None) if ptr is not None else None
        target = None
        if foot is not None and p.get("pos"):
            target = {"id": f"{ptr:#x}" if isinstance(ptr, int) else ptr,
                      "kind": "boss" if tgt is not None and (tgt.get("hp_max") or 0) > BOSS_HP else "majini",
                      "dist_m": E.flat(p["pos"], foot) / 100.0, "bearing_deg": E.bearing_right_deg(p, foot)}
        yaw = rec.get("yaw_err") if rec.get("yaw_err") is not None else rec.get("est_yaw")
        name = rec.get("weapon") or "unknown"
        if isinstance(self.wid, int):
            name = f"{name} ({self.wid:#x})"
        entry = self.look.record_shot(name, rec.get("gate") or self.stats.get("fire_gate"), target,
                                      aim_err_deg=0.0 - yaw if isinstance(yaw, (int, float)) else None, dot_on=dot,
                                      t=now)
        if len(self._look_pending) > 64:
            self._look_pending.pop(next(iter(self._look_pending)))
        self._look_pending[id(rec)] = (entry, ptr, dict(self._enemy_hp))

    @staticmethod
    def _look_cause(rec) -> str:
        """A miss's cause in the look's words (gbox.mercs.bot_look.MISS_CAUSES)."""
        dot = rec.get("dot_on")
        if dot in ("wall", "floor"):
            return dot
        causes = rec.get("causes") or B.causes(rec)
        if "too far for the weapon" in causes:
            return "out_of_range"
        if rec.get("where") in ("head", "body", "leg") or dot == "target":
            return "no_damage"
        if dot == "off" and rec.get("state") in ("swing", "readying", "stale", "reload", "grab", None):
            return "gun_down"
        if rec.get("target") is None:
            return "nothing"
        return "off_target"

    def _look_resolve(self, rec, result) -> None:
        """A shot's outcome into its look entry: "hit:<kind of the Majini hurt>" with his health change, or
        "miss:<cause>"; an unattributed one stays "unknown"."""
        pend = self._look_pending.pop(id(rec), None)
        if pend is None or self.look is None:
            return
        entry, ptr, hp_then = pend
        if result == "hit":
            cur = {e.get("ptr", e.get("slot")): e for e in (self._obs_snap or {}).get("enemies") or ()}
            drops = {k: hp_then[k] - cur[k]["hp"] for k in hp_then
                     if k in cur and isinstance(cur[k].get("hp"), (int, float)) and cur[k]["hp"] < hp_then[k]}
            k = ptr if ptr in drops else (max(drops, key=drops.get) if drops else None)
            e = cur.get(k) if k is not None else None
            kind = "boss" if e is not None and (e.get("hp_max") or 0) > BOSS_HP else "majini"
            outcome = f"hit:{kind}"
            self.look.resolve(entry, outcome, -int(drops[k]) if k is not None else None)
        elif result == "miss":
            outcome = "miss:" + self._look_cause(rec)
            self.look.resolve(entry, outcome)
        else:
            return
        if self.metrics is not None:
            self.metrics.shot_result(outcome)

    def _shot_record(self, now, where, reach) -> dict:
        """The shot's record (gbox.mercs.ballistics): the aim decided at the last tick - when it is that fresh - and
        the result, filled in when the shot is scored (_resolve)."""
        from .re5_weapons import WEAPONS
        aim = self.last_aim if self.last_aim is not None and 0 <= now - self.last_aim["at"] <= AIM_STALE_S else None
        rec = {"t": round(now - self.round_t0, 2) if self.round_t0 is not None else None,
               "wid": self.wid, "character": self.character, "result": "pending"}
        spec = WEAPONS.get(self.wid)
        if spec is not None:
            rec.update(weapon=spec.name, family=spec.family, rng=spec.preferred_cm)
        if aim is None:
            rec["state"] = "stale"
        else:
            rec.update({k: v for k, v in aim.items() if k not in ("at", "wid", "character") and v is not None})
        rec["where"] = where if where in ("head", "body", "leg") else None
        if where in ("egg_projectile", "projectile"):
            rec["projectile"] = True
        if reach:
            rec["reach"] = reach
        if len(self.round_shots) < SHOTS_PER_ROUND:
            self.round_shots.append(rec)
        return rec

    def _resolve(self, rec, result, now, t, *, headshot=False, cls=None) -> None:
        """A shot's outcome into its record; a solo, attributed hit or miss also into the calibration's band; the record
        to the driver's round map."""
        if not isinstance(rec, dict) or rec.get("result") != "pending":
            return
        if result == "miss" and rec.get("projectile"):
            result = "unconfirmed"                    # an egg / arrow without an observed HP loss is no measured miss
        rec["result"] = result
        if result == "hit":
            rec["tth"] = round(max(0.0, now - t), 3)
            if headshot:
                rec["headshot"] = True
        elif cls:
            rec["miss"] = cls
        if result == "miss":
            rec["causes"] = B.causes(rec)
        try:
            self._look_resolve(rec, result)
        except Exception as exc:                     # noqa: BLE001 - the look never stops the fight
            self.stats["look_error"] = f"{type(exc).__name__}: {exc}"[:160]
        if result in ("hit", "miss") and not self.damage_unattributed and not self.bow_round_observations:
            self.cal.observe(rec)
        if self.shot_sink is not None:
            try:
                self.shot_sink(dict(rec))
            except Exception:                         # noqa: BLE001 - a lost record never stops the fight
                pass

    def _score(self, now):
        st = self.shots.stats
        hits, misses = st["hits"], st["misses"]
        new_hits, new_misses = hits - self._scored_hits, misses - self._scored_misses
        self._scored_hits, self._scored_misses = hits, misses
        pend = getattr(self, "_pending_where", [])
        for _ in range(new_hits):
            row = pend.pop(0) if pend else (now, None, None, None, None, self.wid, self.character)
            t, where, ptr, reach, dist, wid, character = row[:7]
            self._resolve(row[7] if len(row) > 7 else None, "hit", now, t, headshot=where == "head")
            self.round_counts["hits"] += 1
            w = self.tun.weapon(character, wid or 0)
            w['shots'] += 1
            w["hits"] += 1
            counts = self.round_weapons.setdefault((character, wid or 0), {'shots': 0, 'hits': 0})
            counts['shots'] += 1
            counts['hits'] += 1
            if where == "head":
                self.stats["headshots"] += 1
                self.round_counts["headshots"] += 1
                w["headshots"] += 1
            if where == "leg":
                self.stats["legshots"] = self.stats.get("legshots", 0) + 1
            if where in ("head", "leg") and ptr:          # a stun (the kneel / the head reel): in for the finisher
                self.stunned[ptr] = now + STUN_S
            self._log_shot(t, "headshot" if where == "head" else "hit", where, reach, dist, ptr, weapon=wid, character=character)
        for _ in range(new_misses):
            row = pend.pop(0) if pend else (now, None, None, None, None, self.wid, self.character)
            t, where, ptr, reach, dist, wid, character = row[:7]
            self.tun.weapon(character, wid or 0)['shots'] += 1
            self.round_weapons.setdefault((character, wid or 0), {'shots': 0, 'hits': 0})['shots'] += 1
            if where == 'egg_projectile':
                cls,key='egg impact unconfirmed: no observed HP loss','egg_unconfirmed_impacts'
            elif where == "projectile":
                cls, key = "bow impact unconfirmed: no observed HP loss", "bow_unconfirmed_impacts"
            elif where in ("head", "body"):              # the dot was on him and nothing fell: he moved / a frame late
                cls, key = "miss: dot on him, he moved", "miss_moved"
            elif reach == "short":
                cls, key = "miss: line of sight blocked (the dot short of him)", "miss_short"
            elif reach == "past":
                cls, key = "miss: the ray passed him (aim)", "miss_past"
            else:
                cls, key = "miss: the dot beside him (aim)", "miss_beside"
            self.stats[key] = self.stats.get(key, 0) + 1
            self._resolve(row[7] if len(row) > 7 else None, "miss", now, t, cls=cls)
            self._log_shot(t, cls, where, reach, dist, ptr, weapon=wid, character=character)
        self.stats["shots"], self.stats["hits"], self.stats["misses"] = st["shots"], hits, misses
        self.stats["accuracy"] = None if self.damage_unattributed or self.round_unattributed_shots or self.wid==0x0F or self.bow_round_observations else st["accuracy"]
        self.stats.update(round_shots=self.round_counts["shots"], round_hits=self.round_counts["hits"],
                          round_accuracy=(round(self.round_counts["hits"] / self.round_counts["shots"], 3)
                                          if self.round_counts["shots"] and not self.damage_unattributed
                                          and not self.round_unattributed_shots and not self.bow_round_observations else None))

    def _log_shot(self, t, cls, where, reach, dist, ptr, *, weapon=None, character=None):
        """Every shot into the title's run-lessons log (operator: "why did he miss" -> its class)."""
        self.stats["last_shot"] = cls
        weapon = self.wid if weapon is None else weapon
        character = self.character if character is None else character
        try:
            self.lessons({"kind": "shot", "t": round(t, 2), "result": cls, "dot": where, "reach": reach,
                          "dist_cm": dist, "target": ptr, "weapon": weapon, "character": character,
                          "trigger": (self.triggers.get(weapon).mode if weapon in self.triggers else None)})
        except Exception:                              # noqa: BLE001 - a lesson lost never stops the fight
            pass

    def _count_kills(self, snap):
        """Kills from the game's own counter; headshot % and shots per kill follow (the #3046 measures)."""
        k = snap.get("kills")
        if type(k) is int:
            last = getattr(self, "_kills_last", None)
            if last is not None and 0 < k - last < 20:
                key = 'team_kills_seen_by_combat' if self.damage_unattributed else 'kills_seen_by_combat'
                self.stats[key] = self.stats.get(key, 0) + k - last
            self._kills_last = k
        self._headshot_metrics()

    def _headshot_metrics(self):
        shots, kills = self.stats.get("shots") or 0, self.stats.get("kills_seen_by_combat") or 0
        self.stats["headshot_pct"] = (round(100.0 * (self.stats.get("headshots") or 0) / shots, 1)
                                      if shots and not self.damage_unattributed and not self.round_unattributed_shots and not self.bow_round_observations else None)
        self.stats["shots_per_kill"] = round(shots / kills, 2) \
            if kills and not self.damage_unattributed and not self.round_unattributed_shots and not self.bow_round_observations else None

    def start_round(self, now):
        """Called on an observed playing transition, never inferred from a clock bonus."""
        if self.round_t0 is not None:
            return
        self.round_t0 = now
        self.damage_unattributed = False
        self.mine_damage_confounded = False
        self.mine_confounded_until = -math.inf
        self._mine_release_sample = False
        self.round_unattributed_shots = 0
        self._unattributed_hp = {}
        self.round_counts = {"shots": 0, "hits": 0, "headshots": 0, "finishers": 0, "time_gained_s": 0.0}
        self.round_weapons = {}
        self.round_shots = []
        self.round_dots = {}
        self._look_pending.clear()
        self.swing_key = None
        self.last_aim = None
        self.last_timer = None
        self.bow_down_at, self.bow_up_at = None, -1e9
        self.bow_turn_key, self.bow_turning = None, False
        self.bow_turn_started = self.bow_turn_progress_at = 0.
        self.bow_turn_best, self.bow_turn_direction = math.inf, 0
        self.bow_ready_key, self.bow_ready_since = None, None
        self.bow_target_key = None
        self.laserless_feedback_since, self.needs_firing_position = None, False
        self.laserless_progress = None
        self.bow_pending.clear()
        self.bow_aim = None
        self.bow_hp.clear()
        self.bow_hp_at = None
        self.bow_target_damage.clear()
        self.bow_round_observations = 0
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
        self._observe_impacts([], now + HIT_S + 1)
        self._observe_bow({},now+BOW_OUTCOME_S+1)
        self._score(now)
        self._ballistics_round()
        self._round_over()
        self.round_t0 = None
        self.last_timer = None

    def _ballistics_round(self):
        """The round's ballistic one-liner (stats["ballistics"]; the driver's round map adds the hits he took); a solo,
        attributed round's steady hits move the band corrections (ballistics.Calibration.learn)."""
        if self.round_shots and not self.damage_unattributed and not self.bow_round_observations:
            learned = self.cal.learn(self.round_shots)
            if learned:
                self.stats["aim_calibration_learned"] = "; ".join(
                    f"{k} {y:+.2f}/{p:+.2f} deg ({n} hits)" for k, (y, p, n) in list(learned.items())[:4])
        self.cal.save()
        self.last_report = B.report(self.round_shots)
        self.stats["ballistics"] = self.last_report["line"]      # "no shots" when there were none (never last round's)

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
        if self.damage_unattributed or self.bow_round_observations:
            # Preserve measured shots/team time without turning shared HP changes
            # into personal accuracy or adapting the P2 weapon's aim settings.
            if self.lessons:
                try:
                    self.lessons({'kind':'combat_round','character':self.character,'weapon':self.wid,**rc,
                                  'hit_rate':None,'damage_attribution':('unattributed_multiple_players' if self.damage_unattributed
                                      else 'bow projectile impact ownership unavailable'),
                                  'bow_firing_observations':self.bow_round_observations,'calibration_applied':False})
                except Exception:
                    pass
            return
        w = self.tun.weapon(self.character, self.wid or 0)
        w["rounds"] += 1
        w["finishers"] += rc["finishers"]
        w["time_gained_s"] = round(w["time_gained_s"] + rc["time_gained_s"], 1)
        rate = rc["hits"] / rc["shots"] if rc["shots"] and not self.round_unattributed_shots else None
        # Each firing weapon learns from its own observations, never from the weapon held at the results screen.
        groups = self.round_weapons or ({} if self.round_unattributed_shots else {(self.character, self.wid or 0): rc})
        for (character, wid), counts in groups.items():
            tune = self.tun.weapon(character, wid)
            weapon_rate = counts['hits'] / counts['shots'] if counts['shots'] else None
            if weapon_rate is not None and weapon_rate < HIT_RATE_WANT:
                tune["head_r"] = round(max(12.0, tune["head_r"] * 0.85), 1)
                tune["settle_s"] = round(min(0.3, tune["settle_s"] + 0.04), 3)
            elif weapon_rate is not None and weapon_rate >= 0.999 and counts['shots'] >= 10:
                tune["head_r"] = round(min(HEAD_R, tune["head_r"] * 1.1), 1)
                tune["settle_s"] = round(max(0.03, tune["settle_s"] - 0.02), 3)
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
            self.cal.save()
