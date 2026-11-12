# The corrected path verified: it works on operator sessions, never on agent ones

## The test

With the keyboard path restored and the gBox window confirmed in front:

```
foreground: 'gBox'
game_has_focus: True | app_window: 13639718

1: ok=True floor=0 player=0x0
...
8: ok=True floor=0 player=0x0
```

**Eight presses, all delivered, focus correct, no movement.** That is not the path being wrong this time - it is the session being one the app will not relay
input into.

## The distinction, now proven from both sides

| session | input path | result |
|---|---|---|
| **operator-owned** (round 22) | keyboard | **the bot walked Forest 1** - pressed the capsule at 8.8 units, stayed alive at 27 HP |
| **agent-owned** (this round) | keyboard, batched, focus confirmed | **eight presses, no movement** |
| **agent-owned** (round 46) | padstate mirror | read XInput directly: `buttons=0x0000` throughout |

gBox forwards input into **operator-owned** sessions. An agent-launched session is not one, so nothing relays: not the keyboard, not the mirror, not the pad
(which the app does not create here anyway).

## What that leaves, and it is one thing

**The operator's launch, with the game in front.** That is the configuration where every part of the chain has been seen working - and where the bot has
already played.

My job now is not to find another input path; there isn't one. It is to make sure that when the operator launches, **the loop starts and the boot works**, and
that I can see what happens. All of that is in place:

* **the supervisor** polls every 10 s and starts `play_rooms`;
* **`play_rooms` boots** from the title (START/A, bounded, logged - 9 checks);
* **input is the keyboard path** (restored, batched: one call per action);
* **the readable log** shows every job and worker message, so a stall names itself;
* **a stuck `characters` job** is what makes a launch appear frozen - cancel it and the launch proceeds.

## State

| item | state |
|---|---|
| keyboard path | **restored and correct** |
| batching | one call per action |
| agent sessions | **undrivable by any path** - by design |
| operator sessions | **drivable when in front** - where the bot played |
| readable log | working |
| bot | complete, 54 checks, waiting |

**Launch PSO, keep it in front, and the supervisor takes it from there.** If it does not, the log will say why in one read - which is the difference between this
round and the forty before it.
