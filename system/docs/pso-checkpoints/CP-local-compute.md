# Local compute on PSO: Ghidra analysed the executable, and Ollama is up

## Ghidra decompiled PSO's main executable on this machine

`D:\gBox\pso-ds\pso_v3.elf` (4.99 MB) through `analyzeHeadless`:

```
Total Time   149 secs
REPORT: Analysis succeeded for file: /D:/gBox/pso-ds/pso_v3.elf
REPORT: Save succeeded for: /pso_v3.elf (pso:/pso_v3.elf)
```

and read back through PyGhidra from the project at `D:\gBox\pso-ds\ghidra_proj`:

```
language: PowerPC:BE:32:default   entry point: 0x8000c040   5 memory blocks
largest functions: 10784 bytes @ 0x803b5eac, 6392 @ 0x80011824, 6292 @ 0x8027375c ...
strings recovered: MESETA, TAdADXlogo, AdDrawLineTask.prs, adx_logo, sofdec_logo, end_font-gc_01 ...
```

**That is the game's code, in a queryable database, analysed by the local Ghidra.** `MESETA` is PSO's currency, `adx_logo`/`sofdec_logo`
are CRI ADX (Sega's audio middleware) and Sofdec (its video middleware), and `TAd*` are the classes behind them - so the analysis is reading real
internals, not noise.

Two syntax facts cost a run each: `analyzeHeadless` needs `-import` before the file, and `PowerPC:BE:32:Gekko` is **not** a language id in this
install - omitting `-processor` lets Ghidra detect `PowerPC:BE:32:default` correctly.

`gbox ghidra-bridge-install` also succeeded (`pyghidra 3.1.0` into `D:\gBox\runtime\pyghidra-venv`), and the module validates locally -
`ghidra_bridge.unavailable(config)` returns `None` - although the **worker** still reports it unavailable, so the bridge path needs one more look
even though direct analysis works.

## The GPU and the local models

```
NVIDIA GeForce RTX 3090   24576 MiB   103 MiB used   0 %     <- idle, 24 GB free
NVIDIA GeForce RTX 2070    8192 MiB  1109 MiB used  19 %
Ollama: started (gBox.LocalOllama) - deepseek-r1:14b (8.4 GB), deepseek-r1:8b (4.6 GB)
```

The 3090 is idle and Ollama is serving two reasoning models, so local inference is available for analysis that suits an LLM rather than an analyst.

## The disc's own map, for path-guiding

`pso_coop_town` already carried the city's collision, and it loads straight off the disc:

```
REL Scene/map_city00_00c.rel   70144 bytes
sha256 6d5f5d5d0ff9c18958d1ab577e5be9e6f83c66808537b085ca4c9d2cd97535ec  -> matches the module's REL_SHA
1497 triangles -> 5626 walkable cells, 4959 safe cells
landmarks: TObjCityDoor_Warp (254.001, 0, 25.002), TObjCityDoor_Guild, TObjCityDoor_Med
platform: (360.003, 25.998)
```

`Corridor.route(start)` then returns a real A* path with every leg checked against the mesh. **It only covers the east town (x 180-380, z 5-290)**,
and the wandering bot had taken the character to `(-340.8, -153.5)`, outside it - which is why the route came back empty. Writing the position to
the warp re-placed it at `(232.4, -5.7)`: inside the x range and **just below** the z range, one short walk from usable.

## The worker trap, now understood

Twice the worker refused to activate with:

```
RuntimeError: Worker activation held: a delivered native launch still has an owned PID record; no emulator was stopped
```

Both times the cause was the same: **restarting gBox while a session runs orphans its emulator**, the orphan keeps its PID in `gbox-running.json`, and
`protected_sessions` correctly refuses to start a worker that would abandon it. **The rule: stop the session before restarting gBox.** Clearing the
orphan and the manifest brings the worker up in seconds.

## Controller

`operator_slot` used to fall back to **slot 0** - the virtual pad - and cache it forever; the bot's own presses then looked like the operator taking
over, and `pad_takeover` dropped them. Fixed: the session's vpad slot is recorded and excluded, a pad that merely answers is accepted, and `-1` means
"no operator pad". **But XInput currently enumerates no physical pad at all** (`slot 0` absent after the restart, `1-3` absent before), so there is
nothing for the relay to mirror - the controller has to be reconnected/woken before it can reach the game.
