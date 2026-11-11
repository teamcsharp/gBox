# From collision route to walking: the calibrated walker closes the loop

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110    Commits: this branch
Goal: 2

`gbox/pso_kbwalk.py` (the calibrated keyboard walker) is the right control half for `pso_walk.path`: it calibrates by holding each key
and measuring the world delta, then repeatedly picks the key that best reduces the remaining distance. Wired to the proven input path
(`win_send_keys` with the gBox window focused) and the actor's RAM position, it **walks the extracted Forest 1 route**.

A clean calibration on open ground:

```
up    (-1.00,  0.07)  35.7 units/s
down  ( 1.00, -0.08)  33.6
left  ( 0.11,  0.99)  36.3
right (-0.20, -0.98)  30.8
```

A proper orthogonal frame with exact opposites - and note it is **rotated** relative to the naive assumption (up is roughly -x, left is
roughly +z), which is why the earlier hand-rolled walker pushed the character the wrong way.

Then `pso_kbwalk.walk_path` over the 27-waypoint route:

```
leg 1  -> (-25, 65)   arrived
...
leg 10 -> (-115, 65) arrived
leg 11 -> (-125, 65) gave up after 40 steps
end (-116.3, 88.2), remaining 120.2
```

**Ten consecutive waypoints arrived**, roughly 92 units of collision-aware walking, each leg confirmed by reading the position back.

## Three traps, each found by a failed run

1. **A single key name, not a list.** `pso_kbwalk._measure` calls `hold(key, seconds)` with a string; a `hold` that does `list(keys)`
   turns `"up"` into `['u', 'p']`, presses nothing real, measures zero movement and the walker reports "no key points at the target".
   The callback must wrap a string.
2. **A second key driver poisons the measurement.** The background walk driver pressed keys during calibration, producing nonsense
   vectors (`left` and `right` both +x). Navigation needs exclusive input.
3. **Calibrate on open ground.** Standing against a bank gave `up = (0, 0)` - the direction was simply blocked - and a zero vector is
   indistinguishable from a broken binding until you look at the screen.

## Still open

Leg 11 gives up: the straight-line route segment is not reachable in practice (drifting to z=88 while the waypoint is z=65). The
next step is to detect the stall (position not improving) and re-route from the new position rather than holding a key for 40 steps -
`pso_walk.path` from the current position, exactly as the walker already does per leg, with a shorter re-plan interval.
