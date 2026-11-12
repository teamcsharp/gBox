# The speed figure, measured properly: 5.5x median, 7.3x peak - not 10x

## What a single sample said, and what four windows say

One 12-second sample read **342.4 fps (11.34x)** - which looked like the target had been reached. A 30-second window then read **145.1 fps (4.8x)**, and four 15-second windows
settled it:

| window | frames | seconds | fps | ratio |
|---|---|---|---|---|
| 1 | 3426 | 15.5 | **220.8** | **7.31x** |
| 2 | 2318 | 15.0 | 154.4 | 5.11x |
| 3 | 2203 | 15.1 | 145.8 | 4.83x |
| 4 | 2616 | 15.6 | 167.3 | 5.54x |
| **median** | | | **167.3** | **5.54x** |

**The 342 fps was a transient** - a load or frame-skip burst - not sustained speed. **The honest figure is a median of 5.5x, peaking at 7.3x.**

## Why the samples disagree, and why that matters

PSO's rate is not constant: it swings between roughly **146 and 221 fps** in the same room within a minute, because the guest work per frame changes with what is on screen
(effects, enemies, doors). A single sample of an unstable quantity is worthless; that is the lesson from reading 11.34x and 4.8x twenty seconds apart.

## The CPU, during the fast-forward

```
Dolphin PercentProcessorTime:  113, 153, 113, 134, 139, 113   (~1.1 - 1.5 of 16 cores)
total CPU:                     43, 47, 50, 50, 53, 57 %
Dolphin settings present:      DSPThread = True               (everything else default)
GFX.ini:                       empty -> Dolphin defaults
```

**No single core is pegged** and the machine is half idle, so the limit is not raw CPU occupancy either - it is the **serial dependency chain inside the emulator**: frame
time is bounded by the longest single-threaded step, and adding cores cannot shorten it. That is why the EFB experiment could only make things worse, and why no setting has
moved this number.

## The objective, honestly

| clause | state | evidence |
|---|---|---|
| decrypt PSO | **done** | Ghidra on `pso_v3.elf`, 149 s, entry `0x8000c040`, `MESETA`/`adx_logo`/`sofdec_logo` recovered |
| bot autoplaying | **done** | `running: true`, 50-208 steps; 499 units/24 s in the Forest |
| map analysed & internalised | **done** | `map_city00_00c.rel` sha-verified -> 1497 triangles, 5626 walkable, 4959 safe cells |
| used for path-guiding | **done** | the safe cells found the warp trigger `(361.2, 28.8)`; the 29-waypoint route first reached the Forest |
| speedrunning at 10x | **not met** | **5.5x median, 7.3x peak**, area-dependent (Forest 4.2x, cave 4.8-7.3x) |

**Four of five clauses are done and demonstrated. The fifth is 55% of the way and bounded by Dolphin's serial emulation on this CPU**, not by anything the app can set: the
frame limiter is uncapped, the EFB lever was tested and rejected, and the core that matters is not saturated, which leaves only "make the emulator's critical path
shorter", i.e. a different CPU or a different emulator.

## What is running

The bot is in a cave field (130 entities, 7 gates) at fast-forward, moving **782 units per 33 s** and crossing rooms 1 and 111, having reached a cave gate with its sabre
drawn.
