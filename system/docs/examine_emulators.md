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
| Yuzu | unsupported | vulkan (planned) | still frame only today |
| RPCS3 | unsupported | vulkan (planned) | still frame only today |
| Xenia, Steam, RocketLauncher, Linux sessions | unsupported | - | 2D frame only |

## Status of the plan

1. Capability matrix, session capabilities and panel reason: **done** (`tests/test_scene_support.py`).
2. Vulkan-first capture sessions (`video_driver=vulkan` + RenderDoc's Vulkan layer, only in an agent-owned capture
   session's config): **not started**. The matrix already names the driver each row needs.
3. *Capture again* on the operator's live session (save state, capture session, load state, capture, GLB handed back):
   **not started**.
4. 2D fallback for software cores and Xenia: the panel labels these rows 2D-only and shows the live frame. Frame dump /
   free-look integration is **not started**.

## Live checks

Run these on the agent test PC (JAYBUILTFINALE, 2% audio), never in the operator's session:

- PSO Ver.2 (Flycast, RetroArch GL) -> `relaunch_under_capture`, driver `vulkan`.
- A PS2 game (pcsx2 core, d3d11) -> `supported`; Examine 3D returns a GLB.
- A Switch game (Yuzu) -> `unsupported`, reason names the planned Vulkan route; the still frame is still available.
- A SNES game (snes9x) -> `unsupported`, 2D frame only.
