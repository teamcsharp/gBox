# Round 246: clicking a room now shows what is in it, and the map draws every placed object

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
PSO not running (fifteenth round).

## What the viewer does now

* **draws every placed set object** per floor, coloured by kind: sensors grey, rocks dark grey, symbol-chat collision violet, everything else
  blue - 150 markers on Forest 1, 196 on Forest 2;
* **on a click**, finds the room under the cursor (nearest room cell within 25 units) and writes its contents into the side panel:

```
room 6 (438 cells, centre 475.8,503.1): TOSensorAncient01 x29, TObjEnvSoundEx x12, TORockCaveBL03 x10, ...
```

  or `no placed objects` for an empty room, or `-` for a click outside every room;
* the existing behaviours are untouched: click still sends the bot to that point, shift+click still targets an enemy, the floor selector still
  switches between Forest 1 and Forest 2.

The per-room object counts are computed **once when a floor loads** (`loadObjects` assigns each object to its nearest room and caches the
grouping), so a click is a map lookup rather than 150 x 1000 distance tests.

## Verified

```
/api/objects?floor=1  150 objects (map_forest01d.dat)
/api/objects?floor=2  196 objects (map_forest02d.dat)
page 200, 6729 bytes, contains roominfo, loadObjects, roomObjects
```

## Why this is the editor's next real step

The operator's stated shape was: top-down map first, then everything else as a layer on it. That map now carries **three layers** - rooms,
doorways, and the placed objects - and the interaction that an editor needs first: *select a room and see what it already contains* before
placing anything.

What remains for a working editor is the **write** side: choosing a piece, choosing a room, and emitting a modified set file. The PM's CP11
branch has an endpoint for that (`POST /api/pso/editor/build`) but it is unmerged, so I am not going to duplicate it here.

## Files

* `map_viewer.py` - object drawing, `loadObjects`, room-contents panel
