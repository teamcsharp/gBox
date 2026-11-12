# Round 25: a guard against the backlog, and the honest state of the worker

## The worker is still hung

The game is the same session from 20:17, the queue still holds stuck `running` jobs, and a batched `tap` took **20.8 seconds and moved nothing**:

```
tap ok: False | took 20.8 s | moved 0.0
```

That is the residue of round 23. **Cancellation cannot free a job that is already executing**, so only a restart clears it. Everything else is ready and
waiting on that one action.

## What this round added

**`job_guard.py`** - the piece that makes the failure non-recurring. It watches `/api/jobs` and, when more than **8** input jobs are outstanding for longer
than **45 seconds**, cancels the ones still `queued` and prints what it removed. It never touches a `running` job, because that cannot be cancelled - the
point is to act **before** the queue becomes a hung worker, which is what round 23 turned out to be.

It is running now beside the bot:

```
guard: limit 8 jobs, patience 45s, polling every 5s
20:52:49 active=7 queued=3
```

## Why this closes the loop on round 23

Round 23's failure had three parts, and each now has an answer:

| part | answer |
|---|---|
| one press = two jobs | **`tap()`** - one job (round 24) |
| a movement = dozens of holds | **`move()`** - many taps in one job (round 24) |
| nothing capped the queue | **`MAX_IN_FLIGHT = 4`** in `send`, plus this guard (rounds 24-25) |

A backlog can now only form if the worker itself stalls - and when it does, the guard cancels what is still queued rather than letting it pile up, and the
input path stops adding above four outstanding presses in the first place.

## State

| item | state |
|---|---|
| batched input | done - one job per action |
| job guard | **running**, cancels backlog before it hangs the worker |
| worker | **hung** on executing jobs from round 23 |
| game | running, unresponsive to input |
| **needed** | **restart gBox** - the only thing that clears an executing job |
