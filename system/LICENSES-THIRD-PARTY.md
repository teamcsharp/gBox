# Third-party components

gBox bundles almost no third-party code. Python dependencies are installed via pip, and external tools run as separate processes.
The exceptions are vendored under `gbox/vendor/`, each with its licence file and pinned upstream commit:

| Vendored | Use | License | Where |
|---|---|---|---|
| universal-modder (rehan-remade), commit 5ba8150e27b4f1bf17ae19dcecdb2341e467885a | `um_*` tools: game scan, field notes, save backups, publish lint, sprites, ComfyUI, 3D-to-sprite | MIT | `gbox/vendor/universal_modder/` (LICENSE there; changes listed in its `__init__.py`; docs/universal_modder.md) |

| Component | Use | License | How it's integrated |
|---|---|---|---|
| FastAPI, Pydantic, Uvicorn, HTTPX | control plane | MIT / BSD-3 | pip dependency |
| RetroArch | emulator frontend | GPLv3 | separate process, UDP commands; not bundled |
| shadPS4 | PS4 emulation | GPL-2.0-or-later | optional official portable release, separate process with IPC and process-memory inspection; source: https://github.com/shadps4-emu/shadPS4 |
| Flycast (libretro core) | Dreamcast | GPLv2 | loaded by RetroArch; not bundled |
| Ghidra | static analysis | Apache-2.0 | separate process (`analyzeHeadless`); the gBox script ships in `adapters/ghidra` |
| Blender | 3D reconstruction | GPLv2+ | separate process; the bridge script runs inside Blender. ponytail: a script that imports `bpy` is arguably GPL-covered, so keep it under a GPL-compatible license if distributed |
| ffmpeg | frame capture | LGPL/GPL (build-dependent) | separate process |
| Steam client | PC launch | proprietary | `steam://` URI only |
| audio.cpp `audiocpp_server` (ShugoAI LLC; `github.com/mirek190/audio.cpp`, reviewed at `73c55549`) | local speech assistant (TTS/ASR) | Apache-2.0 (models: Kokoro-82M and Qwen3-ASR Apache-2.0) | separate process built and installed by the operator; HTTP on localhost; not bundled (`docs/audio_cpp.md`) |
| Sunshine / Moonlight (planned) | streaming + remote input | GPLv3 | separate process |
| ComfyUI | local image generation (`um_comfy`) | GPLv3 | separate server, HTTP API only; not bundled |

Check each license again before bundling anything in a Windows installer.

## Resident Evil 4 (2023) stack (`gbox/re4r.py`, `adapters/reframework/`)

Downloaded on demand by gBox into the PC's runtime folder (`D:/gBox/runtime/reframework`, `D:/gBox/runtime/re_engine`),
pinned by sha256 in `gbox/re4r.py`, never bundled in the repo. Only REFramework's `dinput8.dll` and gBox's own bridge
script are placed in the game folder, recorded in a manifest so `re4r op=uninstall` removes them. See `docs/re4-remake.md`.

| Component | Use | License | Source (exact) |
|---|---|---|---|
| REFramework (praydog) | loads into the game as `dinput8.dll`: Lua scripting, object explorer, type database, loose file loader | MIT | `github.com/praydog/REFramework-nightly` release `nightly-01424-d1461375aee4ec3f313170f8eaad12064eb542d9`, asset `REFramework.zip` (sha256 `f035f1da…2b14c`) |
| ree-pak-rs `ree-pak-cli.exe` (eigeen) | read-only extraction from `re_chunk_000.pak` + patches | MIT | `github.com/eigeen/ree-pak-rs` release `v0.7.2`, asset `ree-pak-cli.exe` (sha256 `bc4e5611…23101`) |
| `RE4_STM_Release.list` (Ekey) | file-name list for the paks (path data only) | none declared in the repo | `github.com/Ekey/REE.PAK.Tool` commit `ad05ce82c9e7412b95d410ae46be44416b23bef4`, `Projects/RE4_STM_Release.list` |
| RE Mesh Editor (NSACloud) | Blender add-on: RE Engine `.mesh`/`.mdf2`/`.tex` import/export; loaded from gBox's own scripts folder (the operator's Blender config is untouched) | GPL-3.0 | `github.com/NSACloud/RE-Mesh-Editor` commit `622daa75b41ec622c3444ecb44ef31a651692687` (zip); bundles Microsoft's texconv.dll (MIT) |
| DirectXTex `texconv.exe` (Microsoft) | PNG → DDS (BC7 …) for texture mods | MIT | `github.com/microsoft/DirectXTex` release `may2026`, asset `texconv.exe` |

