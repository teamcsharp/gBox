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

## Inbox and visual evidence

Use `list_requests` with `status=open,in_progress`, a small limit, and offsets to work through the inbox. Call `get_request` for the complete prompt; call `read_request_artifact` for each relevant screenshot or text attachment. Start with the newest operator request, and distinguish automated child reports from operator prompts. Search knowledge with a narrow game name and `k=2` when needed; broad searches can overwhelm the context.

Hermes permits exactly one local gBox MCP tool per `tool_call` invocation. Never batch `mcp__gbox__*` calls in one wrapper. For replies pass `{"request_id":"...","text":"..."}`; for usage pass `{"request_id":"...","tokens_in":0,"tokens_out":0,"tokens_detail":{"token_count_unavailable":1}}` when precise token counts are unavailable. Do not try guessed `gbox://operator/...` resources; the inbox is exposed by tools.

For each material action, post `reply_request` with `task_step={"action":"what was attempted","attempt":"1","result":"observed result","status":"finished|failed|running"}`. When a game is visible, call `capture_request_screenshot` after a meaningful attempt and after verification. Supply the live `session_id`, explanatory text and the same `task_step` fields. Screenshots appear as clickable thumbnails in the inbox's full-screen detailed report. Do not describe a queued save-state or job as completed. If a screenshot cannot be captured, record the reason in a reply and continue work.

For an auto report caused by a failed model replacement or mod application, inspect the model, game, target and moment, the failed job, screenshot, and saved-state job before retrying. Fix the underlying writer or application path and verify the requested replacement in-game. Record each retry and result; do not treat an overlay as an in-engine replacement. Preserve the running game and its save state. Post a final reply with the verified outcome and any limitation, call `record_request_metrics` with actual token/tool/file counts (or `token_count_unavailable` when exact counts are inaccessible), then call `set_request_status(status=done)` only when the whole request is complete. Otherwise leave it `in_progress` with a specific next step.
