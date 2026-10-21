"""RE5 Gold (BLUS30491) Mercenaries: the combat layer - only landed shots (operator 2026-10-21: "i am absolutely tired
of seeing missed shots in mercenaries ... I want only landed shots happening"; "I need him doing only headshots").

The game's own laser sight is the truth about a shot: the bullet goes from the laser's origin (the muzzle) to the laser
dot, the first thing the ray hits (uLaserSight, an FxCore unit: +0x200 origin, +0x30 dot). The camera ray is not the
shot ray (5 deg off, up to 15), and the body's yaw is not either (the upper body aims inside a cone): a loop closed on
anything but the dot misses. So every tick:
  * the dot is read and tested against the target Majini's head (a sphere HEAD_R at HEAD_H above his feet) and his
    body (a capsule BODY_R wide from KNEE_H to SHOULDER_H): on the head = a headshot, on the body = a hit, elsewhere
    = the ray hits something else first (the floor, a wall, a prop) or passes him;
  * the aim is steered until the dot sits on the head: the pitch is written straight into the player (+0x1AA0, + =
    down: the game keeps it, the upper body follows next frame), the yaw with the right stick in pulses (the game's
    own aim loop: ~30 deg/s), both from the dot's error as seen from the laser's origin;
  * the trigger is pulled only while the dot is on him (headshot first; a body shot after BODY_AFTER_S on the body
    with the head out of reach): a tap (R1 down TAP_DOWN_S, up TAP_UP_S) for the handguns and magnums (a held R1
    fires them once), a hold for the Gatling; which one a weapon wants is learned (no shot from a hold = taps) and
    kept per weapon id;
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
    mode, the head tolerance) is kept under gbox-data (TUNABLES_FILE) and adjusted after every round: a round under
    HIT_RATE_WANT tightens the head tolerance and the settle time, one at 100 % loosens them a notch.

RAM writes (the operator wants RAM cheating for RE5): only the player's aim pitch (+0x1AA0) and only while aiming; the
mods agent writes the globals and the weapon definitions, never the player (agreed 2026-10-21). Read-only when the
memory can't be written (no pid: a test, another platform's view).
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
P_ACTION_OBJ = 0x30B0                  # -> the current cPlAction (mods agent, live 2026-10-21 with Chris; with Barry
                                       # the object there kept one vtable 0x0163C3B8 through 180 shots: not used then)
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
HEAD_LEAD_S = 0.06                     # the dot is a frame old and the trigger two more: lead his head by this
TAP_DOWN_S, TAP_UP_S = 0.045, 0.06     # a tap: R1 down (two frames), then up (three) before the next
HOLD_NO_SHOT_S = 0.45                  # held on target this long without a shot: this weapon wants taps
TAPS_NO_SHOT = 8                       # ... taps without a shot: it wants a hold (the Gatling)
HOLD_FIRE_IDS = frozenset({0x25})      # weapon ids that fire on a hold (the Gatling); the rest learned
BODY_AFTER_S = 0.5                     # the dot on his body (not the head) this long: a body shot is still a hit
SETTLE_S = 0.08                        # the dot on the head this long before the first shot (it moves with him)
AIM_TURN_RAD_S = 0.52                  # the right stick while aiming: ~30 deg/s (the mods agent scales it)
FINE = math.radians(4)                 # closer than this: the stick in pulses (a tick on, a tick off)
PITCH_WRITE = True                     # the pitch straight into +0x1AA0 (else the stick)
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
    """Where the laser dot sits on a Majini standing at foot: "head" (inside the head sphere), "body" (inside the body
    capsule), else None (the ray ends somewhere else: short of him, past him, beside him)."""
    dx, dy, dz = dot[0] - foot[0], dot[1] - foot[1], dot[2] - foot[2]
    if math.sqrt(dx * dx + (dy - HEAD_H) ** 2 + dz * dz) <= head_r:
        return "head"
    flat = math.hypot(dx, dz)
    if flat <= body_r and KNEE_H - 10 <= dy <= SHOULDER_H + 20:
        return "body"
    return None


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
        self.triggers: dict = {}
        self.act_seen = None                  # (vtable, frames) of the action object last tick
        self.pulse = 0
        self.dot_head_since = None
        self.dot_body_since = None
        self.last_dot = None                  # (where, tgt ptr, t) the dot at the last tick: what a shot left on
        self.stunned: dict = {}               # Majini ptr -> until
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

    # --- the tick ---
    def tick(self, snap: dict, p: dict, tgt: dict, now: float) -> dict:
        pl = p.get("ptr") or self._player_ptr()
        self.character = CHARACTERS.get(u32(self.m, pl), f"vt{u32(self.m, pl):#x}") if pl else "?"
        wid, rounds = self._in_hand(snap, pl)
        self.wid = wid
        enemies = snap.get("enemies") or []
        shot = self._shot(pl, rounds, p.get("action") == AIMING, now)
        if shot:
            self._on_shot(now)
        self.shots.update(enemies, now)
        self._score(now)
        self._clock(snap, now)
        # the laser dot against him (the driver's snapshot carries it as {"from", "at"} when it read it)
        sl = snap.get("laser")
        lz = (tuple(sl["from"]), tuple(sl["at"])) if sl and sl.get("from") and sl.get("at") and any(sl["from"])             and math.dist(sl["from"], sl["at"]) >= 5.0 else (None if sl else self.laser.read(now))
        foot = tgt["pos"]
        lead = self._lead(tgt, now)
        head = (foot[0] + lead[0], foot[1] + HEAD_H, foot[2] + lead[1])
        tune = self.tun.weapon(self.character, wid or 0)
        where = None
        if lz is not None:
            where = dot_on(lz[1], (foot[0] + lead[0], foot[1], foot[2] + lead[1]), head_r=tune["head_r"])
        self.last_dot = (where, tgt.get("ptr"), lz, foot, now)
        if p.get("action") != AIMING or lz is None:
            self.dot_head_since = self.dot_body_since = None
            self.stats["combat"] = "readying"
            return {"hold": {"l1"} | self._face(p, foot)}
        # steer the dot onto his head
        yaw_err, pitch_err = ray_error(lz[0], lz[1], head)
        keys = {"l1"}
        keys |= self._yaw(yaw_err)
        keys |= self._pitch(pl, p, pitch_err, now)
        # the trigger: on the head (settled), or on the body after BODY_AFTER_S with the head out of reach
        self.dot_head_since = (self.dot_head_since or now) if where == "head" else None
        self.dot_body_since = (self.dot_body_since or now) if where in ("head", "body") else None
        on_head = where == "head" and now - self.dot_head_since >= tune["settle_s"]
        on_body = where == "body" and now - self.dot_body_since >= BODY_AFTER_S
        on_target = (on_head or on_body) and (rounds is None or rounds > 0)
        if rounds == 0:
            if now - self.reload_at > EMPTY_RELOAD_EVERY_S:   # empty: reload (the driver switches weapons)
                self.reload_at = now
                self.stats["reloads"] += 1
                return {"hold": {"l1", "cross"}}
            return {"hold": {"l1"}}
        trig = self.triggers.get(wid)
        if trig is None:
            trig = self.triggers[wid] = Trigger(tune["mode"])
        keys |= trig.keys(now, on_target, shot)
        tune["mode"] = trig.mode
        self.stats["combat"] = (f"{self.character} w{wid:#x} dot {where} yaw {math.degrees(yaw_err):+.1f} "
                                f"pitch {math.degrees(pitch_err):+.1f} {trig.mode} {'FIRE' if on_target else ''}")
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
        new_hits, new_misses = hits - self.stats["hits"], misses - self.stats["misses"]
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
                if ptr:
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

    def _log_shot(self, t, cls, where, reach, dist, ptr):
        """Every shot into the title's run-lessons log (operator: "why did he miss" -> its class)."""
        self.stats["last_shot"] = cls
        try:
            self.lessons({"kind": "shot", "t": round(t, 2), "result": cls, "dot": where, "reach": reach,
                          "dist_cm": dist, "target": ptr, "weapon": self.wid, "character": self.character,
                          "trigger": (self.triggers.get(self.wid).mode if self.wid in self.triggers else None)})
        except Exception:                              # noqa: BLE001 - a lesson lost never stops the fight
            pass

    def _clock(self, snap, now):
        """The round's start / end and the clock's jumps (finisher kills give +5 s)."""
        t = snap.get("timer")
        if t is None:
            return
        if self.round_t0 is None or (self.last_timer is not None and t > self.last_timer + 20):
            if self.round_t0 is not None:
                self._round_over()
            self.round_t0 = now
            self.round_counts = {"shots": 0, "hits": 0, "headshots": 0, "finishers": 0, "time_gained_s": 0.0}
        elif self.last_timer is not None and 3 < t - self.last_timer <= 20:
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

    def stunned_target(self, enemies, p, now):
        """A Majini stunned by a headshot, in finisher reach: close in on him (the prompt comes at ~1.5 m)."""
        for e in enemies:
            until = self.stunned.get(e.get("ptr"))
            if not until or now > until or (e.get("hp") or 0) <= 0:
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
            self._round_over()
            self.round_t0 = None
        else:
            self.tun.save()
