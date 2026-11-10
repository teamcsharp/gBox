"""The steering model: PSO's left/right TURN, so a walker must point and advance, not translate sideways."""
import math

import pytest

from gbox import pso_kbwalk as B


class Steering:
    """A character with a facing: `up`/`down` move along it, `left`/`right` rotate it (and the camera)."""

    def __init__(self, start=(0.0, 0.0), facing=(-1.0, 0.0), speed=30.0, rate=1.6):
        self.pos = list(start)
        self.facing = list(facing)
        self.speed = speed
        self.rate = rate
        self.holds = []

    def read(self):
        return tuple(self.pos)

    def hold(self, keys, seconds):
        keys = [keys] if isinstance(keys, str) else list(keys)
        self.holds.append((tuple(keys), round(seconds, 3)))
        for k in keys:
            if k == "left":
                a = self.rate * seconds
                x, z = self.facing
                self.facing = [x * math.cos(a) - z * math.sin(a), x * math.sin(a) + z * math.cos(a)]
            elif k == "right":
                a = -self.rate * seconds
                x, z = self.facing
                self.facing = [x * math.cos(a) - z * math.sin(a), x * math.sin(a) + z * math.cos(a)]
            elif k == "up":
                self.pos[0] += self.facing[0] * self.speed * seconds
                self.pos[1] += self.facing[1] * self.speed * seconds
            elif k == "down":
                self.pos[0] -= self.facing[0] * self.speed * seconds
                self.pos[1] -= self.facing[1] * self.speed * seconds


def test_calibration_measures_forward_and_a_turn_rate():
    s = Steering()
    cal = B.steer_calibrate(s.read, s.hold)
    assert abs(cal["speed"] - 30.0) < 2
    assert abs(abs(cal["turn_rate"]) - 1.6) < 0.25


def test_a_target_behind_the_character_is_reached_by_turning_first():
    """The old model would push `down`; the real game needs a turn and then forward."""
    s = Steering(start=(0.0, 0.0), facing=(-1.0, 0.0))
    out = B.steer_walk(s.read, s.hold, (60.0, 0.0), tolerance=7.0, max_steps=25)
    assert out["ok"] is True, out
    assert B.distance(out["end"], (60.0, 0.0)) <= 7.0
    assert any(k in ("left", "right") for keys, _s in s.holds for k in keys)


def test_the_facing_is_re_measured_so_an_overshoot_is_corrected():
    s = Steering(start=(0.0, 0.0), facing=(-1.0, 0.0))
    out = B.steer_walk(s.read, s.hold, (-40.0, -40.0), tolerance=6.0, max_steps=25)
    assert out["ok"] is True, out
    assert B.distance(out["end"], (-40.0, -40.0)) <= 6.0


def test_a_dead_forward_binding_is_refused_with_a_reason():
    class Stuck(Steering):
        def hold(self, keys, seconds):
            self.holds.append((tuple([keys]) if isinstance(keys, str) else tuple(keys), round(seconds, 3)))

    with pytest.raises(RuntimeError, match="dead"):
        B.steer_calibrate(Stuck().read, Stuck().hold)


def test_a_binding_that_does_not_turn_is_refused():
    class NoTurn(Steering):
        def hold(self, keys, seconds):
            keys = [keys] if isinstance(keys, str) else list(keys)
            if "left" in keys or "right" in keys:
                return
            super().hold(keys, seconds)

    s = NoTurn()
    with pytest.raises(RuntimeError, match="not the steering model"):
        B.steer_calibrate(s.read, s.hold)
