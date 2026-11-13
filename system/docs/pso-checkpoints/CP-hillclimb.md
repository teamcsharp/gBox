# Hill-climbing on distance: steering that works, and a second kill

## Why the heading had to go

Five controllers were built around `heading_deg` and all of them failed the same way - the readings did not match the presses. Measured on a calm field with the pad neutral:

```
left  0.15s: heading 55.8  -> 185.4  delta +129.6
left  0.30s: heading 185.4 -> 206.9  delta  +21.5
left  0.50s: heading 206.9 -> 206.9  delta   +0.0
right 0.15s: heading 206.9 -> 351.9  delta +145.0     <- wrong sign entirely
right 0.30s: heading 351.9 -> 256.6  delta  -95.3
```

**Same direction, wildly different results, and `right` sometimes increases the heading.** Whatever that field contains, it is not a heading a servo loop can track.

## What replaced it: control by evidence

Hill-climb on **distance** - the one unambiguous quantity:

1. nearest enemy, note the distance;
2. turn one way, step forward;
3. re-measure: **if closer, keep that side; if not, flip.**

No heading, no assumption about facing. **And it converges**:

```
 24: TObjEneBeast hp 60 d 12.1 side -1
 48: TObjEneBeast hp 60 d 12.0 side -1
...
swings: 110 | remaining: [('TObjEneBeast', 60)]
```

Started at **210 units**, closed to **12.0**, and when the swing threshold was raised to 15.5 (the enemy's body blocks closer than ~16.7) it **killed one**: the room went from
`[Beast 60, Beast 60]` to `[Beast 60]`.

**That is the second verified kill of the session, and the first a controller can reproduce** - the first was hand-driven.

## Installed in the loop, verified clean

```
[20:01:26] arming: walk_through, best weapons, survival
[20:01:28]   walk_through : succeeded
[20:01:29]   give 009d00: succeeded     <- DARK FLOW
[20:01:31]   give 003200: succeeded     <- TSUMIKIRI J-SWORD
[20:01:32]   give 004400: succeeded     <- RED HANDGUN
[20:01:34]   survival : succeeded
[20:01:44] unstick: up freed it (1.0 units)
[20:01:59] unstick: left freed it (83.5 units)
[20:02:20] played 45s, 4.0 travel steps
[20:02:35] unstick: left freed it (5.0 units)
```

and no stderr. `play()` now swings inside 15.5 units with `b` then `a`, and otherwise hill-climbs.

## Two mistakes made and corrected while installing it

* the first patch referenced `enemy_count_before` which was never defined - a `NameError` waiting at runtime. It was removed rather than papered over: the kill counter was cosmetic, and an
  enemy leaving the list is the real evidence.
* an intermediate insert landed at the wrong indentation and broke the file with an `IndentationError`; caught by compiling before every launch, not by running it.

## Where the objective stands

| clause | state |
|---|---|
| decrypt / analysed | done - Ghidra, `pso_v3.elf`, entry `0x8000c040`, internals recovered |
| map analysed, internalised, path-guiding | done - sha-verified REL -> 1497 triangles, 5626 walkable / 4959 safe; the warp trigger and the 29-waypoint route both came from it |
| walk through the gate | done - 211 units through one, verified |
| fastest rate | 4.8-7.3x measured (median 5.5x) |
| every boss reachable | done - four named warps; arenas recognised as destinations |
| **defeat enemies** | **reproducible now** - hill-climb closes to 12-15 units and swings; two kills verified |
| explore rooms | done - rooms 7, 10, 11, 15, 16 crossed unaided |
| never stand around | done - continuous travel, unstick freeing it repeatedly |
| speedrun a level to completion | still blocked on character power - a boss is 1300 HP with knockback against 68 max HP, and `stat` ops are refused |
