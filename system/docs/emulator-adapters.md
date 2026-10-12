# Emulator / runtime adapters

Interface: `gbox/adapters.py`. The ops list in `OPS` mirrors plan §6. `get_capabilities()` maps every op to `supported`/`unsupported`, and unsupported calls raise `Unsupported`. A live session's capabilities also carry `rewind = native | checkpoint | unsupported | off`: Select+L2 rewind / Select+R2 fast-forward on the operator's pad in every game, through the emulator's own rewind or gBox's checkpoint ring (`gbox/rewind.py`, [rewind.md](rewind.md)).

| Adapter | Platforms | Supported | Status |
|---|---|---|---|
| RetroArchAdapter | any libretro core, first is Dreamcast/Flycast | launch, stop, pause, resume, read/write memory, save/load state, step frames, query, screenshot | protocol tested against a fake; no real RetroArch yet |
| CommandAdapter | any emulator CLI | launch, stop, query | tested |
| SteamAdapter | pc_steam | launch | uses the real Steam client's URI; not run in tests |

Configure one per platform:

```toml
[emulators.dreamcast]
adapter = "retroarch"
executable = "/usr/bin/retroarch"
core = "/usr/lib/aarch64-linux-gnu/libretro/flycast_libretro.so"
stage_local = true      # copy from the NAS into the LRU cache before launch
```

Open questions to verify on real builds:

- Does Flycast expose SH-4 main RAM to `READ_CORE_MEMORY`? It requires a core memory map.
- RetroArch's network-remote input (port 55400) for `send_input`.
