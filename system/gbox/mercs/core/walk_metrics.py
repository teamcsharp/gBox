"""Walk-quality telemetry shared by the Mercenaries bots (#9527): how erratic and how wall-hugging a walk is.

WalkMetrics.observe(now, pos, rot, doing, near_wall) once per tick; summary() gives the counters the title merges into
its stats (all measured from the ticks the bot saw, nothing guessed):
  * wm_ticks / wm_s: ticks and seconds observed;
  * wm_reversals: facing turn direction flipped (each way over TURN_MIN_RAD) within REVERSE_S of the last turn - the
    swivel in place a tank-control title shows when unwall and the walker alternate; wm_reversals_pm per minute;
  * wm_unwall_ticks / wm_unwall_share: ticks whose action was the unwall step;
  * wm_wall_s: seconds spent within the wall distance (near_wall) while not cornered, wm_wall_s_pm per minute;
  * wm_path_mm / wm_net_mm_pm: distance walked (sum of steps, jumps over JUMP_MM ignored: a respawn) and per minute.
"""
from __future__ import annotations

import math

TURN_MIN_RAD, REVERSE_S, JUMP_MM = 0.05, 1.0, 20000.0


def _wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


class WalkMetrics:
    def __init__(self) -> None:
        self.t0 = self.last_t = None
        self.pos = self.rot = None
        self.turn_dir = 0
        self.turn_at = -1e9
        self.ticks = self.unwall = self.reversals = 0
        self.wall_s = self.path_mm = 0.0

    def observe(self, now, pos, rot, doing=None, near_wall=False) -> None:
        if pos is None or now is None:
            return
        if self.t0 is None:
            self.t0 = now
        dt = 0.0 if self.last_t is None else max(0.0, min(now - self.last_t, 1.0))
        self.last_t = now
        self.ticks += 1
        if doing == "unwall":
            self.unwall += 1
        if near_wall:
            self.wall_s += dt
        if self.pos is not None:
            d = math.hypot(pos[0] - self.pos[0], pos[2] - self.pos[2])
            if d < JUMP_MM:
                self.path_mm += d
        if isinstance(rot, (int, float)) and isinstance(self.rot, (int, float)):
            dr = _wrap(rot - self.rot)
            if abs(dr) >= TURN_MIN_RAD:
                sgn = 1 if dr > 0 else -1
                if self.turn_dir and sgn != self.turn_dir and now - self.turn_at <= REVERSE_S:
                    self.reversals += 1
                self.turn_dir, self.turn_at = sgn, now
        self.pos, self.rot = tuple(pos), rot if isinstance(rot, (int, float)) else self.rot

    def summary(self) -> dict:
        s = (self.last_t - self.t0) if self.t0 is not None else 0.0
        pm = (60.0 / s) if s > 0 else 0.0
        return {"wm_ticks": self.ticks, "wm_s": round(s, 1), "wm_reversals": self.reversals,
                "wm_reversals_pm": round(self.reversals * pm, 1), "wm_unwall_ticks": self.unwall,
                "wm_unwall_share": round(self.unwall / self.ticks, 3) if self.ticks else 0.0,
                "wm_wall_s": round(self.wall_s, 1), "wm_wall_s_pm": round(self.wall_s * pm, 1),
                "wm_path_mm": round(self.path_mm), "wm_net_mm_pm": round(self.path_mm * pm)}
