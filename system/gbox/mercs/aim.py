"""Aim and shots (docs/mercenaries_engine.md, section 3): the player's turning and aiming rates, learned while playing,
and every shot scored by what it did to the enemies' health.

    rates = AimRates.from_profile(prof.aim)        # the map's mercs.aim, then learned
    rates.observe_turn(d_facing, dt, aiming)       # what a held stick did
    rates.ready_in(err, pose_left, gun_left)       # seconds until a shot can leave the gun
    shots = Shots(gun_gap_s=rates.gun_gap_s)
    shots.fired(now)                               # a shot the game fired (RAM), or shots.press(now) without that
    shots.update(enemies, now)                     # hit = any enemy's health fell / one started dying within HIT_S
"""
from __future__ import annotations

import math
from dataclasses import dataclass


def _attr(e, name, default=None):
    return e.get(name, default) if isinstance(e, dict) else getattr(e, name, default)


def _dying(e) -> bool:
    hp = _attr(e, "hp")
    r = _attr(e, "r")
    tags = set(_attr(e, "tags", ()) or ())
    return (hp is not None and hp <= 0) or bool(tags & {"dying", "gone"}) or (r is not None and r[0] in (3, 0xFF))


@dataclass
class AimRates:
    turn_rad_s: float = 3.0           # the stick turning the player (not aiming)
    aim_turn_rad_s: float = 0.5       # aiming
    pitch_rad_s: float = 0.17
    pose_s: float = 0.25              # R down -> the aim pose up
    gun_gap_s: float = 35 / 30.0      # the gun's own rate
    quick_turn_s: float = 0.55        # a half turn by the quick turn

    @classmethod
    def from_profile(cls, aim: dict | None) -> "AimRates":
        r = cls()
        for k, v in (aim or {}).items():
            if hasattr(r, k):
                setattr(r, k, float(v))
        return r

    def observe_turn(self, d_facing: float, dt: float, aiming: bool) -> None:
        """A tick with the stick held sideways turned the player d_facing in dt: fold it into the rate."""
        if dt <= 0.02 or dt > 0.3:
            return
        rate = abs(d_facing) / dt
        if rate < 0.05 or rate > 20:
            return
        name = "aim_turn_rad_s" if aiming else "turn_rad_s"
        setattr(self, name, 0.9 * getattr(self, name) + 0.1 * rate)

    def observe_pitch(self, d_pitch: float, dt: float) -> None:
        if 0.02 < dt <= 0.3 and 0.01 < abs(d_pitch) / dt < 10:
            self.pitch_rad_s = 0.9 * self.pitch_rad_s + 0.1 * abs(d_pitch) / dt

    def ready_in(self, err: float, aiming_on_target: bool, pose_left: float, gun_left: float,
                 quick_turn_err: float = 2.3) -> float:
        """Seconds until a shot at a target err radians off the facing can leave the gun."""
        err = abs(err)
        if aiming_on_target:
            turn = err / max(self.aim_turn_rad_s, 0.05)
        else:
            turn = self.quick_turn_s if err > quick_turn_err else err / max(self.turn_rad_s, 0.1)
        return max(turn + pose_left, gun_left) + 0.1


class Shots:
    """Shots and what they did: a shot hit when any enemy's health fell, or one started dying, within HIT_S of it (a
    bullet that goes through bodies hits whoever it hits); else it missed."""

    HIT_S = 0.5

    def __init__(self, gun_gap_s: float = 35 / 30.0):
        self.GUN_GAP = gun_gap_s
        self.hp: dict = {}
        self.pending: list[float] = []
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

    def update(self, enemies, now: float) -> list:
        """Score the pending shots against this tick's health; returns the enemies hurt since the last tick."""
        hurt, cur = [], {}
        for e in enemies:
            k, hp, dy = _attr(e, "slot", _attr(e, "id")), _attr(e, "hp"), _dying(e)
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
