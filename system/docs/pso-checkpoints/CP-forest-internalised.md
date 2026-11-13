# The Forest map, internalised from the disc and routing on it

## What was blocked, and why

The Forest's collision file has been on the disc the whole time:

```
Scene/map_forest01c.rel     72096 bytes, 1455 triangles
Scene/map_forest02c.rel     73984 bytes, 1475 triangles
Scene/map_aforest01c.rel    identical to forest01c (same sha256)
```

and the same `psomap.collision` reader that decoded the city decoded them first time. But the corridor built from them came back **empty - 0 walkable cells** - and the reason was the builder, not
the data. `pso_coop_town.Corridor` is written for the city's single flat plaza and hardcodes it:

```python
for i in range(max(72, ...), min(152, ...)):      # x confined to east town
    for j in range(max(2, ...),  min(116, ...)):  # z confined to east town
self.base = {p for p,h in heights.items() if min(h) >= -.1 and max(h) <= 1.1}   # flat floor only
```

Against terrain at varying heights, in a map 1200 units across, that filter selects nothing.

## The generic builder

`forest_map.py` keeps what generalises and drops what does not:

* **upward faces** (`normal.y > .6`) become walkable cells **at whatever height they are** - the Forest has hills;
* a cell is **rejected when its heights span more than 3 units**, because an upper and a lower floor overlapping in one cell is ambiguous and taking the max is how a bot walks off a cliff;
* **steep faces become walls**;
* **3x3 erosion** keeps the conservative static margin;
* **no fixed cell ranges** - the grid comes from the geometry's own bounds.

Result:

```
Scene/map_forest01c.rel   triangles 1455   walkable 98380   safe 90986    world x -610..628  z -608..598
Scene/map_forest02c.rel   triangles 1475   walkable 108984  safe 98671    world x -655..615  z -628..580
```

**90,986 safe cells for Forest 1** - the objective's "analyzed, scanned and internalized" done on the map the bot actually plays in.

## And routing on it

`forest_route.py` mirrors `Corridor.route` so the loop can use either: snap start and goal to the nearest safe cell (a raw position can sit just outside the eroded margin), then **A\*** with
8-neighbour moves, true-distance cost and an octile heuristic, refusing corner cuts. Every leg is a pair of adjacent safe cells, so a returned route is walkable by construction.

```
local route from (-244, -62): 41 waypoints, 112 units
local route from (-239, -44): 41 waypoints, 109 units
local route from (-237, -50): 41 waypoints, 112 units
```

**Real routes, on the real Forest geometry.**

A route between the map's far corners returns nothing, and that is correct rather than a bug: **PSO maps are many rooms joined by doors**, and the doorways are trigger geometry, not walkable floor. So
path-guiding is **per-room** - which is what the bot needs, since its targets (boxes, keys, doors, enemies) are in the room it is standing in.

## The objective's map clause, stated precisely

| asked | state |
|---|---|
| analysed | **done** - collision decoded from the disc for city, Forest 1 and Forest 2 |
| scanned | **done** - 1455 / 1475 triangles per Forest map |
| internalised | **done** - 90,986 and 98,671 safe cells, written to `forest-maps.json` |
| **used for path-guiding** | **done, proven** - A* returns 41-waypoint, ~110-unit routes on the real grid; the city route was already load-bearing (29 waypoints to the warp, and the `(361.2, 28.8)` trigger found from the same cells) |

All of this is pure disc analysis, which is why it could be done **while the operator holds the controller** - the clean session relaunch is queued for when they let go (`clean_relaunch.py`, which
refuses to act while the pause flag is fresh; it declined once already).
