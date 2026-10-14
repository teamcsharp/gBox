# Background operations and presentation health

The Tasks menu lets each PC opt into background testing and choose a resource
admission budget (default 70%, configurable from 10–90%). Untick a PC for gaming.
The choice is stored by PC name, so it survives worker restarts.

This is an **admission limit**, not a hard CPU/GPU throttle: an already running
program can exceed it. No synthetic load is created to meet a utilization target.

Before an agent or low-priority compute job is claimed, the server checks:

- No human-owned emulator session on that PC, including controller-only play.
- Background testing is enabled; a Windows PC has at least five minutes without
  operator input.
- Resource telemetry is current (at most 30 seconds old), with a real CPU sample
  interval; CPU and each reported GPU are below the selected budget.
- At least 2 GiB memory is available and less than 90% is used.

Deferred jobs remain durably queued and may run on another compatible worker.
Save, stop, frame capture and session diagnostics remain available. The evidence
capture chooser uses the same admission result, avoiding a launch that will only
wait at the worker queue. Windows idle time alone never overrides human session
ownership.

Workers sample CPU/RAM and, when installed, NVIDIA utilization using a bounded
two-second `nvidia-smi` query. Unsupported GPU telemetry is displayed as
unreported; this does not enforce a GPU cap on those adapters. The first CPU
sample is unknown rather than an invented zero. Existing workers must load the
updated code before their new background compute is admitted.

After five minutes without input, an open, visible desktop gBox instance can
show the operations display automatically. It dismisses on input, does not steal
OS focus or reopen minimized windows, and never overlays a human-owned game.
While an owned native test is running, it selects that existing game view instead
of covering gameplay with a dashboard. Persistent black or missing windows stay
on the operations/diagnostic surface. It shows measured CPU/GPU/RAM, current tool stages, queue deferrals, receipts,
recent results and unavailable capabilities. The Three.js wave uses external
telemetry at low quality and at most 20 rendered frames per second. Hidden pages
stop rendering; unavailable 3D leaves readable operation data. Polling never
creates work. A completed tool and a captured frame are not goal acceptance.

Every live Sessions view now watches presentation status independently of the
video backend. Server-confirmed ended/missing sessions retire the live view,
including native windows that have no MJPEG stream. Offline workers, covered
windows and capture timeouts report uncertainty without relaunching a game.

The passive observer also measures a small grayscale image. Near-black means
mean luminance at most 3/255 and at least 99.9% of sampled pixels at most 8/255.
Repeated captures spanning 90 seconds are marked persistent. Agent-owned tests
get one deduplicated presentation investigation with a captured image. Human
games are never stopped, reset or relaunched. A loading transition is not proof
of a game failure; capture/window logs must establish its cause.

## Endpoints

- `GET /api/testing/workers`: policy, measured resources and admission reasons.
- `POST /api/testing/workers/{name-or-id}`: `{available: false}` for gaming,
  `{available: true}` to allow new work, or `{budget_percent: 70}`.
- `GET /api/background/workers/{name-or-id}/status`: read-only operations,
  compatible queued work, recent tool results, live session ownership and tools.
  History is bounded to the newest 200 jobs and ten worker results.
- `/viz/background-operations.html#worker=...&token=...`: operations display.
- `GET /api/sessions/{sid}/stream/health`: frame age, worker connection,
  native-window flag, observer presentation measurements and terminal exit.

## Work remaining against the operator's complete request

This change does not implement cooperative checkpoint/migration of running
compute jobs, hard utilization throttling, local GPU learned autoplay, physical
controller training capture, a local semantic/vector memory database, a Three.js
memory timeline, automatic level-win interpretation by Ghidra, or cross-game
transfer of verified logic. Those require durable work stages, emulator-specific
state/input compatibility, bounded storage and evidence-based acceptance. Keep
the complete request open until those pieces and actual gameplay recovery are
validated. The operations display must never conceal these gaps with animation.
