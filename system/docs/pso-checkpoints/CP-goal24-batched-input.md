# Round 24: the input is batched - the fix round 23 owed

## What changed

Round 23's failure was arithmetic: a held direction was **two jobs**, and a movement was dozens of holds, so the worker's queue ran to 41 and the character
froze on input minutes stale. Three changes, none of which alter what the character experiences:

**1. `tap(key)` is one job.** It carries `[down, up]` in a single job. Dolphin reads a same-batch press-and-release as a real press - `vpad_win.TAP_S`
documents exactly this: *"two frames: a press released in the same batch is still seen"*. So a tap costs **one** job instead of two.

**2. `move(*keys)` is one job for many taps.** `[down, up, down, up, ...]` in a single job, so crossing a room costs **one** job instead of one per step.

**3. A cap on jobs in flight (`MAX_IN_FLIGHT = 4`).** `send` waits while more than four presses are outstanding, which turns a runaway into backpressure
instead of a backlog.

**4. `pso_input.hold` is one job.** Every movement in the loop goes through it, and it used to call `send` twice. Its signature and meaning are unchanged -
press, wait, release - but it now costs half the jobs.

**5. `clear_jobs.py`** cancels stuck `session_op` jobs. It worked: **40 cancelled**, and the queue dropped from 41 to 4.

## What the batching means in practice

| action | before | after |
|---|---|---|
| one movement step | 2 jobs | **1 job** |
| a held direction | 2 jobs | **1 job** |
| crossing a room (30 steps) | 60 jobs | **1-30 jobs**, and `move()` can make it 1 |
| worst case in flight | unbounded | **4** |

## Still blocking: the worker is stuck

The four remaining `session_op` jobs are stuck in `running` and **occupy the worker**: a press took **41.8 seconds and moved nothing**. Cancelling does not
remove a job that is already executing, so **the worker needs a restart** - which ends the current session.

That is the residue of round 23's backlog, and it clears with one restart. After it, the batched path means the queue should not form again.

## State

| item | state |
|---|---|
| batched input | **done**: tap, move, capped in flight, one-job hold |
| stuck-job cleaner | **works** (40 cancelled) |
| worker | **blocked by 4 executing jobs** |
| game | still running, unresponsive to new input |
| next | **restart gBox**, then run the bot on the batched path |
