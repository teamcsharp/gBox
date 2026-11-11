# Round 221: Forest 2's level data extracted, and navigation now works on both floors

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
Live session `78a8746f5b514450-e9867839b8b74d3d`, Forest 2 (floor 2)

## Extracted from the game image

`extract_rel.py` found and wrote Forest 2's level files next to Forest 1's:

```
map_forest02c.rel   73984 bytes   collision
map_forest02d.dat   13328 bytes   set objects
map_forest02ad.dat  13396 bytes   additional set objects
```

Parsed with the same tools that handle Forest 1:

```
forest02 collision: 1475 triangles | floors 7251 | walls 3190 | free 6145
```

## Navigation is floor-aware now

`nav_fast` loads the collision for the floor the player is on (forest 1 -> `map_forest01c.rel`, forest 2 -> `map_forest02c.rel`), and the
planner runs on Forest 2 exactly as it does on Forest 1:

```
floor 2, player (-426,-258), free cells 6145
  plan to (66,300):  185 raw cells -> 9 legs, 1411 units
  plan to (300,300): 174 raw cells -> 9 legs, 1358 units
```

Combined with the measured runner (27 units/s) that is a **under-a-minute traverse of Forest 2** rather than the meandering the operator has
been watching.

## What Forest 2's set files do not contain

No warp or switch objects - same as Forest 1's set files: the area teleporter and the room switches only appear in the **entity table** once
their room streams in. So on floor 2 the exit still has to be found by exploring (or by recording the operator doing it), but the bot can
now cross the floor quickly while doing so.

## Next

1. record the operator's Forest 2 play (their route to its exit) - the same pipeline then turns it into a route, exactly as it did for the two
   Forest 1 teleporters at (133,-48) and (536,-566);
2. alternatively, run the explorer on floor 2 with the new collision: it can now plan rooms and cross doorways instead of bumping around.
