---
name: gbox
description: "Use the connected gBox MCP server to inspect the game library, run long background jobs, collect character models, and verify game mods."
tags: [gaming, emulator, models, gbox, mcp]
platforms: [linux]
---
# gBox on the DGX Spark

The `gbox` MCP server connects to the live gBox control plane. Use its tools for game state and jobs. Hermes registers them with the `mcp_gbox_` prefix, for example `mcp_gbox_list_favorites` and `mcp_gbox_start_job`; call those tools directly rather than trying to import them in a terminal. A new Hermes session discovers the server automatically; in an existing session run `/reload-mcp` if the tools are absent. A one-shot test with `gemma4:e4b` and `-t gbox` returned the live favorite count.

## Favorites and model collection

1. Call `list_favorites`, then `game_roster` for the relevant `game_id`.
2. Favoriting a game automatically dispatches one native `characters` collection job when that game's format has a registered reader. `game_roster` reports its collection state and job ID. Do not launch a game merely to collect its models.
3. For an explicit retry, call `start_job` with `{"tool":"characters","input":{"op":"collect","game_id":"<id>"},"require_os":"linux"}`. Save the returned job ID and poll `get_job`. Never describe `queued` or `running` as completed.
4. Read the result's per-character verification and failures. An `unsupported` reader means no native extraction happened; do not invent character assets. Report the title and missing reader in the relevant gBox inbox request. Developing and validating a format reader is separate work.

## Replacing a model

Use `job_characters` with `op=coverage` or the game's `game_roster` to check for a native writer. `characters op=use` may offer an overlay when no writer exists. An overlay is visual only; it is not a replacement in the game's own model data. For a native swap, use `job_characters` or `start_job` with the requested character, game, and slot. Follow the result, inspect the generated artifact, and verify it in the emulator before reporting success.

When a native reader or writer is missing, work from the exact ROM or executable version, locate the asset container and model format, implement and test the reader/writer in gBox, then verify a rebuilt game in the emulator. Ghidra and other reversing tools can provide evidence, but their presence alone does not establish format support. Keep the original files intact and preserve a rollback artifact.

## Long tasks

Use `start_job` for gBox registry work that may outlast a chat turn, then `get_job` to track it. Supply `parent_request_id` when continuing an inbox report so the job is linked to that request. Use `job_<name>` only when it is useful to wait for the final result in the current turn. State the job ID and its observed state in progress reports; a queued job is not a completed task.

## Cross-game links (game_link)

`job_game_link op=start` links two live sessions on the same worker: while the host game runs, a watched trigger fires (e.g. Stranglehold bullet-cam) -> the host pauses (or slows to `slow_rate` with `style=overlay`), the guest loads its saved state (e.g. a parked Puyo Puyo Tetris vs-CPU match) -> a win/lose flag decides a host `script_patch` preset -> the host resumes. Inputs: `host`, `guest` session ids, `trigger`/`win`/`lose` specs (`{address, type: u8|u16|u32|f32, eq|ne|lt|gt, value}`, found with `job_memory_search`), and `on_win`/`on_lose` preset names (Stranglehold presets: `god_hit` = infinite life + lethal precision shots, `god_miss` = infinite life + always miss, `hit`, `miss`, `god`, `off`).

Workflow for a "Tetris decides the bullet" request: 1) `launch_game` the host, then `launch_game` the guest with `keep_session=<host session id>` so both stay live on the same worker (the worker otherwise saves and closes the previous game; RPCS3 gives each instance its own home folder, up to 5). Library has Stranglehold BLUS30081 and Puyo Puyo Tetris BLJM61097, both PS3/rpcs3; 2) play or warp the guest to a vs-CPU match and save state; 3) find the host bullet-cam flag and the guest win/lose flags with `job_memory_search` (toggle the state between scans — PS3 searches run against the RPCS3 process, so pass `ranges` when the search needs pruning); 4) `job_game_link op=start` with the specs; 5) `op=status` reports rounds/verdict history. RPCS3 guest sessions relaunch when the link loads the save state; the loop waits for the window itself. PS3 is big-endian and `_watch_true` handles it. One link per host|guest pair; `op=stop` ends it.

## Testing on the other Windows computer