`adapters/reframework/re_blender.py` imports `bpy` and RE Mesh Editor at runtime: keep it under a GPL-compatible licence
if distributed. `adapters/reframework/gbox_bridge.lua` is gBox's own code. Public RE4R REFramework scripts on GitHub
were read only to learn type/method names (`chainsaw.CharacterManager`, `CurrPTAS`, `CsInventoryController.useWeapon`…);
no code was copied. Game data extracted with these tools stays on the operator's machines (local use only).

## Controller glyphs (`clients/web/glyphs/`)

The controller diagrams in the session sidebar (`glyphs/*.svg`, embedded in `padglyph.js`) are **original line art drawn for gBox** by `glyphs/draw.py`. They contain no third-party artwork. Button layouts, shapes and colours follow the real controllers; console and button names are trademarks of their owners and are used only to identify the hardware. Wikimedia Commons photos were used **only as visual reference** while drawing (nothing copied or bundled).

Sources evaluated for reuse, and why none was bundled:

| Source | Licence | Outcome |
|---|---|---|
| [Kenney Input Prompts](https://kenney.nl/assets/input-prompts) | CC0 | Usable, but only single-button icons (no whole-controller diagrams, no Dreamcast/N64/Saturn/Mega Drive). Not used. |
| [Xelu's Free Controller & Key Prompts](https://thoseawesomeguys.com/prompts/) | CC0 | Single-button prompts for modern pads only. Not used. |
| [8th Gen Console Vector Gamepad Collection](https://opengameart.org/node/97182) (TheHoodieGuy02, OpenGameArt) | CC0 | Usable, but modern (PS4/Xbox One/Switch-era) pads only. Not used. |
| [ES-DE controller graphics](https://gitlab.com/es-de/emulationstation-de/-/tree/master/resources/graphics/controllers) (credited to Bezza191) | Not stated separately for the artwork (the repo's MIT licence names the code authors) | Not used: licence for the art not confirmed. They are also pictorial icons without per-button parts. |
| Wikimedia Commons controller photos (e.g. *Sega-Dreamcast-Controller-FL.jpg*, *N64-Controller-Gray.jpg*, *GameCube controller.png*, *Sega-Saturn-Controller-NA-Mk-II-FL.jpg*, *PSX-DualShock-Controller.jpg*, *Wii-Classic-Controller-White.jpg*, *Xbox-Controller-S-FR.jpg*, *PSP-1000.png*) | various CC BY / CC BY-SA | Looked at as layout reference only. Not copied or traced, not bundled. |

## Resident Evil 6 (Xbox 360, Xenia) stack (`gbox/re6.py`, `gbox/re6_models.py`, `gbox/re6_items.py`, `gbox/re6_tool.py`)

Nothing is downloaded or bundled: the disc reader (XDVDFS), the XEX2 image decoder, the MT Framework `.arc` reader /
writer, the LZX (XMemCompress) decoder, the Xbox 360 texture untiler / DXT1 encoder and the `.mod` / `.mrl` reader /
writer are gBox's own Python. Formats were written from public documentation, read only (no code copied):

| Reference | What it documented | License of the reference | Source |
|---|---|---|---|
| RevilLib (Lukas Cone / PredatorCZ) | MT Framework `.mod` header / primitive / bone layouts, vertex-format hashes | GPL-3.0 (read only, not linked or copied) | `github.com/PredatorCZ/RevilLib`, `src/mtf_mod/*.hpp`, `common.cpp`, `serialize.cpp` (master, read Oct 2026) |
| libmspack `lzxd.c` | the LZX bitstream (block types, pretree, aligned offsets) | LGPL-2.1 (algorithm only) | `github.com/kyz/libmspack` |
| Xenia `xex2_info.h` | XEX2 header / security-info / file-format layout | BSD-3 | `github.com/xenia-project/xenia` |

Runtime tools already in gBox: Xenia Canary (the library's RocketLauncher copy, BSD-3) and Ghidra 12.1.4 (Apache-2.0,
`adapters/ghidra/Xbox360Pdata.java` + `FindRefs.java` are gBox scripts). Item icons, names and character models are cut
from the operator's own disc into `gbox-data/re6` and the local mod folders; they are never redistributed.

## AKI wrestling (N64) stack (`gbox/aki_wrestling.py`)

Nothing is downloaded at run time or bundled. The file-table reader/writer, the Asmik LZSS decoder/encoder, the AkiModel
and Ci8 readers/writers and the MIPS hook are gBox's own Python. Formats and ROM offsets were read from open-source
references (read only, no code copied or run):

| Reference | What it documented | License | Source |
|---|---|---|---|
| VPW Studio (AKI-Club, freem) | FileTable, Asmik LZSS, AkiModel / Ci4 / Ci8 / palette layouts, per-game ROM locations, the file-id database | MIT | `github.com/AKI-Club/VPWStudio` (master, read Oct 2026) |
| akifiletable, akiarc (AKI-Club) | file table builder / archive layout | Unlicense | `github.com/AKI-Club/akifiletable`, `github.com/AKI-Club/akiarc` |
| AKI-Club docs wiki | general notes | not stated (read only) | `github.com/AKI-Club/docs/wiki` |

Wrestler models and textures are read from the operator's own ROM into the local collection and mod folders; they are
never redistributed. No community mods or models were downloaded.

## GoldenEye 007 PC port (`gbox/native_ports.py`, `adapters/ge007_port/`)

Not bundled. `native_port op=build` clones the pinned upstream commit on the worker into `<runtime>/ports/ge007/src`
and compiles it there. `op=prepare` copies the operator's own ROM into that folder and runs the port's converters on
it. The ROM and every file made from it stay in that runtime folder and never enter the repository.

| Component | Use | License | Source (exact) |
|---|---|---|---|
| GoldenEye 007 PC port (James Dansereau): port layer `port/`, build system, `tools_pc/` converters | built and run on the worker | MIT (`LICENSE`) | `github.com/jkdansereau/goldeneye-pc-port` tag `v0.6.0`, commit `5b86a9bbeba89508a0c7d6b797361b7454ceda20` |
| n64decomp/007 decompilation files carried by that repo (`src/`, `include/`, `assets/`, `tools/`) | compiled into the worker's build | none stated (the port's `NOTICE`) | same commit |
| `port/fast3d` (software RSP, Perfect Dark port / libultraship lineage) | compiled into the worker's build | MIT (`port/fast3d/LICENSE.txt`) | same commit |

`adapters/ge007_port/gbox_bridge.c` is gBox's own code: the bot bridge, copied into the worker's build. gBox also
applies two hook lines (`src/boss.c`, `port/src/input.c`) and two aarch64 fixes (`assets/animationtable_data.h`,
`src/game/bg.c`) as exact string replacements at build time. No upstream file is copied into this repository. The
bot logic (`gbox/bot_brain.py`, `gbox/ge007_bots.py`) is gBox's own Python. It was written after reading the
decompilation's guard AI; no code was copied. docs/goldeneye_bots.md cites the functions it follows.

## REA (`rea-agents` 6.0.0)

The complete tool contract catalog is derived from the MIT-licensed
https://github.com/morluto/rea npm distribution. The upstream license is preserved
in `docs/REA-LICENSE`. The pinned runtime and its transitive dependencies install
locally into each worker runtime; none of their binaries are vendored. See
`docs/rea.md` for provenance, installation, capability limits and verification.
