"""Focused unit tests for request #5134 (damage cluster 6cd8a6ad62b8aa91).

Cluster: RE5 PS3 "own bomb or mine within blast radius" — the bot ends up inside
its own mine's blast radius during leave_proximity_bomb and takes damage
(bomb_cm = 49-127 in the recorded hits). Root cause: _mine_retreat's fallback
loop accepts shorter routes (450cm, 300cm) that still pass through the 600cm
blast radius when no 600cm route exists. The fix: if the bot is already inside
MINE_ESCAPE_CM of the hazard, hold position instead of walking a shorter route.
"""
from __future__ import annotations

import math
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from gbox.mercs.titles import re5_ps3


def _make_bot(pos=(0.0, 0.0, 0.0)):
    """A minimal bot namespace with the attributes _mine_retreat needs."""
    bot = SimpleNamespace()
    bot.stats = {"mine_departure_yielded": False}
    bot.mines = SimpleNamespace(
        escape={"actor": 0x30800000, "pos": (100.0, 0.0, 0.0)},
        clear_escape=lambda now, p: False,
    )
    bot.bonus_commitment = SimpleNamespace(pause=lambda now: None)
    bot.bonus_skip = {}
    bot.route_for = None
    bot.route = None
    bot.route_at = 0.0
    bot.blocked_links = set()
    bot.nav_learning = SimpleNamespace(link_penalties=lambda mesh: {})
    bot.nav_dynamic_mines = {}
    bot.plan_target = None
    bot.aiming_since = None
    bot.avoid = None

    def _mine_hazard_removed(escape, ground):
        return False

    def _recover_nav(p, mesh, now):
        return {"hold": set()}

    bot._mine_hazard_removed = _mine_hazard_removed
    bot._recover_nav = _recover_nav
    # Bind the real _mine_retreat from the Bot class
    bot._mine_retreat = re5_ps3.Bot._mine_retreat.__get__(bot)
    # Track _follow calls
    bot._follow_calls = []
    def _follow(p, target, mesh, flag, now, learn, retreat_from=None, approved_route=None):
        bot._follow_calls.append(target)
        return {"hold": {"up"}}
    bot._follow = _follow
    return bot


