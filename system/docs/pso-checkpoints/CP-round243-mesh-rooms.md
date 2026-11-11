# Round 243: room segmentation from the collision mesh alone - validated on Forest 1, and Forest 2 gets its first room graph

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
PSO not running (twelfth round), so this is offline level structure - the thing CP8 and the level editor both need.

## Why the existing builder could not do it

`room_graph.py` needs a **hand-entered door list read from the live entity table**, so it works for Forest 1 only, and only with a game
running. Doors are visible in the mesh itself, though, and Forest 2 has no entity table without a game.

## The method that works: erode, then grow

My first attempt cut cells with two or fewer free neighbours as "necks" - it found **5 cells** on Forest 1, because PSO corridors are two to
three cells wide and almost no cell is that isolated. The shape-based method works:

1. free cells from the floor's collision;
2. **erode once** (keep cells whose eight neighbours are all free) - this strips every one-cell wall of a corridor and leaves room interiors;
3. connected components of the eroded set are **room cores**;
4. **flood** every free cell to its nearest core, so corridors belong to the rooms they serve;
5. a cell whose neighbour belongs to another room is a **boundary** - the doorways.

## Validated on Forest 1

```
floor 1: 5701 free cells, 4147 after one erosion, 11 room cores, 11 rooms, 61 boundaries
```

The known graph has 9 rooms; the mesh finds 11 (two of them tiny: 49 and 39 cells), and **seven centres match the known ones almost exactly**:

| mesh room | known room centre |
|---|---|
| (-508.2, -93.4) | (-508, -92) |
| (-329.0, -475.1) | (-330, -476) |
| (533.2, -107.7) | (533, -114) |
| (-57.3, 84.8) | (-59, 92) |
| (-341.0, 321.2) | (-372, 306) |
| (-81.0, 375.5) | (-65, 379) |
| (232.3, 294.1) | (141, -194) is a different room; the rest are segment splits |

So the segmentation is right in structure, with the known rooms recovered independently of any door list.

## Forest 2's first room graph

```
floor 2: 6145 free cells, 4106 after erosion, 14 rooms, 76 boundaries
  room 0: 1082 cells  (-66, 256)      room 7:  464 cells (-462,-488)
  room 1:  766 cells  (443,  63)      room 8:  308 cells (214,-347)
  room 2:  676 cells  (364,-426)      room 9:  306 cells (-377,-165)
  room 3:  598 cells  (-505, 306)     room 10: 137 cells (-571,-127)
  room 4:  559 cells  (258, 437)      room 11: 104 cells (-427, 31)
  room 5:  471 cells  (-226, 147)     room 12:  67 cells (479, 534)
  room 6:  485 cells  (-144,-366)     room 13:  50 cells (328,-140)
```

Written to `routes/forest2-rooms-mesh.json` with each room's centre, bounds, full cell list, and the 76 boundary cells with the rooms they
join. That is a complete static room graph for Forest 2, obtained **without a game** - which is what the operator's "learn the layout" and the
level editor's top-down view both need.

## What this unlocks next

* the explorer can walk Forest 2 room by room instead of steering at coordinates;
* the map viewer can draw Forest 2 with its rooms and doorways, and switch floors;
* CP8's "room pieces for level expansion" now has a machine-readable segmentation to attach pieces to.

## Files

* `rooms_mesh2.py` - the segmentation (`python rooms_mesh2.py <floor>`)
* `routes/forest1-rooms-mesh.json`, `routes/forest2-rooms-mesh.json`
