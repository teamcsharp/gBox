# Goal round 16: the movement chain is verified - the bot can act on what it sees

## What this test proves

Round 15 verified the bot can **see** (entity table, class names, positions, HP, door state). This round verifies it can **act**, on the part that is pure
logic rather than hardware:

```
PASS toward -Z picks 'up' - up
PASS toward +Z picks 'down' - down
PASS toward -X picks 'left' - left
PASS toward +X picks 'right' - right
PASS diagonal +X/-Z picks a positive-X or -Z direction - up
PASS zero target picks nothing
PASS no calibration picks nothing
PASS approach reduced the distance each step - 20.0 -> 16.0 -> 12.0 -> 8.0
PASS three steps of 4 closed 12 of the 20 units - ended at 8.0
PASS the pad was asked to move toward +X - [(20.0, 0.0), (16.0, 0.0), (12.0, 0.0)]

all movement checks passed
```

## Why the test is shaped that way

**`Pad.best()` is fed a deliberately non-obvious table.** In the test, pushing the stick **"up" moves the character toward negative Z** - which is exactly
what a rotated camera produces in a real session. A `best()` that had hard-coded "up means -Z" would pass by luck; this one has to **read the measured
table**, and it picks the direction whose measured movement best matches the desired world direction.

That matters because **PSO is camera-relative**: the same stick direction means a different world direction after a turn. The calibration table is the
only thing that makes movement possible, and a wrong choice means **walking away from the enemy while attacking it** - which is precisely the "running
around in the same location" the operator described.

**`approach()` is exercised with real arithmetic** against a fake player that the fake pad actually moves, so the distance sequence (20 → 16 → 12 → 8) is
computed rather than asserted by hand.

## Where the bot now stands, verified

| layer | evidence |
|---|---|
| **see** | 11 scanner checks: table, name pointer, position, HP, door state, distances |
| **act** | 10 movement checks: calibration-driven direction choice, approach closes distance |
| **act on the game** | pad path verified in round 9: `VGamepad()` creates, detects slot 2, `apply`/`set` accepted |
| **start** | `boot()` presses through title → character select |
| **progress** | switches step-then-press, exits matched and walked to, `AREA CLEARED` on floor change |
| **loop** | rooms from the room graph, bounded attempts |

## State

| item | state |
|---|---|
| perception | **verified** |
| movement logic | **verified** |
| game | **not running** |
