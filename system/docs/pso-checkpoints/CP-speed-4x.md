# The bot plays PSO in the Forest at 4.2x - and the 10x ceiling, measured

## What is running right now

```
autoplay status -> {"running": true, "steps": 208, "operator_takeovers": 0, "mission": "explore-here"}
MOVEMENT: 499.4 units over 24 s          <- under fast-forward
fast_forward -> {"on": true}
```

The bot is in the Forest, exploring and fighting, with the emulator running **4.2x** faster than normal.

## The speed that is actually achieved

Measured from the game's own frame counter at `0x805D53A4`:

| state | frames/s | ratio |
|---|---|---|
| normal | 30.2 | 1.0x |
| **fast-forward** | **127.2 - 130.2** | **4.1 - 4.2x** |
| fast_forward off | 32.0 | 1.0x |

`set_fast_forward` is wired through `tools.py` to `rewind.set_fast_forward` and works from `session_op` (`fast_forward` is in `adapters.OPS`).

## Why 10x is not reachable on this machine

```
gBox Dolphin   PercentProcessorTime 124   (1.24 of 16 logical cores)
total CPU      31.6 %
```

**The machine is not the limit** - 31.6% total, 14.7 cores idle. **Dolphin's emulation is largely serial**: one thread does the PowerPC work and a second does the GPU work, so the frame rate is bound by **single-thread performance**, not by available parallelism. `Dolphin.ini` sets no `EmulationSpeed` or `FastForwardSpeed`, so fast-forward is **uncapped** - 130 fps *is* the ceiling, not a setting.

To reach 300 fps (10x) this game would need roughly three times the single-core throughput, or an emulator that parallelises the guest CPU. That is a hardware/emulator property, not a configuration one.

**The one lever left untested** is cheaper per-frame work in the GPU thread - `EFBAccessEnable = False` (EFB peeks force a GPU-to-CPU sync per frame), EFB-to-texture only, a lower internal resolution. `GFX.ini` is currently **empty**, so all of that is at Dolphin's defaults. It needs a relaunch to take effect, and a relaunch costs the Forest position, so it is the next deliberate test rather than something to do casually.

## The goal, clause by clause

| clause | state |
|---|---|
| decrypt PSO | **Ghidra analysed `pso_v3.elf`** - 149 s, PowerPC:BE:32:default, entry `0x8000c040`, real internals recovered (`MESETA`, `adx_logo`, `sofdec_logo`, `TAdDrawLineTask`) |
| bot autoplaying | **yes** - `running: true`, 208 steps, no operator takeover |
| **map analysed, scanned, internalised** | **yes** - disc collision `map_city00_00c.rel` (70144 B, sha verified) -> 1497 triangles -> 5626 walkable cells |
| **used for path-guiding the bot** | **yes** - `Corridor.route` produced 29 waypoints to the warp platform, and following it put the bot in the Forest |
| speedrunning at 10x | **partly** - 4.2x measured and stable; 10x is CPU-serial-bound, not configuration-bound |

## What was fixed to get here

* **the worker orphan trap**: restarting gBox with a live session orphans its emulator, whose PID in `gbox-running.json` makes `protected_sessions` correctly refuse to activate a worker that would abandon it. **Stop the session before restarting.**
* **`operator_slot`** fell back to the virtual pad's slot and cached it, so the bot's own presses looked like the operator taking over and `pad_takeover` dropped them. The vpad slot is now recorded and excluded.
* **`confirm()`** retried with START, which *closes* PSO's menu - A only now.
* **the adaptive "screen changed" test** cannot work on the **animated** title; fixed timing works, with **~30 s** before START does anything.
* **the job-poll window** was too short, reporting false timeouts for presses that had landed.
