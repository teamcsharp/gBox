# Goal round 13: the bot can start from the title screen

## The gap this closes

Every loop written so far assumed a character already existed and simply **idled** otherwise. That is a silent failure mode: the bot "runs" for an hour,
never leaves the title, and the log fills with `no player` - busy, not progressing. A launch drops the emulator at the title screen, so **the first thing
an unattended run must do is get past it.**

## What was added

`boot(pad)` presses **START and A in alternation** until `player()` returns a real actor, which walks PSO's whole bootstrap - title, mode select,
character select, Start Game - because each step is a confirm. It is bounded at 120 rounds and it **logs the count**:

```
no character yet - pressing through the title and menus
character appeared after N rounds of start+A
  still no character after 10 attempts        (every tenth round)
```

That turns "it never started" into a number that says where it stalled.

It uses the **pad**, for the same reason as everything else: no focus needed.

It also cannot be skipped by accident - it runs before the stick calibration, and calibration is meaningless without a character, so the ordering is
boot → calibrate → play.

## The loop is now complete end to end

| stage | mechanism |
|---|---|
| off | nothing running |
| **title screen** | `boot()` - START+A until a character exists |
| stuck on a key door | switches: walk to them, **step toward before each press** (faces the character, shows the reticle) |
| enemies | A in melee, B beyond it |
| **level finished** | exit objects matched broadly, walked to, pressed; `AREA CLEARED: floor N -> M` when the floor id changes |
| nothing left in the room | next room from the room graph, bounded attempts |

## State

| item | state |
|---|---|
| boot from title | **added**, logged, bounded |
| pad bot | compiles, boot → calibrate → play |
| supervisor | one, lock working, waiting |
| game | **not running** |
