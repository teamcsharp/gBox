# Round 23: the bot played, then my own input design backed the worker up

## What worked

The bot got into the field and played. From the log:

```
20:42:36   pressed A near TObjDoorKey (state 1129705297, 12 units)
20:42:44   in reach: TOCapsuleAncient01 at 8.8 units - pressing
20:43:22   switch TObjDoor state 880 at 116 units
```

It **pressed things in reach**, **chose a real door over a key-locked one**, and **moved** - the fixes from rounds 22 and 23 all behave as intended:

* key-locked doors (state 224) are no longer destinations, so it stopped obsessing over a wall it could not open;
* the phantom door (`hp 0`) is excluded by the hit-point test;
* anything within 10 units is pressed regardless of state, which is the operator's rule.

## Then the queue ran away

```
active jobs: 40 ... 41
one press took 41.6 s
moved 0.0
```

**Every key event is a job.** A held direction is `down` and `up` - **two jobs** - and the loop presses constantly, so the bot submits faster than the worker
can apply. The queue grew to **41 pending `session_op` jobs**, each press waited behind all of them, and the character appeared frozen at exactly 116.0 units
because its input was **minutes stale**.

That is my design, not the game's: the input path I built treats a button press as a network request. Stopping the bot did **not** drain it - some jobs are
marked `running` and never finish, so the worker is now effectively hung and the game is unresponsive.

## The fix, for the next round

**Fewer jobs per action, not faster waiting:**

1. **one job per tap** - `send_input` accepts multiple events, and a same-batch `down`+`up` is a tap, so a movement step is **one** job instead of two;
2. **a batched movement** - several taps in one job, so crossing a room costs one job rather than thirty;
3. **a hard cap on in-flight jobs** - if the queue exceeds a few, the loop waits instead of adding, which turns a runaway into backpressure.

None of that is exotic; it is the difference between an input path built for interactive presses and one built for a bot.

## The immediate situation

The worker has to be restarted to clear the stuck jobs, which ends this game session. **That is the cost of the backlog, and it is mine.**

## State

| item | state |
|---|---|
| bot in the field | **verified** - it pressed, chose, moved |
| input design | **bottleneck**: one job per key event |
| queue | **41 stuck jobs**, some `running` forever |
| game | unresponsive to jobs; needs a worker restart |
| next | **batch the input** (one job per tap, capped in-flight) |
