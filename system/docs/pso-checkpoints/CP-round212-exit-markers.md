# Round 212: the minimap exit marker is read correctly, and the operator lock proved itself mid-run

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
Live session `78a8746f5b514450-e9867839b8b74d3d`, Forest 1, room 6

## The minimap's exit markers are now read correctly

The first attempt matched **17,227 green pixels** across the whole frame - the forest is green foliage, so a naive green test reads the
level as one giant marker. Sampling the minimap panel showed the actual marker colour:

```
(0, 240, 0)   72 px     <- the marker green
(64, 128, 16) 216 px    <- foliage, correctly ignored once tightened
```

With the detector tightened to `g > 200, r < 70, b < 70`, the crop yields **one** exit marker:

```
(64,107)  57px  bearing +170 deg
```

That is the **west exit the operator pointed at** - the map is north-up and player-centred, so a bearing near 180 degrees is west. The
marker is now something the bot can steer by (`map_exit.exits_from_map()` returns the world direction for each marker).

## The operator lock proved itself in the middle of a run

While walking to that exit, the run stalled and then the log shows:

```
12:46:30   walked toward the exit: arrived=False final=41 (stalled)
12:46:30   operator has the controller; waiting
```

The operator picked up the controller at that moment and the bot **stopped immediately** - the v2 lock with `pso_input` as the only key
path works in live conditions, not just in its unit test.

## What is still wrong

The walk to the exit **stalled 41 units short**. The marker direction is right, so the failure is terrain: a doorway is a narrow opening
and my controller walks at the marker's straight-line bearing, which can meet the jambs. The fix is stall recovery that **strafes along
the wall** - when no direction helps, step perpendicular to the exit bearing for a second and retry the approach, repeating left and
right, until the character passes the threshold.

## State

All bots stopped; the operator has the controller. Player at (-69,-23) in room 6, HP 40, floor 1. `map_exit.py` exposes
`exits_from_map()` (marker bearings and world directions) and `walk_through_exit()` (steers, obeys the lock).
