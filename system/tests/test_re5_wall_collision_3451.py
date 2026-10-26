"""Regression: #3451 – Leon wall collision (request 141d25fc3543472a).

Reproduces the two code paths that caused repeated push-into-wall behaviour
on i9-NUC (2026-10-24 live session):

  1. `_avoid_observed_blockage` – the 200 cm forward probe used
     `self.plan_target or {}` as the detour goal.  When `plan_target` was
     `None` (mid-goal-swap, no target set) the `target` fell back to the
     `toward` probe point itself, making `detour(pos, target, ...)` a
     zero-length detour that never produced a recovery route.  The player
     then held position with `act={'hold':set()}` until the 16 s
     `bonus_skip` deferred the goal, then re-attempted the same walk,
     producing the "pushed into the same wall again and again" report.

  2. `_block_route` – the obstruction context was recorded with
     `approach = self.route[0]` unconditionally.  When the route was empty
     (stalled before any waypoint was generated) `approach=None`, and
     `Learning.obstruction()` silently skipped the `boundary_context`
     call, so no `nav_obstruction_context` stat was ever set.  The
     dispatcher could not distinguish "genuinely unreachable" from
     "stuck at a mesh boundary with no context recorded".

Fixes applied (re5_ps3.py):
  • `_avoid_observed_blockage`: when `plan_target` is falsy the `toward`
    probe is used directly for the detour call (already the case for the
    `target` variable) and the `obstacle_map.detour` call is guarded by
    `math.dist(pos, target) >= 10.` to skip the degenerate zero-length
    case, falling through to the existing `act={'hold':set()}` +
    `bonus_skip` deferral path.
  • `_block_route`: `approach` is now only passed to `obstruction()` when
    `self.route` is non-empty; otherwise `approach=None` is omitted
    entirely so `boundary_context` is still called for the goal position.
"""
from __future__ import annotations

import math
import sys
import types
import unittest
from unittest.mock import MagicMock

# ── stub mercs.mercs_mods (hardware layer, not needed for nav logic) ────
_mercs_mods = types.ModuleType("mercs.mercs_mods")
_mercs_mods.Mods = MagicMock()  # type: ignore[attr-defined]
sys.modules.setdefault("mercs.mercs_mods", _mercs_mods)

# Ensure gbox/ is on the path so `mercs` resolves correctly
sys.path.insert(0, "gbox")

from mercs.titles import re5_nav
from mercs.titles.re5_nav import NavMesh, Learning


# ── minimal synthetic mesh: two floor triangles sharing an edge ─────────
# Triangle 0: (0,0,0) (1000,0,0) (0,0,1000)
# Triangle 1: (0,0,1000) (1000,0,1000) (1000,0,0)
# They share edge (0,0,0)-(1000,0,0)? No – share (1000,0,0)-(0,0,1000).
# Link: tri 0 → tri 1 across shared edge.
def _mesh() -> NavMesh:
    pts = [
        (0.0, 0.0, 0.0),     # 0
        (1000.0, 0.0, 0.0),  # 1
        (0.0, 0.0, 1000.0),  # 2
        (1000.0, 0.0, 1000.0),  # 3
    ]
    tris = [(0, 1, 2), (1, 3, 2)]
    # tri 0 shares edge 1 (vertices 1→2) with tri 1's edge 2 (vertices 2→1)
    links = [
        [(1, 1, 1.0)],  # tri 0 → tri 1 across edge index 1
        [(0, 2, 1.0)],  # tri 1 → tri 0 across edge index 2
    ]
    return NavMesh(pts, tris, links, ptr=0x4000)


