"""The Mercenaries 3D bot: one solo player against sEnemy's units, from merc3d_3ds.snapshot().

The operator's standing rules (RE5 / RE6 Switch, 2026-10-26/27) are the policy:

    * fire only on a confirmed line: the aim ray (the laser's muzzle -> dot) passes through the target's body, or the
      target is point blank in front; a long shot is welcome once the ray confirms it, never a shot into a wall
    * never aim at the sky: the ray is pushed down when it climbs past the target's own elevation (SKY_MARGIN_DEG), and
      it is only raised for a target that is really above
    * crowd control and kiting: CC_N foes inside CC_R (or one at arm's length behind him) -> gun down, turn away from
      their centroid and run until there is room, then turn and fight; nearest threat first
    * no idling among foes: with a live enemy anywhere he turns, closes in, aims or kites - never stands still
    * keep the combo: with nobody in reach he runs to the nearest enemy anywhere on the map (the full census)

Type A controls (Capcom's RETM_3DS_DMNL_EN.pdf, pp.10-13): circle pad runs, B walks,
R aims and Y fires. A uses a herb; it must never be tried as a trigger.
Headings follow merc3d_3ds.heading_of: 0 = +z, positive toward +x; a target's bearing is atan2(dx, dz).
"""
from __future__ import annotations

import math
import time

CONTROLS = {"raise": "r", "fire": "y", "walk": "b", "forward": "lup", "back": "ldown", "left": "lleft",
            "right": "lright", "aim_left": "lleft", "aim_right": "lright", "aim_up": "lup", "aim_down": "ldown"}
TURN_LEFT_IS_LARGER = True              # stick left turns toward a larger heading (verified live before the flip)
# Confirm damage in play, but never guess unrelated controls when aim is blocked.
FIRE_PROBE_R = 350.0
FIRE = {"key": CONTROLS["fire"], "confirmed": False}
RELOAD_KEEP = ()  # discard the previous build's guessed trigger on a bot reload
# The engine diffs held keys; holding a semi-automatic trigger forever produces
# only one press. Keep the aim raised but give the game observable release frames.
FIRE_DOWN_S, FIRE_UP_S = 0.10, 0.08

CC_R, CC_N = 260.0, 3                   # crowd control: this many foes inside this radius (cm)
GRAB_R = 130.0                          # a foe this close behind / beside him: get out first
KITE_S, KITE_CLEAR_R = 1.6, 420.0       # kite this long at most, or until the nearest foe is this far
POINT_BLANK = 160.0                     # cm: a target this close in front is shot without the ray
TURN_DEG = 32.0                         # past this the body turns with the gun down; inside it the gun aims
AIM_TOL_DEG = 3.5                       # the yaw error the aim accepts before it waits for the ray
CHASE_R = 900.0                         # farther than this: run to him, after LONG_LOOK_S looking for a long shot
LONG_LOOK_S, LONG_LOOK_EVERY_S = 1.2, 4.0  # the gun up this long on a far target before the chase (confirmed shots only)
BODY_R, HEAD_R = 38.0, 18.0             # the target's chest capsule / head sphere radii (cm)
CHEST_Y, HEAD_Y = 120.0, 160.0          # above his feet (cm); Majini stand about 175 cm
SKY_MARGIN_DEG = 12.0                   # the ray may climb this far past the target's own elevation, no more
FALLBACK_FIRE_R = 600.0                 # no ray read at all: fire only this close, square on (never a long blind shot)
STUCK_S, BLOCK_S = 3.0, 2.5             # aiming this long at one target without a confirmed shot: try another
TARGET_HOLD_S = 0.6                     # keep a target this long before a nearer one may take over
ANGLE_COST = 3.0                        # cm per degree off his facing when ranking targets


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def bearing(src, dst) -> float:
    return math.atan2(dst[0] - src[0], dst[2] - src[2])


def flat(a, b) -> float:
    return math.hypot(b[0] - a[0], b[2] - a[2])


def near_ray(origin, dot, point, radius: float, slack: float = 60.0) -> bool:
    """Whether the ray origin -> dot reaches point (it ends no more than slack short of it: no wall in between) and
    passes within radius of it."""
    have, want = math.dist(origin, dot), math.dist(origin, point)
    if have < 1.0 or want < 1.0 or have < want - slack:
        return False
    d = tuple((dot[k] - origin[k]) / have for k in range(3))
    along = sum((point[k] - origin[k]) * d[k] for k in range(3))
    if along <= 0.0:
        return False
    return math.dist(point, tuple(origin[k] + along * d[k] for k in range(3))) <= radius


