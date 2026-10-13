# decomp.me / IDA Pro / N64Recomp

Three op-based native tools registered by `gbox/decomp_tools.py`, filling the
reverse-engineering stack around the existing Ghidra tools (`analyze_binary`,
`ghidra_script`) and the pinned REA MCP bridge (`rea_*`).

All state stays on the node that runs the job (`cfg.runtime`), never on a network
share or the operator PC, unless a job is explicitly dispatched there.

## decompme

REST client for the decomp.me API (`https://api.decomp.dev`, override with
`decompme_base_url`).

- **Read ops** (no token needed when the API permits): `scratch` (GET
  /scratch/{slug}), `search` (GET /scratch?platform=n64&preset=zelda64&...),
  `compilers`.
- **Write ops** — `create`, `claim`, `update`, `fork`, `compile` — require a
  GitHub OAuth token because **decomp.me publishes submitted source publicly**.
  The tool refuses these ops without a token and declares the publication as a
  side effect so gBox permission prompts name it.

Token resolution order: `DECOMPME_TOKEN` env var, then `decompme_token` in the
config (keep it in the per-machine `gbox.local-<host>.toml` overlay, not the
shared `gbox.toml`). The API serves empty 200 bodies on token-gated routes, so
the client raises a clear "this endpoint requires a token" error instead of
returning a phantom result.

Example job: `decompme {op: search, params: {platform: n64, preset: zelda64}}`.

## ida_pro

Locates and drives the operator's IDA Pro on the node that runs the job. Set
`ida_home` in gbox.toml or let the search find it (Windows: `C:\Program Files\IDA*`;
Linux: `~/IDA*`, `/opt/IDA*`, or `runtime/ida`).

- `op=locate` — report ida_home, executable and user dir.
- `op=analyze` — headless auto-analysis (`-A -B`) with the embedded
  `gbox_export.idc` census script, exporting functions/strings as
  `analysis.json` in the same shape as `analyze_binary`'s Ghidra export.
- `op=mcp_start` — write `ida_mcp/config.toml` into the IDA user dir
  (`%APPDATA%\Hex-Rays\IDA Pro` / `~/.idapro`), launch IDA on a binary and wait
  for the MCP port. Returns `rea_env_hint` whose `REA_IDA_MCP_CONFIG` value plugs
  into `config.rea_env` so the REA bridge (`rea_*` tools) can drive the same
  database through mrexodia/ida-pro-mcp (streamable HTTP on
  `http://127.0.0.1:<port>/mcp`). Keep subsequent REA calls on the same
  `worker_id`.
- `op=mcp_status` / `op=mcp_stop` — probe the port and stop the IDA process gBox
  started (PID file in runtime).

Requires the ida-pro-mcp plugin installed in IDA's plugins dir
(<https://github.com/mrexodia/ida-pro-mcp>). `check_port = false` is written so
an existing IDA instance is never killed by a second launch.

## n64recomp

Source build and ROM recompilation (Mr-Wiseguy/N64Recomp).

- `op=toolchain` — report git/cargo/cmake/Vulkan SDK/MSVC availability.
- `op=provision` — shallow-clone N64Recomp into `runtime/n64recomp/N64Recomp`,
  `cargo build --release` the backend crate, and record a receipt (commit sha,
  toolchain, result). The RT64 frontend stays a documented manual step on
  Windows: `cmake -B build -S RT64` with MSVC + the Vulkan SDK.
- `op=generate` — copy the upstream `config/RecompModInfo.toml` template into
  `runtime/n64recomp/mods/<name>` (or `project_dir`) and run the recompiler
  (`cargo run --release -- --rom <rom> --config <toml>`), producing the Rust mod
  project from an owned ROM. Runs only on the node holding the ROM; never the
  operator PC.
- `op=status` — repo readiness, toolchain, and this node's provision/generate
  receipts.

## Permissions and safety

| Tool        | Permissions                                                      | Side effects                          |
|-------------|------------------------------------------------------------------|---------------------------------------|
| `decompme`  | read, execute, network                                           | publish decompiled source publicly    |
| `ida_pro`   | read, execute, file_mutation                                     | launch/stop IDA; write MCP config     |
| `n64recomp` | read, execute, install, network, file_mutation                   | clone/build source; generate projects |

All three are unavailable-safe: missing IDA, tokens or toolchains raise
`ToolUnavailable`/`RuntimeError` with the exact cause instead of half-running.
