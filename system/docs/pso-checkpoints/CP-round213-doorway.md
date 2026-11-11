# Round 213: doorway crossing proved adversarially (seek the gap, don't wander)

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
Live session `78a8746f5b514450-e9867839b8b74d3d`, Forest 1

## The problem with v1, found by testing instead of trusting

Round 212's doorway loop alternated +/-90 degree strafes blindly and counted *any* 45 units of travel as success. The adversarial
simulation caught both faults at once:

```
start (0,40), wall x=-40, gap z in [-10,10], target (-80,0)
result: through=True at (-40.0,16.3)   <- declared success while still jammed against the wall
actually on the far side: False
```

The character had wandered 46 units sideways and never crossed.

## v2 - and it now crosses

Two changes:

* success requires **advancing along the approach axis** (or the room id changing), so lateral wandering cannot count;
* the strafe goes **toward the target's lateral offset** instead of guessing sides, and is longer (40 units), so the bot seeks the gap.

Same adversarial setup:

```
start (0,40), wall x=-40, gap z in [-10,10], target (-80,0)
result: through=True at (-61.1, 7.8)  reason: through on the straight approach
actually on the far side of the wall: True
```

It found the opening (z = 7.8, inside the gap) and crossed. `door_sim2.py` checks the wall crossing **directly** from the simulated world
state, not from the planner's own verdict, so the test cannot be fooled by a false positive.

## Live attempt: inconclusive, and that is the lock working

I also ran the live doorway approach toward the minimap's west exit. The log shows the bot repeatedly standing down:

```
12:47:28  attempt 0: jammed 52 short (stalled); strafing +90 deg
12:47:34  operator has the controller; pausing it out
12:47:41  attempt 1: jammed 47 short (stalled); strafing -90 deg
12:47:44  operator has the controller; pausing it out
...
12:48:21  through=False at (-53,-19) (attempts exhausted)
```

Every measurement was polluted by the operator's own movement, and the bot refused to press keys while they were active. That is the
behaviour the operator asked for, and it means a clean live doorway test needs a window when nobody is on the controller.

## Files

* `door_pass2.py` - doorway approach v2 with `GameDeps` (live, all keys via `pso_input`) and `approach(deps, target)`
* `door_sim2.py` - the adversarial simulation that gates the algorithm
* `map_exit.py` - minimap exit markers (marker green 0,240,0), used to choose the doorway

## Next

Run `door_pass2.py` live in an idle window and confirm a **room id change** from the collision-graph room map as the success signal;
then feed that back into `explore.py` so room-to-room travel goes through the map's doorways rather than at room centres.
