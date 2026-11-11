# CP17-CP19 (mastery): walking the collision graph instead of warping

Session identity: DeepSeek    Branch: ds-pso-cp17-walk-graph-20261110    Commits: this branch
Goal: 3 (P3) and the mastery family

## What CP17 asks

> **CP17 (P3): Forest 1 -> Forest 2 by walking the collision graph.**
> Use `psomap.collision`, the floor resolver and `pso_floor_map`, then `re5_nav`'s pattern. Do it with both players, and
> develop it from CP5's state. **Accept:** the floor id changes by walking, with no warp.

The live half needs CP5's state (a character in Forest 1) and the pad (rounds 103-104). The **offline half is the graph**, and
this branch builds it.

## Round 108: the collision graph is routable (`gbox/pso_walk.py`)

`psomap.collision` already parses a room's `c.rel` and `psomap.walkable_cells` already turns its triangles into floor cells and
wall cells (with the rules for ramps, curbs and cliffs). What was missing is the graph on top:

```
floors, walls = pso_walk.cells(c_rel_bytes)          # psomap's own walkability rules
route = pso_walk.path(c_rel_bytes, start, end)       # [(x, z), ...] cell centres, or None
```

* only floor cells are walkable; wall cells block, so a diagonal never slips through a corner;
* the start and end **snap to the nearest floor cell** within three cells, so a position read from RAM does not have to be
  exact;
* `describe()` returns the floor/wall/walkable counts for a route to be checked against.

**Tests** (`tests/test_pso_walk.py`, **4 passed**) on the real `Scene/map_aancient01_00c.rel`:

1. the room has a real graph (more than 100 floor cells, some walls, and walkable ≤ floors);
2. the **largest connected region** (`≥ 20` cells) is routable between its two extreme cells, the route's endpoints are those
   cells' centres, and every step is a four-neighbour move of exactly one cell;
3. a point far outside the room yields **no route** (the snap radius is bounded);
4. `to_cell`/`cell_centre` are inverse.

The first attempt picked the two *extreme* walkable cells and failed - they sit in **different connected components**. That is
itself a useful fact for the walker: a room's collision data can contain islands, so a route must be planned inside one
component, and a failed route is not a broken graph.

## What is left, and what it needs

1. **The floor resolver's ground truth**: `pso_floor_map` is not on main (the guide names it; the branch that carries it is
   docs-only). The floor table itself is measured (CP15's work: 36 floors, floor 0 = `map_city00`), so the walker can resolve
   the current floor from RAM's floor id and the collision file of the layout it is in.
2. **The route from a live position**: read the player's position from RAM, snap it, route to the exit/teleporter cell, then
   walk it with direction taps through the pad (round 104's mechanism). The waypoints are world positions; the pad taps are
   relative directions, so the walker needs a heading from the camera/player yaw - that is the next piece of code, not a
   research question.
3. **Both players**: CP17 says "with both players", so the route is walked once with each player as the lead, or co-op
   movement is driven for both.

Tests: 4 new, all green. No other suite touched.

## Round 109: waypoints to stick taps (`gbox/pso_steer.py`)

The second half of the walker: given a world route, the player's position and a yaw, which stick keys to hold. The yaw
convention is an explicit argument (`forward_at_zero`), so the live calibration is one number and the rest is testable:

```
direction_taps((0, -1), 0.0)              -> ("up",)                 # forward at yaw 0
direction_taps((1, 0), 90.0)              -> ("up",)                 # the camera turned to +x
direction_taps((1, -1), 0.0)              -> ("up", "right")         # a diagonal is two keys
route_taps(route, position, yaw, reach=6) -> [{"to", "direction", "keys"}, ...]
```

Two bugs were found by the tests and fixed before committing:

* the screen-right vector was rotated the wrong way (`(f.z, -f.x)` instead of `(-f.z, f.x)`), which mirrored every diagonal;
* `route_taps` took each waypoint's direction from the **start** position rather than the **previous waypoint**, so a corner
  came out as a diagonal instead of a turn - the corner test caught it.

**Tests:** `tests/test_pso_steer.py` **7 passed** (the four cardinals at yaw 0, a yaw-90 turn, a diagonal, a zero direction, the
reach skip, the corner turn, and `describe`'s length), and together with `test_pso_walk.py` **11 passed**.

**What the live walk needs next:** the one calibration number (`forward_at_zero`, from the first live read of the player's yaw
and a step in a known direction), the player's position per frame, and a tap cadence (hold, read, re-plan). Those are live
inputs; the planner itself is done and tested.
