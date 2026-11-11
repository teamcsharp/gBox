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

## Round 110: the walker's control loop (`gbox/pso_walker.py`), tested against a simulated world

The planner turns a direction into keys; the **walker** closes the loop: read the player's position, plan the next leg, hold
the keys, repeat until the target is reached - or until something proves the walk wrong.

The one input it needs that the game does not hand over directly is "which world direction is the stick's forward". Instead of
digging that out of the actor struct, the walker **calibrates it from the game**: tap `up` briefly and take the displacement as
forward:

```
walker = Walker(read_position=lambda: pso_ram.position(reader, actor),
                press=lambda keys, seconds: pad.apply(taps(keys, seconds)),
                read_floor=lambda: pso_ram.floor(reader))
forward = walker.calibrate()                     # the world direction of one forward tap
result  = walker.walk_to((x, z), stop_on_floor_change=True)
```

`walk_to` returns `{arrived, why, legs, position, floor}`, and stops with a named reason: `within reach`, `the floor changed
(N -> M)`, `no stick direction for the target`, `gave up after N legs`, or `calibration failed` (the player did not move on a
forward tap - the honest signal that the session is not taking input at all).

**Tests: `tests/test_pso_walker.py` 6 passed** against a simulated world (a fake actor that moves along the stick's world
direction, with an optional wall and an optional floor change):

1. calibration reads forward from a tap (including a world where "up" means +x);
2. a straight walk arrives using only `up`;
3. an L-corner uses both `up` and `right` and still arrives;
4. a floor change stops the walk and reports both floor ids;
5. a player that moves once and then faces a wall yields `gave up`;
6. a player that never moves yields `calibration failed`.

With `test_pso_steer.py` and `test_pso_walk.py` that is **17 passed** for the walker's three layers: the collision graph, the
tap planner and the control loop.

**What is left for CP17's accept is now only the live part:** a session with a character in Forest 1 (CP5's state), the pad
(round 104), `pso_ram.floor` watched for the change, and the target cell taken from `pso_walk.path` to the next floor's
entrance. The three offline layers are done and tested.
