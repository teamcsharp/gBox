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
| `bot_sessions()` | The running sessions with their PC (`host`), the game's mod tool (`mod_tool`: `re5_mods` / `re_mods`) and the Mercenaries autobot's live summary from `/api/autoplay/telemetry/{sid}` (running, phase, screen, rounds, kills, `directive_status`, mines cadence, team role). Read only; the way to find a `session_id` for the three tools below. |
| `bot_directive(session_id, command?, text?, hold_s?)` | An instant command for the session's autobot (`POST /api/sessions/{sid}/directive`, `gbox/mercs/directives.py`): `fight`, `next_area`, `explore`, `hunt`, `score`, `repetitive`, `mine`, `mine_trail`, `missing`; or free `text` matched to one ("drop landmines while fleeing" -> `mine_trail`); unmatched text is an error and nothing is sent. `hold_s` (0..600) sets how long a standing mode lasts. Returns the stored row. |
| `game_mod(session_id, op, params?, tool?)` | One live RAM mod on the session's own PC, waited for like a `job_` tool: `re5_mods` for Resident Evil 5, `re_mods` for Resident Evil 4, chosen from the session's game (never from the emulator alone). `params` holds that tool's own job fields; anything else is rejected instead of silently dropped. Returns the job (`output.result.verified`). |
| `game_mod_ops(session_id?, tool?)` | Every op `game_mod` accepts for that game: params with allowed values, effect, when it takes effect (now / next round / next menu), and whether the tool retains it as the operator's setting. |
| `bot_strategy(session_id, settings?)` | What the bot plays with for the rest of the session: `settings.mods` (the retained ops: RE5 `fire_rate turn_speed bullet_damage infinite_ammo unlimited_health kill_time infinite_spray instant_qte mines rotten_egg_only weapon_override`; RE4 `unlimited_health infinite_ammo combo_freeze merc_timer_freeze grenade_safe merc_time_bonus combo_time aim_turn_speed spawn_multiplier random_loadout merc_loadout mercenaries_unlock`), `settings.mercmode` (`POST /api/mercmode` for the session's PC), `settings.team` (`mercs_team configure`, RE5 / RE6). Empty settings: the options, the PC's current MercMode settings and what is **not** settable (the RE5 `Policy` constants, the RE4 package radii, the profile's `playing_ops`). |
| `spawn_enemies(...)` | Not available yet: no verified enemy-spawn write in RE4 or RE5 (RE4's `spawn_multiplier` only clones what the game spawns). Sends nothing; returns `{supported: false, reason, ticket}` with the open inbox request tracking the work. |
| `get_broadcast_feeds()` | Current program, available PCs/sessions and stable playback URLs, including frame rate and freshness. |
| `get_broadcast_status()` | Encoder frame progress, viewers, restarts and isolated emulator audio availability. |
| `read_memory(session_id, address, length?)` | Session RPC `read_memory` (read-only peek, max 4096 bytes). |
| `ask_gbox(text, session_id?, chat_id?, timeout_s?)` | Runs gBox's own chat agent (`/api/chat`), waits for the turn, returns `{chat_id, answer, tool_calls, errors, choices}`. Pass `chat_id` back to continue the conversation. Every turn is a metered request in the inbox. |
| `kb_search(query, game?, k?)` | `/api/kb/search`. |
| `list_recipes()` | `/api/recipes`. |

On the DGX Spark, Hermes has a `gbox` stdio MCP registration using the Linux service venv and local control-plane URL. Verify it with `hermes mcp test gbox`. The server discovers 206 tools; Hermes selects 12 useful tools in `~/.hermes/config.yaml`, with `start_job` covering the full job registry without loading 194 additional schemas into each conversation. New Hermes sessions load the registration; use `/reload-mcp` in an existing session. The Hermes workflow is in `system/hermes/gbox/SKILL.md` and deployed to `~/.hermes/skills/gaming/gbox/SKILL.md`.

Hermes tool names use the `mcp_gbox_` prefix. A verified one-shot command on the Spark is `hermes -m gemma4:e4b -t gbox -z 'Call mcp_gbox_list_favorites and report its total'`; it returned 28 favorites at the time of the test. The configured default 30B Nemotron model was not verified in the same bounded test.

Resources: `gbox://sessions` (live sessions), `gbox://games` (first 500 library entries + total).

Write/launch tools (`launch_game`, `job_write_memory`, `job_mod`, ...) act on the real games; the job permissions in
`gbox.toml` (`granted_permissions`) still apply.

For Pine Box on the Spark, `deploy/gbox-mcp.service` is a user service binding only `127.0.0.1:8766/mcp`.
It uses the deployment's existing bearer token in the Authorization header. Pine's host-network container can
connect locally; the MCP control interface is not published through the public Tailscale Funnel. Stream discovery
is read only. Pine relays the selected broadcast feed under its own listener authorization and keeps the gBox
credential server-side. The standalone reviewer remains available at `/mercenaries` in gBox.

## Register on this Windows machine

Code comes from the mirror (`C:\_tools\gBox\system`), the config and token from the share (so nothing secret is copied).

The venv needs the SDK once: `%LOCALAPPDATA%\gbox\venv\Scripts\python.exe -m pip install "mcp>=2.3"` (without it the server
exits at import and Claude reports `CONNECTION_CLOSED`).

Claude Code (one line, **from PowerShell or cmd**; user scope so it works from any folder). Git Bash eats the backslashes of
unquoted Windows paths (`C:\Users\...` arrives as `C:Users...`, which is how the 2026-10-26 registration broke) and turns a
`\\server` UNC path into `\server`; the share config is therefore given with forward slashes, which Python accepts:

```
claude mcp add gbox -s user -e PYTHONPATH=C:\_tools\gBox\system -- "%LOCALAPPDATA%\gbox\venv\Scripts\python.exe" -P -m gbox --config //10.89.1.246/ehm_eckx/gBox/system/gbox.toml mcp
```

(`-P` keeps the working directory off `sys.path`, as the Spark's Hermes registration does.) A config path that does not
exist is not an error for `gbox --config`: it falls back to the defaults and then stops with `no token: ... gbox-data/api_token
missing` next to the package, so check the path first when that message appears. Check with `claude mcp get gbox` (`√ Connected`),
`claude mcp list`, or `/mcp` inside a session.

Claude Desktop: add to `%APPDATA%\Claude\claude_desktop_config.json`, then restart Claude Desktop:

```json
{
  "mcpServers": {
    "gbox": {
      "command": "C:\\Users\\<you>\\AppData\\Local\\gbox\\venv\\Scripts\\python.exe",
      "args": ["-P", "-m", "gbox", "--config", "//10.89.1.246/ehm_eckx/gBox/system/gbox.toml", "mcp"],
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

Hermes can call `list_workers` and `select_idle_worker` to find the Windows worker the operator is not using. Use `launch_game(node="idle")` for a fresh emulator test or `start_job(require_worker="idle")` for analysis and modding, then pin later jobs to the returned worker ID. Session operations route to their owning worker. `capture_worker_screen` returns a desktop image and can attach it to an inbox request with a task step. The gBox desktop's **Other PC** button opens a live, resizable picture-in-picture of that worker: by default only its gBox window (cropped server-side from the bounds the worker reports), **Desktop** expands to the whole screen, the wheel zooms at the pointer, the middle button pans, and **Fit** / **1:1** reset the view. Agent use holds Windows playback outputs at 2% while a job or agent-started game is active.

The title bar's checkbox controls a Hermes cron job on Spark. Checking it schedules an immediate inbox run and repeats every thirty minutes. Tasks follow Hermes's connected cron cloud route and available fallbacks; the interactive local model remains separate. Each run claims one request, works in an isolated Git worktree, validates changes and uses `publish_task_changes` for a real draft PR. A PR remains separate from verified ticket completion. See [dispatch and delivery](hermes-throughput.md).

For Hermes worktree jobs, launch the gBox MCP Python with `-P -m gbox` so the task working directory cannot shadow its implementation. Set `PYTHONPATH=/home/ehm_eckx/gBox/system`, `GBOX_HERMES_DISPATCH_STATE=/home/ehm_eckx/gBox/system/gbox-data/hermes-dispatch`, and `GBOX_OPERATOR_WORKER` to the PC currently in use. Set `GBOX_TEST_WORKER` when the operator explicitly assigns a test PC; that assignment takes precedence over recent-input telemetry. The no-agent feedback supervisor repairs canonical MCP paths automatically while preserving both PC preferences and the tool allowlist. Enable `prepare_task_workspace`, `publish_task_changes`, and `get_dispatch_feedback` in the gBox MCP tool allowlist.
