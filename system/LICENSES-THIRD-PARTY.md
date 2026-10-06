# Third-party components

G-Box bundles **no** third-party code. Python dependencies are installed via pip, and external tools run as separate processes.

| Component | Use | License | How it's integrated |
|---|---|---|---|
| FastAPI, Pydantic, Uvicorn, HTTPX | control plane | MIT / BSD-3 | pip dependency |
| RetroArch | emulator frontend | GPLv3 | separate process, UDP commands; not bundled |
| Flycast (libretro core) | Dreamcast | GPLv2 | loaded by RetroArch; not bundled |
| Ghidra | static analysis | Apache-2.0 | separate process (`analyzeHeadless`); the G-Box script ships in `adapters/ghidra` |
| Blender | 3D reconstruction | GPLv2+ | separate process; the bridge script runs inside Blender. ponytail: a script that imports `bpy` is arguably GPL-covered, so keep it under a GPL-compatible license if distributed |
| ffmpeg | frame capture | LGPL/GPL (build-dependent) | separate process |
| Steam client | PC launch | proprietary | `steam://` URI only |
| Sunshine / Moonlight (planned) | streaming + remote input | GPLv3 | separate process |

Check each license again before bundling anything in a Windows installer.
