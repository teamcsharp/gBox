"""CP17: world waypoints to stick taps - the convention is an argument, so this is testable without a session."""
import math

import pytest

from gbox import pso_steer as S


def test_forward_at_yaw_zero_is_up():
    assert S.direction_taps((0.0, -1.0), 0.0) == ("up",)
    assert S.direction_taps((0.0, 1.0), 0.0) == ("down",)
    assert S.direction_taps((-1.0, 0.0), 0.0) == ("left",)
    assert S.direction_taps((1.0, 0.0), 0.0) == ("right",)


def test_a_yaw_turn_rotates_the_stick():
    """At yaw 90 the camera looks along +x, so a target at +x is still "up" and a target at -z becomes a side push."""
    assert S.direction_taps((1.0, 0.0), 90.0) == ("up",)
    assert S.direction_taps((0.0, -1.0), 90.0) in (("right",), ("left",))


def test_a_diagonal_is_two_keys():
    keys = S.direction_taps((1.0, -1.0), 0.0)
    assert set(keys) == {"up", "right"}


def test_a_dead_direction_asks_for_nothing():
    assert S.direction_taps((0.0, 0.0), 0.0) == ()


def test_route_taps_skip_waypoints_within_reach():
    route = [(0.0, -5.0), (0.0, -50.0), (0.0, -100.0)]
    segments = S.route_taps(route, (0.0, 0.0), 0.0, reach=10.0)
    assert len(segments) == 2                       # the first waypoint is inside the reach
    assert all(seg["keys"] == ("up",) for seg in segments)


def test_route_taps_turn_at_a_corner():
    route = [(0.0, -50.0), (50.0, -50.0)]
    segments = S.route_taps(route, (0.0, 0.0), 0.0, reach=1.0)
    assert segments[0]["keys"] == ("up",)
    assert segments[1]["keys"] == ("right",)


def test_describe_sums_the_legs():
    summary = S.describe([(0.0, 0.0), (0.0, -30.0), (40.0, -30.0)])
    assert summary["waypoints"] == 3
    assert summary["length"] == pytest.approx(70.0)
