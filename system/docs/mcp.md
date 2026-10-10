# gBox MCP server

`gbox mcp` exposes gBox to any MCP client (Claude Desktop, Claude Code, other agents). It is a thin client of the
control plane (`http://10.89.1.246:8765`): it holds no state and uses the same bearer token as every other client
(`GBOX_TOKEN`, else `<data_dir>/api_token` next to the `--config` file; it refuses to start rather than mint a new one).

Code: `gbox/mcp_server.py`. Dependency: `pip install "mcp>=2.3"` (the `mcp` extra in `pyproject.toml`).

## Tools

| Tool | What it does |
|---|---|
| `job_<name>` | One per registry tool (`GET /api/registry`), with the tool's own input schema plus optional `require_os`. Submits `POST /api/jobs`, waits for it, returns `{id, state, worker_id, output, error}`. A `session_id` in the input routes the job to that session's worker. |
| `list_games(query, platform?, limit?)` | Ranked library search (`/api/catalog/best`). |
| `list_favorites(limit?)` | Favorited games, with IDs for roster work. |
| `game_roster(game_id)` | Native reader, roster and background collection state for one game. |
| `start_job(tool, input, require_os?, require_worker?, parent_request_id?)` | Submit a registry job without waiting; returns its ID and initial state. |
| `get_job(job_id)` | Poll a background job's state, progress, result and error. |
| `launch_game(game_id, node?, debug?)` | `POST /api/games/{id}/launch`; returns the launch job (output carries the session id). |
| `list_sessions(include_ended?)` | `/api/sessions`, live ones by default. |
| `read_memory(session_id, address, length?)` | Session RPC `read_memory` (read-only peek, max 4096 bytes). |
| `ask_gbox(text, session_id?, chat_id?, timeout_s?)` | Runs gBox's own chat agent (`/api/chat`), waits for the turn, returns `{chat_id, answer, tool_calls, errors, choices}`. Pass `chat_id` back to continue the conversation. Every turn is a metered request in the inbox. |
| `kb_search(query, game?, k?)` | `/api/kb/search`. |
| `list_recipes()` | `/api/recipes`. |

On the DGX Spark, Hermes has a `gbox` stdio MCP registration using the Linux service venv and local control-plane URL. Verify it with `hermes mcp test gbox`. The server discovers 206 tools; Hermes selects 12 useful tools in `~/.hermes/config.yaml`, with `start_job` covering the full job registry without loading 194 additional schemas into each conversation. New Hermes sessions load the registration; use `/reload-mcp` in an existing session. The Hermes workflow is in `system/hermes/gbox/SKILL.md` and deployed to `~/.hermes/skills/gaming/gbox/SKILL.md`.

Hermes tool names use the `mcp_gbox_` prefix. A verified one-shot command on the Spark is `hermes -m gemma4:e4b -t gbox -z 'Call mcp_gbox_list_favorites and report its total'`; it returned 28 favorites at the time of the test. The configured default 30B Nemotron model was not verified in the same bounded test.

Resources: `gbox://sessions` (live sessions), `gbox://games` (first 500 library entries + total).

Write/launch tools (`launch_game`, `job_write_memory`, `job_mod`, ...) act on the real games; the job permissions in
`gbox.toml` (`granted_permissions`) still apply.

## Register on this Windows machine

Code comes from the mirror (`C:\_tools\gBox\system`), the config and token from the share (so nothing secret is copied).

Claude Code (one line; user scope so it works from any folder):

```
claude mcp add gbox --scope user -e PYTHONPATH=C:\_tools\gBox\system -- C:\Users\maste\AppData\Local\gbox\venv\Scripts\python.exe -m gbox --config \\10.89.1.246\ehm_eckx\gBox\system\gbox.toml mcp
```

Check with `claude mcp list` (or `/mcp` inside a session).

Claude Desktop: add to `%APPDATA%\Claude\claude_desktop_config.json`, then restart Claude Desktop:

```json
{
  "mcpServers": {
    "gbox": {
      "command": "C:\\Users\\maste\\AppData\\Local\\gbox\\venv\\Scripts\\python.exe",
      "args": ["-m", "gbox", "--config", "\\\\10.89.1.246\\ehm_eckx\\gBox\\system\\gbox.toml", "mcp"],
      "env": { "PYTHONPATH": "C:\\_tools\\gBox\\system" }
    }
  }
}
```

To point at another control plane: add `--server http://host:8765` after `mcp`; to use a token from elsewhere, set
`GBOX_TOKEN` in `env` instead of relying on the share's `gbox-data/api_token`.

## Remote clients (streamable HTTP)

```
python -m gbox --config gbox.toml mcp --http          # http://<api_host>:<api_port+1>/mcp, i.e. :8766 on the Spark
```

Every request needs `Authorization: Bearer <gBox token>` (401 otherwise). It binds `api_host` from the config, so it is
LAN-only like the control plane; not run as a service. On the Spark, install the SDK into the service venv first:
`/home/ehm_eckx/gBox/system/.venv-linux-aarch64/bin/pip install "mcp>=2.3"`. Register a remote client with:

```
claude mcp add gbox --transport http http://10.89.1.246:8766/mcp --header "Authorization: Bearer <token>"
```

# Other-PC testing

Hermes can call `list_workers` and `select_idle_worker` to find the Windows worker the operator is not using. Use `launch_game(node="idle")` for a fresh emulator test or `start_job(require_worker="idle")` for analysis and modding, then pin later jobs to the returned worker ID. Session operations route to their owning worker. `capture_worker_screen` returns a desktop image and can attach it to an inbox request with a task step. The gBox desktop's **Other PC** button opens a live, resizable picture-in-picture of that worker. Agent use holds Windows playback outputs at 2% while a job or agent-started game is active.

The title bar's checkbox controls a Hermes cron job on Spark. Checking it schedules an immediate inbox run and repeats every thirty minutes. Tasks follow Hermes's connected cron cloud route and available fallbacks; the interactive local model remains separate. Each run claims one request, works in an isolated Git worktree, validates changes and uses `publish_task_changes` for a real draft PR. A PR remains separate from verified ticket completion. See [dispatch and delivery](hermes-throughput.md).

For Hermes worktree jobs, launch the gBox MCP Python with `-P -m gbox` so the task working directory cannot shadow its implementation. Set `PYTHONPATH=/home/ehm_eckx/gBox/system`, `GBOX_HERMES_DISPATCH_STATE=/home/ehm_eckx/gBox/system/gbox-data/hermes-dispatch`, and `GBOX_OPERATOR_WORKER` to the PC currently in use. The no-agent feedback supervisor repairs canonical MCP paths automatically while preserving the selected operator PC and tool allowlist. Enable `prepare_task_workspace`, `publish_task_changes`, and `get_dispatch_feedback` in the gBox MCP tool allowlist.
