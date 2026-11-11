# Round 209: empirical steering proves itself; the map bot walks at your click

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
Live session `78a8746f5b514450-e9867839b8b74d3d`, Forest 1, `supported: true`

## The steering controller - proved

`steer.py` measures what each of the four directions actually does (0.3 s hold) immediately before choosing, then strides with the key
whose measured displacement points closest at the target, with the stride shrinking as the gap closes. A calibration table cannot go
stale this way because the measurement is taken in the same breath as the stride.

**Measured arrival**: target `(-157,104)`-style leg from `(-83,189)` to `(-115,70)`:

```
now: (-83, 189)
step 0: 123 units, key=down align=0.96 moved=16
step 1:  93 units, key=down align=1.00 moved=16
step 2:  61 units, key=down align=0.83 moved=16
step 3:  34 units, key=left align=1.00 moved=16
step 4:  10 units, key=left align=0.68 moved=3
arrived=True steps=5 final=7.3
```

**123 units in 5 steps, arriving 7.3 units from the point.** That is the first walker this session that provably closes distance to a
chosen destination.

## What that fixed in the map bot

1. `pso_kbwalk.walk_path` is gone from the bot: it drifted (ordered to `(-40,240)` it walked away, distance 202 -> 235).
2. Flat-route waypoints are gone too: the graph places waypoints where the live area will not let the character walk - measured
   `waypoint (-95,75) not reached (65 units)` - so the bot orbited them. It now steers **straight at the clicked point**, because the
   controller walks in whatever direction it can actually move.
3. A stuck handler taps B (a menu or dialog freezes movement) and probes sideways when no direction moves.

## What the bot does now on a click

Observed order progress in the live log: `235 -> 98 units` and `54 -> 25 units` on the way to targets, i.e. it closes. It does not always
finish inside its 10-step budget: stalls ("no direction moves") and terrain still interrupt some approaches, and the log shows the
distance jumping back up when the controller picks a direction that curves away.

## Honest state of this capability

* **Single-leg steering to a reachable point: verified.** 123 units, arrived in 5 steps.
* **Click-to-command: works, not yet reliable.** The order is accepted, the character walks toward it and closes most of the gap, but the
  last 25-40 units sometimes fail with a stall or a wrong turn.
* The next improvement is to treat a stall as a re-plan (probe all four directions twice, then walk the best one for a full second)
  instead of retrying the same measurement, and to reject directions that increased the distance on the previous step.

## Services running

demo recorder (detached, writing `demos/demo-*`), operator lock, map viewer on **http://127.0.0.1:8801/**, map bot following clicks.
Final state: player around `(-122, 3)`, HP 40, TP max 999, 7 equipped items including 5 Sabers.
