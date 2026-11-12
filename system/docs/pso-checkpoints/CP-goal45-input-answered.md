# The input question, answered

## The experiment

With the readable log in place, a live agent-owned session, and `send_input` reporting success:

```
1: ok=True floor=0 player=0x0
...
10: ok=True floor=0 player=0x0
```

and the log showed **every press processed** - twenty `result for job ... its job slot is free` lines inside a few seconds. The presses arrive. The game does
not move.

Then the focus test:

```
windows: [(13639718, 'gBox'), (655754, 'gBox - File Explorer')]
foreground: 'gBox - File Explorer'
game_has_focus: False
```

**There is no game window to focus.** Agent-launched sessions run headless (`-b`), so the emulator has no visible window, `SetForegroundWindow` cannot reach
it, and the plane's input path - which requires the game to be "active" - has nothing to activate.

## What that proves

| claim | evidence |
|---|---|
| `send_input` is delivered | 20 job results in the log during 10 presses |
| the game does not receive it | floor stays 0, player pointer stays null |
| because there is no window | `game_has_focus: False`; the only "gBox" window is File Explorer |
| and the pad does not cover it | `padstate: mirroring the operator's pad on XInput slot 0` - it mirrors the *operator's* pad, not the bot's events |

**So an agent-launched session can never be driven on this machine.** That matches what was measured at the very start of the session and has now been
confirmed with the instruments to see it: the bot needs an **operator-owned** session, which has a visible window, which can be active.

## Which configuration works

**The operator's own launch, with the game left in front.** That is exactly the configuration in which the bot has already played - round 22: booted from the
title, walked between rooms, pressed the capsule at 8.8 units, survived at 27 HP.

What it cannot do is press while the operator types, because the input path requires the game to be active and typing makes the operator's window active
instead. **That trade is real and I could not remove it**: the one focus-free path is the virtual pad, which this app does not create on this machine.

## What the operator gets from this round

**A working readable log** - every launch, every job, every worker message on disk at `D:\gBox\pso-ds\app-console.log`. It answered this in one read and
answered the "why so slow" question in another (a `characters` job stuck queued).

## State

| item | state |
|---|---|
| readable log | **working** |
| launch stall cause | `characters` job stuck queued - cancel it |
| agent sessions | **undrivable** - headless, no window, no focus |
| operator sessions | **drivable when in front** - where the bot has played |
| bot | complete, 54 checks |
