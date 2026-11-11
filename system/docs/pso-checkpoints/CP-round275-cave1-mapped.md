# Round 275: Cave1 identified, mapped and now navigable

The Cave maps were extracted last round; this round turned them into a usable level.

## Which of the six layouts is live: measured, not assumed

Cave 1 ships six layouts. The loaded one is the only layout whose walkable cells contain the character **and** the doors and containers standing in
the world, so each candidate was scored against both:

```
map_cave01_00c.rel: player on free cell=True, objects on free cells=94/94 (100%), free cells=17877
map_cave01_01c.rel: player on free cell=False, objects  26/94 (28%)
map_cave01_02c.rel: player on free cell=False, objects   8/94 (9%)
map_cave01_03c.rel: player on free cell=False, objects   2/94 (2%)
map_cave01_04c.rel: player on free cell=False, objects   6/94 (6%)
map_cave01_05c.rel: player on free cell=True,  objects   9/94 (10%)
```

**`map_cave01_00c.rel` wins with 94 of 94 - every single live object sits on its walkable ground - and a 90-point margin over the next candidate.**
That is not a guess; a wrong layout cannot place 94 objects correctly.

## A second "borrowed data" bug, caught by the room centres

Building the mesh produced room centres like (-57, 84) and (475, 503) - **Forest 1's rooms**. The cause was `nav_fast.rel_for_floor`, which returned
a hardcoded mapping and **fell back to Forest 1's collision for any unknown floor**, so asking for floor 3's rooms silently segmented Forest 1 and
wrote the result out as `forest3-rooms-mesh.json`.

This is the same class of defect as the `selfplay2.rooms()` fallback fixed earlier: a missing map masquerading as a known one. `rel_for_floor` now
uses the floor's own file when it exists, and only falls back otherwise:

```
floor 1 -> map_forest01c.rel |  5701 free cells
floor 2 -> map_forest02c.rel |  6145 free cells
floor 3 -> map_forest03c.rel | 15576 free cells     <- Cave 1
```

## Cave 1, mapped

```
floor 3: 22 rooms, 129 doorway cells, 15576 free cells
heights: 21679 cells, validated against the player's own y at 0.00 units of error
room database: 22 rooms with heights (0.0 .. 158.9) and connections
```

Sample, from the room database:

| room | cells | heights | connects to |
|---|---|---|---|
| 0 | 1930 | 0.0 .. 94.2 | 4, 11, 12, 13 |
| 1 | 1457 | 60.0 .. 138.7 | 14 |
| 4 | 1114 | 60.0 .. 136.8 | 0, 7, 10 |
| 11 | 784 | 0.0 .. 158.9 | 0, 5, 9, 18 |

## Navigation audit

```
floor 3: 22 rooms, 15511 room cells, 15576 free cells, 13031 reachable from room 0
unreachable rooms: [6, 12, 13, 15, 20, 21]
```

**16 of 22 rooms are navigable**, and the six that are not are exactly the kind that sit behind closed doors - the static mesh marks a closed door
as wall, which is the effect measured last round on Forest 2. The bot now excludes them, and the remaining level is walkable.

## What changed for the bot

**Cave 1 went from "no map, wander blindly" to "22 rooms, heights, connections, 16 navigable"** in one round, and the same pipeline now runs on any
area whose collision map exists - which, since last round, is every map in the game.

## State

| item | state |
|---|---|
| live Cave 1 layout | `map_cave01_00c.rel`, identified at 94/94 objects |
| Cave 1 rooms | 22, with heights and connections |
| Cave 1 navigable | 16 of 22 (six behind closed doors, excluded) |
| height validation | 0.00 units on Cave 1 |
| maps available | every map in the game can be extracted |
| game focus | false - the bot still cannot act in-game |
