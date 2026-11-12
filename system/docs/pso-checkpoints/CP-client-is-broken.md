# The server launches PSO in 21 seconds. The client is what is broken.

## The proof

A `launch_game` job submitted directly to the server, with the full catalog entry `LaunchIn` requires:

```
job: 98de93394e3848e4
t+  0s running   5.0%  Runtime: dolphin · core dolphin
t+  6s running  72.0%  Starting Dolphin
t+  9s running  72.0%  Dolphin started; releasing the boot hold
t+ 21s succeeded 100.0%  Running natively in its own window
```

**21 seconds, `succeeded`, no error.** The image, the worker, the emulator, the memory card - everything the launch needs **works**. So the frozen
`state_transfer` the operator sees is **the client never submitting the launch**, not the server failing to perform it. And `?state=queued,running`
returns **zero** jobs the whole time - the request is not even arriving.

## Why I cannot simply launch it myself

The session that job created is `agent_owned`, and driving it fails with the exact reason:

```
RuntimeError: gBox or the emulator must be active to send emulator input safely
```

That is `win_send_keys`'s polite verdict: it requires the game - or gBox - to be the foreground window. gBox runs agent-launched emulators **headless**
(`-b`), so there is no window to be active, and **no input can ever reach those sessions**. This is the constraint this whole effort started under, now
measured precisely rather than assumed.

**So the launch has to come from the operator's client, and the operator's client is the broken half.**

## What this means for the next action

| side | state | evidence |
|---|---|---|
| server | **works** | launches in 21 s, `succeeded` |
| worker | **works** | ran the launch job to completion |
| agent-launched session | **unusable for play** | input refused: "must be active" |
| **operator's client** | **stuck** | shows `state_transfer`, submits nothing |

**Fixing the client is the whole task now.** The two things that can clear it:
1. **a reload** - F5 or Ctrl+R - which clears a stale in-progress launch record;
2. **restarting the gBox app**, which replaces its in-memory launch state entirely.

## Also learned: the launch payload

`launch_game` requires a **full `CatalogEntry`** in `game`, not a `game_id`:

```
input invalid: 1 validation error for LaunchIn
game  Field required
```

The entry comes from `GET /api/catalog`. That is worth recording because the truncated payload is what produced a 422 and cost a round of probing.

## The session I started is still running

`c7272b95a11c4bed-98de93394e3848e4`, pid 58320, agent-owned, at the title screen. It cannot be played, so it should be stopped to free the resource - but I will
leave it for now in case the operator's client can adopt it (an operator-owned attach would make it drivable, which would be a win).
