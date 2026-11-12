# Round 39: the gate instrumentation is in place - and what blocks it from running

## What was added

Three plain log lines inside `_setup_vpad`, applied with backup-and-compile discipline and no regex:

```
vpad: _want_vpad() -> <verdict>
vpad: VGamepad() attempt N failed: <exception>
vpad: attempt N detected slot <slot or None>
```

Any of the three explains why the pad is refused, and none of them change behaviour - three `print(..., flush=True)` statements at the three places that can
return None.

**Verified**: `py_compile` OK, import OK, restore path printed (`adapters.py.bak-041012`).

## Why the lines have not appeared yet

The launch writes `GCPadNew.ini` from `DolphinWinAdapter._argv` (line 3150), which calls `_setup_vpad` (line 3133). **No `vpad:` line appeared in any log**, and
the reason is not the code:

* the app **respawns its own server within seconds** - I killed every `gbox ... serve` and started one immediately, and by the time I checked, port 8765
  belonged to a **process started 16 seconds earlier by the app**, while mine had failed to bind and written nothing;
* that app-owned process loaded `adapters.py` **before my edit**, so it runs the old code;
* my server's log files stayed **0 bytes** - it never served a request.

**So the instrumentation needs the app restarted, not another server race.** The app owns its stack, which is correct, and the patched file will be loaded the
next time it starts.

## The one action that closes this

**Restart gBox.** Then launch PSO once. The log will contain one of the three lines, and that names the gate:

| line seen | meaning | fix |
|---|---|---|
| `_want_vpad() -> False` | the gate refuses (env flag, capture backend, or `available()`) | set the flag / start without capture |
| `VGamepad() attempt N failed: ...` | ViGEm refuses the pad at launch | the transient contention its own comment describes - a retry or a longer backoff |
| `detected slot None` | the pad exists but XInput does not report it | the `_detect_slot` sentinel needs a different value |

Each is a small, specific change - which is the point of doing this rather than guessing again.

## State

| item | state |
|---|---|
| instrumentation | **in place**, compiles, imports |
| loaded by the running server | **no** - it predates the edit |
| blocker for the log | **an app restart** |
| focus stealing | removed at the source |
| bot | complete, 54 checks |
