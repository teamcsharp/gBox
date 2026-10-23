# Stream stability: the game view must not go black

Operator report (2026-10-13, about 04:50-05:00 Spark time): "I hate how emulation is always blacking out. I'm playing
Dead or Alive 2 and while I'm playing it, it just randomly goes black at random points." They also found a DOA2
session running that they did not remember starting.

The session was `2882962538984a44-18835ca8a18e4a03`: DOA2 Limited Edition (Japan), game `1de2e7634f3161ff`, mod
`doa2_gen_sa2_amy_rose`, RetroArch (Flycast) on the Spark worker `lilspark`. RetroArch rendered on its own Xvfb display
`:91`. `ffmpeg -f x11grab -framerate 60 -video_size 960x720 -i :91 ... -f image2pipe -vcodec mjpeg` read that display,
the worker uploaded the frames to `/api/sessions/{sid}/stream`, and the desktop app's webview showed them in an
`<img src=".../mjpeg">` (`clients/web/index.html` `#scr`). Window occlusion could not cause a black picture on this path.

## What made the picture go black

1. **The operator's game was restarted under them.**
   - A `session_swap` job `d39d1d04375c4eed` with `{mod: "", to: "", keep_state: false}` was submitted while they
     played. Only one code path sends exactly that body: the web client's `hardReset()`. A single Ctrl+click on the
     session Reset button ran it with no confirmation. It relaunches the original game from boot without the mod
     (they were playing the Amy Rose mod) and discards the current moment. The server accepted any
     `keep_state=false` request without asking why.
   - Any `launch_game` that reaches a worker saves and then closes the game already running there
     (`tools._close_previous_games`: one emulator per PC). The swap's own launch does this. So does every other launch
     routed to `lilspark`. The server had no guard for automated launches aimed at the PC the operator was playing on.
     MCP's `select_background_worker` only protects the `node=idle` path. `POST /api/games/{gid}/launch?mod=…` and the
     `@launch` pseudo-tool both swap a running copy of the game, whoever calls them.
   - A swap waits up to 900 s for its child launch. On the overloaded Spark the child stayed queued or slow, and the
     swap sat at "running" with no output for many minutes.
2. **Black frames were streamed when an emulator exited.** x11grab keeps grabbing the Xvfb display after RetroArch exits
   (a swap, a crash or a relaunch), and an empty Xvfb root is black. Those black frames went out until the display was
   torn down, so the last picture the operator had was black.
3. **The encoder was not supervised.** `MjpegStream._read` simply ended when ffmpeg died: no restart and no log line. A
   hung grab, which is likely with load 30-40, 47/47 GB of swap in use and kcompactd at about 90% CPU, froze the
   session's stream until it was relaunched.
4. **The client showed black while it recovered.** The stream watchdog reattached errored streams, but during the
   backoff and until the first new frame arrived the `<img>` was broken, and a broken `<img>` is black. Every view
   rebuild (following a swapped session, re-rendering Sessions) also started from black. There was no stall indicator.
5. **The machine was starved.** A Hermes agent sandbox ran its own Dolphin (bwrap under `~/.hermes/cache/scratch/r1362`,
   300% CPU), and earlier a 26 GB CPU llama.cpp server had run. The Hermes dispatcher did not know an operator game was
   running on the same machine.

The following were checked and are not causes:

