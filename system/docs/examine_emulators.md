# Examine 3D across emulators (#971)

`gbox/scene_support.py` answers, for every session, whether **Examine 3D** can rebuild the frame on screen as a 3D
scene. `scene_capture.support(adapter, core, driver)` returns one of:

- `supported`: RenderDoc captures this renderer as it runs.
- `relaunch_under_capture`: capturable after a relaunch. `driver` names the backend the capture session must use
  (`vulkan` first, `glcore` for GL-only cores). With `driver: null` the session only needs RenderDoc inside
  (it started without Examine 3D) and the panel offers *Save state and relaunch for 3D capture*.
- `unsupported`: no 3D capture path today. `fallback: frame_2d` means the panel shows the live 2D frame, labelled 2D-only.

Every launch stores the row in the session (`detail.scene_capture`, `capabilities.scene_capture`). The Examine 3D
panel shows that reason instead of the generic capture error, and `scene_capture` raises the same reason when
RenderDoc isn't inside the process.

## Matrix

| Emulator / core | Status | Capture driver | Notes |
|---|---|---|---|
| RetroArch, D3D11/D3D12/Vulkan core | supported | (current) | needs Examine 3D on at launch |
| RetroArch, GL session of a Vulkan-capable core (Flycast, ParaLLEl N64, Beetle PSX HW, PCSX2, Dolphin, Citra, SwanStation, PPSSPP) | relaunch_under_capture | vulkan | agent-owned capture session only |
| RetroArch, GL-only 3D core (Kronos, YabaSanshiro, melonDS, Play!) | relaunch_under_capture | glcore | not live-checked |
| RetroArch, software core (Snes9x, Genesis Plus GX, mGBA, FBNeo, ...) | unsupported | - | 2D frame only |
| Dolphin (Windows, D3D12) | supported | (current) | |
| Yuzu (Windows, Vulkan) | relaunch_under_capture | vulkan | agent-owned capture session; the operator's game keeps running |
| RPCS3 (Windows, Vulkan) | relaunch_under_capture | vulkan | agent-owned capture session; the operator's game keeps running |
| Xenia, Steam, RocketLauncher, Linux sessions | unsupported | - | 2D frame only |

## Status of the plan

1. Capability matrix, session capabilities and panel reason: **done** (`tests/test_scene_support.py`).
2. Vulkan-first capture sessions for RetroArch (`video_driver=vulkan` + RenderDoc's Vulkan layer, only in an
   agent-owned capture session's config): **done** (`gbox/capture_relaunch.py`, `tests/test_capture_relaunch.py`).
3. *Capture again* on the operator's live RetroArch session (save state, capture session, load state, capture,
   GLB handed back): **done**.
4. Standalone Vulkan emulators (Yuzu, RPCS3): capture session architecture and Yuzu launcher in place
   (`frame_rip.launch_yuzu`, `capture_relaunch` Yuzu path). Live check on JAYBUILTFINALE is outstanding.
5. 2D fallback for software cores and Xenia: the panel labels these rows 2D-only and shows the live frame. Frame dump /
   free-look integration is **not started**.

## Live checks

Run these on the agent test PC (JAYBUILTFINALE, 2% audio), never in the operator's session:

- PSO Ver.2 (Flycast, RetroArch GL) -> `relaunch_under_capture`, driver `vulkan`.
- A PS2 game (pcsx2 core, d3d11) -> `supported`; Examine 3D returns a GLB.
- A Switch game (Yuzu) -> `relaunch_under_capture`, driver `vulkan`; agent-owned capture session boots fresh.
- A SNES game (snes9x) -> `unsupported`, 2D frame only.

## Capture sessions for `relaunch_under_capture` rows (#971 stages 2-3)

When a RetroArch session rates `relaunch_under_capture` with driver `vulkan` or `glcore` (for example PSO Ver.2 on
Flycast under `gl`), **Examine 3D** no longer stops at the reason text. `scene_capture` calls
`gbox/capture_relaunch.py`, which works as follows:

1. It saves the operator's moment to the agent-owned state slot 70 and puts the operator's slot counter back.
2. It starts a separate RetroArch under RenderDoc (`frame_rip.launch`) with the same core file and content. The
   capture session uses its own config dir, `runtime/capture_sessions/<ms>/ra.cfg`, and never touches the operator's
   `retroarch.cfg`. Its video_driver is the matrix driver: `vulkan` loads RenderDoc's Vulkan layer for that process
   only (`VK_LAYER_PATH`, `VK_INSTANCE_LAYERS`, `ENABLE_VULKAN_RENDERDOC_CAPTURE`) with no injection, and `glcore`
   requests the core-profile GL context that RenderDoc supports.
3. It loads the saved state (slot 0, in a flat state folder), captures, rebuilds the GLB and stops the capture
   session.

The operator's game is never paused. The result carries `summary.capture_session` = {driver, moment
(`save_state` | `fresh_boot`), note, work}, plus `paused: false` and `resume_on_leave: false`. If the save fails,
the capture session boots the content fresh and says so in `note`.

Live check, still outstanding, on JAYBUILTFINALE after deployment: launch PSO Ver.2 (Flycast, `gl`), press
Examine 3D, and expect a GLB with `capture_session.driver = vulkan`, `moment = save_state`, and the operator's
window still running. Then repeat with a GL-only core (`glcore`).

## Standalone Vulkan capture sessions (Yuzu, RPCS3)

Yuzu and RPCS3 rate `relaunch_under_capture` with driver `vulkan`. `capture_relaunch` starts a separate,
agent-owned process for these emulators:

- Yuzu is launched under `renderdoccmd` with `--user-path <agent-owned dir>` and `[Renderer] backend=Vulkan`
  forced in `qt-config.ini`, so RenderDoc's Vulkan layer captures the frame without touching the operator's
  Yuzu profile.
- The operator's game keeps running. Yuzu save-state moment preservation is not implemented yet, so the
  capture session boots fresh and the result says `moment: fresh_boot`.
- Captures are handed to the same `scene_capture.extract` path used by RetroArch, producing a GLB for the
  Examine 3D panel.

RPCS3 uses the same architecture; its launcher (`frame_rip.launch_rpcs3`) is the remaining piece once the
Yuzu path is live-checked.
