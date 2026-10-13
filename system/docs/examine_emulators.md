# Examine 3D across emulators (#971)

`gbox/scene_support.py` answers, for every session, whether **Examine 3D** can rebuild the frame on screen as a 3D
scene. `scene_capture.support(adapter, core, driver, hooked=...)` returns one of:

- `supported`: RenderDoc captures this renderer as it runs (it is inside the emulator).
- `relaunch_under_capture`: capturable in a separate **capture session**. `driver` is the backend that session
  runs (`vulkan` first, `d3d11` for PS2, `glcore` for GL-only cores) and `attach` how RenderDoc gets in (`layer` =
  RenderDoc's Vulkan layer, no injection; `inject` = renderdoc.dll loaded at process start). With `relay: true`
  *Capture again* captures the operator's exact moment without touching their game (below). With `relay: false`
  the emulator's save states can't be carried (Yuzu, RPCS3), so the game itself has to be relaunched with Examine 3D on.
- `unsupported`: no 3D capture path. `fallback: frame_2d` means the panel shows the live 2D frame, labelled 2D-only.

`verified: true` marks rows whose capture session was run end to end on the test PC (live checks below).
Every launch stores the row in the session (`detail.scene_capture`, `capabilities.scene_capture`).

## Capture sessions (stage 2)

A capture session is a second copy of the game that gBox starts only to capture one frame. It is agent-owned:

- **Its own config only.** RetroArch gets `runtime/capture_sessions/ra-<port>/retroarch.cfg`, a *copy* of the
  operator's core options with the renderer pinned, and its own `states/`, `saves/`, `shots/` folders. Dolphin's
  backend is switched with `-C Dolphin.Core.GFXBackend=Vulkan` (Dolphin's command-line layer is never saved). RPCS3
  gets `--config <own yml>` with `Video: Renderer: Vulkan`. The operator's retroarch.cfg, core-options.cfg, Dolphin
  and RPCS3 configs are only read (`tests/test_capture_backend.py` checks this).
- **No sound, no pads, no hotkeys, never on screen.** Audio off; every player is bound to a pad slot that doesn't
  exist (RetroArch on Windows has no null joypad driver and reads XInput without focus); the window opens
  shown-but-not-activated and is parked off-screen for its whole life (a minimized window presents no frames).
  No rewind ring, no gameplay recording. The session is labelled `owner: agent` in the tray.
- **RenderDoc through its Vulkan layer.** `capture_backend.layer_env` points the Vulkan loader at the portable
  RenderDoc folder's `renderdoc.json` (`VK_ADD_IMPLICIT_LAYER_PATH` + `ENABLE_VULKAN_RENDERDOC_CAPTURE=1`, with
  `VK_ADD_LAYER_PATH`/`VK_INSTANCE_LAYERS` as the explicit fallback for older loaders, stale
  `DISABLE_VULKAN_RENDERDOC_CAPTURE_*` removed, `RENDERDOC_CAPFILE` = capture path). renderdoc.dll is loaded by the
  loader when the game makes its Vulkan device: no process injection, no registry change. `layer_check` confirms it
  is mapped before the session reports `examine: true`. D3D11 (PS2) and glcore keep the injection path.
- **RenderDoc is provisioned.** A capture PC without RenderDoc gets the pinned portable build
  (`RenderDoc_1.46_64.zip` from renderdoc.org, sha256-checked) in `<runtime>/tools`.

Backend per emulator (`capture_backend.plan`):

| Emulator / core | Capture session backend | RenderDoc | Core option pinned |
|---|---|---|---|
| RetroArch Flycast | `video_driver=vulkan` | Vulkan layer | (follows the frontend) |
| RetroArch Beetle PSX HW | vulkan | Vulkan layer | `beetle_psx_hw_renderer = hardware_vk` |
| RetroArch Dolphin core | vulkan | Vulkan layer | `dolphin_renderer = Hardware` |
| RetroArch Citra | vulkan | Vulkan layer | `citra_graphics_api = Vulkan` |
| RetroArch SwanStation / DuckStation | vulkan | Vulkan layer | `swanstation_GPU_Renderer` / `duckstation_GPU.Renderer = Vulkan` |
| RetroArch PPSSPP | vulkan | Vulkan layer | `ppsspp_backend = vulkan` |
| RetroArch PCSX2 / LRPS2 | `video_driver=d3d11` | injected | (Vulkan renderer aborts on the test PC) |
| RetroArch Mupen64Plus-Next | `video_driver=glcore` | injected | GLideN64 + HLE RSP |
| RetroArch GL-only cores (Kronos, YabaSanshiro, melonDS, Play!) | glcore | injected | - |
| RetroArch core not in the matrix | vulkan (tried first) | Vulkan layer | - |
| Dolphin (standalone) | `-C Dolphin.Core.GFXBackend=Vulkan` | Vulkan layer | - |
| RPCS3 | `--config` with `Renderer: Vulkan` | Vulkan layer | - |
| Yuzu | its default Vulkan renderer (qt-config `[Renderer] backend`) | Vulkan layer | - |

Yuzu and RPCS3 also start the **operator's own** session with RenderDoc's Vulkan layer when Examine 3D is on (only
the environment changes, never their config), so they are `supported` live when they render with Vulkan.

## Capture again keeps the moment (`gbox/scene_relay.py`)

For a `relay` row, `POST /api/jobs {"tool": "scene_capture", "input": {"session_id", "relay": true}}` (or the row
alone) becomes the in-server job `scene_relay`, polled like `scene_capture`:

1. `state_transfer export` on the operator's session: their game keeps running, nothing is paused.
2. `launch_game` with `capture_backend` + `capture_for` on the test PC (`examine_capture_worker`, default
   JAYBUILTFINALE) when it is online, ticked for background testing (Tasks menu), has no live game and isn't the
   operator's PC. Otherwise RetroArch runs the capture session hidden on the operator's own worker beside their game
   (`keep_session`: their game is not closed). Dolphin capture sessions only run on another PC (they would share the
   operator's portable User folder). If the test PC's launch fails, RetroArch retries on the operator's PC.
3. `state_transfer import` into the capture session (it saves and loads in its own state folder).
4. `scene_capture` on the capture session (RenderDoc frame, scene.glb, frame.png from RetroArch's own SCREENSHOT).
5. `session_op stop_game` on the capture session, always, and the session is marked ended.

The output is `scene_capture`-shaped (`glb`, `summary`, `paused: false`, `resume_on_leave: false`) plus
`capture_session` (worker, where, driver, attach, moment, load_verified, seconds). The Examine 3D panel starts it when
entering Examine on a relay row, shows *Captured in: capture session on JAYBUILTFINALE (test PC) · vulkan · your game
kept running*, never pauses or resumes the operator's game for it, and keeps that scene when you come back to the
tab; *Capture again* takes a new one. Failures say why and that the game keeps running
(`tests/test_scene_relay.py`, `tests/test_examine_relay.cjs`).

## Matrix (after stage 2)

| Emulator / core | Status | Capture session | RenderDoc | Notes |
|---|---|---|---|---|
| RetroArch, D3D11/D3D12/Vulkan session with Examine 3D on | supported | (current) | injected at launch | |
| RetroArch, D3D/Vulkan session started without Examine 3D | relaunch_under_capture (relay) | vulkan for Vulkan-capable cores, else the same driver | layer / injected | game keeps running |
| RetroArch, GL session of a Vulkan-capable core (Flycast, Beetle PSX HW, Dolphin, Citra, SwanStation, DuckStation, PPSSPP) | relaunch_under_capture (relay) | vulkan | Vulkan layer | Flycast + PPSSPP live-checked |
| RetroArch PS2 (pcsx2 / LRPS2) | supported with Examine 3D on (D3D11); relay otherwise | d3d11 | injected | Vulkan aborts; D3D11 capture held no GS draws on the test PC |
| RetroArch, GL-only 3D core (Kronos, YabaSanshiro, melonDS, Play!) | relaunch_under_capture (relay) | glcore | injected | not live-checked |
| RetroArch N64, Mupen64Plus-Next | relaunch_under_capture (relay) | glcore + GLideN64 | injected | not live-checked |
| RetroArch N64, ParaLLEl N64 | unsupported | - | - | no draw calls (ParaLLEl-RDP) / compat GL; 2D frame only |
| RetroArch, software core (Snes9x, Genesis Plus GX, mGBA, FBNeo, ...) | unsupported | - | - | 2D frame only |
| Dolphin (Windows, D3D12) with Examine 3D on | supported | (current) | injected at launch | |
| Dolphin started without Examine 3D | relaunch_under_capture (relay) | vulkan (-C Dolphin.Core.GFXBackend=Vulkan) | Vulkan layer | test PC only; capture held 1 draw (open) |
| Yuzu / RPCS3 on Vulkan with Examine 3D on | supported | (current) | Vulkan layer at launch | |
| Yuzu / RPCS3 started without Examine 3D | relaunch_under_capture | relaunch the game | Vulkan layer | states can't be carried |
| Yuzu / RPCS3 set to OpenGL | unsupported | - | - | switch the emulator to Vulkan |
| Xenia, Steam, RocketLauncher, Linux sessions | unsupported | - | - | 2D frame only |

## Live checks

Run on the agent test PC (JAYBUILTFINALE, RTX 3070), never in an operator session: the capture session is started
through the real adapter code (`capture_backend.plan` -> RetroArchAdapter/DolphinWinAdapter launch with
`capture_backend`), a saved moment is loaded the way `state_transfer import` does (save into the session's own state
folder, overwrite, load that slot), then `scene_capture.capture_session` runs. RenderDoc 1.46 portable was
provisioned by `scene_capture.ensure_renderdoc`.

| Game (core) | Backend | Result (2026-10-13) |
|---|---|---|
| PSO Ver.2 (Flycast), the operator's GL moment in Pioneer 2's teleporter | vulkan + layer | **pass**: renderdoc.dll loaded by the Vulkan loader (no injection); the screenshot after the load matches the operator's state thumbnail; 281 draws -> 200 scene + 47 HUD, 15 textures, 1469 triangles, binary glTF 388 KB; capture 7 s, rebuild 42 s. The rebuilt teleporter rings, platform, walls and character are 3D from an orbit view. Needed the new `flycast` extract mode: Flycast draws screen-space vertices (w = 1) with `vtx_uv = (u*q, v*q, q)`. |
| Naruto Shippuden: Ultimate Ninja Impact (PPSSPP), saved moment | vulkan + layer | **pass** (capture path): layer loaded, moment restored (the PSP username keyboard), 29 draws -> 22 HUD, 10 textures. That moment is 2D, so no 3D layer. |
| Def Jam: Vendetta (pcsx2 = LRPS2) | vulkan | **fail**: LRPS2's Vulkan renderer aborts on this PC with or without RenderDoc ("Failed to allocate expansion index buffer", 0xC000041D). |
| Def Jam: Vendetta (LRPS2) | d3d11 + injection | **fail**: the session runs and the moment loads, but the capture holds only RetroArch's 3 present blits (also in a plain booted session): the GS draws are not in RetroArch's captured frame. Open: PS2 scene capture needs a follow-up. |
| Super Mario 64 (ParaLLEl N64), Glide64 HLE on glcore | glcore + injection | **fail**: crashes under injection; without RenderDoc the core asks for a compatibility GL context and stalls under glcore. ParaLLEl N64 is now `unsupported` (2D frame). |
| Bloody Roar: Primal Fury (standalone Dolphin) | `-C GFXBackend=Vulkan` + layer | **partial**: Dolphin runs and RenderDoc loads through the layer, but after 20 s and 90 s of attract the captured frame held 1 draw (the XFB present). Open. (Dolphin's D3D12 + injection exited on this PC during the same check.) |

Reproduce with `scratchpad/live/live_capture.py <platform> <core> <rom> <state|-> <out>` (kept out of the repo:
it launches emulators directly). Not live-checked yet: the server relay end to end (needs this branch deployed on the
Spark and both workers; covered by `tests/test_scene_relay.py` with a fake control plane), Yuzu/RPCS3 with the layer,
glcore cores, Citra/SwanStation/Beetle PSX HW.

## Status of the plan

1. Capability matrix, session capabilities and panel reason: **done** (stage 1, `tests/test_scene_support.py`).
2. Vulkan-first capture sessions with RenderDoc's Vulkan layer, agent-owned config only: **done**
   (`gbox/capture_backend.py`, `tests/test_capture_backend.py`); Flycast and PPSSPP live-checked.
3. *Capture again* keeps the moment (save state -> capture session -> load -> capture -> GLB to the panel):
   **done in code** (`gbox/scene_relay.py`, server `relay_job`, panel), tested with fakes; live relay after deploy.
4. 2D fallback for software cores, Xenia and ParaLLEl N64: the panel labels these rows 2D-only and shows the live
   frame. Frame dump / free-look integration is **not started**.
5. Open: PS2 (LRPS2) GS draws missing from the D3D11 capture; Dolphin Vulkan capture holding only the XFB present.
   Both now come back labelled 2D-only with the reason instead of as an empty 3D scene (see *Empty frames* below),
   and every capture attempt is listed in `summary.capture_attempts`, so the next live check shows whether the
   running-game retry reaches the game's draws.

## Empty frames: retry, then 2D-only

A rebuilt frame with no 3D draw and at most `EMPTY_SCENE_MAX_DRAWS` (6) draw calls is the emulator's own present,
not the game: the cached frame a paused RetroArch re-presents without running the core, a 30 fps game's duplicate
frame, Dolphin's XFB-only frames (movies, logos, attract), or a renderer drawing outside the device RenderDoc
captures (LRPS2 on D3D11 so far). `scene_capture` then captures `RETRY_FRAMES` (4) more frames once with the game
running (after `RETRY_SETTLE_S` = 1 s), keeps the busier rebuild and pauses the game again. In a relay this runs in
the capture session, so the operator's game is still untouched; on a session captured directly it moves that game
on by about a second, and only when the first frame was empty.

If the kept frame still has no 3D draw, the result carries `fallback: "frame_2d"`, `scene_empty` (true: present
blits only; false: a real 2D screen with HUD draws) and a `note` with the reason (plus the known PS2 / Dolphin gap).
The Examine panel shows a "3D scene: none (2D-only)" row with that note and, after a retry, the draw counts of each
attempt. Tests: `tests/test_scene_capture_empty.py`.
