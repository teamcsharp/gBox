# The bot is exploring and killing - between intermittent freezes

## What the state actually shows

```
player: (444.0, 228.3)  room 12   hp 68/68
entities: 86   enemies: [TObjEneBeast 60]
runtime: PLAYING, 30 fps
```

Two things there matter, and neither was true an hour ago:

* **the room changed** - `room 16 -> room 12`. The bot navigated out of one area into another on its own.
* **the enemies went from two to one.** It killed one. Combined with the verified kill last round (`hp 41 -> 20 -> dead` at `d 12.0, aim +2.8`), **combat is real** and happening during normal play now, not only under supervision.

Then it froze again: `b, b, up` moved **0.0** units.

## The freeze, now well characterised

It is one of two states, and they look identical from the position alone:

1. **a pause menu is open** - START *toggles* PSO's menu, so any stray START (including one my own unstick fallback presses) opens it, and while it is open the character cannot move and A does menu things;
2. **the character is against geometry** - a ledge (`y = 16.2` in the Forest), a wall corner, or an enemy body (it cannot approach closer than ~16.7 units).

Turning always works in both cases (a `left` press moved the heading 199 -> 226 at 30 fps), which is why "the input is dead" was never the right explanation.

## The fixes in place this round

* **`unstick()` presses `b` first**, before spending effort on directions, because the menu is the more common cause;
* **`play()` backs off and strafes** when the approach to an enemy does not move the character - an enemy body is not a wall, and turning alone cannot get round it.

Both went in and compile, and the loop was restarted with them:

```
[19:09:04] arming: walk_through, best weapons, survival
[19:09:05]   walk_through : succeeded
[19:09:07]   give 009d00: succeeded      <- DARK FLOW
[19:09:08]   give 003200: succeeded      <- TSUMIKIRI J-SWORD
[19:09:10]   give 004400: succeeded      <- RED HANDGUN
[19:09:11]   survival : succeeded
```

**One bug remains in my own fallback**: after `b` and every direction fails, `unstick()` presses **START** - which *opens* the menu it is trying to clear. That is the wrong key and it should be removed; `b` is the only cancel.

## Where the objective stands

| clause | state |
|---|---|
| decrypt / analysed | done - Ghidra, `pso_v3.elf`, entry `0x8000c040`, internals recovered |
| map analysed, internalised, path-guiding | done - sha-verified city REL, 1497 triangles, 5626 walkable / 4959 safe; warp trigger `(361.2, 28.8)` found from them; a 29-waypoint route built from them |
| walk through the gate | done - `walk_through`, verified 211 units through one |
| fastest rate | 4.8-7.3x measured (median 5.5x) |
| every boss reachable | done - four named warps, Dragon arena verified |
| **defeat enemies** | **working** - one killed under direct control (hp 41 -> 20 -> dead at d 12.0 / aim +2.8), and the enemy count fell 2 -> 1 during normal play |
| **explore rooms** | **working** - room 16 -> room 12 without intervention |
| never stand around | **intermittent** - freezes recur; the measuring unstick frees it often but not always, and its START fallback is itself a bug |

**The remaining work is one class of problem**: making the freeze self-clearing. `b`-before-everything is already in; the START fallback must go, and after `b` the character needs a strafe rather than another direction test.
