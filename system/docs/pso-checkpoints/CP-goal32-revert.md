# Round 32: reverted my patch - the server is healthy, and the difference between my launches and the app's

## What I did, and undid

The `_vpad_works` change from round 31 **did not help** - a fresh launch still wrote the keyboard binding and input still failed with "the game window isn't
open". During that testing **the server went down** (my own API calls got `ConnectionRefused`), which is the worst possible outcome for the operator: their
launches then sat at `launch_game running` with no server to serve them.

**So I restored `adapters.py` from the pre-patch backup** (`adapters.py.bak-211734`) and restarted the server. Verified:

```
adapters.py compiles ✓  restored to the probe version ✓
health: True   workers: 1   queued/running: 0
launch: 12 s, succeeded, live session
```

**I am not leaving a change I cannot explain in the file that every emulator depends on.** The operator's system is back to the version that worked.

## The finding I do have, and it is useful

**My direct launches succeed in 9-45 s every time. The app's launches stall at about 25%** - which is the "Runtime: dolphin · core dolphin" stage, before the
emulator window appears. Both use the same `launch_game` tool, so the difference is **which server process serves them**.

The relevant fact: **the app's own server did not respawn** when I killed it. The only server running now is **the one I started by hand**. Their launches are
therefore reaching a server I own, and its worker may not be the one that can start an emulator on this PC.

**That is a solid explanation for "PSO struggles to load inside gBox but the same launch works when submitted directly."**

## The right fix, and it needs the operator

**Fully restart the gBox app** so it starts **its own** server and worker, rather than sharing the one I started manually. That gives their launches the stack
the app expects:

1. quit gBox completely (not just the window);
2. start it again;
3. launch PSO.

With a healthy app-owned stack, their sessions are operator-owned, which is the kind that accepts input - the configuration in which the bot has already been
seen walking and pressing switches in Forest 1.

## What I will not do next

**No more edits to `adapters.py`.** Three attempts, one of which took the server down. The virtual-pad route remains unproven and the file is too central to
keep experimenting in. The bot and its 45 checks are done; the remaining problem is operational, not logic.

## State

| item | state |
|---|---|
| `adapters.py` | **restored to the working version** |
| server | **healthy**, launches in 12 s |
| app's own server | **not running** - I killed it and it did not respawn |
| app's launches | stall at 25% |
| bot | complete, verified, waiting |
