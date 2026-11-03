"""Replay test for damage cluster fba3e558be591a5b (request #5130): low_hp_no_heal on RE5 PS3 (BLUS30491).

The bot deferred heals while Majini stood 2.5-4 m away, but RE5's melee range is 2.5 m. The fix tightens
HEAL_SAFE_R from 400 to 250 so only a Majini actually within melee reach defers the heal. This test replays
the recorded fixtures through the bot and asserts that:

1. A bot with HP > critical (25%) and a Majini within 250 cm does NOT defer the heal (pre-fix would defer
   at 2.5-4 m with HEAL_SAFE_R=400).
2. A bot with HP <= critical (25%) always heals regardless of enemy distance.
3. The full replay of the cluster fixtures produces a valid bot decision (no crash).
"""
import json
import math
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gbox.mercs.titles import re5_ps3
from gbox.mercs import incident_replay

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "mercs_incidents"
CLUSTER_FIXTURES = sorted(
    FIXTURES_DIR.glob("re5_ps3_*.json"),
    key=lambda p: p.stem,
)


def _load_fixture(name: str) -> dict:
    path = FIXTURES_DIR / name
    assert path.exists(), f"missing fixture {name}"
    return json.loads(path.read_text())


def _make_bot(temp_dir: str) -> re5_ps3.Bot:
    """A Bot with no RAM writer, isolated learn_dir, and a fake clock."""
    clock = [0.0]
    return re5_ps3.Bot(m=None, stats={}, clock=lambda: clock[0], learn_dir=temp_dir)


# --- Unit tests on _heal_safe directly (the core logic the fix changes) ---


@pytest.mark.parametrize(
    "hp, hp_max, enemy_dist_cm, expect_heal",
    [
        # HP far above critical, enemy within melee range (250): defer (correct - fight first)
        (500, 1000, 200, False),   # 50% HP, Majini 2 m away -> defer
        (300, 1000, 200, False),   # 30% HP, Majini 2 m away -> defer
        (300, 1000, 240, False),   # 30% HP, Majini 2.4 m away -> defer
        # HP at critical threshold with enemy at melee range: heal (critical)
        (250, 1000, 200, True),    # 25% HP = critical -> heal
        # HP just above critical with enemy at melee range: defer (correct)
        (251, 1000, 200, False),   # 25.1% HP, Majini 2 m away -> fight first
        # Enemy beyond melee range (HEAL_SAFE_R=250): no deferral
        (500, 1000, 251, True),    # 50% HP, Majini just outside melee range -> heal
        (300, 1000, 251, True),    # 30% HP, Majini just outside melee range -> heal
        (300, 1000, 400, True),    # 30% HP, Majini 4 m away -> heal (old 400 would defer)
        (300, 1000, 500, True),    # 30% HP, Majini 5 m away -> heal
        (500, 1000, 300, True),    # 50% HP, Majini 3 m away -> heal (old 400 would defer)
        # No enemies at all: always heal
        (100, 1000, 0, True),
    ],
)
def test_heal_safe_melee_range(tmp_path, hp, hp_max, enemy_dist_cm, expect_heal):
    """With HEAL_SAFE_R=250, only a Majini within melee reach defers a non-critical heal."""
    b = _make_bot(str(tmp_path))
    p = {"pos": [1000.0, 0.0, 1000.0]}
    enemies = []
    if enemy_dist_cm > 0:
        enemies.append({
            "pos": [1000.0 + enemy_dist_cm, 0.0, 1000.0],
            "hp": 800,
            "hp_max": 800,
        })
    snap = {"enemies": enemies}
    result = b._heal_safe(p, snap, hp, hp_max)
    assert result is expect_heal, (
        f"hp={hp}/{hp_max} ({hp/hp_max:.0%}), enemy at {enemy_dist_cm} cm -> "
        f"heal={result}, expected {expect_heal}"
    )


def test_heal_safe_no_enemies(tmp_path):
    """No Majini on the field: heal immediately at any HP."""
    b = _make_bot(str(tmp_path))
    p = {"pos": [0.0, 0.0, 0.0]}
    snap = {"enemies": []}
    assert b._heal_safe(p, snap, 500, 1000) is True
    assert b._heal_safe(p, snap, 100, 1000) is True


