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
| `launch_game(game_id, node?, debug?)` | `POST /api/games/{id}/launch`; returns the launch job (output carries the session id). |
| `list_sessions(include_ended?)` | `/api/sessions`, live ones by default. |
| `read_memory(session_id, address, length?)` | Session RPC `read_memory` (read-only peek, max 4096 bytes). |
| `ask_gbox(text, session_id?, chat_id?, timeout_s?)` | Runs gBox's own chat agent (`/api/chat`), waits for the turn, returns `{chat_id, answer, tool_calls, errors, choices}`. Pass `chat_id` back to continue the conversation. Every turn is a metered request in the inbox. |
| `kb_search(query, game?, k?)` | `/api/kb/search`. |
| `list_recipes()` | `/api/recipes`. |

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
