# Round 222: Forest 2's object layer censused - the exit is not in the set data either

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
Live session `78a8746f5b514450-e9867839b8b74d3d`, Forest 2, player (-475,337), HP 20/48

## The census

Decoding every record of Forest 2's two set files with the verified mapping (class id >> 8, little-endian floats at 0x10/0x14/0x18):

```
forest02d : 5 classes
  class 1024  x77   first at ( -54,  90, -36)
  class 256   x68   first at (-696,  77, -67)     <- TORockCaveBL02 (rocks)
  class 5888  x40   first at ( 301,  20, 716)     <- TOSymbolchatColli
  class 1792  x7    first at (-473,  18, 381)
  class 1536  x4    first at (-765,  24,-544)

forest02ad: the same five plus
  class 7680  x1    first at ( 900, 283, 334)     <- one unique object at the map's edge
```

**No warp class and no switch class.** Forest 2's set files describe rocks, collision props and sound objects only. The one unique object
(class 7680, at x=900 which is outside the playable bounds) is a boundary marker, not a teleporter.

So the conclusion from Forest 1 holds on Forest 2 as well: **the area teleporter only exists in the entity table when its room is
streamed**. There is no static coordinate for it in the extracted data, which is exactly why the operator's own demonstration was the thing
that revealed Forest 1's two exits at (133,-48) and (536,-566).

## What the bot has for Forest 2 right now

* collision: `map_forest02c.rel`, **6,145 free cells**, planner verified (9-leg routes of 1,358-1,411 units, under a minute at 27 u/s);
* set objects: 5-6 classes, with positions (useful for obstacle context, no exits);
* the demonstrated play: a 7,332-unit run that **ends where the player stands**, so no route ahead yet.

## Next

The same pipeline that solved Forest 1 needs the same input: **the operator's play on Forest 2**, recorded by the already-running recorder,
then `learn_paths.py` + `exit_routes.py` turn it into the route to the exit. Nothing else in the codebase is blocking that.

State: the operator was on the controller throughout this round, so no input was sent.
