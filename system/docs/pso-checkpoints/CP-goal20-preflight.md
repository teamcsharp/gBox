# Goal round 20: pre-flight clear - a launch has everything it needs

## The check

Rather than diagnose the next freeze after the fact, everything a PSO launch depends on was checked up front. **All of it is present:**

```
API
  OK   health - {'ok': True}
workers
  OK   a worker is online - 2 of 2
game image
  OK   cached image - Phantasy Star Online Episode I & II Plus (USA).gcz
memory card
  OK   a memory card exists for some session - 16 cards
save states (should be clear)
  OK   no live save state to restore - none
dolphin config
  OK   BackgroundInput = True
  OK   GCPad1 has a device line - Device = XInput/2/Gamepad

pre-flight clear - a launch has everything it needs
```

Two of these are the direct result of earlier rounds:

* **"no live save state to restore"** - round 19 moved `lastState.sav` and `GPOE8P.s01` aside; they were 7.6 and 8.1 days old and are exactly what the
  frozen `state_transfer` step reads;
* **`GCPad1 = XInput/2/Gamepad`** - the bot's virtual pad slot. Note the app **rewrites this file at launch** from its own template, so this reading is the
  current state, not a guarantee for the next launch: if the app's `_setup_vpad` succeeds it will write its own binding to its own pad's slot, which is
  the correct outcome anyway.

## What the check is for

The last several attempts failed without naming a cause. This prints each prerequisite and, when one is missing, names it - so a launch either proceeds
or has a specific fault to report instead of a bar stuck at 25%.

Read-only: nothing is created, moved or started.

## State

| item | state |
|---|---|
| pre-flight | **clear on every check** |
| save states | **none live** |
| workers | 2 online |
| image and card | present |
| bot | boot → calibrate → play, 33 checks passing |
| supervisor | one, waiting |
| game | **not running** |
