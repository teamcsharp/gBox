# Coaching from the PiP window (design, not yet built)

Operator 2026-10-21: "in picture in picture mode with autoplay on cloud, put the chat window here so i can talk to
the system and put in reports while watching gameplay. I want to point out issues and it files reports with states,
ram scans, screenshot and 3 second feed of the gameplay ... cause changes to be queued up to be done to the active bot
for that title. Every title ... that I favorite will need an autoplay bot that can be configured with this system."

This page is the design agreed for branch `pip-coaching` (PR draft). State: **researched and designed; no code yet**.
What exists today is the Sessions-header coach box (`gbox/coaching.py`, `clients/web/viz/autoplay-coach.js`, #720/#740,
docs/autoplay.md "Coaching"); everything below extends it rather than adding a second path.

## 1. The coach bar in the PiP window

* The PiP window the operator screenshotted is the desktop app's **compact** view: `clients/desktop/index.html`
  (`compactController` near line 3690; `#compact-controls` is the 28 px top bar: `<span>` title left, "Full app" button
  right, CSS at line ~1254). It is shown on hover (`compactHover`, pointer at y < 32) and hidden otherwise.
* Change: `controls.innerHTML` gets `GBoxAutoplayCoach.html(sid)` between the title span and the button; call
  `GBoxAutoplayCoach.mount(controls, {sid, api})` with the desktop's `api` helper (`gbox.api`, index.html line 3372
  pattern). Keep the bar shown while the input has focus or a note is still capturing (`compactHover(true)` on focus,
  release on blur + settle). `-webkit-app-region:no-drag` on the input so typing never drags the window. Escape blurs
  (the existing Escape = restore handler must skip when the input is focused). The status/ack text reuses the box's
  `coach-st` line (folds to "Note #N ✓").
* `clients/desktop/index.html` needs `<script src="../web/viz/autoplay-coach.js">` (it already loads other
  `../web/viz` scripts, e.g. stream-watchdog.js at line 1248).
* Test: `tests/test_compact_game.cjs` style (node:test, `vm` over index.html) + `tests/test_autoplay_coach.cjs`.

## 2. Evidence captured with every note (server side, `gbox/coaching.py`)

`add_note` already files a ticket message with telemetry + frame/state/RAM jobs on the session's worker. Add:

* **telemetry + tactical frame**: `screensaver.telemetry_get(sid)` (already) plus `app.state.tactical_map.get_frame(sid)`
  (`gbox/tactical_map.py`, in-memory store set by `install`) stored under `coach.tactical` and attached as
  `coach-N-tactical.json`.
* **RAM map read**: `gbox/ram_inspector.py` keeps one `Inspector` per session in `_INSPECTORS`; add a module function
  `live_rows(sid) -> dict | None` returning `insp.values().rows()` (the inspector's live fields) without HTTP, and store
  them under `coach.ram_fields` (bounded, e.g. 200 rows) + attach `coach-N-ram-fields.json`. The `ram_dump` /
  `state_transfer op=snapshot` jobs stay as they are (never Dolphin slot 1: `state_snapshot` uses the demo slot 10).
* **screenshot**: the session's `frame.jpg` is already captured by the `get_frame` job; also attach the control plane's
  newest stream frame at once (`live[sid]["frame"]`, passed to coaching.routes like `ram_inspector.routes(frame=...)`),
  so a note has a picture even when the worker is slow.
* **3-second clip**: `gbox/live_stream.py` gets a bounded ring: `ring_add(lv, frame, ts, seconds=4.0, max_bytes=6 MiB)`
  (a `collections.deque` of `(ts, jpeg)` trimmed by age and total size) called from both ingest paths in
  `gbox/server.py` (`put_frame` ~3735, `ingest_stream` ~3757). `clip(lv) -> (frames, fps)` copies the ring; coaching
  encodes it with ffmpeg (`ring_record.ffmpeg_cmd()`): `-f image2pipe -framerate <fps> -i - -c:v libx264 -preset
  ultrafast -pix_fmt yuv420p -movflags +faststart coach-N-clip.mp4`, in a worker thread, attached when done (same
  reconcile/attach path as the other captures; capture kind "clip"). No ffmpeg: capture state "skipped" with the reason.

## 3. The report is actionable

* The inbox ticket (source "coach", `context.coaching: true`) gets the extra context: `bot` (playbook name from
  telemetry `mission` "playbook: <name>"), `phase` (telemetry `stats.phase` where the engine reports one), `character`,
  `weapon`, `ram_fields` (the map rows), `tactical`, `clip`. `compose()` adds a second bracketed line with bot/phase.
* Lessons log: `coaching._lesson` already appends to `gbox/mercs/lessons` through `mercs_bot.note_lesson` for titles
  with a `mercs` RAM block; extend to fightbot titles (`gbox/fightbot` equivalent) with the same "coach" entry.
* **Queued changes** per title: store kind `bot_changes`, id = game_id, `{items: [{id, note, text, request_id, message_id,
  state: open|acknowledged|applied|verified, by, pr, ts, updated}]}`. `GET /api/autoplay/bots/{game_id}/changes`,
  `POST /api/autoplay/bots/{game_id}/changes/{id}` (state transitions; `pr` number when applied). Each coach note appends
  an item; `scripts/agent_ledger.py` `describe_note` prints the change id and evidence attachment names so an agent can
  acknowledge it (`agent_ledger.py ack CHANGE_ID`).
* Hermes: `hermes_work_queue.is_live_coaching` becomes `is_live_coaching(request, owned=lambda gid: bool)`: a coaching
  ticket whose game has an active agent owner in the bot registry (below) stays excluded; one with no owner is a normal
  inbox item for the Hermes queue (its `sync` and `candidates` call sites at lines ~140 and ~274).

## 4. A bot per favorite title

* Registry `profiles/bots.json`: `{ "<game_id>": {"playbook": "mercs_bot|doa3_bot|sc2_bot|doa2_bot|ge007_bots|imitate",
  "tunables": {...}, "owner": {"agent": "<name>", "since": ts} | null } }`, overlaid by a store collection `bot_registry`
  for owners/tunables changed at runtime. `gbox/bots.py`: `for_game(store, game_id)`, `owner(store, game_id)`,
  `ensure_favorites(store)` (every favorite gets an entry: `tools.PLAYBOOKS` module `matches` by platform/map, else
  "imitate").
* `GET /api/autoplay/bots`, `GET /api/autoplay/bots/{game_id}` (playbook, tunables, owner, phase from telemetry, open
  change count). The Sessions header and the PiP bar title show "<bot> · <phase>" from this.
* Autoplay (`tools._playbook`) consults the registry first when a favorite names a playbook; titles with `imitate` fall
  back to the learned style as today. A coach note on such a title also files a "bot wanted" change item.

## 5. Evidence to collect before merge

PiP bar over the live RE5 session on the Spark (read-only; the session belongs to the RE5 agent), and one filed report
with its attachments listed (frame, clip, RAM fields, tactical, state/RAM artifacts). Label real frames as such.

## Files to touch

`clients/desktop/index.html`, `clients/web/viz/autoplay-coach.js`, `gbox/coaching.py`, `gbox/live_stream.py`,
`gbox/server.py`, `gbox/ram_inspector.py`, `gbox/hermes_work_queue.py`, `scripts/agent_ledger.py`, new `gbox/bots.py`,
`profiles/bots.json`, tests `tests/test_autoplay_coach.py`, `tests/test_coaching_live.py`, `tests/test_live_stream.py`,
`tests/test_autoplay_coach.cjs`, `tests/test_compact_game.cjs`, docs/autoplay.md (link here).
