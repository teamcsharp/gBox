# Round 40: system restored to stock, and the honest state of the goal

## What I did

Chased the virtual-pad gate with three rounds of instrumentation, discovered that the app's server output goes to its own console (so the diagnostics never landed
in a file), converted them to file writes, and then found that even a killed-and-respawned server did not produce them. Rather than keep modifying the adapter
for every emulator in the system, **I restored `adapters.py` from the oldest backup (`adapters.py.bak-035902`)** and verified:

```
compile: OK
no instrumentation in _setup_vpad: True
_vpad_works is the ORIGINAL probe: True
_want_vpad requires GPO (original): True
health: True
```

**The app is stock. None of my adapter changes remain.** Five timestamped backups stay on disk as restore points.

## What is true about the goal

| item | state |
|---|---|
| game launch | **works every time**, 9-21 s, `succeeded` |
| bot logic | **complete**: 54 checks - perception, movement, decision, batched input, boot |
| bot played once | **yes** - round 22, on an operator session: booted from the title, walked rooms, pressed the capsule at 8.8 units, survived at 27 HP |
| focus-free input (vpad) | **does not engage** in the launch path, cause not found |
| keyboard input | **works, but requires the game to be focused** |

## The unsolved conflict, stated plainly

The plane's `send_input` refuses with `"gBox or the emulator must be active"` unless the game window is in front. **A bot using that path cannot press while the
operator types.** The one path that avoids this - the virtual XInput pad, which Dolphin polls every frame regardless of focus - is not being created at launch,
and I could not determine which gate refuses it from outside the app's own server.

## What that means for "without fail"

**The bot can play now, under one condition: the game stays focused.** Whether that is acceptable is the operator's call, not mine - it means using another
window or another device to chat while it plays.

I am not going to claim the pad is fixed when it is not, and I am not going to keep restarting their system in the early hours to chase it. **What would move
this forward is a diagnostic that can actually be read** - the app writing its server's stdout to a file, or the gate being exposed in the job's progress
message rather than a print.

## The bot's condition, unchanged and verified

Slots to fill, exits to find, `AREA CLEARED` when the floor changes, one input job per action with a cap of four, boot from the title. If a game is focused and
running, the supervisor starts the loop within ten seconds.
