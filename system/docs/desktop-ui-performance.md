# Desktop app performance and pop-ups over the docked game (#712, #1081)

## How it was measured

`scripts/ui-perf/probe.cjs` runs the desktop shell (`clients/desktop/index.html`) and the embedded gBox view
(`clients/web`) from any checkout in an isolated Electron instance with the app's own GPU switches. It is read-only
against the control plane (GETs are forwarded, every other method is refused, live video/desktop streams are not
opened), stubs every native call (no worker, no game windows touched) and keeps its own profile, so it runs beside the
operator's app. After a 15 s warm-up it records a 60 s window:

- main-thread time, layouts and style recalculations per renderer (DevTools `Performance.getMetrics`),
- long tasks (> 50 ms), DOM size, endless CSS animations,
- CPU per Electron process (browser, GPU, renderers),
- every control-plane request (count, bytes, latency per endpoint),
- `--interact`: click-to-paint latency of the sidebar sections,
- `--docked`: a synthetic native game docked on this PC, and the time from a pop-up opening/closing (in the shell and
  in the embedded view) to the embed sync that cuts it out of the game window,
- `--update-pending`, `--simulate-etag`, `--profile`: see the file header.

```
"%LOCALAPPDATA%\gbox\app\gBox.exe" system\scripts\ui-perf --seconds 60 --out after.json [--docked] [--section requests --interact]
```

(Unset `ELECTRON_RUN_AS_NODE` if the shell sets it.) Baselines below ran the same probe on `origin/main`'s clients.

## Causes found and fixed

GPU acceleration was not the problem: the app composites and rasterizes on the RTX 3070 (ANGLE/D3D11,
`gpu-status.json`: gpu_compositing, rasterization, webgl, video decode/encode enabled). The time went to work the UI
created for itself.

| Cause | Evidence | Fix |
| --- | --- | --- |
| `/api/sessions` (757 sessions, ~950 KB, 0.25-1.3 s) fetched back-to-back by the docked-game loop, plus chat hints, the RE helper, the status bar and the embedded view's tray | 105-148 requests/min, 75-137 MB/min | `live-poll.js` shared reads; running sessions from `?include_ended=false` (~2 KB); ended ones from a 30 s cached history |
| `/api/requests` (1,539 requests, 7.9 MB) every 5 s on every tab; each answer a ~150 ms main-thread task | 12/min, 77-93 MB/min, 10-14 long tasks/min | every 5 s only while Requests is visible, else once a minute; ETag/304 and an `apiTagged` IPC that does not copy an unchanged answer into the page |
| Requests tab rendered every request with its whole thread and eagerly loaded every screenshot (no cache headers) | 58,748 DOM nodes, 8.9 s first render, 416 artifact downloads/min (223 MB/min) | newest 40 requests with "Show older"; lazy images; artifacts `immutable` |
| "Update ready" logo: two endless `filter`/`background-position` animations from a deploy until the next relaunch | probe: GPU process 6 -> 39.5 %, renderers 34 -> 75 %, 10,857 style recalcs/min; live: 175 % app CPU (GPU process 73 %) with an update pending, 68 % (GPU 5 %) after a relaunch | three pulses, then a still highlight (pulses on hover) |
| Main process: settings file read and parsed 2-3x per API call; a synchronous ~25 ms tree walk every 20 s | measured walk 24-30 ms | settings cached by mtime; asynchronous walk |
| Graphics panel started `nvidia-smi` per read, with a console window from the windowless worker | | cached a minute, `CREATE_NO_WINDOW` |
| Extract tab's three.js loop requested a frame at the display rate from app start, even if never opened | probe `--profile`: `frame extract.js` in an idle Play view | loop only while the tab is open |

### Results (60 s windows, same probe, `origin/main` clients vs this branch)

| Scenario | Metric | Before | After |
| --- | --- | ---: | ---: |
| Idle, Play | data from the Spark | 218-237 MB/min | 8.7 MB/min |
| | requests | 294-319 /min | 161 /min |
| | shell long tasks | 12-14 /min (1.6-2.2 s/min) | 1 /min (0.19 s/min) |
| | shell main thread busy | 15.9-21.1 % | 8.5 % |
| Update pending | app CPU (all processes) | 135.5 % | 31.6 % |
| | GPU process | 39.5 % | 5.2 % |
| Requests tab | DOM nodes | 58,748 | 6,420 |
| | worst long task | 8,938 ms | 435 ms (0 with ETag) |
| | data from the Spark | 265 MB/min | 65 MB/min (~0 once the server sends ETags) |
| | app CPU | 82.1 % | 40.6 % (20.5 % with ETag) |
| | open Requests / Control | 230-269 / 63-114 ms | 27-31 / 19-27 ms |

## #1081: pop-ups over the docked native game

A native emulator window docked into the app is a child HWND above Chromium's own surface, so app pop-ups that overlap
it are cut out of the game window (`SetWindowRgn` holes). The cut-out was only refreshed by `embedTick`, every 250 ms,
and each tick first waited for the whole `/api/sessions` download; `winembed.py` then rescanned every process and
top-level window (49 ms) before applying the region. A menu therefore stayed hidden behind the game, or a closed one
left a hole, for most of a second.

- `embedTick` no longer waits on the network (stale-while-revalidate running-session list).
- A `MutationObserver` on the shell and a menu watcher injected into the embedded view request a sync in the next
  frame when a pop-up opens, closes or moves (coalesced to one sync per 32 ms; the game bar and grips the sync places
  itself are ignored).
- `winembed.py` rescans for a replacement emulator window at most once a second instead of before every region update.
- The voice visualizer window floated above the game also covered the app's menus; it is now shaped around the same
  holes as the game and the overlay-swap window (`embed-geometry.shapeMinusHoles`).

Probe, synthetic docked game (12 pop-ups, median / max, renderer side; the native call is stubbed):

| Pop-up | Before | After |
| --- | ---: | ---: |
| Shell pop-up opens -> cut out | 810 / 1,243 ms | 14 / 18 ms |
| Shell pop-up closes -> game restored | 1,178 / 2,232 ms | 12 / 15 ms |
| Embedded-view menu opens | 1,125 / 4,849 ms | 28 / 35 ms |
| Embedded-view menu closes | 1,002 / 2,500 ms | 28 / 49 ms |

### What remains

- The native dock still composes by cutting rectangles: soft shadows and rounded corners of a pop-up are clipped where
  it overlaps the game, and a pop-up is cut out a frame or two after it first paints. Only a single composition path
  removes that: the GPU game surface (capture of the emulator window presented as a Chromium video layer), which
  exists for RetroArch but fails with `NotReadableError` on the operator's PC, or rendering pop-ups in a separate
  always-on-top transparent window. Neither was changed here.
- The embedded view's controller loop (`padLoop`, `getGamepads` every frame, ~0.8 s/min in a session view) is left
  as is: it forwards pad input to streamed games and is latency-bound.
- Dolphin, Yuzu and RPCS3 stay on the native dock (their input bridges need the native window focused).
- The ETag on `/api/requests` and the artifact cache header take effect when the Spark runs this code; the desktop
  changes when the app is relaunched.
- Not verified live on the operator's PC in this change: the operator was playing (Dolphin, docked); the probe was used
  instead and the live app was only sampled (process CPU), never driven.
