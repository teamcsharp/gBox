"""RE4 native collision raycast (gbox.re4_collision): documentation constants, raycast math, fan layout."""
import math

import numpy as np
import pytest

from gbox import re4_collision as rc


def test_native_addresses_are_documented():
    """Every native address must be a plausible GCN main.dol text address."""
    for name, addr in rc.NATIVE_ADDRESSES.items():
        assert 0x80000000 <= addr <= 0x81800000, f"{name}: 0x{addr:x} out of MEM1 range"


def test_raycast_no_walls_is_clear():
    walls = np.zeros((0, 7))
    hit = rc.raycast(walls, [0, 0, 0], [1000, 0, 0])
    assert not hit.blocked


def test_raycast_hits_a_wall():
    # A wall segment from (-100, 500) to (100, 500), y 0..2000
    walls = np.array([[-100.0, 500.0, 100.0, 500.0, 0.0, 2000.0, 0.0]])
    hit = rc.raycast(walls, [0, 100, 0], [0, 100, 1000])
    assert hit.blocked
    assert hit.point is not None
    assert abs(hit.point[2] - 500.0) < 1.0
    assert 0.4 < hit.distance < 0.6


def test_raycast_see_through_skips_fences():
    # attr 0x20 = fence (see-through)
    walls = np.array([[-100.0, 500.0, 100.0, 500.0, 0.0, 2000.0, 0x20]])
    hit = rc.raycast(walls, [0, 100, 0], [0, 100, 1000], see_through=True)
    assert not hit.blocked
    hit2 = rc.raycast(walls, [0, 100, 0], [0, 100, 1000], see_through=False)
    assert hit2.blocked


def test_raycast_perpendicular_ray_hits():
    # Ray crossing the wall at a right angle
    walls = np.array([[100.0, 0.0, 100.0, 1000.0, 0.0, 2000.0, 0.0]])
    hit = rc.raycast(walls, [0, 100, 500], [200, 100, 500])
    assert hit.blocked
    assert hit.point is not None
    assert abs(hit.point[0] - 100.0) < 1.0


def test_raycast_above_wall_misses():
    walls = np.array([[-100.0, 500.0, 100.0, 500.0, 0.0, 200.0, 0.0]])
    hit = rc.raycast(walls, [0, 500, 0], [0, 500, 1000])
    assert not hit.blocked


def test_fan_returns_n_hits():
    walls = np.array([[-100.0, 500.0, 100.0, 500.0, 0.0, 2000.0, 0.0]])
    origin = [0.0, 100.0, 0.0]
    hits = rc.fan(walls, origin, heading=0.0, n=5, spread=math.pi / 3, length=1000.0)
    assert len(hits) == 5
    # Center ray should hit the wall dead-on
    assert hits[2].blocked
    # Extreme rays at 30 deg off should miss the 200-wide wall
    assert not hits[0].blocked
    assert not hits[4].blocked


def test_fan_all_hit_when_wall_is_wide():
    walls = np.array([[-5000.0, 500.0, 5000.0, 500.0, 0.0, 2000.0, 0.0]])
    origin = [0.0, 100.0, 0.0]
    hits = rc.fan(walls, origin, heading=0.0, n=5, spread=math.pi / 3, length=1000.0)
    assert all(h.blocked for h in hits)