- Session observers never send input, pause, reset or relaunch.
- `graphics op=get` reads `graphics.json` and a cached `nvidia-smi`.
- Linux `get_frame` is a separate one-frame x11grab.
- Flycast checkpoint rewind saves at most every 20 s (#1489), and `gbox.toml` on the share has `checkpoints = false`.

Observers did add load. A stale stream made them submit a `get_frame` job, which starts another ffmpeg on the
struggling machine. They also scheduled native collection (`characters op=collect`) on the Linux node while the
operator played there.

The origin of launch `18835ca8a18e4a03` (agent_use=false, no parent) cannot be read from the repository, because jobs did
not record who submitted them. The control plane's hash-chained audit log does record it. On the Spark:

```sh
sqlite3 ~/gBox/system/gbox-data/gbox.sqlite3 \
  "SELECT datetime(ts,'unixepoch','localtime'), actor, action, data FROM audit
   WHERE subject IN ('18835ca8a18e4a03','d39d1d04375c4eed') ORDER BY seq"
```

`actor` is the `x-gbox-actor` header. It defaults to `operator` for the web UI, curl and any client that does not send
it. A swap's child launch has no parent link before this change; look for a `session.swap` audit row just before it.

## What changed

### Client (`clients/web/viz/stream-watchdog.js`, loaded by the web UI, the desktop webview and the mini player)

- **Last good frame.** Each stream `<img>` carries the server's newest frame (`/frame.jpg`) as its CSS background. The
  frame is set when the view appears, refreshed every 15 s while healthy, and refreshed when trouble starts. A refresh
  is preloaded first, so a failed refresh never replaces the held picture. An errored, reconnecting or rebuilt view
  therefore shows the game, not black. A view rebuilt for the same machine within 5 s starts from the previous view's
  picture, which covers a swap's new session while it boots.
- **Badge.** A small "reconnecting…" pill is shown at the view's top-left corner, with no pointer events, while:
  - `/api/sessions/{sid}/stream/health` reports a source older than 3 s;
  - the stream is reattaching;
  - the server is unreachable.

  The alt text is hidden meanwhile, so no broken-image text is painted over the picture.
- **Transparent reconnect.** The watchdog reattaches the stream, with backoff of 1, 2, 4, 8 and then 10 s, after:
  - an `error` event;
  - 8 s with no picture;
  - a stall of 20 s or more, once frames flow again (that response may have ended or stalled);
  - the server coming back after it was unreachable.

  The old picture stays up until the new response delivers.
- **Blanking only at a real end.** The view is left alone only when the server reports the session `ended`. The app then
  shows its ended view. Other blanking paths (`pip()` closing a hidden picture-in-picture, `hardStop`, the ended
  Sessions panel) are explicit operator actions or real ends. The desktop's local GPU surface
  (`gpu-game-surface.js`) applies only to games on the operator's own PC, and it falls back to the native window, not
  to black.
- `clients/desktop/mini.html` reads authenticated health through desktop IPC, since a file:// page cannot fetch it
  directly. Healthy IPC-monitored streams keep their connection; the previous 60-second reset interrupted gameplay.

### Worker (`gbox/adapters.py` `MjpegStream`, `gbox/tools.py` `_pump`)

- A supervisor checks the encoder every 0.5 s and acts on two conditions:
  - ffmpeg exited;
  - ffmpeg is alive but has produced no JPEG for 8 s. x11grab and gdigrab grab at a fixed rate whether or not the
    picture changes, so that silence means a hung grab.

  Either way only ffmpeg is killed and restarted. The delay starts at 0.5 s and doubles to a 10 s cap while restarts
  produce nothing. The emulator is never touched, and `latest` keeps the last good frame.
- Slow frames are tolerated: a gap of 2 s or more is only logged.
- Every event is printed with a local wall-clock timestamp. Example:
  `gBox stream: kind=encoder_stall at=2026-10-13T04:52:11-0500 stream=<sid> silent_s=8.4`. Events are also posted to
  `POST /api/sessions/{sid}/stream/event` from a bounded background queue, so reporting can never slow the video.
- When the session's emulator process has exited, grabbed frames are not uploaded. The operator keeps the last real
  frame and never sees the empty display.
- Upload reconnects are logged with timestamps.

### Server (`gbox/live_stream.py`, `gbox/server.py`)

- MJPEG viewers now wait on asynchronous frame notifications. Sending each JPEG no longer needs a worker-thread
  dispatch, and a blocked viewer resumes from the newest shared picture instead of retaining a queue of old frames.
  Disconnecting unregisters its notification immediately. Watch leases and held-frame reconnect behavior are retained.
- Ingest records every source gap of 2 s or more with start and end times, and logs
  `gBox stream: <sid> no new frame for N s (start -> end)`.
- `GET /api/sessions/{sid}/stream/health` returns:
  - `state`, `seq` and `age_s` (the source frame age);
  - the upload count;
  - the last 10 stalls;
  - the last 10 encoder events;
  - `pacing`: p50, p95, maximum and count of gaps over 100 ms across the newest 600 source frame intervals;
  - `delivery`: active async viewers, frames delivered and intermediate frames skipped under backpressure.

To match an operator report to a cause, read it together with the journal (`journalctl -u gbox --since 04:45`).

### Spark frame pacing investigation (2026-10-23)

The production feed measured 53.52 fps on Spark over 20 seconds, with median frame gap 16.53 ms, p95 34.86 ms,
maximum 523.23 ms and four gaps over 100 ms. A later Spark-to-Windows sample measured 40.6 fps, p95 45.9 ms,
maximum 1964.37 ms and 13 gaps over 100 ms. These are different time windows under changing host load, not a
controlled comparison between network and capture. Both show real stutter that the old two-second stall log missed.

The live encoder had 73 threads on a 20-core Spark. A short controlled capture-only comparison retained 60 fps with
one filter thread and two encoder threads: 25 process threads and 61.3% CPU, versus 73 threads and 71.5% CPU with
automatic settings. The p95 gaps were 21.41 and 19.29 ms respectively, so this demonstrates reduced overhead, not a
proven capture-jitter improvement. Output flushes each JPEG and retains FFmpeg's default timestamp handling. A live
capture-only stderr trace caught duplicate X11 timestamps with `-fps_mode passthrough`, causing encoder exit 255;
that option was removed. No unrelated processes
were stopped or throttled. Host CPU pressure was approximately 32% during the production sample; changing a stream
cannot guarantee seamless emulation under every competing workload.

Canvas-readable viewers still compare displayed and latest server pictures to detect a silent browser freeze.
Opaque file:// viewers use IPC source health and image errors; source health alone cannot prove that the browser
has painted the newest picture. The generic embedding fallback without health access retains bounded renewal.

### Swap and launch hygiene (`gbox/server.py`, `gbox/operator_guard.py`, `clients/web/index.html`)

- A swap keeps the moment by default (`keep_state: true`). `keep_state: false` now requires
  `intent: "hard_reset" | "reset_model"`. Without it the request gets a 422, so the exact request seen on 2026-10-13 is
  refused.
- In the web UI, Hard reset needs two Ctrl+clicks on the same game's Reset button within 5 s. The first click only arms
  it, and the button turns amber with a warning tooltip. Reset, Restart and Hard reset are one server operation,
  `POST /api/sessions/{sid}/reset` (`mode: reset | restart | hard`); a hard reset needs `intent: "hard_reset"` there
  too, and a reset of a hot-swapped model is relaunched by the server (no client `keep_state: false` swap). A client
  that still swaps with `keep_state: false` sends `intent: "hard_reset"` or `intent: "reset_model"`.
- Background agents (actors `mcp`, `hermes`, `agent`) can no longer swap, reset or restart the operator's live session.
  This blocks every route into `swap_job` and `reset_job`: `/swap`, `/reset`, `launch?mod=` and `@launch`. Agent-owned test sessions (tray label `owner=agent`, or
  launched by an `agent_use` job) are still allowed. The in-app chat agent (`gbox-agent`) acts on the operator's own
  words and is exempt.
- An automated `launch_game` (`agent_use`, actor other than `gbox-agent`) is pinned to a worker with no operator game.
  It is rejected with a clear reason when every candidate has one, instead of saving and closing the operator's game.
- `POST /api/games/{gid}/launch?mod=…` used to turn any Play with a mod into a swap of the newest running copy of
  that game on any online worker (`node=auto` matched every PC). Mods page, Special builds, build notifications and
  the showcase all go through this endpoint. Now it swaps only when the caller names the session's PC (worker id,
  name or OS) as the node, or passes `swap=true`. Otherwise it is a new launch. The swap always keeps the moment
  (`keep_state=true`). These requests send a real mod name and keep the moment, so they do not match the observed
  `{mod:"", keep_state:false}` job. That job came from `hardReset`, the only sender of that body.
