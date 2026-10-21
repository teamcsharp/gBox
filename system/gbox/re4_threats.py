"""Resident Evil 4 (GameCube G4BE08) Mercenaries: who is attacking Leon right now, and what is flying at him, from RAM.

Operator 2026-10-20, watching the bot: "Leon should be able to recognize currently attacking enemies or enemies that are
doing their animations and basically dispatch them immediately. This is part of the RAM scanning. When enemies are doing
attack animations, we need to identify where they are and shoot them to prevent it in a split second." ... "He should be
able to see and shoot any obstacle that's thrown at him out the air."

    from gbox import re4_threats as T
    em = T.em_fields(table, offset)    # one EmMgr slot's combat fields (re4_merc_bot.snapshot adds them to each Ganado)
    tr = T.Tracker()
    threats = tr.update(snapshot, now) # [Threat], most urgent first: attacks by time to land, thrown weapons, the rest

Where it lives (the Ganado code module, REL id 20 in em/em16.drs's DAT tail, decoded with capstone 2026-10-20, and
main.dol):
  em +0xFC..0xFF  the routine bytes r_no_0..3. r_no_0: 0 setting up, 1 acting (r_no_1 = the action: the table of 0x6E
                  (prep, act) pairs at module +0x45610 that 0x817067F4-style dispatch reads), 2 hurt (r_no_1 = how: a
                  stagger, a knock-down), 3 dying (r_no_1 = how), 0xFF gone. r_no_2 is the step inside the action.
  em +0x1D8       the main motion (MOTION_INFO; set by 0x80128DE8, stepped by 0x8012AF34): +0 the motion's data,
                  +0xB0 u32 this frame's events (low byte em+0x28B: 0x01 the attack's hit frames - the grab routine
                  0x81718908 checks for Leon only while it is set -, 0x08 turning onto Leon, 0x20 the swing's sound),
                  +0xB8 f32 the frame (em+0x290), +0xBC u16 the frames in it (em+0x294), +0xC0 f32 its speed (em+0x298).
  em +0x370       f32: the squared ground distance to Leon the Ganado's AI uses (written every frame by 0x800C89C4;
                  its attack picks compare it with 1300^2 .. 4500^2).
  the attack picker (module 0x8172B330, called while the Ganado acts) tries, in order: r_no_1 0x20, 0x27, 0x26 / 0x28,
                  0x29, 0x2A, 0x2B, 0x2C / 0x2D, 0x21 / 0x22 (throws: they make em 0x42 with 0x80011944), 0x23 (lit
                  dynamite), 0x24, 0x25, 0x2F / 0x31 (Ashley), 0x33 / 0x39. The swings check Leon with the module's
                  melee hit 0x817387DC (a weapon point against him, the attack table at module +0x45B48: a 250-750 hit
                  radius, 380-1400 damage, 9999 for the chainsaw) only while the motion's hit bit is on; a hit puts him
                  in his hit reaction (0x800CEF18). 0x2D is the grab, 0x2E-0x38 hold Leon (0x34 / 0x36 hurt him while
                  held). Hit frames from the motions' SEQ events: 0x26 frames 15-21 (0.5 s), 0x24 / 0x25 frame 41,
                  0x28 frames 50-72, 0x29 frames 29-42.
  em id 0x42      a thrown weapon (hand axe, sickle, dynamite): an EmMgr slot of its own, position +0x94; dynamite
                  hurts within 800 (0x800CE1BC: radius 500 + 300, 1200 damage and a knock-down).
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

EM_ROUTINE, EM_ID, EM_TYPE = 0xFC, 0x100, 0x101
EM_MOTION = 0x1D8                       # MOTION_INFO: +0 the motion's data
EM_EVTAB = 0x280                        # MOTION_INFO +0xA8: the motion's per-frame event words (u32 each, low byte =
                                        # the event bits; the motion set 0x80128DE8 stores its 4th argument here)
EM_EVENTS = 0x288                       # u32 events of the motion's current frame (byte 0x28B: the attack bits)
EM_FRAME, EM_FRAMES, EM_SPEED = 0x290, 0x294, 0x298
EM_DIST2 = 0x370
EV_HIT, EV_HOMING, EV_SWING = 0x01, 0x08, 0x20
R_INIT, R_ACT, R_HURT, R_DIE, R_GONE = 0, 1, 2, 3, 0xFF
THROWN_ID = 0x42
FPS = 30.0                              # RE4 runs its game logic at 30 frames a second

# r_no_1 (while r_no_0 = R_ACT) -> (kind, reach: how close the Ganado must be for it to land, lands: seconds from the
# start of the action to its hit frames when the motion can't be read ahead). A swing reaches its weapon point's hit
# radius (250-750) past the Ganado as he lunges; a throw lands from anywhere in sight.
ATTACKS = {
    0x20: ("rush", 2000.0, 1.0),
    0x21: ("throw", 9000.0, 0.9), 0x22: ("throw", 9000.0, 0.9), 0x23: ("dynamite", 9000.0, 1.5),
    0x24: ("swing", 900.0, 0.8), 0x25: ("swing", 900.0, 0.8),
    0x26: ("swing", 1200.0, 0.7), 0x27: ("swing", 1200.0, 0.7), 0x28: ("swing", 1200.0, 0.7),
    0x29: ("swing", 1200.0, 0.7), 0x2A: ("swing", 1200.0, 0.7), 0x2B: ("swing", 1200.0, 0.7),
    0x2C: ("swing", 1200.0, 0.7), 0x2D: ("grab", 1200.0, 0.7),
}
HOLDS = frozenset(range(0x2E, 0x39))    # holding Leon (grab_align 0x800CF968): shoot the holder
MELEE = frozenset({"swing", "grab", "rush"})        # attacks that need him in reach: they can be stepped out of
REACH = {kind: max(r for k, r, _ in ATTACKS.values() if k == kind) for kind, _, _ in ATTACKS.values()}
APPROACH, CLOSE_SPEED = 2000.0, 2500.0  # a melee attack this far beyond its reach is still coming (its picks start
                                        # them from up to 2000-2500 away), closing in at about this speed
THROWN_HIT_R = 900.0                    # a thrown weapon passing this close to Leon is coming for him
THROWN_MIN_SPEED = 800.0                # slower than this (units a second, on the ground plane): not flying
DYNAMITE_R = 800.0                      # 0x800CE1BC: 500 + 300


def em_fields(d: bytes, o: int) -> dict:
    """The combat fields of the EmMgr slot at offset o of the table bytes d."""
    r = d[o + EM_ROUTINE:o + EM_ROUTINE + 4]
    frame, frames, speed = struct.unpack_from(">fHxxf", d, o + EM_FRAME)
    return {"r": tuple(r), "id": d[o + EM_ID], "type": d[o + EM_TYPE],
            "rot": struct.unpack_from(">f", d, o + 0xA4)[0],
            "ev": d[o + EM_EVENTS + 3], "frame": frame, "frames": frames, "fspeed": speed,
            "motion": struct.unpack_from(">I", d, o + EM_MOTION)[0],
            "evtab": struct.unpack_from(">I", d, o + EM_EVTAB)[0],
            "d2": struct.unpack_from(">f", d, o + EM_DIST2)[0]}


def hit_ahead(m, e: dict) -> float | None:
    """Seconds until the Ganado's current motion reaches its hit frames (0 while they are on), from the motion's own
    per-frame event words; None when the motion has no hit frames ahead (or no event table)."""
    p, frames = e.get("evtab", 0), e.get("frames", 0)
    if not (0x80000000 <= p < 0x81800000) or not 0 < frames <= 600 or m is None:
        return None
    cur = max(0, int(e.get("frame", 0.0)))
    if cur >= frames:
        return None
    try:
        words = struct.unpack(f">{frames - cur}I", m.rd(p + 4 * cur, 4 * (frames - cur)))
    except Exception:                                   # noqa: BLE001 - a torn read: no look-ahead this tick
        return None
    for i, w in enumerate(words):
        if w & EV_HIT:
            speed = e.get("fspeed") or 1.0
            return max(0.0, (cur + i - e.get("frame", 0.0))) / (FPS * max(speed, 0.05))
    return None


def thrown(d: bytes, n: int, stride: int) -> list[dict]:
    """The thrown weapons in the air: EmMgr slots of em id 0x42 that are in use (flags & 1) and still flying (r_no_0 1)."""
    out = []
    for k in range(1, n):
        o = k * stride
        if d[o + EM_ID] != THROWN_ID or not struct.unpack_from(">I", d, o)[0] & 1:
            continue
        r = tuple(d[o + EM_ROUTINE:o + EM_ROUTINE + 4])
        if r[0] != R_ACT:
            continue
        out.append({"slot": k, "pos": struct.unpack_from(">3f", d, o + 0x94), "type": d[o + EM_TYPE], "r": r})
    return out


def dying(e: dict) -> bool:
    """Dead or on the way: health gone, the death routine, or no longer set up. Shooting him is a wasted shot."""
    r = e.get("r")
    return e.get("hp", 1) <= 0 or (r is not None and r[0] in (R_DIE, R_GONE))


@dataclass
class Threat:
    slot: int
    kind: str                       # an attack kind (swing, grab, throw, dynamite, rush, hold), "thrown" or "near"
    eta: float                      # seconds until it can land (math.inf: not coming)
    pos: tuple                      # where to shoot (predicted at the shot), world units
    dist: float                     # ground distance from Leon now
    state: tuple = ()
    since: float = 0.0              # when the Ganado started this action
    vel: tuple = (0.0, 0.0, 0.0)
    why: str = ""
    enemy: dict = field(default_factory=dict, repr=False)


class Shots:
    """Shots and what they did, from RAM: a shot is a trigger press the gun could fire (GUN_GAP since the last one);
    it hit when any Ganado's health fell, or one started dying, within HIT_S of it (the Hand Cannon goes through
    bodies: whoever it hit counts); else it missed."""

    GUN_GAP = 35 / FPS                  # the Hand Cannon's own rate: 35 frames a shot
    HIT_S = 0.5

    def __init__(self):
        self.hp: dict[int, tuple] = {}            # slot -> (hp, dying)
        self.pending: list[float] = []            # shot times not yet scored
        self.last_shot = -math.inf
        self.stats = {"shots": 0, "hits": 0, "misses": 0, "kills": 0, "accuracy": 0.0}

    def press(self, now: float) -> bool:
        """A trigger press; True when it counts as a shot (the gun was ready). For titles that can't see the shot."""
        if now - self.last_shot < self.GUN_GAP:
            return False
        self.fired(now)
        return True

    def fired(self, now: float) -> None:
        """A shot the game fired (seen in RAM)."""
        self.last_shot = now
        self.pending.append(now)
        self.stats["shots"] += 1

    def update(self, enemies: list[dict], now: float) -> list[int]:
        """Score the pending shots against this tick's health; returns the slots hurt since the last tick."""
        hurt, cur = [], {}
        for e in enemies:
            k, hp, dy = e["slot"], e.get("hp"), dying(e)
            cur[k] = (hp, dy)
            was = self.hp.get(k)
            if was is not None and ((hp is not None and was[0] is not None and hp < was[0]) or (dy and not was[1])):
                hurt.append(k)
                if dy and not was[1]:
                    self.stats["kills"] += 1
        self.hp = cur
        if hurt and self.pending:
            self.pending.pop(0)
            self.stats["hits"] += 1
        while self.pending and now - self.pending[0] > self.HIT_S:
            self.pending.pop(0)
            self.stats["misses"] += 1
        n = self.stats["hits"] + self.stats["misses"]
        self.stats["accuracy"] = round(self.stats["hits"] / n, 3) if n else 0.0
        return hurt