Call `list_workers` and `select_idle_worker` before interactive testing. The selector uses worker-reported Windows input inactivity and the operator's live game to choose the other PC; a recent human input on that PC causes a 409 instead of stealing it. `launch_game(node="idle")` opens a separate session on that PC. `start_job(require_worker="idle")` routes a new job there; after the first job, pin subsequent work to its returned `worker_id`. Session tools already follow the session's worker. Do not reuse an operator-owned live session for agent testing. Binary analysis, mod builds, emulator test iterations, and autoplay can use the other PC when its registry lists the needed tool. Collection operations that write the central character library still run on the Spark.

The `select_idle_worker` `tool` argument must be a native worker tool such as `get_frame` or `launch_game`; `list_workers` is an MCP convenience tool and returns 409 when used there. Call `list_workers` separately when you need the full inventory.

Call `capture_worker_screen` to see the other PC's entire desktop, including gBox, emulator windows, setup steps, and errors. The tool returns a real image and an artifact ID. Pass `request_id`, `text`, and `task_step` to attach important before/after frames to the relevant inbox report. The operator can watch the same desktop through gBox's Other PC picture-in-picture and minimize or expand it. A frame showing a queued job or a loading screen is progress evidence, not proof of success.

Agent jobs on a Windows PC set every active playback output to 2% before running and maintain that volume while an agent-started game is open. If volume enforcement fails, report the failure and do not begin an audible game test on that PC.

## Inbox and visual evidence

Use `list_requests` with `status=open,in_progress`, a small limit, and offsets to work through the inbox. Call `get_request` for the complete prompt; call `read_request_artifact` for each relevant screenshot or text attachment. Start with the newest operator request, and distinguish automated child reports from operator prompts. Search knowledge with a narrow game name and `k=2` when needed; broad searches can overwhelm the context.

An image artifact may be returned as `MEDIA:/absolute/path/to/image.png`. When passing it to a local image-analysis tool that accepts a filesystem path, remove only the `MEDIA:` prefix and use the absolute path. If the tool cannot read the file, use the MCP image directly or record that visual inspection was unavailable; do not invent screenshot contents.

Hermes permits exactly one local gBox MCP tool per `tool_call` invocation. Never batch `mcp__gbox__*` calls in one wrapper. For replies pass `{"request_id":"...","text":"..."}`; for usage pass `{"request_id":"...","tokens_in":0,"tokens_out":0,"tokens_detail":{"token_count_unavailable":1}}` when precise token counts are unavailable. Do not try guessed `gbox://operator/...` resources; the inbox is exposed by tools.

For each material action, post `reply_request` with `task_step={"action":"what was attempted","attempt":"1","result":"observed result","status":"finished|failed|running"}`. When a game is visible, call `capture_request_screenshot` after a meaningful attempt and after verification. Supply the live `session_id`, explanatory text and the same `task_step` fields. Screenshots appear as clickable thumbnails in the inbox's full-screen detailed report. Do not describe a queued save-state or job as completed. If a screenshot cannot be captured, record the reason in a reply and continue work.

For an auto report caused by a failed model replacement or mod application, inspect the model, game, target and moment, the failed job, screenshot, and saved-state job before retrying. Fix the underlying writer or application path and verify the requested replacement in-game. Record each retry and result; do not treat an overlay as an in-engine replacement. Preserve the running game and its save state. Post a final reply with the verified outcome and any limitation, call `record_request_metrics` with actual token/tool/file counts (or `token_count_unavailable` when exact counts are inaccessible), then call `set_request_status(status=done)` only when the whole request is complete. Otherwise leave it `in_progress` with a specific next step.

Capture-icon issue reports request a save state by default. Read `context.state_job_id` and wait for that job to succeed before reproducing the issue; its slot is the exact moment the operator supplied. When `context.state_export_job_id` exists, wait for it and use the result's `artifact` with `state_transfer op=import` on a compatible test session on the idle PC. If the portable export fails, use the original session's saved slot and explain the limitation. For character swaps, the acceptance test is that the requested replacement works at the supplied saved moment after restoration, not merely at a fresh game's beginning. Capture a screenshot at that moment and attach it to the request with a task step before marking the request complete.
