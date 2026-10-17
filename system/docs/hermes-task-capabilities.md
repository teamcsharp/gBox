# Authorized Hermes task capabilities

The operator explicitly requested that LLM tasks can execute every required tool,
after a scheduled Ghidra task refused a read-only `python3 -c` probe as script
execution. The runtime had `approvals.cron_mode: deny`, excluded `code_execution`
from cron, and exposed only 30 gBox MCP tools. Task instructions also told agents
that Python orchestration was denied.

## Applied profile

`gbox.hermes_capabilities.task_profile` is an explicit opt-in. Scheduling and
status reads do not apply it automatically. The profile preserves model/account
configuration, MCP launch arguments, worker assignments and interactive approval
settings. Hermes's atomic configuration writer applies it without copying keys.

- `approvals.cron_mode`, `single_query_mode`, `unattended_mode`: `approve`.
- Cron gains Python code execution, delegation, model ensembles, video and the
  configured CLI task tools. `cron.allow_agent_scheduling: true` enables follow-up
  scheduling. Hermes still omits interactive clarification and messaging in cron.
- Both `security.allow_private_urls` and `browser.allow_private_urls`: `true`,
  enabling local gBox/worker URLs in the tools that read those separate settings.
- Remove gBox MCP `tools.include` and `tools.exclude`. An empty `include` list
  would disable every tool; absence exposes the current and future registry.
- Agent test sessions run only on `i9-NUC` or the Spark, while idle, never on
  `JAYBUILTFINALE` (the operator's play PC, decision of 2026-10-13). Testing
  remains at 2% audio and preserves existing games, owned ROMs and saved moments.

The operator-approved unattended profile runs task commands without waiting for
a human approval card. It does not change Hermes's built-in command floor or
turn missing game-specific implementations into working model writers.

`hermes_task_mode.status()` includes a credential-free `capabilities` audit.
`python -m gbox.hermes_capabilities` also prints that audit. Explicit `--apply`
must run with Hermes's interpreter and `hermes_bootstrap` loaded, so its own
configuration writer is available. The production configuration has a private
backup in `~/.hermes/config-backups/`; it is never attached to reports or Git.

## Live verification on 2026-10-10

- The same DOA2 BIN probe from the operator's screenshot was still classified as
  `script execution via -e/-c flag`, then approved in actual cron context. Calling
  Hermes's `terminal_tool` without `force` returned exit code 0 and the real BIN
  header results. Calling `execute_code` independently also returned exit code 0.
- A live gBox MCP connection enumerated **220 tools**, including **all 195** job
  registry entries; none were missing. Read-only favorites and worker calls passed.
- Hermes's own discovery registered **222** gBox entries (220 tools plus resource
  helpers). Its effective cron resolution included code execution, delegation,
  ensembles, scheduling and gBox; none were disabled. The browser's actual private
  URL resolver returned true.
- **17 focused checks** passed on Windows and Spark, covering opt-in, empty-filter
  semantics, configuration/worker preservation, credential-free diagnostics,
  scheduling and dispatch feedback. The general inbox and Z.AI Ghidra prompts were
  updated; retired job histories were retained.

Exact results and the complete tool inventory are saved privately at
`gbox-data/hermes-dispatch/task-capabilities-verification.json` and attached to
the completion report. An enabled tool can still fail because of unavailable
workers, missing dependencies, quota or a missing native game writer. Agents must
record the actual cause and preserve their work before correcting it.
