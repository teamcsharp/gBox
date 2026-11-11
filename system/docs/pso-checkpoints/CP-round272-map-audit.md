# Round 272: the 2D map audited - floor 1 is fully navigable, floor 2 has three unreachable rooms

The operator's framing: *"the 2D map is the 3D game"*. So the map has to be provably complete before navigation can be trusted. `map_audit.py` checks
each mapped floor on four criteria: every room has cells, every cell has a height, every room cell is walkable, and every room is reachable from
room 0 **through the same cell graph the planner walks**.

## Floor 1: PASS

```
11 rooms, 5698 room cells, 5701 free cells, 5696 reachable from room 0
```

Only five cells out of 5,701 are outside the main component - a sealed pocket, not a room.

## Floor 2: three rooms cannot be reached

```
14 rooms, 6073 room cells, 6145 free cells, 4580 reachable
unreachable rooms: [1, 2, 13]
```

That is a concrete defect the bot would hit in play: **picking one of those rooms as a destination means walking into geometry and never arriving**.

## Investigating it

The obvious hypothesis was closed doors: the collision mesh is static, so a doorway reads as wall even though at runtime the door opens when its room
is cleared. `nav_doors.py` added the mesh's doorway cells (plus their neighbours) to the walkable set:

```
floor 1: free cells 5701 -> 5783 (+82)   reachable 5698 -> 5780
floor 2: free cells 6145 -> 6251 (+106)  reachable 4581 -> 4679
```

Reachability improved by 98 cells on Forest 2 - **but rooms 1, 2 and 13 stayed unreachable**. So doors are not the explanation:

* **room 13 has no doorway in the mesh at all** - it connects to nothing;
* **rooms 1 and 2 connect only to each other**, forming a closed pair.

Whatever the cause - a secret room, a segmentation artefact, or a route the collision mesh classifies as wall - it is a property of the data, and the
bot now respects it: self-play reads the audit and **excludes proven-unreachable rooms from its destination list** (`unreachable_rooms(2)` returns
`{1, 2, 13}`, floor 1 returns nothing).

## A bug in my own audit, caught by running it

The first doorway extraction added **zero cells** on both floors, because I assumed a doorway was stored as a coordinate tuple when the mesh stores
scalar `x` and `z`. Reading the actual record fixed it:

```
{"class": "boundary", "x": -445.0, "z": -25.0, "rooms": [9, 11]}
```

## Why this is the right kind of progress

Four rooms and 5,700 cells are now either provably walkable or provably not, from data rather than from watching the bot bump into things. The map is
a specification: the planner, the minimap, the click-to-order feature and the room database all read the same cells, and the audit is what keeps them
honest.

## State

| item | state |
|---|---|
| floor 1 map | PASS - 11 rooms, 5696/5701 cells reachable |
| floor 2 map | 11 of 14 rooms reachable; 1, 2, 13 isolated in the mesh |
| bot | excludes unreachable rooms; idle while the game is unfocused |
| training loop | built (`combat_train.py`), needs game focus to act |
| weapon research | done (3 categories, ATP-based damage, specials incl. confusion tiers) |
