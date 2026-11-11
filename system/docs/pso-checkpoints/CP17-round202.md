# Round 202: the stall-triggered door press, and a spawn trap that stopped the run before it began

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110    Commits: this branch
Live: session `e731ee594dde4a89-cae9dad929a34d17`; character in Pioneer 2, randomizer at **38 cycles**

## The door handler was added as diagnosed

`cp17_final2.py` presses A at **any** `TObjDoor`/`TObjDoorKey` within 32 units (turn toward it with a short hold of the direction that
moves that way, A, push, require a >8-unit jump, tag it so it is not re-pressed), then continues the empirical stride walk to the key
door. That is exactly the missing piece from round 201.

## What happened instead

The character never left the spawn bowl: 80 strides around `(480..513, 390..404)`, distance stuck at 493-519 units:

```
stride 10: 502 units (key=up align=0.67)    stride 40: 495 (left 0.33)
stride 20: 512 units (left 0.28)            stride 60: 517 (right 0.10)
stride 30: 494 units (left 0.50)            stride 80: 497 (up 0.72)
```

Alignment readings are low (0.1-0.8) and the position bounces inside a ~50-unit area. That is the spawn area behaving as a **local
trap** - a bowl of slopes the stride walker cannot climb out of - and it is why repeated runs from the same warp start at different
outcomes: sometimes the walker finds the exit ramp, sometimes it does not.

## Where CP17 stands after this round

- navigation: flat routing + receding horizon reaches ~130-140 units from the key door (best 130, round 201);
- the intermediate door problem now has a handler (untested in the field because this run never got there);
- the start itself is a trap: from the arrival point the walker needs a **guaranteed exit** - the flat route's first waypoints, not
  stride-by-stride hill climbing.

That suggests the right structure for the accepting run: **flat route for the first and last legs** (it already crosses the map and
never traps), **empirical strides only for the last short approach**, and the door handler whenever a door is within 32 units. All
three pieces exist and have each worked in isolation; they have not yet been run in that order in one pass from a clean warp.

## Stable

- randomizer: **38 cycles**, `Equipment randomized`, no inventory growth;
- CP18: done (Dragon HP 0/1300 from RAM, entity despawned);
- inputs: both paths work after `B x2` off a pad; ATP boost persists.
