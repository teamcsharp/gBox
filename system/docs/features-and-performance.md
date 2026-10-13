# Features history and emulator performance

## Where to find the changes

Requests now has a **Features** button beside All, Pending and Completed. It includes every completed request and backend subtask, newest completion first. Search covers task titles, delivery notes, test steps, mods and changed files. Pages contain 25 entries to bound rendering work.

Each entry shows what was added, what was accomplished, where to find it, what to test, new mods, verification and the original task reply. **Full task & evidence** opens the task report. Linked mods have an **Open / play mod** button using the existing mod workflow. An unverified mod remains labeled unverified. Reopening a task removes it from the completed list until it is completed again.

Older tasks are included automatically. Where structured delivery notes are missing, the entry says so and retains its last agent reply, files and linked mods. Missing historical acceptance tests cannot be inferred from a `done` status.

## Recording delivery notes

Backend agents should pass `delivery` when calling `set_request_status(status="done")`. The HTTP status endpoint accepts the same object. All fields are optional for compatibility with existing completion writers:

```json
{
  "status": "done",
  "note": "Describe the actual outcome",
  "delivery": {
    "added": ["New controls or behavior"],
    "accomplished": ["Observable improvement"],
    "where": ["Exact navigation, game or command"],
    "test_steps": ["Action and expected result"],
    "mods": [],
    "verification": "Actual checks and any unverified live behavior"
  }
}
```

`PUT /api/requests/{id}/delivery` can document a historical task without changing its status or completion timestamp. `GET /api/requests/features?q=&offset=0&limit=25` is authenticated, searchable and paginated (maximum 100 entries per response). Entries are derived from current request records; no migration, duplicate changelog or scheduled rebuild is required.

## Performance controls

Open a session, then **Graphics & performance settings**:

- **Performance** saves lower-cost settings. RetroArch disables postprocessing, VSync and automatic rewind snapshots, enables the FPS display and requests above-normal Windows CPU priority on the next launch. Manual save/load remains available. RPCS3 uses native resolution, no MSAA/AF and inexpensive scaling.
- **Quality for my GPU** is the existing GPU-oriented quality preset, renamed to distinguish it from performance.
- **Defaults** restores the controls for the selected emulator.
- **Check performance** samples CPU and memory pressure on the session's worker and reads the emulator renderer from its log when available. It does not claim to measure game FPS.
- RetroArch also exposes VSync, threaded video, FPS display, rewind snapshots and Windows CPU priority separately. Threaded video is optional because it can add latency. Headless Linux keeps VSync disabled for its virtual display. Unsupported emulator settings remain explicitly unsupported.

Settings are per game on the worker. Save in-game progress before using **Save & restart game**. Preset buttons save settings without interrupting play. Start with one change, then compare the same scene using the emulator FPS display. Emulator output FPS and a game's animation rate can differ.

RetroArch launches now copy shared core defaults to a private session options file before applying compatibility settings. Concurrent games cannot overwrite each other's core settings. Existing Flycast state compatibility and N64 renderer/RSP pairing are preserved. GPU inventory is cached for 60 seconds, avoiding repeated `nvidia-smi` processes while browsing settings.

## PSO report findings and live acceptance

Report #1488's attached diagnostics and #1489's 2 FPS complaint were read on October 12, 2026. The captured PSO session used Flycast with **NVIDIA GeForce RTX 2070** as its OpenGL renderer, and a locally cached CHD on `D:`. Worker totals recorded **100% CPU**, about 49 GB of 65 GB RAM in use, and 33% GPU utilization. CPU contention is a strong lead; this snapshot alone cannot prove the sole cause of the reported slowdown. The recovery's two changing screenshots prove motion, not a playable frame rate.

After deployment, save progress, record the FPS in the affected PSO scene, run Check performance, and compare the same scene with CPU-heavy background work paused. Then compare the Performance preset after restarting. Verify audio, input, visuals and manual save/load. Restore Defaults and restart to verify settings rollback. Repeat on representative systems before claiming universal performance. Live i9 FPS improvement has not yet been measured by this change.

For Features acceptance, complete a task and a child task with distinct delivery notes, confirm both appear and are searchable, open their evidence and linked mods, then reopen one task and confirm it leaves the list. Historical tasks should remain accessible with honest documentation gaps.

## Validation of this change

89 focused Python tests passed across performance settings, Features persistence and filtering, emulator adapters, Flycast/N64 compatibility, rewind, gamepads and emulation recovery. Eight JavaScript checks passed. A separate headless browser exercised Features search, pagination, report/mod callbacks, newly completed entries, error recovery, performance/defaults/save/diagnostic controls and worker routing with fixture data; no browser errors occurred. This is UI and configuration verification, not a live PSO frame-rate benchmark. The optional MCP integration suite was skipped because the test runtime does not have the MCP package.

Run the focused Python suite from `system`:

```text
python -m pytest tests/test_graphics_performance.py tests/test_request_features.py tests/test_flycast_state_opts.py tests/test_n64_angrylion_rsp.py tests/test_request_metrics_detail.py tests/test_rewind.py tests/test_adapters.py tests/test_gamepads.py tests/test_emulation_issue.py -q
node --test tests/test_request_features.cjs tests/test_request_solvers.cjs
```

Deploy the updated control plane, desktop client (including `request-features.js`) and worker code together. Existing processes need to reload the changed code; this checkout's tests do not update a running remote worker.
