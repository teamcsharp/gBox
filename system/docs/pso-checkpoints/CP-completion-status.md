# Where the "complete every level" work actually stands

## What is proven to work

| capability | evidence |
|---|---|
| **decrypted** | Ghidra analysed `pso_v3.elf` in 149 s, entry `0x8000c040`, real internals recovered (`MESETA`, `adx_logo`, `sofdec_logo`, `TAdDrawLineTask`) |
| **map analysed and internalised** | `Scene/map_city00_00c.rel` off the disc, sha256 verified, **1497 triangles -> 5626 walkable cells / 4959 safe** |
| **used for path-guiding, load-bearing** | the 29-waypoint route to the warp platform is how the bot first reached the Forest; a search of the safe cells found the warp trigger is the specific cell **(361.2, 28.8)** |
| **walk through the gate** | **`walk_through: True`**, and a held direction moved the character **211.3 units straight through a gate** |
| **best weapons** | DARK FLOW (`009d00`) and TSUMIKIRI J-SWORD (`003200`) given and equipped, each `{created: 1, equipped: true, verified: true}` |
| **cannot stay dead** | `survival` -> `{"permanent_scape": true, "verified": true}` |
| **explores and keeps moving** | 206.3 units over 30 s, sampled continuously |
| **the cycle sustains itself** | relaunches when the game is gone, boots to the world, re-arms (walk_through + both weapons + survival) every cycle, then plays |
| **speed** | **median 5.54x** (167.3 fps), peak 7.31x, area-dependent; `move_speed`, native `autoplay_speed` and EFB tuning all unavailable or harmful |

## What does not work, and it is the thing that matters

**The character freezes in place while enemies move around it.** Forty consecutive rounds:

```
TObjEneBeast hp 60  dist 188.2 ... 240.0     <- enemies moving
me (490.6, 380.7)                            <- identical to one decimal, every round
heading error -0.7 .. -12.8                  <- already facing the target
```

and **the enemy's HP never moves off 60**, so no hit lands.

**Why the hits never land** is at least partly explained: `always_hit` is enabled and its own scope says *"targets must still be in range and hittable"* - and the earlier fight log
showed the target at **226-275 units** while A was pressed. Melee reach is a few tens of units, so those swings were into empty air. `kill.py` was written to close that gap and
check range before swinging - but it cannot, because **the character will not move**.

**And movement is not uniformly broken**: the same input API moved it 211 units through a gate minutes earlier, and the exploration sample above covers 206 units. So the freeze
is **position- or state-dependent**, not a dead input path. That is the next thing to isolate: what is different about being at `(490.6, 380.7)` - a wall corner that
`walk_through` does not cover, a ledge, or an interaction lock of the same family as the NPC conversation that trapped it earlier (an NPC saying *"Ah, I miss her…"*, where
neither A nor six B presses freed it).

## Honest position against the request

You asked for a bot that **completes every level, defeats every enemy, explores every room and walks through every gate**. What exists today:

* **it moves, explores, and passes gates** - proven, measured;
* **it is armed with the two best HUmar weapons and revives on death** - proven;
* **it sustains itself indefinitely** - the cycle relaunches, boots, re-arms and plays;
* **it does not yet defeat enemies or complete a floor** - and the reason is now a specific, testable freeze rather than a vague "the bot is bad at combat".

The single next question is narrow and worth one round on its own: **why does the character stop accepting movement at some positions while enemies keep moving?** Answering that
unlocks combat (close to melee range), then gates that need kills, then floors, then the game.
