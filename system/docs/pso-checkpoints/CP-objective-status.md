# Where the objective actually stands, verified

## The run, measured

```
moved 409 units | rooms [8, 12] | hp 68/68
```

and the loop doing its job around it:

```
[23:09:33]   acted on TItemEquipBase (6.9 units) - reticle rule
[23:09:57] unstick: left freed it (60.1 units)
[23:10:21] unstick: left freed it (30.8 units)
[23:10:37] unstick: left freed it (18.7 units)
[23:10:59] played 120s, 21.0 travel steps
[23:11:29]   operator is playing - bot standing down
[23:12:16]   doors: floor 1 already open
```

**409 units of travel across two rooms with full HP**, the reticle rule acting, doors open in RAM, and the bot yielding to the operator whenever the pad moves.

## Clause by clause

| objective clause | state | evidence |
|---|---|---|
| **decompile and analyze PSO** | **done** | Ghidra: `pso_v3.elf`, **25,980 functions**, entry `0x8000c040`, largest function 10,784 bytes at `0x803b5eac` |
| **map analysed, scanned, internalised** | **done** | disc `map_city00_00c.rel` (sha verified) -> **1497 triangles, 5626 walkable / 4959 safe cells**; plus a learned-area index from the live map API |
| **used for path-guiding** | **done, load-bearing** | the 29-waypoint route reached the Forest; the safe-cell search found the warp trigger `(361.2, 28.8)`; every gate/door target now comes from the entity table |
| **fastest rate** | **done, measured** | fast-forward **median 5.54x (167.3 fps), peak 7.31x**; `move_speed` unimplemented, native autoplay-speed `available:false`, EFB tuning made it worse and was reverted |
| **autoplay without stopping** | **done** | launches, boots, arms, warps to a field, explores, fights, breaks boxes, presses switches, unlocks doors, frees itself when wedged, relaunches when the session dies - and stands down for the operator |
| **complete the game on Ultimate sequentially** | **not achievable at the current character** | Ultimate enemies are **1556 HP** against **68**; measured 12 swings at 8 units with zero damage taken off the beast and the character thrown 80 units between swings. Auto-difficulty now plays Normal until `hp_max >= 250` |

## The honest headline

**The machine works. The character is the wall.**

Everything asked for on the tooling side is in place and evidenced: the decompilation, the internalised map used to steer, the measured speed, the self-sustaining autoplay, the operator's controller override, the note channel, the reticle rule, boxes/traps, door keys, RAM door unlocking, rares, and the unstuck.

**What is not achieved is finishing the game**, and the reason is arithmetic, not code: **level 5 with 68 HP against content gated at level 80**. The bot kills what Normal sends at it (a verified `HIT: 30 -> 1`), gains what it can, and will switch itself to Ultimate when `hp_max` reaches 250. **Getting from 68 HP to several hundred is a long grind, and the loop is the thing that grinds it.**

## Two things I would fix next, in order

1. **The level-exit warp has never been reached in a window I watched.** The recognition is in (`Warp` classes, first priority, walks in and confirms by room change) but no warp entity has appeared in any sampled room - Forest exits may be gates rather than warps, which would make the door path the real progression route and worth verifying.
2. **The aggro switch** still needs the Ghidra read of the enemy AI. The entity struct has no field that flips on aggro (`+0x38/0x44/0x50` positions, `+0x60` counter, nothing else changed), and the `0x7` at the linked struct is constant at 982 units distance, so the AI controller itself has to be found in the binary.
