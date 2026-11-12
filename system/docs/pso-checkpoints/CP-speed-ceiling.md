# The 10x ceiling is one CPU core, measured

## What the numbers say

Fast-forward holds, it does not decay:

```
baseline:  32 /s
slice 1:  114 /s     slice 6:  116 /s
slice 2:  116 /s     slice 7:  112 /s
slice 3:  116 /s     slice 8:  128 /s
slice 4:  112 /s     slice 9:  118 /s
slice 5:  114 /s
```

**~3.6x, steady.** Not a key that slips, not a ratio - the earlier 3.49x was the same thing measured over a longer window.

## What it is not

* **Not VSync** - the primary display runs at **59 Hz**, and the game counter exceeds 59/s, so the renderer is not pacing to the display.
* **Not the GPU** - the session's own HUD reads 5%.
* **Not a config cap** - `Dolphin.ini` has no `EmulationSpeed` (100% default) and `GFX.ini` is empty (stock defaults).
* **Not the control** - `fast_forward` reports `on: true` and the rate change proves it took effect.

## What it is

**One saturated CPU core.**

```
process 'gBox Dolphin' cumulative CPU: 1696.9 s
used 6.16 CPU-seconds in 5.9 s = 1.04 cores of a 16-thread machine
```

Dolphin's emulation thread is the bottleneck at **1.04 cores**, so the other 15 threads and the GPU sit idle while the game runs at 3.6x. That matches the HUD's
"9.7 / 20 cores" exactly - an average that hides a single core pinned at 100%.

## So 10x is a hardware ceiling, not a software gap

The control is complete and focus-free; the multiplier path exists; **nothing can make one core go faster.** From here the only routes are to **reduce the work that
core does**, and each is a settings change needing a restart:

| lever | where | why it helps |
|---|---|---|
| `Skip EFB Access from CPU` | GFX.ini `EFBAccessEnable = False` | removes a per-frame CPU readback, one of the largest single-thread costs |
| `Store EFB Copies to Texture Only` | GFX.ini `EFBToTextureEnable = True` | avoids the CPU path for EFB copies |
| DSP on HLE / no audio | Dolphin.ini `[DSP] Backend = No Audio` | `DSPThread = True` already offloads, but audio still syncs |
| Internal resolution 1x | GFX.ini `InternalResolution = 1` | GPU-side, so not the bottleneck here |

I have **not** applied these, because `GFX.ini` is currently empty and Dolphin rewrites its config on exit - editing it while the game runs would be thrown away, and
changing them needs a relaunch to test.

## The honest status of "speedrunning at 10x"

**Measured 3.6x, and the reason 10x is out of reach is now known and quantified**: 1.04 cores pinned on a 16-thread machine with an idle GPU. That is a fact about
this hardware, not about the bot or the mod surface.

If 10x is a hard requirement, the answer is either those settings (which trade visual fidelity for CPU time) or a faster single core - not more code.
