# Hermes delivery and dispatch feedback

Tracking report: #1132 (`6d7a1986e8034411`), 2026-10-10.

Cloud inference was running, but delivery was incomplete. The canonical Spark
runtime is not a Git checkout. Completed agents edited it without publishing
commits. The audited Kimi run consumed 509,687 uncached input / 16,956 output tokens and
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

Cooldowns identify the provider AND model. Structured provider reset timestamps
and Retry-After values determine the next retry. Missing metadata uses a bounded
scheduler backoff (initially five minutes for quota and one minute for rate
limits, increasing to at most one hour); that delay is labelled as policy, not
the subscription reset. A quota inside a tool result does not incorrectly cool
the inference provider. Available configured routes rotate between runs;
newly configured routes join the retained fallback catalog. Routes are changed
only while no agent run is active. Intentional per-job benchmark pins remain
untouched. Interactive model settings remain unchanged.

Provider failures now leave a durable recovery checkpoint containing the actual
Hermes session, occurrence and owned request IDs. The original conversation and
isolated Git workspace remain their source of truth. The no-agent supervisor
can re-arm the same unpinned genuine one-shot with continuity on an eligible
configured route. It first verifies ticket status, current ownership and whether
a later occurrence already superseded the failure. It resumes at most one job
per tick and three occurrences per job in 24 hours. Closed tickets, active jobs,
explicit pins and disabled task-mode activations are preserved. An uncertain
launch is held for review rather than repeated after a restart. The queue does
not create replacement jobs or erase failed history.

Task-mode status includes provider limit observations and recovery states.
Recorded usage uses Hermes's `session_model_usage` per-call route ledger, so
provider/model changes and fallback within one session are attributed to the
actual route. Session aggregates are reconciled against those deltas without
double counting; legacy residuals attributed only by session metadata are
explicitly counted and labelled. The scope is sessions started within the last
24 hours, including cache inputs, output and API calls, with recorded cost and
estimated cost counted separately. At most 1,000 sessions and 10,000 route rows
are aggregated; an incomplete window is explicitly labelled and a truncated
ledger does not manufacture residual attribution.
Z.AI's account windows retain their observation time and become stale after ten
minutes. Other subscription balances remain unknown unless an account endpoint
has actually supplied them. Session token totals never predict remaining quota.

## Nous account activation, 2026-10-11

The Nous login and fresh paid account/model endpoints passed inspection. Old
Nous inference records existed, but recent inbox work was using other routes;
the previous dedicated Nous job was disabled after an HTTP 402 credit error.
That historical failure did not describe the currently available account.
Nous/Claude Opus 5.5 is now included in the retained route catalog. The feedback
supervisor intentionally rotates the global route after completed agent runs,
so a particular primary provider is not a permanent preference. A task pinned
with `--provider nous --model anthropic/claude-opus-5.5` stays on Nous and does
not enter the global fallback ladder.

The installed Hermes cron constructor did not pass an output budget to
`AIAgent`; native Anthropic messages defaulted to 128,000 output tokens. This
can increase the requested credit reservation, although the old failed
request's exact wire payload was not recovered. The maintenance command
`scripts/apply_hermes_nous_output_limit.py` adds support for
`cron.output_token_limits.nous: 8192` only for the actual Nous cron route. It
checks the supported constructor's complete AST, preserves surrounding code,
backs up exact bytes and writes atomically. Unknown runtime versions or a
conflicting patch are refused. Run without `--apply` to check compatibility,
then explicitly apply to the installed `hermes-agent/cron/scheduler.py`.
Recheck after a Hermes update; the new setting is a gBox runtime extension,
not an upstream Hermes configuration key.

This is an initial request budget, not a hard spending ceiling. Existing
length retries may increase it to 16K/32K. The runtime supplies canonical
provider strings and ordinary parsed YAML dictionaries; malformed values
leave the native default unchanged. Keep the configured value a positive
integer within the selected model's supported output limit. Interactive
settings and other providers' initial budgets are unchanged.

Verification included 28 maintenance checks, a real stateless Nous code review
with private memory/context/tools disabled, and a running Nous-only report
#1216 investigation. Its recorded session configuration contains
`max_tokens: 8192`, and its native per-call billing ledger reports Nous with
real API calls and token counts. The task is visible by name in the Tasks
panel with expandable tools and output. Private replay evidence was sent only
after the operator explicitly approved that transfer. The report remains open
until the supplied moment's visual replay and deployed fix pass acceptance.

## Remote testing

MCP registry operations return a durable pending job ID after at most 25 seconds
of polling. Repeated identical active jobs reuse their ID. Explicit offline or
saturated targets fail before another job is queued. Agents continue independent
source work rather than repeatedly consuming five-minute calls.

Hermes's gBox MCP environment protects the operator's selected PC using
`GBOX_OPERATOR_WORKER`. Since 2026-10-13 the operator plays on JAYBUILTFINALE and agent test sessions run
only on i9-NUC or the Spark: `GBOX_OPERATOR_WORKER=JAYBUILTFINALE`, `GBOX_TEST_WORKER=i9-NUC` in Hermes's
`mcp_servers.gbox.env` (`~/.hermes/config.yaml`; the repo sets neither).
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
protected PC (superseded on 2026-10-13, above). JAY's idle worker was refreshed without a local emulator running.
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
Report #1119 remains unfinished until the saved conversation moment is tested
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

## Further autonomous delivery

