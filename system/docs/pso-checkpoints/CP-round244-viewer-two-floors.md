# Round 244: the map viewer now draws both forest floors, with a selector

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
PSO not running (thirteenth round).

## What changed

`/api/rooms` takes a floor and serves that floor's segmentation, preferring the **mesh graph** built last round:

```
/api/rooms?floor=1  ->  11 rooms, 61 doors, method "erode + grow"
/api/rooms?floor=2  ->  14 rooms, 76 doors, method "erode + grow"
```

and the page has a **view selector** (`Forest 1` / `Forest 2`) that refetches and refits the canvas when changed:

```
page: 200, has selector: True
```

Fallback order per floor: `forest<N>-rooms-mesh.json`, then `forest<N>-rooms.json`, then the original Forest 1 door-based graph - so
the viewer keeps working whichever of them exists.

## Why this matters for the operator's ask

They wanted to *"look at the level with a top down view"* and to *"print the map"*, with the minimap-first idea as the foundation of a level
editor. The viewer now draws:

* every room's cell footprint on either forest floor,
* the doorways (61 on Forest 1, 76 on Forest 2) as the room-to-room edges,
* the live player, HP, doors and enemies when a session is running,
* and it answers instantly even with no game, saying so.

## What it still needs to become the editor

* clicking a room should select it and show its cells, bounds and the object records inside it (the set-file decode already gives every
  object's class and position per floor);
* a piece palette: `map_forest01d.dat` and `map_forest02d.dat` decode 150/150 and 150/150 objects respectively, so the objects a room
  contains are already computable from data;
* an export that writes a modified set file - the PM's CP11 branch has the build endpoint, but it is unmerged.

## Files

* `map_viewer.py` - floor-aware `/api/rooms`, floor selector, instant no-session answer
* `routes/forest1-rooms-mesh.json`, `routes/forest2-rooms-mesh.json`
