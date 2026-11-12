# The app starts its own server - do not hand-start one

## What went wrong

For several rounds I started `gbox ... serve` by hand because the workers I killed did not respawn immediately. That created a competing server:

* **my** `serve` owned port 8765 and the job queue;
* the **app's** own server, when it came back, could not take those;
* the operator's launches reached **my** server, whose worker may not be the one that can start an emulator on this PC - which is why their launches
  stalled at ~25% ("Runtime: dolphin") while launches I submitted directly succeeded in 9-45 s.

I read "the app's server did not respawn" as a fault. It was not: **the app starts its server when the app starts**, not when its worker dies. Killing the
worker without restarting the app leaves the worker gone and the app's supervision unaware.

## The rule

**Do not hand-start `gbox ... serve` while the app is running.** Instead:

1. **restart the app** - it starts its own server and worker (observed: app at 21:21:35, its server at 21:22:58);
2. **verify ownership** - port 8765's owner should be a process started *after* the app;
3. only if the app has been restarted and no server exists should one be started by hand, and then it must be stopped again once the app is restarted.

## Verified state after the app's restart

```
health: True
workers online: 1 of 1
live sessions: 0
queued/running: 0
pre-flight clear - a launch has everything it needs
supervisor: waiting for the game to be launched
```

One server, one worker, no leftovers, no queue. The Dolphin config is back to the app's own binding (`XInput/0/Gamepad`) because `adapters.py` was restored
from its pre-patch backup in round 32 - which is the correct, working configuration.

## The path now

**Launch PSO from the app.** Its sessions are operator-owned, which is the kind that accepts input, and the supervisor picks the session up within ten seconds.

**What the bot does when it appears:** `boot()` presses START/A from the title until a character exists, calibrates the stick against the character, then runs
switches → enemies → exit → next room, pressing A near any door it reaches and logging `AREA CLEARED` when the floor changes.
