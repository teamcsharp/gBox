# Hermes delivery and dispatch feedback

Tracking report: #1132 (`6d7a1986e8034411`), 2026-10-10.

Cloud inference was running, but delivery was incomplete. The canonical Spark
runtime is not a Git checkout. Completed agents edited it without publishing
commits. The latest Kimi run consumed 509,687 input / 16,956 output tokens and
150 calls; repeated 300-second calls to the offline i9 worker left its patch
without tests or a GitHub handoff. A DeepSeek investigation used 124,085 output
tokens before reaching the same limit. These are actual session records, not
estimates of the subscription's remaining allowance.

## Delivery

`prepare_task_workspace` creates a reusable per-ticket worktree from origin/main
in `/home/ehm_eckx/gbox-hermes-tasks`. Its repository is the tracked clone at
`/home/ehm_eckx/gbox-hermes-repo`. Dirty patches survive subsequent attempts.
Agents edit this worktree, never the shared live runtime concurrently.

`publish_task_changes` validates explicit source files and focused Python tests,
checks JavaScript syntax when applicable, commits, pushes and opens or updates
a draft PR. It posts the real URL and commit to the report. Failed checks stop
publication. No credentials or runtime data are staged. A PR remains separate
from live acceptance and inbox completion.

Task-mode and incident prompts select one unclaimed ticket, use high reasoning,
and request a 45-tool-call work budget with ten calls reserved for handoff.
This budget is prompt guidance; the global Hermes iteration limit remains
unchanged for interactive use. The publisher itself enforces validation.

## Learning and connected services

`hermes_feedback` reads actual terminal executions and sessions. It stores
deduplicated lessons for quota, throttling, worker timeouts, unattended tool
denials, scheduler ownership, excessive iterations and missing publication.
Later dispatches include those lessons. A no-agent supervisor checks every five
minutes without consuming inference tokens.

Cooldowns identify the provider AND model. Quota errors defer that route for
five hours; rate limits for fifteen minutes. Available configured routes rotate
between cloud runs. Exhausted routes leave the fallback chain until their
cooldowns expire. Intentional per-job benchmark pins remain untouched. Local
interactive model settings remain unchanged. This changes dispatch based on
observed outcomes; it does not claim to retrain the underlying models.

## Remote testing

MCP registry operations return a durable pending job ID after at most 25 seconds
of polling. Repeated identical active jobs reuse their ID. Explicit offline or
saturated targets fail before another job is queued. Agents continue independent
source work rather than repeatedly consuming five-minute calls.

Hermes's gBox MCP environment protects the operator's selected PC using
`GBOX_OPERATOR_WORKER` (currently i9-NUC; JAYBUILTFINALE is the test PC).
Idle selection excludes that PC even when it owns no
live game or has been idle while the operator reads. A test launch also preserves
an existing game on the other PC. Windows agent jobs retain 2% audio enforcement.
Workers register a heartbeat every ten seconds independently of occupied job
slots. Running old worker processes require a safe refresh to load that change.

Initially i9-NUC was reachable on the network but its gBox worker was offline;
its administrative share rejected access and SSH/WinRM were unavailable. Pending
live acceptance therefore remains visible rather than being claimed complete.
Spark continues source analysis, focused tests and Git publication while that
client is unavailable. It subsequently reconnected and a real desktop capture
passed and was attached to the report. The operator then selected i9-NUC as the
protected PC. JAY's idle worker was refreshed without a local emulator running.
The operator's explicit test-PC assignment is stored in GBOX_TEST_WORKER.
It takes precedence over recent-input telemetry, while offline/saturated checks
and preservation of an existing game remain enforced. Unassigned selection
still requires idle telemetry.

## Verification

Thirty-two focused checks passed on Windows and Spark. They cover actual Git
worktree reuse, failed-test publication refusal, a pushed commit before PR
creation, durable model cooldowns and restoration, exclusion of quoted errors,
pending MCP jobs and retry deduplication, operator-PC protection, and heartbeat
recovery with all worker execution slots occupied. Existing FastAPI deprecation
warnings remain unrelated to this change.

## First real GitHub handoff

Hermes OpenRouter `anthropic/claude-opus-5.5` completed source handoff job
`306979feeae9`, execution `977b763d342f43ac9d0db47bade4d99b`. It reviewed the
previous OoT skip patch, corrected unsafe button handling and unsupported memory
assumptions, wrote focused tests, and published
[draft PR #1](https://github.com/teamcsharp/gBox/pull/1), commit
`74354d51b6cd543983282f6a846118ffe89caeeb`. Forty-two offline checks passed.
Report #1119 remains in progress until the saved conversation moment is tested
visually on the idle test PC.

The first publication attempt exposed a workspace-relative state lookup. Hermes
reused the existing record and completed publication. MCP now uses Python `-P`,
canonical PYTHONPATH and an explicit shared GBOX_HERMES_DISPATCH_STATE so a task's
working directory cannot shadow the MCP implementation or its state. That
failure is also included in durable dispatch lessons.

The task panel now includes cache reads and writes in total input, with their
breakdown, actual API calls and separately labelled recorded/estimated cost.
Hermes's canonical input counter excludes cached tokens; the former display
understated total context usage. Subscription quota balance is not inferred from
these counters.

Repeated successful maintenance occurrences are collapsed to the latest one per
job in the task list so they cannot hide completed cloud work. Expanded script
runs show their actual saved stdout instead of a perpetual starting message.
The updated visibility/output checks passed on both machines.
