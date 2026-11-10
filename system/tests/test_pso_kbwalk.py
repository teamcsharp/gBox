"""gbox.pso_kbwalk: camera-relative keyboard walking, calibrated from the game itself."""
import math

import pytest

from gbox import pso_kbwalk as B


class World:
    """A model where each key moves a known world direction -- the point is that the caller does not know them."""

    def __init__(self, start=(0.0, 0.0), basis=None, speed=10.0, walls=()):
        self.pos = list(start)
        self.basis = basis or {"up": (-1.0, 0.0), "down": (-0.14, -0.99),
                               "left": (0.0, 1.0), "right": (1.0, 0.0)}
        self.speed = speed
        self.walls = set(walls)
        self.holds = []

    def read(self):
        return tuple(self.pos)

    def hold(self, key, seconds):
        keys = [key] if isinstance(key, str) else list(key)
        self.holds.append((tuple(keys), round(seconds, 3)))
        dx = sum(self.basis[k][0] for k in keys) / max(len(keys), 1) ** 0.5
        dz = sum(self.basis[k][1] for k in keys) / max(len(keys), 1) ** 0.5
        nx, nz = self.pos[0] + dx * self.speed * seconds, self.pos[1] + dz * self.speed * seconds
        if (round(nx / 10), round(nz / 10)) in self.walls:
            return                                  # blocked: the position does not change
        self.pos = [nx, nz]


def test_calibration_learns_the_real_axes_without_being_told():
    w = World()
    cal = B.calibrate(w.read, w.hold, seconds=0.5)
    assert cal["up"][0] < -0.99 and abs(cal["up"][1]) < 0.01        # up is world -x, not "forward"
    assert cal["down"][1] < -0.9                                    # down is mostly -z
    assert cal["scale"] > 0


def test_the_best_key_is_the_one_that_points_at_the_target():
    cal = {"up": (-1.0, 0.0, 10), "down": (-0.14, -0.99, 10), "left": (0.0, 1.0, 10), "right": (1.0, 0.0, 10),
           "scale": 10}
    assert B.best_key(cal, -50, 0)[0] == "up"
    assert set(B.best_keys(cal, -50, -50)) == {"up", "down"}     # order follows the dots, the set is what matters
    assert B.best_key(cal, 50, 0)[0] == "right"
    assert B.best_key(cal, 0, -50)[0] == "down"
    assert B.best_key(cal, 0, 0)[0] is None


def test_a_walk_arrives_with_a_closed_loop():
    w = World(start=(0.0, 0.0))
    out = B.walk_to(w.read, w.hold, (-60.0, -30.0), tolerance=8.0, max_steps=25)
    assert out["ok"] is True and out["why"] == "arrived"
    assert B.distance(out["end"], (-60.0, -30.0)) <= 8.0
    assert len(out["steps"]) > 1 and len(w.holds) > 1


def test_a_wall_stops_the_walk_instead_of_grinding():
    w = World(start=(0.0, 0.0), walls={(-3, 0), (-4, 0), (-5, 0), (-6, 0), (-2, 0)})
    out = B.walk_to(w.read, w.hold, (-60.0, 0.0), tolerance=4.0, max_steps=12)
    assert out["ok"] is False
    assert len(w.holds) <= 4 + 12                    # four calibration holds plus a bounded number of steps


def test_a_dead_binding_is_reported_not_guessed():
    w = World(basis={"up": (0.0, 0.0), "down": (0.0, 0.0), "left": (0.0, 0.0), "right": (0.0, 0.0)})
    cal = B.calibrate(w.read, w.hold, seconds=0.4)
    assert all(cal[k] == (0.0, 0.0, 0.0) for k in B.KEYS)
    out = B.walk_to(w.read, w.hold, (-50.0, 0.0), cal=cal, max_steps=3)
    assert out["ok"] is False and "recalibrate" in out["why"]


def test_the_step_length_scales_with_the_distance():
    """A long way off gets a longer push than a short one, so the walk does not overshoot at the end."""
    w = World(start=(0.0, 0.0))
    B.walk_to(w.read, w.hold, (-100.0, 0.0), tolerance=8.0, max_steps=25)
    walk_holds = w.holds[4:]                         # the first four are the calibration presses
    assert walk_holds and walk_holds[0][1] > walk_holds[-1][1]


def test_a_diagonal_target_presses_two_keys_because_the_axes_are_skewed():
    """`up` is world -x and `down` is almost -z on this build, so one key can never head diagonally."""
    cal = {"up": (-1.0, 0.0, 10), "down": (-0.14, -0.99, 10), "left": (0.0, 1.0, 10),
           "right": (1.0, 0.0, 10), "scale": 10}
    assert set(B.best_keys(cal, -60, -30)) == {"up", "down"}
    w = World(start=(0.0, 0.0))
    out = B.walk_to(w.read, w.hold, (-60.0, -30.0), tolerance=8.0, max_steps=25)
    assert out["ok"] is True and B.distance(out["end"], (-60.0, -30.0)) <= 8.0
