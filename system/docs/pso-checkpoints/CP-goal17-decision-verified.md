# Goal round 17: the decision logic extracted, tested, and wired in

## What was done

The loop's strategy - switches, then enemies, then the exit, then the next room - lived **inline in the main loop**, so it could only be checked by
watching a live game. It is now a pure function:

```python
choose_action(foes, switches, exits, rooms, me) -> ("switch"|"enemy"|"exit"|"room"|"wait", target)
```

**and the loop calls it** (line 217: `kind, target = choose_action(...)`, then dispatches). A tested function the loop didn't call would be decoration;
this one is the code that runs.

## The 12 checks

```
PASS switch wins over everything
PASS the switch chosen is the closed one
PASS an open switch is not an action
PASS with no live switch the exit is next
PASS enemy is fought before the exit
PASS exit when nothing else
PASS exit target is the exit - TObjVrPortal
PASS room when nothing else
PASS the NEAREST room is chosen (30 away, not 500) - 2
PASS nothing to do waits
PASS wait has no target
PASS a closed switch (state 0) is still an action

all decision checks passed
```

Two of these guard mistakes that are easy to make and expensive live:

* **an already-open switch (state 2) is not chosen** - pressing an open door again is wasted time and looks like a stuck bot;
* **an enemy is fought before the exit** - walking past a room's enemies to the door and being shot in the back is not progress.

## The bot, verified in three layers

| layer | evidence |
|---|---|
| **see** | 11 scanner checks |
| **act** | 10 movement checks |
| **decide** | 12 decision checks, **and the loop dispatches on it** |

**33 passing checks** across perception, movement and strategy - all runnable without an emulator, all re-runnable after any change.

## State

| item | state |
|---|---|
| decision logic | **extracted, tested, wired into the loop** |
| total verification | **33 checks passing** |
| game | **not running** |
