# Emulator / runtime adapters

Interface: `gbox/adapters.py`. The ops list in `OPS` mirrors plan §6. `get_capabilities()` maps every op to `supported`/`unsupported`, and unsupported calls raise `Unsupported`. A live session's capabilities also carry `rewind = native | checkpoint | unsupported | off`: Select+L2 rewind / Select+R2 fast-forward on the operator's pad in every game, through the emulator's own rewind or gBox's checkpoint ring (`gbox/rewind.py`, [rewind.md](rewind.md)).

| Adapter | Platforms | Supported | Status |
|---|---|---|---|
| RetroArchAdapter | any libretro core, first is Dreamcast/Flycast | launch, stop, pause, resume, read/write memory, save/load state, step frames, query, screenshot | protocol tested against a fake; no real RetroArch yet |
| CommandAdapter | any emulator CLI | launch, stop, query | tested |
| ShadPS4Adapter | PS4 on Windows x64 | launch/stop, native frame, default keyboard input, 64-bit process RAM/read-write/disassembly; pause/resume when IPC advertises it | core CLI verified; game validation pending; [setup and limits](shadps4.md) |
| SteamAdapter | pc_steam | launch | uses the real Steam client's URI; not run in tests |
| YuzuAdapter | Switch on Windows | launch/stop, window frame, pause/resume, keyboard pad via the XInput bridge, GDB stub (arm64) on a private debug launch | the operator's portable Yuzu; readiness = a visible game window (#3688/#3769 open) |
| SwitchLinuxAdapter (`eden`) | Switch on Linux (the Spark, aarch64) | launch/stop, stream, frame, xdotool pad (Eden's keyboard layout), pause/resume (SIGSTOP), read/write memory through /proc/<pid>/mem at Eden's HostMemory arena (direct addressing under NCE), GDB stub on debug launches | built from Eden's sources, unit-tested with fakes, not yet run live: [decision and caveats](research/switch-emulator-spark.md) |

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
