# Round 218: 8x faster - measured 27 units/s against 3.4

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
Live session `78a8746f5b514450-e9867839b8b74d3d`, Forest 1

## The two fixes that produced the speedup

1. **The operator lock was eating the bot's own strides** (round 217). The declared action window ended before the character finished
   sliding to a stop, so the deceleration was read as operator motion and the bot was shut down for 3 s after most steps. With the window
   including deceleration and the grace at 0.55 s, all four directions execute again.
2. **No turning at all.** Turn-based drivers spent their time turning: each turn tap swung the heading tens of degrees (measured log:
   `error was +109 deg ... heading -76`, then `+75`, `+49`, then `-140`, `-129` ...), so they never converged. The runner instead picks the
   key whose measured vector points at the target and **holds it for up to 2.5 s**, refreshing that key's vector from the stride itself.

## Measured throughput

```
frozen-table straight run:  552 units in 20.3 s  = 27.2 units/s
scaled-hold run:            1105 units in 40.9 s = 27.0 units/s
previous turn-based driver:                    3.4 units/s
character's own top speed:                    45 units/s (72 units in a 1.6 s hold)
```

**27 units/s sustained is 8x the previous driver and 60% of the character's own top speed.** At that rate a 1230-unit route across Forest 1
takes about **45 seconds** instead of the five-plus minutes it was taking.

## What is still wrong

The last approaches can shuttle: the run ends `left 2.5s: 74 -> 67`, `right 2.5s: 67 -> 74` ... because the test target sat **behind a
wall** - the chosen key runs into it, so the two nearly-opposite keys bounce the character back and forth. The route planner's legs avoid
this by construction (each leg is a clear straight line), so the runner must walk the **planned waypoints** rather than being pointed at an
arbitrary coordinate. That is the next change and it is small.

## Files

* `run.py` - the runner: calibrate once, hold the best key up to 2.5 s, refresh that vector for free, re-calibrate when the alignment
  drops or a stride is blocked, diagonal escape when it cannot move at all
* `nav_fast.py` - free-cell routing plus string-pulling (149 -> 9 legs)
* `pso_input.py`, `pso_operator2.py` - the fixed action window and grace
* `drive_fast.py`, `drive_route.py` - the earlier turn-based drivers, kept for comparison