class Bot:
    """tick(snap) -> {"hold": keys}. stats counts what it did (the engine's round_counters)."""

    def __init__(self, stats: dict | None = None, clock=time.monotonic):
        self.stats = stats if stats is not None else {}
        self.clock = clock
        self.target = None                  # the target's ptr
        self.target_at = 0.0
        self.aim_since = None
        self.blocked: dict = {}             # ptr -> until
        self.kite_until = 0.0
        self.kite_heading = None
        self.long_look = (None, 0.0, -1e9)  # (target, until, last started)
        self.doing, self.why = "idle", ""
        self.probe = None                   # (target ptr, his vitality, trigger seconds so far, last tick)
        self.trigger_down = False
        self.trigger_at = None
        self.movement = None
        self.escape_until = 0.0
        self.escape_side = "lleft"
        self.attack_progress = None
        self.last_hold = set()

    # --- the engine's interface ------------------------------------------------------------------------------------------
    def prompt_ok(self, button, snap, now) -> bool:
        return True                         # no prompt reader yet (prompt_source is None): never asked

    def save(self) -> None:
        return None

    # --- helpers ------------------------------------------------------------------------------------------------------
    def _count(self, key: str, n: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + n

    def _go(self, doing: str, keys, why: str = "") -> dict:
        if doing != "fire":
            self.trigger_down, self.trigger_at = False, None
        self.doing, self.why = doing, why
        self.stats["doing"], self.stats["why"] = doing, why[:160]
        self._count("t_" + doing)
        self.last_hold = set(keys)
        return {"hold": tuple(sorted(k for k in keys if k))}

    def _steer(self, err: float) -> str | None:
        """The stick key that turns the body (gun down) toward a heading error (rad; + = a larger heading)."""
        if abs(err) < math.radians(4):
            return None
        left = err > 0 if TURN_LEFT_IS_LARGER else err < 0
        return CONTROLS["left"] if left else CONTROLS["right"]

    def _aim_keys(self, yaw_err: float, pitch_err: float | None) -> set:
        keys = set()
        if abs(yaw_err) > math.radians(AIM_TOL_DEG):
            left = yaw_err > 0 if TURN_LEFT_IS_LARGER else yaw_err < 0
            keys.add(CONTROLS["aim_left"] if left else CONTROLS["aim_right"])
        if pitch_err is not None and abs(pitch_err) > math.radians(2.5):
            keys.add(CONTROLS["aim_up"] if pitch_err > 0 else CONTROLS["aim_down"])
        return keys

    def _fire_key(self, tgt, dist, err, now) -> str:
        """Use the documented trigger; target damage is recorded separately."""
        FIRE["key"] = CONTROLS["fire"]
        if FIRE["confirmed"] or dist > FIRE_PROBE_R or abs(err) > math.radians(20):
            return FIRE["key"]
        hp, ptr = tgt.get("hp"), tgt.get("ptr")
        pr = self.probe
        if pr is None or pr[0] != ptr:
            self.probe = (ptr, hp, 0.0, now)
            return FIRE["key"]
        if isinstance(hp, (int, float)) and isinstance(pr[1], (int, float)) and hp < pr[1]:
            FIRE["confirmed"] = True                # he took damage: this is the trigger
            self.stats["fire_key"] = FIRE["key"]
            return FIRE["key"]
        self.probe = (ptr, pr[1], 0.0, now)
        return FIRE["key"]

    def _trigger(self, tgt, dist, err, now) -> str | None:
        key = self._fire_key(tgt, dist, err, now)
        if self.trigger_at is None:
            self.trigger_down, self.trigger_at = True, now
            self._count("trigger_presses")
        elif now - self.trigger_at >= (FIRE_DOWN_S if self.trigger_down else FIRE_UP_S):
            self.trigger_down = not self.trigger_down
            self.trigger_at = now
            self._count("trigger_presses" if self.trigger_down else "trigger_releases")
        # Advance only one phase per observed tick. A slow/stalled reader must
        # still send a release, rather than skip it with a wall-clock modulo.
        return key if self.trigger_down else None

    @staticmethod
    def _points(e) -> tuple:
        x, y, z = e["pos"]
        return (x, y + CHEST_Y, z), (x, y + HEAD_Y, z)

    # --- the decision ---------------------------------------------------------------------------------------------------
    def tick(self, snap: dict) -> dict:
        now = self.clock()
        p = snap.get("player")
        if not p or (p.get("hp") or 0) <= 0:
            return self._go("idle", (), "no player")
        me, yaw = tuple(p["pos"]), float(p["rot"])
        # A movement command without displacement is a blocked route, not
        # progress. Back off and change heading before trying forward again.
        if now < self.escape_until:
            return self._go("wall_escape", {CONTROLS["back"], self.escape_side}, "blocked movement: back off and turn")
        if self.doing in ("chase", "kite") and CONTROLS["forward"] in self.last_hold:
            if self.movement is None or flat(me, self.movement[1]) >= 30.0:
                self.movement = (now, me)
            elif now - self.movement[0] >= 1.0:
                self.movement = None
                self.escape_until = now + 0.7
                self.escape_side = "lright" if self.escape_side == "lleft" else "lleft"
                self._count("wall_escapes")
                return self._go("wall_escape", {CONTROLS["back"], self.escape_side}, "no displacement for one second")
        else:
            self.movement = None
        live = [e for e in snap.get("enemies") or () if (e.get("hp") or 0) > 0 and e.get("pos")]
        if not live:
            self.target = None
            return self._go("no_foes", (), "no enemy alive")
        live.sort(key=lambda e: flat(me, e["pos"]))
        # crowd control first: room before a fight
        close = [e for e in live if flat(me, e["pos"]) < CC_R]
        behind = [e for e in live if flat(me, e["pos"]) < GRAB_R and abs(wrap(bearing(me, e["pos"]) - yaw)) > math.radians(90)]
        if now < self.kite_until or len(close) >= CC_N or behind:
            act = self._kite(me, yaw, close or live[:1], now)
            if act is not None:
                return act
        tgt = self._choose(me, yaw, live, now)
        if tgt is None:
            return self._chase(me, yaw, live[0], "every target blocked")
        dist = flat(me, tgt["pos"])
        err = wrap(bearing(me, tgt["pos"]) - yaw)
        # The current native reader has no laser. Body facing alone cannot
        # authorize a distant shot, so close into the range we can actually
        # use instead of spending three seconds raising a gun that cannot fire.
        # An aim-capable reader may still briefly acquire a missing ray.
        if "aim" not in snap and dist >= FALLBACK_FIRE_R:
            return self._chase(me, yaw, tgt, "no laser reader: close to firing range")
        if abs(err) > math.radians(TURN_DEG):
            self.aim_since = None
            if dist > CHASE_R:
                return self._chase(me, yaw, tgt, f"{dist:.0f} cm away")
            key = self._steer(err)
            return self._go("turn", (key,), f"turn {math.degrees(err):+.0f} deg to {tgt.get('class')}")
        if dist > CHASE_R:
            who, until, started = self.long_look
            if who != tgt.get("ptr") and now - started >= LONG_LOOK_EVERY_S:
                self.long_look = (tgt.get("ptr"), now + LONG_LOOK_S, now)
                who, until = tgt.get("ptr"), now + LONG_LOOK_S
            if who != tgt.get("ptr") or now >= until:
                return self._chase(me, yaw, tgt, f"{dist:.0f} cm away")
            return self._aim(snap, me, yaw, tgt, dist, err, now, long=True)
        return self._aim(snap, me, yaw, tgt, dist, err, now)

    def _choose(self, me, yaw, live, now):
        cur = next((e for e in live if e.get("ptr") == self.target), None)
        free = [e for e in live if self.blocked.get(e.get("ptr"), 0) <= now]
        if not free:
            return None
        best = min(free, key=lambda e: flat(me, e["pos"]) + ANGLE_COST * abs(math.degrees(wrap(bearing(me, e["pos"]) - yaw))))
        if cur is not None and cur in free and now - self.target_at < TARGET_HOLD_S:
            return cur
        if best.get("ptr") != self.target:
            self.target, self.target_at, self.aim_since = best.get("ptr"), now, None
            self._count("retargets")
        return best

    def _chase(self, me, yaw, tgt, why: str) -> dict:
        """Run to him (the full census: the nearest anywhere), the gun down: the combo never waits for a foe to come."""
        self.aim_since = None
        err = wrap(bearing(me, tgt["pos"]) - yaw)
        keys = {self._steer(err)}
        if abs(err) < math.radians(60):
            keys.add(CONTROLS["forward"])
        return self._go("chase", keys, why)

    def _kite(self, me, yaw, foes, now):
        """Out of a crowd: turn away from their centroid and run; done after KITE_S or once the nearest is far."""
        nearest = min(flat(me, e["pos"]) for e in foes)
        if now >= self.kite_until:
            if nearest >= KITE_CLEAR_R:
                return None
            cx = sum(e["pos"][0] for e in foes) / len(foes)
            cz = sum(e["pos"][2] for e in foes) / len(foes)
            self.kite_heading = math.atan2(me[0] - cx, me[2] - cz)
            self.kite_until = now + KITE_S
            self._count("kites")
        elif nearest >= KITE_CLEAR_R:
            self.kite_until = 0.0
            return None
        err = wrap(self.kite_heading - yaw)
        keys = {self._steer(err)}
        if abs(err) < math.radians(70):
            keys.add(CONTROLS["forward"])
        return self._go("kite", keys, f"{len(foes)} close, nearest {nearest:.0f} cm")

    def _aim(self, snap, me, yaw, tgt, dist, err, now, long: bool = False) -> dict:
        self.aim_since = self.aim_since or now
        chest, head = self._points(tgt)
        aim = snap.get("aim") or {}
        ray = aim.get("ray") if aim.get("up") else None
        keys = {CONTROLS["raise"]}
        pitch_err = None
        confirmed = False
        why = ""
        if ray:
            origin, dot = ray
            confirmed = near_ray(origin, dot, chest, BODY_R) or near_ray(origin, dot, head, HEAD_R)
            have = math.atan2(dot[1] - origin[1], math.hypot(dot[0] - origin[0], dot[2] - origin[2]))
            want = math.atan2(chest[1] - origin[1], math.hypot(chest[0] - origin[0], chest[2] - origin[2]))
            pitch_err = want - have
            if have > want + math.radians(SKY_MARGIN_DEG):
                pitch_err = -abs(pitch_err) - math.radians(5)          # the sky guard: down at once
                self._count("sky_corrections")
            yaw_err = wrap(math.atan2(chest[0] - origin[0], chest[2] - origin[2])
                           - math.atan2(dot[0] - origin[0], dot[2] - origin[2]))
        else:
            yaw_err = err
            if not long and dist >= FALLBACK_FIRE_R:
                return self._chase(me, yaw, tgt, "no measured ray: close to firing range")
        keys |= self._aim_keys(yaw_err, pitch_err)
        point_blank = dist < POINT_BLANK and abs(err) < math.radians(15)
        blind_ok = not long and ray is None and dist < FALLBACK_FIRE_R and abs(err) < math.radians(AIM_TOL_DEG)
        if confirmed or point_blank or blind_ok:
            progress = self.attack_progress
            identity = tgt.get("ptr")
            hp = tgt.get("hp")
            if progress is None or progress[0] != identity or hp != progress[1]:
                self.attack_progress = (identity, hp, now)
            elif now - progress[2] >= 2.0:
                # Body facing alone is not line-of-sight. Don't fire forever at
                # an unchanged target behind a wall when no laser is available.
                self.blocked[identity] = now + BLOCK_S
                self.target, self.aim_since, self.attack_progress = None, None, None
                self.escape_until = now + 0.7
                self._count("ineffective_bursts")
                return self._go("wall_escape", {CONTROLS["back"], self.escape_side}, "no target damage: change firing position")
            presses = self.stats.get("trigger_presses", 0)
            keys.add(self._trigger(tgt, dist, err, now))
            if self.stats.get("trigger_presses", 0) > presses:
                # Count trigger requests, not every held/released decision tick.
                self._count("confirmed_shots" if confirmed else ("point_blank_shots" if point_blank else "close_shots"))
                if confirmed and dist > 800:
                    self._count("long_shots")
            self.aim_since = now
            why = "ray on him" if confirmed else ("point blank" if point_blank else "square on, close")
            return self._go("fire", keys, f"{why}: {tgt.get('class')} {dist:.0f} cm")
        if now - self.aim_since > STUCK_S:
            self.blocked[tgt.get("ptr")] = now + BLOCK_S             # no line to him (a wall): another one first
            self.target, self.aim_since = None, None
            self._count("los_blocks")
            return self._go("aim", keys, "no confirmed line: next target")
        return self._go("aim", keys, f"aim {math.degrees(yaw_err):+.1f} deg at {tgt.get('class')} {dist:.0f} cm")
