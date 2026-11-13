# Why there were two bots, and the lock that stops it

## The root cause: the `python` launcher

Found by asking the OS instead of assuming:

```
PID 39396 (parent 39176: python.exe) :: ...uv\python\...\python.exe
PID 39176 (parent 40480:          ) :: ...hermes-agent\venv\Scripts\python.exe
```

**`python.exe` in the hermes venv is a launcher.** It starts the real interpreter as a **child**, and **both run the script**. So:

* one `Start-Process python endless.py` produced **two `endless.py` processes**;
* two bots means two controllers on one character - one walks left while the other turns right, neither sees its own press reflected in the position, **and both conclude the character is stuck**. That is why the unstick fired constantly and why the character sat at `(434, -2)` for 130 s with **0 room changes** in 26 samples.

The same thing doubled the relay.

## The fix: an OS-level exclusive lock

A PID file lost the race - the parent writes it and the child reads it microseconds later before the write is visible. So `singleton.py` now uses **`msvcrt.locking`** on a file handle held for the process lifetime:

* the first process locks byte 0 and the kernel keeps it until exit;
* a second attempt fails immediately (`LK_NBLCK`);
* **no stale file to clean up** - the OS releases it.

**One subtlety cost a round:** `"a+b"` opens at **end-of-file**, and `msvcrt.locking` locks from the **current position** - so each process was locking a *different byte* and both succeeded. `handle.seek(0)` before locking fixes it.

## Proven

```
while the holder is alive -> another instance already holds test.lock - exiting
trier acquired: False
after the holder exits   -> trier acquired: True
```

**Excludes a second live process, and frees when the first exits** - both halves matter.

## In place now

* **one bot** - started with the **base python** (`uv\python\...\python.exe`), which is not a launcher, so it is a single process (PID 12344);
* **one effective relay** - started with the venv python (the only one with pygame 2.5.7); the launcher parent waits while the child runs, and the lock refuses any genuinely separate instance;
* `endless.py` takes `LOOP_LOCK` at start and holds it for its lifetime;
* `relay_singleton.py` takes `relay.lock` the same way.

## What this changes for the operator

The relay log shows the pad in use (`relayed 1 event(s): ['a']`, `relayed 5 event(s): ['up','down','left','right','up']` with `operator idle - bot may resume` between bursts), and **for the first time the bot is not being contradicted by a second copy of itself** - so its picture of where the character is can be trusted, which is the precondition for every other behaviour (approaching a door, pressing a key, breaking a box, entering a warp).

## Also confirmed this round

* the **operating environment** is the thing to check first: twice this session "the bot is broken" turned out to be `gBox` being down, or an orphaned Dolphin holding the worker, or here a duplicated process. **Check the environment before the code.**
