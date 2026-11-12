# Goal round 12: a way to finish a level, and a way to prove it

## The gap

The loop could clear rooms but had no notion of **leaving** one. "To completion" needs an exit to walk to and evidence that a level was actually finished.

## What was added

**Exit detection.** In PSO the way out of an area is a portal/warp object in the final room. Its exact runtime class name has **not** been observed in this
session - the classes seen so far are `TObjPlayer`, `TObjDoor`, `TObjDoorKey`, `TObjContainerItem` - so rather than hard-code a guess the loop matches a
broad set of exit-like words:

```
Portal · Warp · Exit · Gate · Teleport · Vr · Stair
```

and **logs whatever it finds**, so the first time one appears its real name is on the record and the match can be tightened to that name exactly. Walking
to it and pressing A is the same approach used for switches.

**Area-clear detection.** The floor id at `0x805D5FC0` changes when a transition completes, so the loop now records the floor it started on and logs:

```
AREA CLEARED: floor 1 -> floor 2
```

That is the difference between "it ran for an hour" and "it moved from Forest 1 to Forest 2" - one is a bot that is busy, the other is a bot that is
progressing. It is also the first hard completion signal this goal has had.

## Order of operations

Progression-first, unchanged and now complete:

1. **switches** - they open the way (step toward, then press, so the character faces it);
2. **enemies** - they block it;
3. **the exit** - walk to it and press;
4. **the next room** - only when none of the above is present.

## State

| item | state |
|---|---|
| exit handling | **added**, matches broadly, logs the real class name when seen |
| area-clear detection | **added**, logs floor transitions |
| pad bot | compiles, ready |
| supervisor | one, lock working, waiting |
| game | **not running** |
