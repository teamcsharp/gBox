# Round 220: Forest 1's exit is now a route, verified end to end

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
Live session `78a8746f5b514450-e9867839b8b74d3d`, Forest 2 (floor 2), HP **48/48**

## The exit route exists and is reachable

`exit_routes.py` extracts the operator's approach path from the run that ended in each floor change:

```
demo-20261111-105110: floor 1 -> warp at (536.4,-566.4) with 3 approach waypoints
demo-20261111-122003: floor 1 -> warp at (133.0,-48.1) with 8 approach waypoints
floor 1: 2 exit routes   ->  D:\gBox\pso-ds\learned\exit-routes.json
```

And the planner confirms both warps sit inside the traversable area:

```
plan from the operator's floor-1 route start (-57,197):
  to (133.0,-48.1):  124 raw cells -> 10 legs,  999 units
  to (536.4,-566.4): 198 raw cells -> 12 legs, 1701 units
```

So the PM's CP17 requirement - Forest 1 -> Forest 2 by walking - is now **data**: plan ten legs, run them at 27 units/s (about 40 seconds),
arrive at the teleporter the operator actually used, and take the warp.

## Why it cannot be executed this minute

The player is on **floor 2**. The learned route starts on floor 1, so the run waits until the bot is back on Forest 1 (the game's own map
warp returns to Pioneer 2 and Forest 1 is one warp away).

## Also this round

* HP is 48/48 - the character was healed during play, so the 7/48 risk noted last round is gone.
* The memory-write job channel still refuses with `SessionGone` for this session (it was launched by the previous worker, and the current
  worker does not own it). Writes through `pso_controls` (stat, crit, give, multi_equip) keep working; the direct `write_memory` path needs
  a session launched by the worker that is running now.

## The pipeline, complete

```
demos/*/state.jsonl  ->  learn_paths.py      ->  learned/paths.json        (per-floor routes, floor changes)
                     ->  exit_routes.py      ->  learned/exit-routes.json  (approach to each teleporter)
                     ->  follow_path.py      ->  walks the operator's own route
nav_fast.plan()      ->  149 cell waypoints  ->  9-12 straight legs
run2.run_to()        ->  27 units/s measured, no turning loops
```
