# Round 280: exit seeking - the bot can now leave an area, not just clear it

Clearing rooms and killing enemies gets the bot through an area; nothing told it how to **leave** one. That was the last mechanical gap between the
play loop and an unattended run through a level.

## What `exit_seek.py` does

1. **Scans the entity table for warp classes** - any `*warp*` name is treated as an exit, and boss warps are distinguished by their class.
2. **Walks to the nearest one** with the height-aware planner, so the route respects the levels rather than a straight line.
3. **Presses A** at it, up to four times, and **checks the floor id after each press** - the floor changing is the proof the exit was taken, not that a
   button was pressed.
4. **Reports honestly when there is no exit**: an area warp only exists once the area is complete, so "no warp entity in this area yet" is a real
   answer rather than a failure.

## Its first measurement in Cave 1

```
player: (-300.1, 1.0, -798.5)
warps in this area: NONE
```

Cave 1 has no warp yet - the area is not complete - so the tool says so. That is the behaviour that matters: it will not wander pretending to leave.

## Wired into the play loop

The loop already explored rooms when nothing was alive. Now, when there is nothing left to visit, it **looks for the exit and takes it**:

```
nothing alive, nothing left to visit -> area exit present -> walk to it -> press A -> floor changes
```

and if no exit exists it keeps exploring instead of standing still.

## State

| item | state |
|---|---|
| exit seeking | built, wired into the play loop, validated against a real area |
| Cave 1 exit | not present yet - the area is not complete |
| play loop | running, waiting for focus, will not steal it |
| character | HP 31/62, floor 3, no enemies within 90 units |
| remaining goal item | CP19, one continuous unattended episode |
