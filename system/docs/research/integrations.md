# The integrations box: MCP servers as gBox tools

Status: **working** (2026-11-07). `gbox/integrations.py` + `gbox/mcp_stdio.py`, with five routes, and two integrations
live: **rea (229 tools)** and **ghidra (27 tools)**.

## The model

An integration is a command that starts an MCP server, plus the name to call it by. That is the whole model because it
is the whole truth: REA, the Ghidra bridge and Playwright are all just argv. One registry, one client, one place a route,
bot, operator or scheduled task can ask "what tools does this system have".

```
~/.hermes/config.yaml  mcp_servers:   ->  rea, playwright, ghidra, gbox     (agents get these)
~/gBox/gBox-data/integrations.json    ->  {"integrations": {name: {command, kind, source, enabled, ...}}}
                                        (gBox itself gets these, over stdio)
```

Both sides matter: the Hermes config makes an integration available *to agents*, and the gBox registry makes it
available *to the system* - a route, a bot loop or a cron task can call it without an agent in the middle.

## Routes

| route | what it does |
|---|---|
| `GET /api/integrations?probe=true` | the catalogue; `probe` starts each and counts its tools |
| `POST /api/integrations` | register `{name, command, ...}` |
| `POST /api/integrations/from-repo` | paste a repository URL; a known recipe decides what to register (dry run unless `apply`) |
| `GET /api/integrations/{name}/tools?search=` | one integration's tools **with the argument fields each takes** |
| `POST /api/integrations/{name}/call` | call `{tool, arguments, timeout}` |

The `fields`/`required` in the tools listing are not decoration: REA validates arguments strictly, and a caller that
cannot see a schema guesses. Measured on the first attempt - `binary_session` was called with a `path` it does not take
and REA refused it with `Unrecognized key: "path"`, which is exactly what a guess produces.

## Live

```
GET /api/integrations?probe=true
  registry: /home/ehm_eckx/gBox/gBox-data/integrations.json
    rea      ok=True  tools=229
    ghidra   ok=True  tools=27

POST /api/integrations/rea/call {"tool":"binary_session","arguments":{}}
  -> {"result":{"open":false,"cleanup_pending":false,"capabilities":[{"provider":{"id":"native-macos",...}}]}}

GET /api/integrations/rea/tools?search=pseudo
  tools 229 | matched 9 | procedure_pseudo_code required ['procedure']
```

## REA (`morluto/rea`)

Installed with npm into `~/gBox_alt/tools/rea` (`rea-agents@6.8.0`), started as `rea --mcp` (MCP over stdio, protocol
`2025-11-25`). Its own doctor is clean: 229 tools and 6 prompts, catalog digest matching the package. Also registered in
`~/.hermes/config.yaml` as `mcp_servers.rea`, so agents get it as well - and that file is backed up before any edit.

A paste of `https://github.com/morluto/rea` resolves through the recipe table: `POST /api/integrations/from-repo` returns
`start_present: true` and the absolute command, without registering anything until `apply` is set. Recipes exist for
`morluto/rea`, `NationalSecurityAgency/ghidra` and `microsoft/playwright-mcp`; an unknown URL is refused with the list of
known ones rather than a guess.

## Why the Ghidra side is different from before

`docs/ghidra-service.md` said "written, not run - Ghidra isn't installed". That is now false twice over: Ghidra 12.2 is
installed at `~/gBox_alt/tools/ghidra_12.2_PUBLIC` with a decompiler **built for arm64** (`ghidra-arm64.md`), and the
existing Ghidra MCP bridge is a registered integration with 27 tools. Two ways in, one registry.

## Adding an integration

1. install the server however its project says (`npm install rea-agents`, a pip venv, a git checkout);
2. `POST /api/integrations {"name": "...", "command": "/abs/path/to/server --mcp"}`;
3. `GET /api/integrations?probe=true` to confirm it starts and see its tool count;
4. (optional) add the same entry to `~/.hermes/config.yaml` if agents should see it too.

No code changes: a new integration is a registry entry minus the parts above.

## Tests

`tests/test_integrations.py` (9) and `tests/test_rea.py` (7) run against stand-in MCP servers over stdio: registration
round-trips, the catalogue probe, a broken command reported instead of raised, shared-client reuse, strict-argument
refusals, recipe matching and the dry-run default. Two real bugs were caught this way - `shlex.split` eating Windows
backslashes in a command line (`WinError 2` for a binary that exists) and the box claiming a package was missing because
it looked only at `PATH`.

## Employable by agents, not just by routes (2026-11-07)

A registry and a call route only help something that can speak HTTP. gBox's own MCP server is what agents actually see,
so the integrations are exposed there too, as three tools:

| MCP tool | what an agent does with it |
|---|---|
| `integrations` | list what this system can use, `probe` to start each and count tools |
| `integration_tools` | read one integration's tools **and the fields each requires** |
| `integration_call` | call one tool |

Verified by speaking to gBox's MCP server exactly as an agent would (stdio handshake, `tools/list`, `tools/call`):

```
server: {'name': 'gbox', 'version': '0.1.0'}
tools: 180
  integrations       present
  integration_tools  present
  integration_call   present
integrations call  -> {"v": 1, ... ghidra: 27 tools, rea: 229 tools ...}
```

Before this, the server offered 177 tools and none of them could reach an integration. Now an agent calls
`integration_call {name: "rea", tool: "procedure_pseudo_code", arguments: {...}}` and gets REA's own result back.

One deployment trap worth recording: a `scp` inside a shell line that PowerShell failed to parse **never ran**, so the
first probe reported the tools missing and the deployed file still had the old hash. The check that caught it was
comparing `md5sum` on the host with the local hash - the same verification every deploy in this project uses.