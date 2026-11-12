# Goal round 18: why the frozen launch never gets fixed - a hang is not a failure

## The gap

The app has a real, well-built failure system: `launch_failures.py` (68 KB) files a report when a launch fails, classifies it by signature, proposes a
remedy, investigates, and verifies the fix. The operator's own rule is in its docstring:

> *"When a game fails to load I need it to auto file a report and I need that report checked into and resolved so we can get these games loading
> fluidly."*

`GET /api/launch-failures?game_id=436e0bb84d5337d1` returns **0 tickets** for PSO.

**That is the finding.** The launch does not *fail* - it **hangs** at `state_transfer` (the save-state restore). A hang produces no failed `launch_game`
job, no crash code, no error, so:

* **no ticket is filed** - the classifier only reacts to failures and crashes;
* **no remedy is proposed** - there is nothing to classify;
* **nothing is verified or resolved** - the loop has no work;
* **and the operator sees an overlay at ~25% that never changes**, retries, and gets the same thing.

The machine that is designed to make launches load fluidly **cannot see a launch that never finishes**.

## Supporting evidence from this session

* the server reports **no `state_transfer` job at all** while the client displays one running - so the step is stalled before it reaches the job list;
* the server itself is healthy (`{"ok": true}`, two workers online within seconds);
* an earlier attempt showed **"Reconnecting…"** in the view, i.e. the client's own link was down;
* two worker registrations exist under the name `i9-NUC`, so a job could be dispatched to one while the client watches another.

## What would fix the class of bug

A **stall detector**: a launch step that has not advanced for N seconds is a failure with its own signature ("launch stalled at <step>"), which files a
ticket like any other. The pieces already exist - the client knows the step name and its progress, the API files by signature, the remedy machinery runs
on tickets - so the missing piece is only the classification rule: **no progress for N seconds counts as a failure**.

## What to do right now

**Cancel the launch and start fresh**, skipping the save-state restore. The bot does not need the saved moment: `play_pad.py` begins with `boot()`, which
presses START and A through the title, mode select, character select and Start Game until a character exists.

## State

| item | state |
|---|---|
| launch failure system | exists, well built, **blind to hangs** |
| PSO failure tickets | **0** - nothing was ever filed for this |
| frozen step | `state_transfer` (save-state restore) |
| workaround | **launch fresh**, the bot boots from the title |
| proposed fix | **stall detection**: no progress for N seconds is a failure |
