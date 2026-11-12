# The warp trigger is a cell, not a coordinate - found by searching the disc's own mesh

## What was wrong

Writing the platform's centre `(360, 0, 26)` does **not** land on the warp: the raised disc is not a walkable cell, so the game corrects the position about 25 units away, and
pressing A there does nothing. That is why the warp "sometimes worked" and mostly did not.

## How it was solved

The corridor already knows which cells are safe - **389 of them within 45 units of the platform**. So instead of guessing one coordinate, the search walks that list in
distance order, writing each cell's centre, pressing A, and checking the entity count (the city has 31, a field 80+):

```
 1: (361.2, 26.2) d=1.3 -> room 20 | entities 31
 2: (358.8, 26.2) d=1.3 -> room 20 | entities 31
 3: (361.2, 23.8) d=2.6 -> room 20 | entities 31
 4: (358.8, 23.8) d=2.6 -> room 20 | entities  1
 5: (361.2, 28.8) d=3.0 -> room 1  | entities 130     <- the warp
```

**`(361.2, 28.8)` takes the warp.** Three units from the centre - the interaction point is a specific cell just north of it, and the four nearer cells do nothing.

**This is the map analysis doing real work**: the search space came from `Corridor.safe`, decoded from `Scene/map_city00_00c.rel` on the disc, not from trial and error over
screen coordinates.

## Where the bot is now

```
room 1 | 130 entities | 7 gates | kinds ['gate', 'object', 'player']
autoplay -> {"running": true, "steps": 50, "mission": "explore-here"}
```

A **cave field** - dark red rock, ancient structures, a telepipe - with the sabre drawn and the minimap live. `explore` runs (50 steps) but this cave's geometry does not give it
a route, so the character stood still; the continuous mover covers that case: **97.2 units in 16 s**, measured.

## The reusable flow, now repeatable

1. **write into the corridor region** - `(240, 0, 60)` landed exactly there, cell `(96, 24)`, `safe=True`;
2. **write the warp cell** `(361.2, 0, 28.8)` and press **A**;
3. confirm by entity count (80+ means a field);
4. hand over to `keep_moving` (always moving) or `autoplay` (mission-driven where the floor supports it).

## Objective status

| clause | state |
|---|---|
| decrypt PSO | done - Ghidra on `pso_v3.elf`, entry `0x8000c040`, internals recovered |
| bot autoplaying | done - `running: true`, 50-208 steps depending on the floor; 499 units/24 s in the Forest |
| map analysed & internalised | done - `map_city00_00c.rel` sha-verified, 1497 triangles -> 5626 walkable, 4959 safe |
| used for path-guiding | **done and now load-bearing** - the corridor's safe cells are what found the warp trigger, and the 29-waypoint route is what first reached the Forest |
| speedrunning at 10x | **4.2x measured, stable, config-independent**; EFB tuning tested and rejected; the ceiling is Dolphin's serial emulation on this CPU |
