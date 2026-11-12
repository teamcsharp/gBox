# Goal round 14: why the launch freezes, and what to do instead

## What the operator is seeing

The launch overlay sits at ~25% with **"state_transfer running"** and the hint *"the game starts by itself and reconnects"*. Pressing launch again repeats it.

## What that step is

`state_transfer` is the launch's **"Moving the save state"** step (the client's own label): it restores the previous session's saved moment into the new
one, so the game resumes where it was. That is a convenience, not a requirement - and it is the step that is hanging.

## What the measurements show

* **The server has no `state_transfer` job at all.** The 100 recent jobs are all `succeeded`; the newest `launch_game` entries are from 18:55. The client is
  displaying a step the server never received.
* **The server itself is healthy**: `{"ok": true}`, and two workers report online within seconds.
* **The view also showed "Reconnecting…"** in the earlier attempt.

So the client's launch pipeline is stalled on a step that never reaches the server. That is why it "just freezes" and why retrying does the same thing.

## The workaround, and it costs nothing

**Launch without restoring the last moment** - a fresh start. The bot does not need the saved state:

* `play_pad.py` begins with **`boot()`**, which presses START and A through the title, mode select, character select and Start Game until a character
  exists. That was added two rounds ago precisely so a run could begin at the title screen.
* Nothing in the loop depends on resuming from a snapshot.

So if the launch menu offers **"start fresh" / "new game"** rather than **"resume"**, take it.

If the overlay stays stuck, **press Esc to cancel**, then **Ctrl+R** to refresh the client - that binding is live since the 19:33 restart and it does a
full refresh-and-reload - then launch.

## Also this round

A scanner test was written (`test_scanners.py`) that builds a synthetic memory image and asserts the bot parses enemy HP, door state 224, positions and
distances correctly. **It currently fails** - the fake memory returns nothing to the scanners, and I have not yet found why (the fake's own read looks
correct on inspection). It is not committed as working, and it changes nothing about the running system; it is noted here so the next round picks it up
rather than pretending it passed.

## State

| item | state |
|---|---|
| launch freeze | **`state_transfer` (save-state restore) never reaches the server** |
| server | healthy, workers online |
| workaround | **launch fresh** (the bot boots from the title) |
| bot | boot → calibrate → play, exits and area-clear logging in place |
| scanner test | written, **failing**, not claimed as working |
