# Round 219: the operator's demonstrations now yield routes AND the teleporter coordinates

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
Live session `78a8746f5b514450-e9867839b8b74d3d`, **Forest 2** (floor 2), player at (66,449)

## What the recorded play contains

`learn_paths.py` reads every `demos/*/state.jsonl` and emits a polyline per floor plus every floor change:

```
floor 1: 5 demonstrated runs, 19,899 units, 324 waypoints
floor 2: 3 demonstrated runs, 12,126 units, 166 waypoints
floor changes (teleporters taken):
  demo-20261111-105110: floor 1 -> 2 at (536.4, -566.4)
  demo-20261111-122003: floor 1 -> 2 at (133.0, -48.1)
```

**Two Forest 1 -> Forest 2 transitions, with their exact coordinates.** The teleporter the bot has been hunting all session was in the
operator's own play the whole time - the bot just had not mined it.

That directly addresses the PM's CP17 ("Forest 1 -> Forest 2 by walking"): the destination is now a coordinate, not a search. The bot can
walk to `(133, -48)` and take the warp.

## The follower

`follow_path.py` takes the longest demonstrated run for the current floor and enters it at the nearest waypoint, then drives it with the
fast runner:

```
python follow_path.py --show
floor 2: following demo-20261111-122003 (7332 units, 122 waypoints), entering at waypoint 121
```

The catch is visible in that line: on floor 2 the run **ends where the player already stands** (waypoint 121 of 122), because the recording
stopped there. So there is nothing ahead to follow on this floor yet - the demonstration needs to continue (more play, or the route loop
restarted) before the follower has anything to walk.

## What this changes

* **Forest 1's exit is known**: `(133, -48)` or `(536, -566)`. No more searching.
* Routes are now **data from the operator**, not my planning: 324 waypoints on floor 1, 166 on floor 2, all of it their actual paths.
* The next recording session should capture the rest of Forest 2, so the same pipeline produces a route to Forest 2's exit.

## Files

* `learn_paths.py` - sessions -> per-floor polylines + floor-change events (`learned/paths.json`)
* `follow_path.py` - follow the demonstrated route (`--show` to inspect without input)
* `run2.py` - the runner used to walk the waypoints (cheap calibration per stride, 27 units/s measured last round)
