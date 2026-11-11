# Round 245: room contents - which set objects stand in which room, on both floors

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
PSO not running (fourteenth round).

## The data the editor needs next

After the room map, the editor needs "what is in this room". Three pieces now exist:

1. **objects per floor** - `set-objects-floors.json`: Forest 1's `map_forest01d.dat` decodes **150 objects**, Forest 2's
   `map_forest02d.dat` **196**, each with class and position (sensors, rocks, sound sources, symbol-chat collision);
2. **endpoint** - `/api/objects?floor=N` verified serving `{set, objects}` for both floors;
3. **assignment** - `room_contents.py` puts every object in the room whose footprint is nearest, recording the distance, and writes
   `routes/room-contents.json`.

## What the assignment shows

```
floor 1: 150 objects
  room 0  1625 cells (237,-287): 12   TORockCaveBL03 x5, TOSensorAncient01 x3, TObjEnvSoundGlobal x3
  room 5   427 cells (-57,  85): 20   TORockCaveBL03 x11, TOSensorAncient01 x5
  room 6   438 cells (476, 503): 59   TOSensorAncient01 x29, TObjEnvSoundEx x12, TORockCaveBL03 x10
  ...
floor 2: 196 objects
  room 1   766 cells (443,  63): 46   TOSensorAncient01 x19, TORockCaveBL03 x17, TOSymbolchatColli x10
  room 4   559 cells (258, 437): 54   TOSensorAncient01 x31, TOSymbolchatColli x13
  ...
```

**80 of Forest 1's 150 and 88 of Forest 2's 196 lie outside every room** (or more than 60 units from one). That is not a bug: the set files
place **sensor volumes and sound emitters in the void** - `TOSensorAncient01` first appears at `(1082,1030)` on Forest 1, far outside the
playable footprint. The distance is stored per object, so terrain placements (rocks, symbol-chat collision) are cleanly separated from volume
triggers by looking at it.

## What this enables

* the viewer can draw object markers per floor and, on a room click, list that room's contents;
* an editor can select a room and see everything it already contains before adding a piece;
* the outside-room objects are a **candidate list of trigger volumes** - exactly the sort of thing a level expansion needs to know about
  before moving geometry.

## Files

* `set_objects_floors.py` -> `routes/set-objects-floors.json`
* `room_contents.py` -> `routes/room-contents.json`
* `map_viewer.py` - `/api/objects?floor=N`
