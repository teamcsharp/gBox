# Field doors are geometry, not data - so the collision grid is the map

## What the disc actually contains

**Cave 1 places five class types, none of them a door:**

```
TORockCaveBL03        155
TOSymbolchatColli      14
TOSensorAncient01      11
TOSensorGeneral01      11
index 6 (unresolved)    8
```

**No door, warp, gate, teleport or area class at all.** The registry's door classes are **city** doors (`TObjCityDoor_Shop/_Guild/_Warp/_Med/_Lobby`) plus
ruins map/goal warps - nothing that appears in a cave.

**And there are no event scripts to hold them either:**

```
.evt files on the entire disc: 5
  map_boss02jm.evt  map_boss05jm.evt  map_jungle01_off.evt
  map_jungle05_00_jm.evt  map_ruins01_00_jm.evt

cave01: 99 files - 36 rel, 12 dat, 12 tam, 10 bin - zero evt
cave02, cave03, machine01, machine02, ancient01/02/03, forest01: zero evt
```

## The conclusion

**A field-room connection is not a record anywhere.** Cave doors are part of the room's **collision geometry** - a doorway is a gap in the walls, and the door itself
is a moving piece of the map. That is why:

* the placement sets do not name them;
* `pso_evt`'s docstring says door transitions were never found in the placement sets;
* only 5 `.evt` files exist, all for boss rooms, jungle and ruins.

## Why this is good news for path-guiding

**It means the collision grid already is the map, and the door graph was never needed.**

The 51 decoded collision grids encode **every navigable surface including the doorways**, and they were already proven to route: 25 points across Cave 1 room 00,
**277 units against 256 straight (1.08x), zero points inside a wall, zero illegal transitions**.

So the sparse `link` graph (`cave01`: 8 edges) is **not a gap that blocks anything**. It was a detour, and the evidence now says so:

| source | what it gives | status |
|---|---|---|
| **collision `c.rel`** | **every walkable surface, doorways included** | **51 rooms decoded, routing proven** |
| placement `link` | a prior where the field happens to hold a room number | 998 edges, sparse in caves - **optional** |
| `.evt` scripts | boss/jungle/ruins events only | 5 files, none for caves |

## Correction to round 11's `link` reading

`link` is a **union field**, not a room-connection field. In `cave01_00`, 62 of 199 records carry a non-zero link, and most values are large ids (`2098688`,
`2097920`, `1442560`), not room numbers. Only room 1 (`20, 50, 51, 52, 53, 60, 120`) and room 60 (`1, 7`) hold genuine room numbers.

**So the 998-edge graph is conservative**: it counts only records whose `link` happens to name a room, and it can contain a coincidental small number. It is a **useful
prior, never an authority** - which is what `pso_roomgraph` already labels it as.

## Where this leaves the goal

The map question is **answered**: collision geometry is authoritative, it is internalised for 51 rooms, and it routes. What remains for "used for path-guiding the
bot" is not more map data - it is **mapping live positions onto that geometry**, which needs the per-room instance transform, and **input that reaches the game**,
which needs the relaunch.

Both are already diagnosed; neither is a data problem.
