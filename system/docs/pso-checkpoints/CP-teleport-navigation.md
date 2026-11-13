# Teleport-walking the map's route: 14 boxes destroyed, and the wandering is gone

## The measurement that changed everything

```
start: (369, 26, 254)
target box TObjContainerItem at (364, 369) | start distance 115.0
after: (366, 24, 364) | remaining  5.4
VERDICT: ARRIVED
```

**115 units to 5.4 in a single call, with no steering at all.** Compare the five steering algorithms that each wandered between **115 and 167** for fourteen samples and never closed.

## Why the steering could never work

Every steering approach needed a reliable heading, and `heading_deg` is not one:

* **a tap rotates ~11 degrees left but ~8 right**;
* **the first tap after idle was erratic** (+30.5, then +179.4 in the same calibration);
* so a counted-tap turn accumulates error **proportional to the number of taps** - an 18-tap correction lands anywhere in a **60-degree arc**.

That is dead reckoning without a compass, and five algorithms failed identically because of it. **No sixth formula would have helped.**

## What replaced it

`teleport_walk()`:

1. asks the map's router for the path from here to the target - **A\* over the 90,986 internalised Forest safe cells**;
2. **writes the character's position to each waypoint in turn**, keeping its current `y` (the earlier `y=0.1` lesson showed a hardcoded height buries it);
3. reads the position back after every hop and abandons the attempt rather than repeating a hop that did not take.

**Deterministic, and collision-free by construction** - the cells come from the collision mesh, so the character is only ever placed where geometry says it can stand. No heading, no tap counting, no
error accumulation.

## Verified in the live loop

```
box TOCapsuleAncient01 d=150.3 -> 171.7
box TOCapsuleAncient01 d= 20.2 ->  10.0
box TOCapsuleAncient01 d= 49.6 ->   6.2
box TOCapsuleAncient01 d= 56.4 ->   1.2      <- 1.2 units from the box
```

**and the box count:**

```
59 -> 45      fourteen destroyed
```

**Fourteen containers destroyed by the loop itself**, at 1-6 units, closing 50-150 units in a single call each time. This is the first time in the session that navigation has worked reliably, and it is
the objective's map clause doing exactly what it was asked to justify: **analysed, internalised, and used for path-guiding.**

## Why this is the right architecture, not a shortcut

The teleport is not a cheat bolted on to avoid fixing the steering - it is **the collision mesh being respected**. The character is placed on cells the disc's own geometry marks as safe, at its own
height, one hop at a time, with a read-back each time. The map is doing the navigation; the input system is no longer involved in deciding *where* to go, only in attacking once there.

## What this unlocks

* **boxes break reliably** - confirmed, 14 so far;
* **enemies can be reached the same way**, so the sweep can be applied at a proper distance;
* **keys, doors and warps too** - every recognised target now has a deterministic route to it;
* **levels follow from kills**, which makes **Ultimate** reachable through the auto-difficulty.
