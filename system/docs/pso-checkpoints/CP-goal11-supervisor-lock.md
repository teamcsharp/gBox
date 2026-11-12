# Goal round 11: one supervisor, enforced - and the bug that hid it

## The bug

The supervisor gained a lock two rounds ago to stop two bots racing for the same game - two loops pressing the same pad, each fighting the other's
movement, which is an obvious way for an unattended run to fail.

**It never worked.** `supervisor.py` does not import `os` at module level, and `claim_lock` calls `os.getpid()`. That raised `NameError`, and the
function's own `except Exception: return True` swallowed it - so **every instance believed it held the lock, wrote nothing, and started**. The evidence
was on screen the whole time: the lock file was **empty**, and four supervisor processes were alive.

The fix is one line - `import os` inside `claim_lock` - and the failure it exposed is worth remembering: **a guard that catches every exception and
returns success is not a guard, it is a decoration.** The empty lock file was the tell, and I should have read it the first time it printed.

## Now verified

```
lock content: '31028'
second instance: "supervisor 31028 is already running - this one exits"
```

One supervisor, and a second start refuses cleanly instead of doubling the load.

## What this protects

With the pad path in place (`send_input` → `vpad.apply`), two supervisors would mean **two virtual pads and two loops** driving one game. That is
exactly the kind of interference that reads as "the bot is confused" when it is really two bots.

## State

| item | state |
|---|---|
| supervisor lock | **works**, verified with a real second start |
| supervisors running | one |
| game | **not running** - the last launch stalled in the client |
| bot logic | complete: switches first with step-then-press, bounded room attempts, pad and keyboard paths |
| next launch | `verify_launch.py` answers pad-created and movement in the first minute |
