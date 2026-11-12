# The whole map, decoded from the disc and used to route

## What was already there, and what was missing

`D:\gBox\pso-ds\routes\` had **15 Forest files** (mesh, heights, doors, 27-44 rooms each) and `map-audit.json` reporting 14 floors. **Cave, Mine and Ruins had
zero coverage** - and the operator plays in Cave 1.

But the **172 collision RELs** for every room of every area were already extracted at `D:\gBox\pso-ds\rel\`:

```
cave01_00..05  cave02_00..04  cave03_00..05      (17 rooms)
machine01_00..05  machine02_00..05               (12 rooms)
ruins01_00..02  ruins02_00..02                   (6 rooms)
ancient01/02/03_00..04                           (15 rooms)
forest01..14, boss*, lobby*, jungle*, seabed*, space*, city*, vs*
```

and `gbox/psomap.py` already decodes them - `collision(data, be=True)` returns the triangles, `walkable_cells(tris, size=10, step=6, body=18)` reduces them to a
grid. Its docstring records the verification: *"69 meshes, 1455 triangles, the raster matches Forest 1's layout"* on `map_forest01c.rel`.

## What this round did

**Internalised every Episode I interior from the disc**:

```
50 rooms to internalise across 10 areas
wrote 50 room maps in 36.0s
  304698 triangles, 219675 blocked cells total
  per area: cave01=6, cave02=5, cave03=6, machine01=6, machine02=6,
            ruins01=3, ruins02=3, ancient01=5, ancient02=5, ancient03=5
```

Each file carries the floor, the source REL, the triangle count, the **blocked cells** (what a router avoids) and the walkable count - the same shape as the
Forest files that were already there.

## And it routes

On the decoded **Cave 1 room 00** - the room the operator is standing in:

```
room: cave01_00 | triangles: 7934
  walkable cells: 886 | wall cells: 7458
  largest reachable component: 318 cells
  start cell: (-5, -22) -> goal cell: (4, 2)   manhattan: 33

route: 25 points
  points inside a wall:     0
  illegal transitions:      0
  path 277 units vs 256 straight (1.08x)

VERDICT: the decoded map guides a legal route
```

**A* over the disc's own collision geometry, avoiding 7,458 wall cells, within 8% of the straight line.** That is the goal's "map layout analyzed, scanned and
internalized and used for pathguiding the bot", demonstrated end to end on the room in play.

## The pathfinder itself

`pso_coop_nav.RoomMap` learns blocked edges from failed moves (`observe`) and routes with A* (`route`, `toward`). Verified separately: a synthetic room with a
learned wall across the middle produced a route with **0 points inside the wall span** and 77 units against 60 direct - it goes around.

So there are now **two** map sources that agree in shape:

* **disc-derived** walls for all 50 interior rooms (this round), authoritative and complete;
* **observed** blocked edges learned while playing (the module's original purpose).

## Status of the other two goal items

**10x speed** - reachable but gated twice. `pso_controls` reports:

```json
"autoplay_speed": {"requested": 1.0, "choices": [1, 2, 4, 8, 10],
                   "known": false, "measurement_verified": false}
```

`known: false` means `set_speed` refuses with *"Speed input was interrupted; relaunch to restore a known 1x baseline"*, and it also requires
`_pso_coop_new_card.isolated` - a dedicated buddy session. **So 10x needs a fresh launch** (which also carries the `pad_route` fix), not a code change.

**Decryption** - the map RELs decode cleanly, and the disc catalogue already has the encrypted quest container handled elsewhere; what this round proves is that
**the collision data needed for pathing is not encrypted at all** - it parses directly from the retail RELs.
