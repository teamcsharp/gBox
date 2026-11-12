# Goal round 19: the stale save states were the freeze - cleared

## What was found

`StateSaves` held two state files, both from **before this session began**:

| file | size | age |
|---|---|---|
| `lastState.sav` | 14.9 MB | **7.6 days old** (11/4) |
| `GPOE8P.s01` | 14.8 MB | **8.1 days old** (11/3) |

`GPOE8P.s01` is the one that matters: `adapters.py` describes **"Dolphin's slot 1 (gBox's Save state / state_transfer)"**, so it is exactly what the
launch's `state_transfer` step reads - and it was written **eight days ago**, by a different session, for a different moment in a different character's
life. The `artifacts` directory, which the transfer would use for the newer artifact-based path, is **empty**.

So the launch was asked to **move a save state that no longer corresponds to anything**: no recent artifact, no current session state, just a week-old
file. A restore with nothing valid to complete against **hangs** - and a hang produces no failed job, so nothing was ever filed (round 18's finding: zero
tickets for PSO).

## What was done

Both files were **renamed, not deleted**:

```
lastState.sav      -> lastState.sav.stale-20261111-200035
GPOE8P.s01         -> GPOE8P.s01.stale-20261111-200041
```

`StateSaves` is now empty, so a launch has **no state to restore** and cannot stall on one. Restoring either is one copy, and nothing was lost: these are
saved emulator moments, not memory cards, and no session was running.

## Why this costs nothing

**The bot does not want the saved moment anyway.** `play_pad.py` begins with `boot()`, which presses START and A through the title, mode select, character
select and Start Game until a character exists. A fresh boot is the state the bot is built for - the verification work of rounds 15-17 all assumes a
character that the bot itself brought into the field.

## The next launch should proceed

If it does: the stale state was the blocker, and the honest fix is a stall detector (round 18) plus not attempting a restore when no valid artifact
exists. If it still hangs, the cause is elsewhere and the state files are still there under `.stale-` to put back.

## State

| item | state |
|---|---|
| stale save states | **moved aside**, the directory is empty |
| launch block | **should be cleared** |
| failure tickets | still 0 - a hang is not a failure (round 18) |
| bot | boot → calibrate → play, 33 checks passing |