class Tracker:
    """Memory across ticks: when each Ganado started its current action (r_no_0, r_no_1), its velocity, the thrown
    weapons' flights. update() -> threats, most urgent first."""

    def __init__(self, m=None, lead_s: float = 0.15):
        self.m, self.lead_s = m, lead_s                # m: RAM for the motions' look-ahead (hit_ahead)
        self.acts: dict[int, tuple] = {}          # slot -> ((r0, r1), since)
        self.track: dict[int, tuple] = {}         # slot -> (t, pos, vel)
        self.flights: dict[int, dict] = {}        # thrown slot -> {"t0", "p0", "last", "vel"}
        self.leon_r0, self.leon_hit_at = 0, -math.inf
        self.stats = {"attacks_seen": 0, "thrown_seen": 0, "prevented": 0, "avoided": 0, "landed": 0}

    def _vel(self, slot: int, pos: tuple, now: float) -> tuple:
        prev = self.track.get(slot)
        vel = None
        if prev is not None and 0.02 < now - prev[0] < 0.6:
            dt = now - prev[0]
            raw = tuple((pos[i] - prev[1][i]) / dt for i in range(3))
            if math.hypot(raw[0], raw[2]) < 20000:  # a respawn / teleport is not a velocity
                vel = raw if prev[2] is None else tuple(0.6 * raw[i] + 0.4 * prev[2][i] for i in range(3))
        elif prev is not None and now - prev[0] <= 0.02:
            vel = prev[2]
        self.track[slot] = (now, pos, vel)
        return vel or (0.0, 0.0, 0.0)

    def _ended(self, act: tuple, now: float, killed: bool):
        """An attack is over: prevented (he died in it), landed (Leon was hit while it ran), or avoided."""
        landed = self.leon_hit_at >= act[1] - 0.05
        key = "prevented" if killed and not landed else ("landed" if landed else "avoided")
        self.stats[key] = self.stats.get(key, 0) + 1

    def update(self, s: dict, now: float) -> list[Threat]:
        p = s.get("player")
        if not p:
            return []
        px, py, pz = p["pos"]
        if (p.get("r") or (0,))[0] == 1 and self.leon_r0 != 1:
            self.leon_hit_at = now                             # hit or held this tick
        self.leon_r0 = (p.get("r") or (0,))[0]
        out = []
        live = set()
        for e in s.get("enemies", []):
            k = e["slot"]
            live.add(k)
            vel = self._vel(k, e["pos"], now)
            if dying(e) or "r" not in e:
                was = self.acts.pop(k, None)
                if was is not None and was[0][0] == R_ACT and was[0][1] in ATTACKS:
                    self._ended(was, now, killed=True)          # killed in his attack: prevented
                continue
            st = e["r"][:2]
            prev = self.acts.get(k)
            if prev is None or prev[0] != st:
                if prev is not None and prev[0][0] == R_ACT and prev[0][1] in ATTACKS:
                    self._ended(prev, now, killed=False)
                self.acts[k] = prev = (st, now)
                if st[0] == R_ACT and st[1] in ATTACKS:
                    self.stats["attacks_seen"] += 1
            since = prev[1]
            ex, ey, ez = e["pos"]
            d = math.hypot(ex - px, ez - pz)
            lead = (ex + vel[0] * self.lead_s, ey, ez + vel[2] * self.lead_s)
            if st[0] == R_ACT and st[1] in HOLDS:
                out.append(Threat(k, "hold", 0.0, lead, d, st, since, vel, "holding Leon", e))
                continue
            if st[0] == R_ACT and st[1] in ATTACKS:
                kind, reach, lands = ATTACKS[st[1]]
                if e.get("ev", 0) & EV_HIT:
                    eta = 0.0                                 # the hit frames are on now
                else:
                    ahead = hit_ahead(self.m, e)              # the motion's own hit frames, read ahead
                    eta = ahead if ahead is not None else max(0.0, lands - (now - since))
                    if kind in MELEE and d > reach:
                        eta = max(eta, (d - reach) / CLOSE_SPEED)   # still has to close in
                if d <= reach + APPROACH or kind not in MELEE:
                    out.append(Threat(k, kind, eta, lead, d, st, since, vel, f"r_no_1 {st[1]:#x}", e))
                    continue
            out.append(Threat(k, "down" if st[0] == R_HURT else "near", math.inf, lead, d, st, since, vel, "", e))
        for k in list(self.acts):
            if k not in live:
                self.acts.pop(k, None)
        for k in list(self.track):
            if k >= 0 and k not in live:                      # (thrown weapons: negative keys, kept by _thrown)
                self.track.pop(k, None)
        out += self._thrown(s.get("thrown", []), (px, py, pz), now)
        return sorted(out, key=lambda t: (t.eta, t.dist))

    def _thrown(self, items: list[dict], leon: tuple, now: float) -> list[Threat]:
        out, seen = [], set()
        px, py, pz = leon
        for it in items:
            k = it["slot"]
            seen.add(k)
            f = self.flights.get(k)
            if f is None:
                self.flights[k] = f = {"t0": now, "p0": it["pos"]}
                self.stats["thrown_seen"] += 1
            vel = self._vel(-k, it["pos"], now)
            x, y, z = it["pos"]
            vx, vz = vel[0], vel[2]
            sp2 = vx * vx + vz * vz
            if sp2 < THROWN_MIN_SPEED ** 2:
                continue                                       # lying there (a dropped weapon), or not known yet
            # closest approach to Leon on the ground plane
            tca = max(0.0, -((x - px) * vx + (z - pz) * vz) / sp2) if sp2 > 1.0 else 0.0
            cx, cz = x + vx * tca, z + vz * tca
            miss = math.hypot(cx - px, cz - pz)
            d = math.hypot(x - px, z - pz)
            if miss > THROWN_HIT_R and d > THROWN_HIT_R:
                continue                                       # not coming his way
            lead = (x + vx * self.lead_s, y + vel[1] * self.lead_s, z + vz * self.lead_s)
            out.append(Threat(k, "thrown", tca, lead, d, it.get("r", ()), f["t0"], vel,
                              f"miss {miss:.0f} in {tca:.2f}s", it))
        for k in list(self.flights):
            if k not in seen:
                self.flights.pop(k, None)
                self.track.pop(-k, None)
        return out