- `@launch` with a named node swaps only a session on that node. It still swaps in place with `node=auto`, which is
  the chat and character-swap path.
- A worker tool calling the control plane back sends `x-gbox-parent-job` (`worker._run_job`). Its requests inherit
  the job's identity: a `characters op=use` inside a Hermes job counts as automation and cannot swap the operator's
  game. Inside an in-app chat job it can.
- A swap's child launch must be picked up within 180 s (`SWAP_LAUNCH_QUEUE_S`). Otherwise the child is dropped and the
  swap fails with "lilspark did not start launch_game within 180 s (it is busy). Nothing was changed; your current game
  keeps running." The old game is untouched until the worker starts the launch.
- Jobs record `actor` and `origin` (client header `x-gbox-client` = `web` or `desktop-webview`, the user agent, the
  remote address, or `via: session_swap` with `parent_job`). Swap jobs keep every request in `requests`, and each swap
  request adds a `session.swap.request` audit row. The next unexplained launch or swap can be traced from the job
  itself.
- `/api/sessions` rows for running sessions carry `agent_owned`.

### Keeping background work off the operator's machine

- **Observers** (`gbox/session_observers.py`):
  - A streamed session with a stale source is no longer sampled through a new `get_frame` job. The observer waits for
    the stream.
  - Native collection is not scheduled while the operator plays on the Linux node. Its status is still reported.
