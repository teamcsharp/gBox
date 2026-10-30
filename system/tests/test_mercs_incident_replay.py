"""Replay test for the frontal-grab sidestep fix (request #5135, cluster 16c8292da3adc4a2).

The fixture (tests/fixtures/mercs_incidents/re5_grabbed_front_16c8292da3adc4a2.json) records the bot
standing 100 cm from a Majini who was walking in to grab him. Before the fix, the bot walked straight
into the grab (doing="walk", keys included "lup"). After the fix, the bot sidesteps instead.
"""
import json
import pathlib
import pytest

from gbox.mercs.incident_replay import replay, keys
from gbox.mercs.titles import re5_switch as R

FIX = pathlib.Path(__file__).parent / "fixtures" / "mercs_incidents" / "re5_grabbed_front_16c8292da3adc4a2.json"


def test_replay_does_not_walk_into_grab(monkeypatch):
    """The bot must sidestep, not walk into the Majini who is about to grab him."""
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "CROWD_FIRE", False)
    monkeypatch.setattr(R, "RAMPAGE", False)
    monkeypatch.setattr(R, "QUICK_TURN", False)
    monkeypatch.setattr(R, "WALL_GOV", False)          # the replay feeds the same snapshot each tick (no real
                                                       # movement): the wall heuristic would fire on 0 cm progress

    fx = json.loads(FIX.read_text())
    result = replay(fx, ticks=10)
    ks = keys(result)

    # The bot must sidestep: the first decision is a sidestep, not a walk or a turn
    first = result["ticks"][0]
    assert first["doing"] == "sidestep", f"first tick not a sidestep: doing={first['doing']!r} why={first['why']!r}"

    # The bot must hold a sidestep key (lup or ldown) on the first tick
    assert "lup" in first["act"].get("hold", ()) or "ldown" in first["act"].get("hold", ()), \
        f"first tick no sidestep key: act={first['act']}"

    # The bot must not be walking forward into the grab on any tick before the sidestep resolves
    doing_set = {t["doing"] for t in result["ticks"][:8]}   # the first 0.4 s
    assert "walk" not in doing_set, f"bot walked into the grab: doings={doing_set}"

    # Across the replay, the sidestep keys must appear
    assert "lup" in ks or "ldown" in ks, f"bot did not sidestep: keys={ks}"


def test_grab_front_constants_exist():
    """The new constants are defined and reasonable."""
    assert hasattr(R, "GRAB_FRONT_R") and R.GRAB_FRONT_R > 0
    assert hasattr(R, "GRAB_FRONT_CONE") and R.GRAB_FRONT_CONE > 0
