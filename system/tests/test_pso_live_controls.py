"""The live controls' pure logic: the turbo chord's decision and the walk-to-mission conversion."""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from gbox import pso_chords as C                                   # noqa: E402

R1 = C.RIGHT_BUMPER
UP, DOWN = C.DPAD_UP, C.DPAD_DOWN


def test_r1_and_up_turns_turbo_on_only_once():
    assert C.decide(R1 | UP, 0.0, False) == C.TURBO_ON
    # already in turbo: a held D-pad must not re-fire
    assert C.decide(R1 | UP, 0.0, True) is None


def test_r1_and_down_returns_to_normal_only_from_turbo():
    assert C.decide(R1 | DOWN, 0.0, True) == C.TURBO_OFF
    assert C.decide(R1 | DOWN, 0.0, False) is None


def test_the_analog_trigger_is_r1_too_and_nothing_happens_without_it():
    assert C.decide(UP, 0.0, False) is None                        # D-pad alone is ordinary movement
    assert C.decide(UP, 255.0, False) == C.TURBO_ON                  # right trigger pulled hard
    assert C.decide(UP, 20.0, False) is None                        # light trigger is not R1
    assert C.decide(UP, 20.0, False, rt_threshold=0.05) == C.TURBO_ON


def test_diagonals_and_other_buttons_do_not_confuse_the_chord():
    assert C.decide(R1 | C.DPAD_LEFT, 0.0, False) is None
    assert C.decide(R1 | UP | DOWN, 0.0, False) == C.TURBO_ON        # up wins when both edges appear
    assert C.decide(0x1000 | R1, 0.0, False) is None                 # A + R1 is not the chord


def test_simplify_keeps_a_straight_line_to_its_endpoints():
    line = [(0.0, 0.0), (5.0, 0.1), (10.0, -0.1), (15.0, 0.0)]
    assert C.simplify(line, 1.0) == [(0.0, 0.0), (15.0, 0.0)]


def test_simplify_keeps_a_real_corner():
    corner = [(0.0, 0.0), (0.0, 20.0), (20.0, 20.0)]
    assert C.simplify(corner, 1.0) == corner


def test_a_recorded_walk_becomes_a_navigate_mission_with_provenance():
    rows = [{"t": i, "x": float(i * 5), "z": 0.0 if i < 4 else 10.0, "floor": 3} for i in range(8)]
    mission = C.route_mission(rows, game_id="436e0bb84d5337d1", name="route-test", tolerance=2.0, source="unit")
    assert mission["policy"] == "learned-from-operator-route"
    assert set(mission["provenance"]) == {"source", "samples", "waypoints", "tolerance", "floors"}
    assert mission["provenance"]["samples"] == 8 and mission["provenance"]["floors"] == [3]
    assert all(step["op"] == "navigate" and len(step["to"]) == 2 for step in mission["steps"])
    assert mission["steps"][0]["to"] != mission["steps"][-1]["to"]


def test_a_route_too_short_or_without_coordinates_is_refused():
    with pytest.raises(ValueError):
        C.route_mission([{"t": 0, "x": 0.0, "z": 0.0}], game_id="g", name="n")
    with pytest.raises(ValueError):
        C.route_mission([{"t": i, "x": None, "z": None} for i in range(10)], game_id="g", name="n")