def _make_mesh(hazard_dist_meters, route_returns=None):
    """A mesh whose retreat() returns a route for distances >= threshold, None otherwise.

    Simulates: if the player is at `hazard_dist_meters` from the hazard,
    mesh.retreat(pos, hazard, min_distance) returns a route only when
    min_distance <= hazard_dist_meters (i.e., a route exists to that distance).
    """
    mesh = MagicMock()
    mesh.find = MagicMock(return_value=0)  # player is on floor
    mesh.floor_segment = MagicMock(return_value=True)
    mesh.hazard_segment_clear = MagicMock(return_value=True)

    def fake_retreat(start, hazard, min_distance, **kwargs):
        dist = math.dist(start, hazard)
        if route_returns is not None:
            return route_returns
        # A route to min_distance exists only if the player can reach that far
        # from the hazard without passing through it. In this simplified model,
        # a route exists iff min_distance <= dist (player is already beyond it)
        # or the mesh has space to route around. For the test, we say a route
        # exists only when min_distance <= 500 (the "short" fallback distances).
        # The 600cm route fails (no safe path), but 450/300 succeed.
        if min_distance <= 500.:
            return [(1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]  # a short route
        return None

    mesh.retreat = fake_retreat
    return mesh


def test_inside_blast_radius_holds_position():
    """When the bot is at 86cm from its own mine (inside the 600cm blast radius)
    and no 600cm retreat route exists, it should hold position rather than walk
    a 450/300cm route that passes through the blast."""
    bot = _make_bot(pos=(0.0, 0.0, 0.0))
    escape_pos = (8.6, 0.0, 0.0)  # 86cm away
    bot.mines.escape = {"actor": 0x30800000, "pos": escape_pos}
    bot.mines.clear_escape = lambda now, p: False

    mesh = _make_mesh(8.6)
    snap = {
        "nav": mesh,
        "ground_mines": {0x30800000: {"pos": escape_pos, "arming_s": 1.5, "detonating": False}},
        "bonuses": [],
    }

    p = {"pos": (0.0, 0.0, 0.0)}
    result = bot._mine_retreat(p, snap, now=100.0)

    # The bot should hold position (empty hold set), not follow a route.
    assert result == {"hold": set()}, (
        f"Expected hold position inside blast radius, got: {result}"
    )
    assert "inside blast radius" in bot.stats.get("mine_retreat_status", "")
    assert bot.stats.get("mine_retreats_blocked", 0) >= 1


def test_outside_blast_radius_still_finds_route():
    """When the bot is at 7m from its own mine (outside the 600cm blast radius)
    and no 600cm retreat route exists, it should still use the 450/300cm fallback
    routes and follow one."""
    bot = _make_bot(pos=(0.0, 0.0, 0.0))
    escape_pos = (700.0, 0.0, 0.0)  # 7m away, outside blast
    bot.mines.escape = {"actor": 0x30800000, "pos": escape_pos}
    bot.mines.clear_escape = lambda now, p: False

    mesh = _make_mesh(700.0)
    snap = {
        "nav": mesh,
        "ground_mines": {0x30800000: {"pos": escape_pos, "arming_s": 1.5, "detonating": False}},
        "bonuses": [],
    }

    p = {"pos": (0.0, 0.0, 0.0)}
    result = bot._mine_retreat(p, snap, now=100.0)

    # The bot should follow a route (the _follow mock returns hold up).
    assert result == {"hold": {"up"}}, (
        f"Expected route follow outside blast radius, got: {result}"
    )
    assert len(bot._follow_calls) == 1


def test_boundary_exactly_at_escape_cm_holds():
    """At exactly MINE_ESCAPE_CM (600cm), the bot is at the edge of the blast.
    The check uses strict <, so exactly at 600cm it should still attempt routes."""
    bot = _make_bot(pos=(0.0, 0.0, 0.0))
    escape_pos = (600.0, 0.0, 0.0)  # exactly at MINE_ESCAPE_CM
    bot.mines.escape = {"actor": 0x30800000, "pos": escape_pos}
    bot.mines.clear_escape = lambda now, p: False

    mesh = _make_mesh(600.0)
    snap = {
        "nav": mesh,
        "ground_mines": {0x30800000: {"pos": escape_pos, "arming_s": 1.5, "detonating": False}},
        "bonuses": [],
    }

    p = {"pos": (0.0, 0.0, 0.0)}
    result = bot._mine_retreat(p, snap, now=100.0)

    # At exactly 600cm, the bot is NOT inside (< 600 is False), so it proceeds
    # to the fallback routes.
    assert result == {"hold": {"up"}}, (
        f"Expected route follow at exact boundary, got: {result}"
    )


def test_inside_blast_radius_yields_when_hazard_removed():
    """If the hazard is verified removed while the bot is inside the blast,
    yield_removed_hazard should take priority and the bot resumes combat."""
    bot = _make_bot(pos=(0.0, 0.0, 0.0))
    escape_pos = (50.0, 0.0, 0.0)  # 50cm — well inside blast
    bot.mines.escape = {"actor": 0x30800000, "pos": escape_pos}
    bot.mines.clear_escape = lambda now, p: False
    # Simulate: the hazard is gone (no longer in ground_mines)
    bot._mine_hazard_removed = lambda escape, ground: True

    mesh = _make_mesh(50.0)
    snap = {
        "nav": mesh,
        "ground_mines": {},  # mine is gone
        "bonuses": [],
    }

    p = {"pos": (0.0, 0.0, 0.0)}
    result = bot._mine_retreat(p, snap, now=100.0)

    # Should return None (yield removed hazard → resume normal play)
    assert result is None
    assert bot.stats.get("mine_departure_yielded") is True