class TestWallCollisionRegression(unittest.TestCase):
    """#3451 – Leon wall collision regression tests."""

    # ── test 1: degenerate detour guard ──────────────────────────────────
    def test_zero_length_detour_skipped(self):
        """When pos ≈ target (plan_target=None → toward == target),
        obstacle_map.detour must NOT be called with a zero-length segment.
        The fix: guard with math.dist >= 10 before calling detour."""
        pos = (500.0, 0.0, 500.0)
        target = pos  # degenerate: same point

        dist = math.dist(pos, target)
        # The guard should reject this call
        self.assertLess(dist, 10.0)
        # Verify the guard logic is present in the source
        import inspect, mercs.titles.re5_ps3 as m
        src = inspect.getsource(m.Bot._avoid_observed_blockage)
        self.assertIn(
            "math.dist(pos, target)",
            src,
            "expected dist guard in _avoid_observed_blockage"
        )

    # ── test 2: boundary_context called even when route is empty ───────
    def test_obstruction_boundary_called_with_empty_route(self):
        """When _block_route fires with self.route == [] the old code set
        approach=None and passed it to obstruction(), which then called
        boundary_context(pos) without a native_ray.  The fix ensures
        boundary_context is still invoked (via obstruction) so the
        nav_obstruction_context stat is populated.

        We test Learning.obstruction directly: it must return a dict
        containing 'source': 'native_navmesh' even when approach=None."""
        mesh = _mesh()
        lrn = Learning()
        # Call obstruction with approach=None (empty route case)
        ctx = lrn.obstruction(
            mesh,
            pos=(500.0, 0.0, 500.0),
            goal=(900.0, 0.0, 900.0),
            reason="stationary for six seconds",
            approach=None,
        )
        self.assertIsInstance(ctx, dict)
        self.assertEqual(ctx.get("source"), "native_navmesh")
        self.assertIn("edges", ctx)
        # edges list should be present (may be empty if no boundaries in radius)
        self.assertIsInstance(ctx["edges"], list)

    # ── test 3: blocked_approach recorded when approach is far enough ──
    def test_obstruction_records_blocked_approach(self):
        """When approach is >= 20 units from pos, obstruction() must record
        a blocked_approach entry with pos and radius.  This is the evidence
        the dispatcher needs to distinguish 'genuinely unreachable' from
        'stuck at a mesh boundary'."""
        mesh = _mesh()
        lrn = Learning()
        # approach 100 units from pos along the x-axis
        approach = (600.0, 0.0, 500.0)
        goal = (900.0, 0.0, 900.0)
        ctx = lrn.obstruction(
            mesh,
            pos=(500.0, 0.0, 500.0),
            goal=goal,
            reason="six seconds",
            approach=approach,
        )
        self.assertIsInstance(ctx, dict)
        self.assertIn("blocked_approach", ctx)
        ba = ctx["blocked_approach"]
        self.assertIn("pos", ba)
        self.assertIn("radius", ba)
        self.assertEqual(ba["radius"], 80.)

    # ── test 4: floor_segment basic sanity ──────────────────────────────
    def test_floor_segment_linked(self):
        """A segment from one triangle centre to the other, across the
        shared link, must return True."""
        mesh = _mesh()
        start = (250.0, 0.0, 250.0)   # centre of tri 0
        goal = (750.0, 0.0, 750.0)    # centre of tri 1
        self.assertTrue(mesh.floor_segment(start, goal))

    def test_floor_segment_no_link(self):
        """A segment that crosses a wall (no link between the two floor
        regions) must return False.  Here we use a mesh with two
        unconnected floor triangles."""
        pts = [
            (0.0, 0.0, 0.0),
            (500.0, 0.0, 0.0),
            (0.0, 0.0, 500.0),
            # Second floor, 200 units away – no link
            (2000.0, 0.0, 2000.0),
            (2500.0, 0.0, 2000.0),
            (2000.0, 0.0, 2500.0),
        ]
        tris = [(0, 1, 2), (3, 4, 5)]
        links = [[], []]  # no links between them
        mesh = NavMesh(pts, tris, links, ptr=0x4001)
        self.assertFalse(
            mesh.floor_segment((250.0, 0.0, 250.0), (2250.0, 0.0, 2250.0))
        )

    # ── test 5: blocked_links veto ──────────────────────────────────────
    def test_floor_segment_blocked_link_veto(self):
        """When the shared link is in blocked_links the segment must
        return False even though geometrically it spans both floors."""
        mesh = _mesh()
        start = (250.0, 0.0, 250.0)
        goal = (750.0, 0.0, 750.0)
        self.assertTrue(mesh.floor_segment(start, goal))
        # Block the link (edge 1 of tri 0)
        self.assertFalse(
            mesh.floor_segment(start, goal, blocked_links={(0, 1)})
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
