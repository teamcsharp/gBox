"""RE5 Switch calm camera (operator 2026-10-27 16:47: "smoothly looking around so it's like organic and it doesn't
cause any sort of motion sickness"): no stick reversal within CALM_REVERSE_S, the gun-down turn held to
CALM_TURN_DEG_S on average, the quick turn only for one close behind, and the heading's speed measured."""
import math

import pytest

from gbox.mercs.titles import re5_switch as R


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)


def snap(rot=0.0):
    return {"player": {"ptr": 1, "pos": (0.0, 0.0, 0.0), "rot": rot, "hp": 1000, "hp_max": 1000, "motion": 0},
            "enemies": [], "inventory": []}


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


def test_a_stick_reversal_coasts_first():
    b, clock = bot()
    b.doing = "turn"
    assert b._calm_sticks({"hold": ("rleft",)}, snap(), 0.0)["hold"] == ("rleft",)
    assert b._calm_sticks({"hold": ("rright",)}, snap(), 0.05)["hold"] == ()         # straight back: coast
    for t in (0.1, 0.15, 0.2):
        b._calm_sticks({"hold": ()}, snap(), t)
    assert b._calm_sticks({"hold": ("rright",)}, snap(), 0.3)["hold"] == ("rright",)
    assert b.stats["calm_coasts"] == 1


def test_the_gun_down_turn_is_held_to_the_cap_on_average():
    b, clock = bot()
    b.doing = "turn"
    pressed = 0
    for k in range(200):                                           # 10 s of 50 ms ticks, the stick wanted all along
        out = b._calm_sticks({"hold": ("rleft",)}, snap(), 0.05 * k)
        pressed += "rleft" in out["hold"]
    rate = pressed * 0.05 * R.TURN_SPEED_DEG_S / 10.0
    assert rate == pytest.approx(R.CALM_TURN_DEG_S, rel=0.1) and b.stats["calm_caps"] > 0
    aimed = b._calm_sticks({"hold": ("rleft", "zl")}, snap(), 10.05)        # aiming: the aim's own slow speed
    assert "rleft" in aimed["hold"]


def test_the_heading_speed_is_measured():
    b, clock = bot()
    b.doing = "turn"
    for k in range(11):
        b._calm_sticks({"hold": ()}, snap(math.radians(10 * k)), 0.1 * k)   # 100 deg/s
    assert b.stats["spin_deg_s"] == pytest.approx(100.0, rel=0.02) and b.stats["spin_max_deg_s"] == pytest.approx(100.0, rel=0.02)
