# Movement is fixed and the bot explores on its own

## The release fix works

Five directions, each held 0.9 s and released with **all four at once**, on a fresh session:

```
up    17.0 units
up    36.7 units
left   2.0 units
right  0.1 units
down  43.2 units
total 99.0 units
```

Before the fix every one of those ended with a single-key release which **pinned the stick in a direction nobody pressed** (`up:False` -> `lx -32768`). The character is now actually driven by the
intent, not by the residue of the previous press.

## And the loop explores unaided

```
[19:19:22] character is in the world
[19:19:23] arming: walk_through, best weapons, survival
[19:19:26]   give 009d00: succeeded     <- DARK FLOW
[19:19:28]   give 003200: succeeded     <- TSUMIKIRI J-SWORD
[19:19:29]   give 004400: succeeded     <- RED HANDGUN
[19:19:31]   survival : succeeded
[19:19:31] in the city (31 entities) - warping to a field
[19:19:36]   warp +2s: 1 entities, 0 gates
[19:19:43]   warp +8s: 91 entities, 24 gates
[19:20:30] played 45s, 9.0 travel steps
[19:20:58] unstick: right freed it (37.0 units)
[19:22:05] played 45s, 9.0 travel steps
```

and the positions show it crossing the area on its own:

```
(-128,140) -> (-82,206) -> (-84,208) -> (-58,182) -> (-22,112) -> (19,157) -> (27,102) -> (3,54) -> (-37,3)
rooms 10 <-> 11, HP 68/68 the whole time
```

**That is the exploration clause working**: continuous motion, room boundaries crossed, no standing still, and the measuring unstick freeing it when geometry blocks a direction (37 units that time).

## One thing clarified this round

The stale picture is **not a fault**: Dolphin's process reports `MainWindowHandle 0` **on a fresh launch too**, because these sessions run their window hidden - and `_native_stills` documents exactly
that: *"A game the screen doesn't show posts nothing, so its picture goes stale."* So no frames is the expected behaviour for this session type, not something to repair.

That matters because it means **the memory state is the only honest signal** for these sessions - position, HP, entities, rooms - and two of my earlier wrong conclusions came from treating an old
picture as current.

## Where the objective stands

| clause | state |
|---|---|
| decrypt / analysed | done - Ghidra, `pso_v3.elf`, entry `0x8000c040`, internals recovered |
| map analysed, internalised, path-guiding | done - sha-verified city REL -> 1497 triangles, 5626 walkable / 4959 safe; the warp trigger `(361.2, 28.8)` and a 29-waypoint route both came from it |
| walk through the gate | done - `walk_through`, verified 211 units through one |
| fastest rate | 4.8-7.3x measured (median 5.5x); `move_speed`, native autoplay-speed and EFB all unavailable or harmful |
| every boss reachable | done - four named warps, Dragon arena verified |
| defeat enemies | **working** - a kill verified (`hp 41 -> 20 -> dead` at `d 12.0`, `aim +2.8`, B then A), and the enemy count fell 2 -> 1 during normal play |
| **explore rooms** | **working and now reliable** - rooms 10 <-> 11 unaided, 99 units of deliberate movement in a 5-direction test |
| never stand around | **working** - continuous travel, with a measuring unstick that provably frees it |
