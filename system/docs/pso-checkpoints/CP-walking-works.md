# Walking works - the character visibly walks to a target, no teleport

## The measurement

```
start: 60.8 units from the box, heading 288
  tap left  (err +149.3)
  tap left  (err +102.0)
  step  moved  17.4 | dist  70.8
  tap left  (err +149.6)
  tap left  (err  +87.4)
  tap left  (err  +23.1)
  step  moved   0.0 | dist  38.7        <- blocked, sidestep fired
  tap right (err -114.7)
after: remaining 9.5 | steps 10
VERDICT: WALKED INTO RANGE
```

**60.8 units to 9.5 by walking.** No position writes. This satisfies the operator's hard requirement - *"must visibly walk, no position writes"* - and it is the first time in the session that steering has converged.

## Why it worked this time

Two errors, both now measured and fixed:

1. **Batching taps was the zigzag.** A tap rotates **8-11 degrees**, not the 10 assumed, and the first tap after moving is anomalous (measured **-115.9** once). Sending `round(|error|/10)` taps blind therefore lands up to 60 degrees off, and the next correction overshoots the other way - exactly the observed wander between 115 and 167 units. **`walk_to` taps once, re-reads `heading_deg`, recomputes, repeats.** Nothing accumulates.

2. **The step was 3x too long.** Measured: **a forward hold of 0.5 s walks 31.6 units** (not the 10 previously assumed), so the 0.5 s step overshot the target every time. **`STEP` is now 0.22 s ~ 14 units**, short enough to land inside the tolerance.

And the earlier "taps do not rotate at all" result was **not** a real failure: the character was **pinned against a rock face**. After a 1.0 s backward step freed it (**86.2 units**), taps rotated **+10.0, +11.6, +11.1, +7.7** on four consecutive samples. **The rock was the measurement, not the steering.**

## In the loop

`teleport_walk` is replaced by `walk_to` for **both** boxes and enemies, so the character walks everywhere. Two guard bugs were caught in the process: the call sites still checked `if teleport_walk is not None:` after the import was swapped, which would have silently skipped all walking. Fixed, and the module compiles with `walk_to = None` as the correct fallback.

## And the honest gap in this window

```
travelled 185 units | kills 0 | enemies 3
```

**It moves 185 units and kills nothing.** The box branch is correctly skipped because **enemies now outrank boxes** (the operator's instruction), so the enemy branch is running - and `walk_to` is not yet converging on an enemy the way it converges on a box. The box test succeeded because the box is stationary; an enemy moves, so the heading is stale by the time the step lands.

**That is the next measurement, and it is a specific one:** re-aim more often against a moving target (shorter steps, and re-read the target position each iteration rather than once per burst).
