# Why the launch takes so long: a `characters` job sits queued forever

## The log answered it

With the readable log in place, the launch's own pipeline is visible:

```
10:28:18.296 [worker] result for job 21daeebb72914daa was answered ... its job slot is free
10:28:19.744 [worker] padstate: mirroring the operator's pad on XInput slot 0
10:28:33.050 [worker] result for job 5ef999aa47ad4e71 was answered ... its job slot is free
10:28:49.807 [worker] result for job 7174a092440345f4 was answered ... its job slot is free
```

and the queue query:

```
active: 1
  characters | queued | pct None | None
```

**A `characters` job** - the launch's "Working with the character collection" step - is **queued and never runs**. The launch waits for it, so the bar sits at
about 25% ("Runtime: dolphin") doing nothing. **It is not the emulator, not the image, not the memory card: it is one job the worker will not pick up.**

Cancelling it cleared the queue (`before: 1 -> after: 0`) and a session went live immediately.

## What this means

* **The launch itself is fine** - it completes in 9-21 seconds when nothing is blocking it;
* **`characters` can hang in the queue**, and that is what makes a launch look stuck;
* **the workaround is to cancel the stuck job** - the launch proceeds, as it just did.

## Why it hangs

Not established. What is known: the worker was processing other jobs seconds earlier (`result for job ... its job slot is free`), so the worker is alive; the
`characters` job simply is not dequeued. That points at how the job is routed - a worker requirement it cannot satisfy, or a queue state it does not leave -
rather than at anything the launch does.

## The value of the log, demonstrated

This was invisible for forty rounds. The log showed the queue state and the worker's own account in one read, and the answer took one command instead of a
night of guessing. **Every future stall is now this cheap to diagnose.**

## State

| item | state |
|---|---|
| readable log | **working**, and it solved this |
| stuck job | `characters` - cancelled, queue clear |
| launch | proceeds once the queue is clear |
| session | one live, at the title |
| bot | complete, 54 checks |