def test_heal_safe_dead_enemies_ignored(tmp_path):
    """Dead Majini (hp=0) don't count toward the near-enemy deferral."""
    b = _make_bot(str(tmp_path))
    p = {"pos": [0.0, 0.0, 0.0]}
    snap = {"enemies": [
        {"pos": [100.0, 0.0, 0.0], "hp": 0, "hp_max": 800},   # dead, close
        {"pos": [50.0, 0.0, 0.0], "hp": 0, "hp_max": 800},   # dead, very close
    ]}
    assert b._heal_safe(p, snap, 500, 1000) is True


# --- Replay tests: full fixture replay through the bot ---


@pytest.mark.parametrize("fixture_file", CLUSTER_FIXTURES, ids=lambda p: p.stem)
def test_cluster_fixture_replay_runs(tmp_path, fixture_file):
    """Replaying a recorded cluster fixture through the bot must not crash."""
    fx = _load_fixture(fixture_file.name)
    assert fx["schema"] == incident_replay.SCHEMA
    assert fx["title"] == "BLUS30491"
    with tempfile.TemporaryDirectory() as td:
        result = incident_replay.replay(fx, ticks=5, dt=0.05, stats={}, start=1000.0)
    assert result is not None
    assert len(result["ticks"]) == 5
    # Each tick should produce an act dict (possibly empty)
    for tick in result["ticks"]:
        assert isinstance(tick["act"], (dict, type(None)))


@pytest.mark.parametrize("fixture_file", CLUSTER_FIXTURES, ids=lambda p: p.stem)
def test_cluster_fixture_heal_deferred_correct(tmp_path, fixture_file):
    """In the cluster fixtures, the bot's heal decision must follow the fixed threshold.

    The cluster is 'low_hp_no_heal': the bot sat at low HP with heals deferred. With HEAL_SAFE_R=250,
    a Majini at >250 cm must NOT defer a non-critical heal. We check the _heal_safe logic directly
    on the fixture snapshot (the full replay also covers this, but this isolates the threshold).
    """
    fx = _load_fixture(fixture_file.name)
    snap = fx["snapshot"]
    player = snap["player"]
    hp_before = fx["hp_before"]
    hp_max = fx["hp_max"]
    assert hp_max > 0

    b = _make_bot(str(tmp_path))
    # Use the fixture's actual enemy positions
    enemies = snap.get("enemies", [])
    result = b._heal_safe(player, snap, hp_before, hp_max)

    # Determine what the correct answer should be:
    critical = re5_ps3.HEAL_CRITICAL  # 0.25
    if hp_before <= critical * hp_max:
        # At or below critical: must always heal
        assert result is True, (
            f"{fixture_file.name}: hp={hp_before}/{hp_max} ({hp_before/hp_max:.0%}) <= critical "
            f"({critical:.0%}) but heal was deferred"
        )
    else:
        # Above critical: heal unless a live Majini is within HEAL_SAFE_R
        live_near = sum(
            1 for e in enemies
            if (e.get("hp") or 0) > 0 and (e.get("hp_max") or 0) > 1
            and math.dist(player["pos"], e["pos"]) < re5_ps3.HEAL_SAFE_R
        )
        if live_near == 0:
            assert result is True, (
                f"{fixture_file.name}: no live Majini within {re5_ps3.HEAL_SAFE_R} cm "
                f"but heal was deferred (hp={hp_before}/{hp_max})"
            )
        else:
            assert result is False, (
                f"{fixture_file.name}: {live_near} Majini within {re5_ps3.HEAL_SAFE_R} cm "
                f"but heal was not deferred (hp={hp_before}/{hp_max})"
            )


def test_bots_dict_includes_blus30491():
    """The replay BOTS dict must map BLUS30491 to the re5_ps3 module."""
    assert "BLUS30491" in incident_replay.BOTS
    assert incident_replay.BOTS["BLUS30491"] == "gbox.mercs.titles.re5_ps3"


def test_heal_safe_r_is_250():
    """The fix: HEAL_SAFE_R must be 250.0 (RE5 melee range), not the old 400.0 or 500.0."""
    assert re5_ps3.HEAL_SAFE_R == 250.0
