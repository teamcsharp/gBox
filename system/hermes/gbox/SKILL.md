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
