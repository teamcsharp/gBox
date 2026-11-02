"""Incident replay tests for cluster 6cd8a6ad62b8aa91 (RE5 PS3, own_bomb, mine_retreat).

The bot was inside or near its own planted bomb's blast radius (dist < MINE_ESCAPE_CM
= 600cm) while the arming window was still open.  Before the fix it would pick a
retreat route and walk through the blast; now it holds position until the hazard
clears or separation is safe.

Each fixture was recorded at the moment of damage (the Observer froze the snapshot
before health maintenance), so the player position and mine position are the
exact values the bot saw when it took the hit.
"""
import json
import math
from pathlib import Path

from gbox.mercs import incident_replay
from gbox.mercs.titles import re5_ps3 as R

FIXTURES = Path(__file__).parent / "fixtures" / "mercs_incidents"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def _dist(player, mine):
    return math.dist(player, mine)


# ---- fixtures 0-2: player well inside MINE_ESCAPE_CM, not detonating yet ----
def test_inside_blast_holds_position_fixtures_0_1_2():
    """Fixtures 0-2: player < 600cm from own mine, arming_s=0 (not detonating).
    The bot must hold position (empty hold set) rather than walking a route
    that passes through the blast radius."""
    for i in (0, 1, 2):
        fx = _load(f"re5_ps3_mine_retreat_blast_{i}.json")
        result = incident_replay.replay(fx, ticks=10)
        # The bot should be in the leave_proximity_bomb phase
        assert result['stats'].get('phase') == 'leave_proximity_bomb', \
            f"fixture {i}: expected leave_proximity_bomb, got {result['stats'].get('phase')}"
        # The mine_retreats_blocked counter should have incremented (holding inside blast)
        assert result['stats'].get('mine_retreats_blocked', 0) >= 1, \
            f"fixture {i}: expected mine_retreats_blocked >= 1, got {result['stats'].get('mine_retreats_blocked')}"
        # No movement keys should be held (no d-left/d-right/d-up/d-down/rleft/rright)
        movement_keys = {'dleft', 'dright', 'dup', 'ddown', 'rleft', 'rright'}
        held = incident_replay.keys(result)
        assert not (held & movement_keys), \
            f"fixture {i}: bot held movement keys {held & movement_keys} while inside blast"
        # The status string should mention the blast-radius hold
        assert 'blast radius' in result['stats'].get('mine_retreat_status', ''), \
            f"fixture {i}: expected 'blast radius' in status, got {result['stats'].get('mine_retreat_status')}"


# ---- fixture 3: player at 134cm, mine detonating, phase=clear_nearby ----
def test_detonating_mine_inside_blast_holds_position_fixture_3():
    """Fixture 3: player 134cm from detonating own mine. The bot was in
    clear_nearby phase. It must hold, not walk through the active blast."""
    fx = _load("re5_ps3_mine_retreat_blast_3.json")
    result = incident_replay.replay(fx, ticks=10)
    stats = result['stats']
    # The mine_retreats_blocked counter should have incremented
    assert stats.get('mine_retreats_blocked', 0) >= 1, \
        f"fixture 3: expected mine_retreats_blocked >= 1, got {stats.get('mine_retreats_blocked')}"
    # No movement keys
    movement_keys = {'dleft', 'dright', 'dup', 'ddown', 'rleft', 'rright'}
    held = incident_replay.keys(result)
    assert not (held & movement_keys), \
        f"fixture 3: bot held movement keys {held & movement_keys} while inside blast"


# ---- fixture 4: player at 131cm, mine detonating, phase=leave_proximity_bomb ----
def test_detonating_mine_leave_proximity_holds_position_fixture_4():
    """Fixture 4: player 131cm from detonating own mine in leave_proximity_bomb
    phase. Must hold, not walk through the active blast."""
    fx = _load("re5_ps3_mine_retreat_blast_4.json")
    result = incident_replay.replay(fx, ticks=10)
    stats = result['stats']
    assert stats.get('phase') == 'leave_proximity_bomb', \
        f"fixture 4: expected leave_proximity_bomb, got {stats.get('phase')}"
    assert stats.get('mine_retreats_blocked', 0) >= 1, \
        f"fixture 4: expected mine_retreats_blocked >= 1, got {stats.get('mine_retreats_blocked')}"
    movement_keys = {'dleft', 'dright', 'dup', 'ddown', 'rleft', 'rright'}
    held = incident_replay.keys(result)
    assert not (held & movement_keys), \
        f"fixture 4: bot held movement keys {held & movement_keys} while inside blast"


# ---- sanity: player far from mine should NOT trigger the blast-radius hold ----
def test_far_from_mine_does_not_trigger_blast_hold():
    """A synthetic snapshot with the player 2000cm from its own mine should
    NOT trigger the blast-radius hold. The bot should proceed with a normal
    retreat route (or at least not report 'blast radius' in the status)."""
    fx = _load("re5_ps3_mine_retreat_blast_0.json")
    # Push the player far from the mine
    snap = fx['snapshot']
    mine_pos = list(next(iter(snap['ground_mines'].values()))['pos'])
    # Place player 2000cm away along the x-axis
    snap['player']['pos'] = [mine_pos[0] + 2000., mine_pos[1], mine_pos[2]]
    result = incident_replay.replay(fx, ticks=10)
    stats = result['stats']
    # Should NOT be in the blast-radius hold
    assert 'blast radius' not in stats.get('mine_retreat_status', ''), \
        f"far-from-mine: unexpected blast-radius hold, status={stats.get('mine_retreat_status')}"
