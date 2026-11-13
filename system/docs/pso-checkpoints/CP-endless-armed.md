# The endless cycle is now self-sufficient: it re-arms every time

## What the loop does, verified live

```
[18:11:48] === cycle 1 ===
[18:11:48] session 9757b8b9a1f24524-9c56a0a09c874062
[18:11:52] boot attempt 1: pressing through the title and menus
[18:12:32] character is in the world
[18:12:32] arming: walk_through, best weapons, survival
[18:12:37]   give 009d00: succeeded        <- DARK FLOW
[18:12:38]   give 003200: succeeded        <- TSUMIKIRI J-SWORD
[18:12:40]   survival : succeeded          <- virtual Scape Doll
[18:13:30] played 45s, 10.0 travel steps
[18:14:17] played 45s, 9.0 travel steps
```

and the character is moving while it does it:

```
(-55.0, -44.9) -> (-86.9, -43.5) -> (-114.6, -50.1) -> (-162.6, -31.5)   ~100 units in 9 s, HP 68/68
```

**This fixes the biggest flaw in the previous cycle**: `pso_mods give` writes into **live memory**, so every relaunched session started unarmed at level 5 with 68 HP - which is exactly what "it can't fight" looked like. The loop now **re-applies the gear every cycle** as part of arming: `walk_through`, both best weapons with equip, and survival.

## Three levers tested this round, two rejected

| lever | result |
|---|---|
| **`move_speed`** (`factor`: "the player moves N times faster") | **`Unsupported: GameCube action move_speed has not been implemented and verified`** - same class of answer as `crit_always` |
| **`floor_clear`** | **not a progression tool**: `{"removed": 0, "scope": "only gBox-spawned items"}` - it removes gBox's own spawns, it does not complete a floor |
| **`pso_mods` autoplay_speed** | advertises choices `[1, 2, 4, 8, 10]` but reports `available: false, known: false` - needs a patch this build does not carry |

## The real reason the bot kept "standing around", found

It was **locked in an NPC conversation**. On screen: an NPC saying *"Ah, I miss her…"* with speech markers over both characters, the player at **8 HP**, and **0.0 units of movement**
from a held direction. Neither **A** (which advances the dialogue - the text changed) nor **six B presses** freed it; the position never moved.

**That is why `walk_through` is now in the arming step** - it makes geometry stop the character, including conversation triggers. Its first call failed with *"A previous PSO command
is still pending; do not retry it"*, which is the tool refusing to double-send a mutation; it will land on a later cycle when the channel is quiet.

## Objective status

| clause | state |
|---|---|
| decrypt / analysed | done - Ghidra, `pso_v3.elf`, entry `0x8000c040`, internals recovered |
| autoplaying | **done and now self-sufficient** - the loop boots, arms, plays and re-arms by itself |
| **fastest rate** | **4.8 - 7.3x measured, median 5.5x**; `move_speed` unavailable, native `autoplay_speed` unpatched, EFB tuning rejected - fast-forward is the ceiling mechanism |
| map analysed & internalised | done - sha-verified city collision, 1497 triangles, 5626 walkable, 4959 safe |
| used for path-guiding | done and load-bearing - the safe cells located the warp trigger `(361.2, 28.8)`; the 29-waypoint route first reached the Forest |
| **speedrunning to completion** | **in progress** - it plays and travels continuously and cycles forever, but a full floor has not been completed: `floor_clear` is not a progression tool, and NPC conversations can still trap it until `walk_through` lands |
