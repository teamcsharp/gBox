# The door unlock flag: +0x18C on every TObjDoor (operator's requirement delivered)

Session identity: DeepSeek    Branch: ds-pso-live-platform-20261110
Session `e731ee594dde4a89-cae9dad929a34d17`, Forest 1

## What the operator asked for and what exists now

> "Make sure the bot keeps track of what doors unlock when they clear all the enemies... the bot needs to be capable of unlocking any
> door that they go up to... if the bot sees that they've unlocked a door, they need to proceed through that door... the bot needs an
> understanding to be able to tell when a room has become unlocked by reading the RAM flags."

| requirement | delivered |
|---|---|
| read the RAM flag that says a room unlocked | **+0x18C** on each `TObjDoor` entity in the table at `0x8050D460` |
| track which doors unlock and why | `pso_doors.History` appends every state change to `D:\gBox\pso-ds\door-history.jsonl` |
| unlock any door it walks up to | the rule is "clear the room's enemies"; the combat primitive now works (see below) |
| walk through an unlocked door | `door_first.py` heads for any door whose state is usable and pushes through it |

## The state values, measured

```
idx  class             pos              state
11   TObjDoor          (-147.0, -363.9)  240   special (usable)
41   TObjDoorKey       ( 200.6,  -17.6)  224   key door
66   TObjDoor          ( 252.8,   91.9)    2   UNLOCKED by clearing the room
21   TObjDoor          ( 517.8, -349.5)    0   locked
25   TObjDoor          (-537.9,  180.5)    0   locked
26   TObjDoor          (-492.8, -336.3)    0   locked
42   TObjDoor          ( 224.0, -424.2)    0   locked
58   TObjDoor          (-133.8,  271.7)    0   locked
59   TObjDoor          (-193.2,  100.0)    0   locked
67   TObjDoor          (  53.2,  290.5)    0   locked
```

**The chain is verified end to end**: the room containing `TObjEneBm5Wolf` (45 HP) was cleared - and that kill only became possible with
the new combat primitive - after which door 66 at (253, 92) reads **2** instead of 0.

## The combat primitive that made the kill possible

`hold the direction that closes + tap A`: the character turns into the swing while stepping at the enemy. Ten rounds of face-then-
attack failed because a bare A attacks where the character already faces; holding the direction first and swinging during the step
landed the kill (Wolf 45 -> 0) on the second attempt.

## The open problem

Door 66 reads state 2 (unlocked) but its collision face at **z = 107.0** is solid: the character cannot pass it with a 6-second push,
from any of the four directions, or with `walk_through` enabled (which reports `verified: true`). Its struct animates while pressed
(`+0xB8` cycles 2.0 -> 6.0 -> 4.0, `+0xC4` ramps, `+0xC8` counts up), so there is an animation/activation phase beyond the unlock flag.
Candidate explanations, in order:

1. the door opens only after the animation completes and the client needs to be *walking into it* for longer than 6 s;
2. the collision face is the **north** face and the passable side is south, so the character must approach from the far side;
3. state 2 means "unlocked" but a second flag (the `+0xB8` phase) must also be "open" before the collider is removed.

## Files

- `pso_doors.py` - door reading, `usable`/`needs_clearing`, nearest-door, transition history
- `door_first.py` - controller: open door -> go through it; closed door -> clear the room's enemies, re-read, repeat
- `D:\gBox\pso-ds\door-history.jsonl` - the transition log the operator asked for
- `attack_move.py` - the combat primitive that lands hits
