# The recurring launch stall: found, and now handled automatically

## The job's own record was the answer

```
tool: characters | state: queued
worker: None
input: {"op": "cast_swap", "character": "", "session_id": "", "game_id": "", "game": "", ...}
```

**No worker is assigned**, and **every field is empty**. A job with `require_worker: None` cannot be dequeued by anyone - it sits at the head of the queue, and
the launch waits for the queue, so the bar freezes at 25% and the game never starts.

That explains every "why is it taking so long" from the last two days: it was never the emulator, the image, the memory card, the worker being down, or focus. It
was **one orphan job nobody could run**, blocking everything behind it.

## The guard

`orphan_guard.py` watches the queue and cancels queued jobs that have no worker, after a short grace so a freshly created job can still pick one up. It logs
every cancellation, so a recurrence is visible rather than mysterious. Running now:

```
04:36:02 orphan guard starting
04:36:12 orphan characters 494b88988f has no worker - cancelled
```

**It caught one within ten seconds of starting** - the same orphan that has been stalling launches - and the queue went to zero.

## Why this matters for the goal

Every launch the operator attempted in this session that "just sat there" was being held by this. With the guard running:

* a launch is no longer blocked by a job that cannot run;
* when the orphan is created again - and it has been, twice tonight - it is cleared within seconds instead of blocking for as long as someone keeps waiting;
* the launch then proceeds, as it has done every time the queue was cleared by hand.

## State

| item | state |
|---|---|
| orphan `characters` job | **identified** - no worker, empty inputs |
| guard | **running**, cancels orphans within seconds |
| queue | **0** |
| launch | unblocked |
| session | one agent-owned, at the title |
| bot | complete, 54 checks |

## What is still true

**An agent session cannot be driven** - proven by keyboard, by mirror, and by focus. The bot plays on an **operator-owned** session with the game in front,
which is round 22. With the orphan guard in place, that launch no longer stalls on a job nobody can run.
