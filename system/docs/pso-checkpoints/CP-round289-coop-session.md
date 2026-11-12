# Round 289: the co-op session, the job unlock, and giving the computer back

Three findings this round, in increasing order of importance.

## 1. The app can be minimised, and that ends the domination

The gBox window re-applies `topmost` after every external change, but it **can be minimised**:

```
ShowWindow(hwnd, SW_MINIMIZE)   -> True
gBox iconic: True               (still minimised 8 seconds later)
foreground: 'Grenade Ring to PSO - DeepSeek Harness'
```

So the operator's computer is usable again: another application holds the foreground and the app stays out of the way. That is the immediate fix for
"G Box was forcing itself on top of the application and I couldn't click anything underneath".

## 2. Jobs DO dispatch - with the right flags

Every earlier attempt to queue a job sat at `worker=None` forever. The difference is the flags:

```json
{"tool": "launch_game", "input": {...}, "require_worker": "bcd14c8d972940b2", "agent_use": false}
```

With `require_worker` naming the online worker **and `agent_use: false`**, the job ran and **succeeded**:

```
job c25969f531a04870 -> succeeded
session bcd14c8d972940b2-c25969f531a04870
```

That is a capability this session did not have before: **the agent can launch a game**.

## 3. The co-op session is the real mechanism, and it is headless by design

The launch used `pso_coop: true`, which the plane describes as *"two real controllers for offline PSO Plus, with native observation on each step"*. The
emulator it starts is:

```
"D:\gBox\runtime\dolphin\Dolphin-x64\gBox Dolphin.exe" -b -u C:\_tools\gBox\...
```

**`-b` is batch mode: no window at all.** That is why the frame capture reports `covered: 9, mean_luma: 0.06` - there is no window to capture - and it
is also the answer to background play: **a headless emulator driven by virtual pads cannot care about window focus.**

`pso_coop_setup` writes a **private pad map** for the two players, so input goes through virtual controllers rather than the operator's keyboard.

## Where the co-op session stands

```
pid 28856   gBox Dolphin   2.9 minutes   914 MB   alive
memory at 0x8050D460: not mapped yet
```

The process is running and grown to 914 MB, but the gameplay addresses are **not committed**, so it is still booting, or at the title screen waiting
for input. The co-op stack is what normally drives it through character creation and into the field.

## What this changes for the goal

CP19 is *"Episode I unattended, with the mastery build"*, and the mastery build is `pso_master_build` - one idempotent entry point "the co-op bot loop
calls on spawn / area change / periodically". So **CP19 is the plane's co-op loop**, not the custom loops this session wrote, and the co-op session now
has a real, running instance behind it.

CP17 and CP18 also read *"with both players"* - and the two `TObjPlayer` slots this mode creates are exactly what those criteria mean. The evidence
already recorded for both is **single-player**, which should be stated plainly rather than glossed.

## State

| item | state |
|---|---|
| gBox window | **minimised**, computer usable |
| job dispatch | **works** with `require_worker` + `agent_use: false` |
| co-op session | running, headless, still booting |
| CP17 / CP18 | pass single-player; the "both players" clause is not met by that evidence |
| CP19 | the co-op loop is the right mechanism and is now running |