DeepSeek finished the saved-slot source handoff for #1106 in
[draft PR #2](https://github.com/teamcsharp/gBox/pull/2), commit
`241023b7f9c9b6d226174f752841ffef53cdb3c8`, with nine focused checks passing.
It remains in progress for deployment and exact saved-moment acceptance on JAY.

The recurring inbox dispatcher subsequently used DeepSeek to investigate #1130
and delivered [draft PR #3](https://github.com/teamcsharp/gBox/pull/3), commit
`2adf113c02f53a6de17c4bbeb132bc2b8b4004c7`. Its endpoint checks passed; the
agent also ran nineteen related checks. The patch reuses an in-flight capture
report instead of stacking another save job. Live acceptance remains pending.
Codex manually corrected the initial draft's lost-input behavior: only matching
issue details reuse a pending report; each repeated capture appends its new
screenshot, diagnostics and timestamped session/context snapshot. Distinct
issue details create a separate report. Twenty-one related checks passed,
including preservation of the latest evidence and separation of distinct
issues. The revised PR head is `46fb89887d6f82cc53a7418f63ea1d19264a5f58`.
Deployment and live capture-system acceptance are still pending.

Resumed publication now refreshes the draft PR's title and validation body via
GitHub REST. This avoids the installed CLI's deprecated classic-project GraphQL
field and ensures future task iterations update the review description as well
as the source branch. A focused real-Git test verifies push precedes this update
and that title/body text is preserved through a structured JSON input file.

At the time of that dispatch repair, all three were actual open draft PRs,
verified through GitHub. Full measured session usage,
including cache reads/writes, is recorded once on the associated inbox tickets.
Report #1132 is complete with implementation, patch, screenshot and usage
attachments. Codex's unavailable session token count is explicitly marked
unavailable rather than estimated.

## Continuing tasks after a PR merge

On 2026-10-11, PRs #1 through #15 were integrated into main at
`b0559ef3e96f77466c3ea479e60802e90d5fe7bd`. Their merge does not establish
adoption by already running applications or acceptance of unresolved gameplay.

Task workspaces and branch records survive a merge so an agent can preserve
its patch and continue the same request. Publication refreshes `origin/main`
without resetting the branch, index or working files. An already integrated
commit cannot be reported as new source delivery.

`publish_task_changes` discovers only open PRs targeting main. If the earlier
PR was merged or closed, new commits on the existing task branch receive a new
draft PR. If an open PR exists, its description is updated. Both paths verify
the returned PR is open and belongs to the exact pushed commit and task branch
before recording successful publication. A failed lookup defers publication
instead of assuming no PR exists and creating a duplicate. An uncertain create
or readback is reconciled through open-PR discovery on the next attempt; the
workspace and pushed commit remain intact.

## Continuous favorite-game engineering queue

Task mode can now run a no-agent admission pump every minute instead of waiting
30 minutes after each model run. `hermes_work_queue` inventories the durable
`/api/favorites` list, including missing catalog entries, and retains one work
record per game. Selected games receive one recoverable child request under the
operator's configured parent request. No catalog page limit truncates the queue.

The pump reserves capacity before creating or resuming genuine one-shots. It
uses the existing configured cloud route, excludes known provider cooldowns,
and counts both queued and running agent jobs. At most four agents run, balanced
between inbox work and favorite-game analysis when both have eligible work.
Each lane alternates first attempts with follow-ups: acceptance and later game stages
do not wait until every untouched request or title has been visited. Explicit pick-whips,
native repairs and published work awaiting acceptance receive priority within each group.
Automatic replacement failures, extraction requests, tool gaps and operator child requests
remain actionable; recurring review reminders and agent notifications are excluded.
Two pending heavyweight native analysis jobs defer new inventory
and analysis admissions while allowing independent writer or acceptance work.
This is admission backpressure, not a new worker execution limit.

Per-game milestones are exact-build inventory, actionable executable/format
analysis, native reader, native writer, and runtime replacement verification.
`get_game_work_queue(game_id=...)` returns the saved next step;
`record_game_work` records partial, blocked or evidence-backed verified stages.
Verified stages require consistent source identity and existing artifacts
attached to that game's request. Runtime additionally requires an image, with
agent instructions requiring real donor/slot gameplay evidence. These checks
validate evidence references, not the truth of an image's contents. Readiness
is limited to the demonstrated build and donor/slot; it is never universal
character compatibility.

Pending native job IDs and active ownership suppress duplicate work. Lost
request-creation responses reconcile by a stable context marker. Uncertain
cron writes remain held instead of being blindly repeated. Ended runs without
new checkpoints back off from five minutes to six hours. Games rotate by last
dispatch, so one difficult title cannot monopolize the queue. Unfavoriting
stops new admissions while preserving existing work and evidence. Disabling
task mode pauses pending queue jobs and allows already active work to finish.

Pick-whip replacement/rebuild requests preserve the donor slug, selected actor name,
normalized game point, session, screenshot and saved moment. Managed Hermes queues
own these requests without also launching a local chat. An existing local resolution
still reserves its request. Same-game repair and favorite work cannot be admitted
together. Missing writers return an incomplete native result and a durable repair
request; an overlay is available only as an explicit operator action. The desktop
offers target identification/correction and marking the selected actor for rebuild.

The Z.AI quota monitor continues cheap account checks. Under queue control it
only restores an eligible route after quota recovery; it does not launch its
old competing favorites job. The one-minute pump and new MCP processes load
fresh source; an already running backend needs ordinary safe activation for
its updated toggle and task-view code.
