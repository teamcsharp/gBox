# PSO did load - the launch screen was lying

## The measurement

The launch was healthy. Job `79276d0fa07c45cc`:

```
created:   08:41:57
started:   08:41:58
finished:  08:42:16      <- 18.4 seconds
pct:       100.0
msg:       Running natively in its own window
output.session_id: 0b1c2656706343d6-79276d0fa07c45cc   (present)
```

And the emulator right now:

```
gBox Dolphin  pid 38024  570.5 CPU-seconds  937 MB
runtime: {"running": true, "emulator": "dolphin", "state": "PLAYING"}
floor: 0   player: None          <- PSO's title screen
worker i9-NUC: online: true
active jobs: 0
```

**The game is running and sitting at its title screen.** Nothing is frozen, and nothing is queued.

## Why it looked frozen

`web/index.html`'s launch loop only leaves the splash when it **observes** `j.state === "succeeded"`:

```js
if (j.state === "succeeded") { ... LOADING = null; loader.hide(); ... }
```

If that observation is missed - a backgrounded tab whose timers are throttled (very likely in a remote-desktop view), a dropped request, a suspended page - **nothing
else ever clears the overlay**. The game plays behind a splash that never lifts, which reads exactly as "PSO freezes while loading". Twenty minutes after a launch that
had finished in eighteen seconds, the screen still showed 25%.

**So this was a client-side staleness bug, not a slow or failing launch.**

## The fix

While the launch job is not terminal, the loop now also asks whether a session for this game is **already running**. If one is, the launch succeeded by definition:

```js
if (!["succeeded","failed","cancelled","rejected"].includes(j.state) && i % 5 === 4) {
  const live = await api("/api/sessions", undefined, "GET", 10000).catch(() => null);
  ...
  if (mine) { LOADING = null; loader.progress(100, "Running - opening the game");
              return show("Sessions", mine.session_id); }
}
```

It matches on the game's title, its id, or the job id, checks every fifth poll (about two seconds), and uses the same `api()` signature as the surrounding code. Verified
in place, inside the async `play()` function.

**The screen now agrees with the game instead of depending on one message arriving.**

## On "load as fast as possible"

**18.4 seconds** is the launch's real cost, and it is already the fast path: one second for the worker to pick the job up, then the emulator starting and PSO's own
disc load and boot. The splash's 25% was never tracking that - it was a stale number.

What made it *feel* like it never loaded is now fixed. There is no evidence of a slow component to optimise: no queued job, an online worker, and a launch that
reported complete with its message and session id intact.

## What still needs doing - and it is a person's job

**PSO is at the title screen.** Getting from there into the field needs a button press, and **an agent's presses are dropped by design** (`server.py`: *"the worker
gives the pad to the operator only, never to an agent"*).

So: **play into the field, then press F3.** F3 starts the app's own autoplay, which injects inside the worker and is the only path that works on your session - it is
what produced 258 units of movement earlier. It is now a take-over rather than a toggle, so it cannot stop a running bot.