- **Hermes** (`gbox/hermes_work_queue.py` `tick`). On every tick, while an operator session (not agent-owned) runs on a
  Linux worker:
  - Every process in a Hermes agent sandbox (a bwrap root naming `~/.hermes/cache/scratch` or `~/.hermes/sandbox`, plus
    its descendants, such as the agent's own Dolphin) is set to nice 19 and `ionice -c 3`. This runs even when the
    dispatcher is off. Raising niceness needs no privileges. It is not undone, so the sandbox finishes at low priority.
  - Emulator-launching queue items are deferred: the favorite `runtime` stage and inbox repairs that need gameplay
    acceptance.
  - Dispatch is capped at one task per tick, unless the route is the inference pool (spark2, cloud nodes): those runs keep their node capacity, since their model does not run on the Spark (operator 2026-10-22).
  - Dispatched prompts tell the agent that the operator is playing on this machine. The agent must not start an
    emulator here and must run runtime tests through `launch_game node=idle`.
  - `tick()` reports this under `operator_playing`.
- gBox showcase and special builds already wait for idle. The 26 GB CPU llama.cpp server is a Hermes model route, not
  gBox work. It is not throttled here.

## Tests

- `tests/test_stream_stability.py` covers:
  - encoder restart, backoff and hang detection;
  - suppression of frames from an exited emulator;
  - stall logging and the health and event endpoints;
  - the swap intent requirement and job origin recording;
  - the agent swap and launch guards;
  - the queue-wait fail-fast;
  - the sandbox throttling helpers.

  It also runs `tests/test_stream_watchdog.cjs` (node), which covers:
  - the last-good-frame poster and the badge;
  - transparent reconnect after errors, long stalls and server outages;
  - ended sessions;
  - the mini player;
  - the two-step hard reset.
- `tests/test_hermes_work_queue.py` covers the operator gate and the tick throttling and prompt.
- `tests/test_session_observers.py` covers stalled-stream waiting and deferred collection on the Linux node.

### Connected views protect the game

An active session MJPEG connection or the app's viewing heartbeat reserves that
session's worker against new game loads, including watched bot demos. Launch
submission excludes watched workers; queued launches recheck at claim time and wait
if viewing began after submission. Session replacements are refused while watched.
The app continues its heartbeat while hidden because PiP can still be visible.
Close the connected view before loading another game on that PC. Other workers remain
available. Each stream has its own lease, released on disconnect; heartbeat leases
expire after three minutes if a client disappears without closing cleanly.

### Keep the watched game in PiP through a restart

The desktop compact player previously held its original session ID forever, while
the web PiP cleared its selected game as soon as that session ended. Both now follow
the replacement chain, including several restarts. When a worker reboot has no
replacement link, recovery requires the same game, build and named computer; it
does not select an unrelated running game. Main and PiP selections are checked
independently. Closing PiP or choosing another game cancels a pending handoff.

The compact window retains its bounds and last picture during an outage. Before
attaching a replacement stream, it checks a decoded frame in the same-origin game
webview. Black boot frames keep the previous picture visible; a boot logo or game
frame permits the handoff. The reconnect badge remains visible in compact mode.
F5 also resolves saved session IDs to their replacements. These are display and
input-target updates; they never launch, pause or restart a game.

Validated on 2026-10-23 with the existing 1112-by-625 RE5 PiP: client refresh
recovered gameplay from its stale Save successful screen, and a service restart
was followed to the replacement RE5 session without closing the PiP. Regression
coverage includes replacement chains, worker reboots, held frames, black boot
frames, offline recovery and a user closing PiP during a delayed frame probe.
