# Fast-forward works, and it is measured at 3.49x

## The control was already routed - I found where

`session_op` accepts `{op: 'fast_forward', args: {on: true}}` and delegates to `rewind.set_fast_forward(sid, ad, on=...)`, which on Dolphin calls
`DolphinWinAdapter.fast_forward`, holding the **"Disable Emulation Speed Limit"** lane key with **`hidden_ok=True`** - no native-window focus needed. So the game
can be sped up while it sits in the PiP.

## Verified, not inferred

Dolphin's `query_runtime` returns only `{running, emulator, state}` - **no rate** - so speed had to be measured on something the game increments itself. A 12 KB scan
of the globals found counters, and one moves at a game rate:

```
at 1x:              0x805D53A4   30.5 /s
fast-forward on:    0x805D53A4  106.5 /s     x3.49
```

**3.49x on the same address**, then restored to 1x with the same job path. The earlier 43.7 kHz counter was a real-time timer, which is why the first attempt showed
`x1.00` - the wrong instrument, not a missing feature.

## Honest limit

**3.49x, not 10x.** The counter tops out at 106.5/s, which is what this machine sustains with the current Dolphin settings, not what the control allows.
Eliminating the speed limit removes the cap; the hardware then decides. Reaching 10x needs cheaper rendering (resolution, internal scale, texture filtering) or
the `autoplay_speed` multiplier, which is separately gated:

```
autoplay_speed: {"choices": [1,2,4,8,10], "known": false, ...}
set_speed() -> "Speed input was interrupted; relaunch to restore a known 1x baseline"
and it requires _pso_coop_new_card.isolated - a dedicated buddy session
```

So the multiplier path needs a fresh launch; the fast-forward path works now and gives 3.49x.

## Also added

An RPC op beside `normal_speed`, since the dispatcher could turn fast-forward **off** but not on:

```python
if op == "fast_forward":                           # the speed-run control: hold the no-speed-limit hotkey
    return rewind.set_fast_forward(sid, ad, on=bool(args.get("on", True)))
```

`tools.py` compiles. The job path works today; the RPC op needs a worker reload to take effect.

## What this changes for the goal

**"Speedrunning the game at 10x"** now has a working, measured control at **3.49x** and a clear path to more: lower Dolphin's render cost, or relaunch to unlock the
`speed` multiplier. **It is no longer a gated unknown** - it is a number with a known ceiling and two known ways to raise it.
