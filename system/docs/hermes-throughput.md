# Hermes throughput audit — 2026-10-21

This audit used read-only authenticated API requests, canonical local state, retained execution records, and archived run evidence on the prime Spark. It did not dispatch duplicate work, change models or capacity, restart a provider, or interrupt gameplay. Times below are UTC.

## Dispatch outcomes and denominator

The fixed reporting window is **2026-10-20 17:53:39 through 2026-10-21 17:53:39**. The denominator is **121 distinct inbox reports whose latest confirmed dispatch falls within that window**. It is not every execution occurrence, every retry, or all favorite-game work.

| Latest dispatched occurrence | Reports |
| --- | ---: |
| Completed execution | 62 |
| Failed execution | 40 |
| Running at the cutoff | 19 |
| Cancelled or timed-out execution status | 0 |
| Total | 121 |

The queue labels 102 of these reports `finished` and 19 `queued`. `finished` includes both the 62 completed and 40 failed occurrences. It does not mean that the request is solved. The reports themselves were 93 `open`, 26 `in_progress`, and 2 `done` when checked. The two done reports were #2857 and #2910; this audit did not independently repeat their acceptance checks.

Method:

1. Read `~/gBox/system/gbox-data/hermes-dispatch/work-queue.json`; select inbox items with a nonempty job ID and `last_dispatched` within the fixed window.
2. Match the latest occurrence in `~/.hermes/cron/executions.db` by job ID and start time no earlier than dispatch minus two seconds. Do not use a previous execution of the same recurring job. Exclude claims after the cutoff and treat completion after the cutoff as still running.
3. For a pruned occurrence, use the exact queue `last_run_id` to find `run:<id>` in `~/gBox/system/gbox-data/hermes-dispatch/result-review.sqlite3`. Validate the archived canonical run's job ID and start time before accepting its status.
4. This recovered 67 occurrences from the execution DB and 54 from archived canonical run payloads, leaving no unknown outcomes in the 121-report cohort. Read failure text from the matching cron output's `## Error` section, not from a model's diagnosis or an older error quoted in its prompt.

Hermes caps the execution DB at 1,000 terminal records (`~/.hermes/hermes-agent/cron/executions.py`, `MAX_TERMINAL_EXECUTIONS` and its delete query). Frequent control jobs share this retention budget. Counting only retained execution rows initially missed 54 outcomes; treating those missing rows as successes would be incorrect.

## Failure evidence

| Terminal error in the cohort | Count | Latest failed execution |
| --- | ---: | --- |
| HTTP 429: `Local inference: too many concurrent requests` | 30 | Oct 21 14:31:37 |
| Response remained truncated after four continuation attempts | 9 | Oct 21 15:32:24 |
| Context compression timed out without reducing the conversation | 1 | Oct 21 11:47:29 |

The 30 concurrency failures span Oct 21 03:29:10–14:31:37. The 40 failed occurrences were assigned to MiniMax in 39 cases and Spark2 in one. The compression timeout is recorded as `failed`, not as a separate `timed_out` status.

A later proxy-log check at **18:05:28** found MiniMax's last concurrency-error call timestamp at **14:31:31**. Its last-hour retained calls were **467 successful, zero errors**. Other overload errors occurred at 15:00 and 15:50. Thus the cohort's concurrency failures are historical evidence, not proof that MiniMax is currently failing at the same rate.

Spark2's last-hour retained proxy calls at 18:05:28 were **253 successful, 36 errors, and one busy response**; recent errors said `Local inference stream interrupted before completion`. That log message does not distinguish caller cancellation, upstream disconnect, or timeout. It needs correlation with request/execution timing before attributing a cause. A partially emitted tool stream must never be replayed automatically.

Proxy log timestamps identify call start, whereas execution timestamps identify run completion. Rotating `local-llm-calls.jsonl` logs are an observation window, not an unlimited historical ledger.

## Active capacity and admission

At **17:53:39–17:53:44**, 38 Hermes executions were active: Spark2 22 and MiniMax 16. The inference pool caps were **24 and 16**, respectively. Spark2 had 24 active proxy calls and five waiting; its upstream metrics showed 15 running and nine waiting. MiniMax had six active proxy calls and none waiting. Agent counts and simultaneous inference calls measure different things.

At **18:05:28**, the same caps remained in place: Spark2 24 active calls/three waiting; MiniMax eight active calls/zero waiting. Both nodes reported Ready. The active models were `Qwen/Qwen3-Coder-Next-FP8` and `minimax-m3.1-flash:cloud`. A separate shared/default route advertised a Qwen3.8 trial with capacity two; that did not replace the active 24-slot Spark2 pool in these observations. The `ollama-cloud/kimi-k2.7-code` route had no recorded calls or runs in the server's current-day window inspected at 17:52.

Worker CPU readings at **17:58:32** were Spark 66.9%, i9-NUC 53.4%, and JAYBUILTFINALE 45.6%. All were online with background testing enabled. Earlier Spark admission was denied because its NVIDIA GB10 was at **87% GPU utilization against a 70% admission budget**; 87% was not a CPU reading. The protected operator PC was waiting for five minutes without operator input. No worker was launched or restarted for this audit.

Read-only API surfaces used: `/api/hermes/local/nodes`, `/api/hermes/local`, `/api/hermes/task-mode`, `/api/hermes/providers?window=today`, and `/api/workers`. The provider `today` window began Oct 21 06:00 UTC and must not be confused with the rolling 24-hour dispatch cohort. The pure activation snapshot and local job DB were used instead of `GET /api/tasks`, which can enqueue inventory work.

## Why completed runs are not closed reports

The queue's `reconcile()` records a model report, requests result review, marks the occurrence finished, and applies retry backoff. It does not close the request. A completed execution can be a useful partial milestone, a blocked investigation, or an unsuccessful publication attempt.

Of the 62 completed occurrences, 55 had no publication receipt, six had an older receipt, and one had a publication within the fixed window (#2057, PR #765, already merged). A subsequent review-ledger read found 42 of the completed occurrences without a verdict, 15 with a blocked verdict, and five with a retry verdict. Those review counts can change after the fixed execution cutoff. Review output is guidance, not independent proof that its diagnosis is correct.

Concrete bottlenecks and bounded next actions:

- **Tool argument mismatches:** #1371's status closure failed because `solved_by.verified_by` exceeded its 80-character limit. #2970's publisher call used an object where a list of file strings was required. Other reviews show numeric report numbers used in place of full request IDs, incorrect checkpoint stage/status values, and test lists containing objects rather than path strings. Use the actual tool schema and validate the small final payload before retrying the failed handoff.
- **Missing publication and wiring:** #2969 produced a local commit but exhausted its budget before publishing or completing HTTP/coaching wiring. Preserve and review that patch rather than dispatching duplicate implementation. Reserve the final calls for tests, a durable checkpoint, and publication.
- **Unverified research scope:** Several completed runs contain inventory or static analysis but no verified writer, fresh-boot test, or rollback proof. Keep the parent request open while publishing a truthful, useful bounded source milestone. Do not label missing game assets or save semantics as solved.
- **Review backlog and errors:** The observed review ledger had hundreds of pending records, plus invalid JSON answers and transient network errors. Deliver durable review guidance without rerunning already completed implementation; refresh stale worker-admission diagnoses against current workers before treating them as current blockers.
- **Stale workspaces:** #1371's isolated copy lacked later fixes already deployed. Compare against current main before publishing, so a retry cannot regress the current implementation.

These actions do not require raising concurrency caps or changing the operator's model trials.

## Reviewable output and assimilation

- **#2969:** commit `3aaca405e358658b5af9d1ddd8b5d624c82ccf30`, branch `hermes/request-2969-1792597115713632580`, workspace `/home/ehm_eckx/gBox_alt/gbox-hermes-tasks/5d8e0482ffa54a08`. It completed at 17:18:23. No publish receipt or PR existed at audit time. Source review found the registry expected `tools.PLAYBOOKS` to be a dict even though the actual contract is a tuple, persistence failures were swallowed, and read-modify-write updates lacked concurrency protection. Its tests were model-reported, not independently rerun by this audit. These findings were handed to the separate assimilation agent for repair and verification.
- **#2970:** completed at 17:26:23 with only an untracked `system/docs/spark2-live-state-2026-10-21.md`; no new commit or PR. It documented incomplete downloads/build prerequisites, not successful model activation.
- **#2964:** still running in the initial snapshot; no duplicate was launched. #2965–#2968 had no dispatch job in that snapshot.
- Fresh GitHub metadata showed publication receipts #783 and #765 already merged, #753 closed unmerged as a draft, and #726 still an open draft. Receipt `pr_state` alone was stale and was not used as merge evidence.
- One favorite-game checkpoint in the rolling window was verified at the **analysis** stage for Illbleed (request `9f15106993224139`); that does not establish runtime or writer acceptance.

## Retry-After repair

The deployed local admission path already queues within the configured permit count; its full-queue/wait-timeout responses are 503. The quoted `Local inference: ...` 429 comes from an upstream error response. Before this repair, both `LocalLLM.complete()` and `LocalLLM.stream()` discarded upstream `Retry-After`, and the pool's sub-500 `Busy` response discarded any retry hint. Hermes's retry implementation supports `Retry-After`, so losing it prevents the caller from honoring the provider's requested delay.

The repair preserves valid integer delay-seconds (including zero) or HTTP dates through completion, pre-stream errors, and the pool response. Malformed, negative, fractional, oversized, or multiline hints are omitted. When all existing 5xx failover candidates fail, the last valid hint is retained; without one, the existing 30-second fallback remains. Context-size retry reports the final response's hint. Existing HTTP status mapping, concurrency limits, model selection, failover order, and partial-stream behavior are unchanged. The repair adds no new inference retry or stream replay.

Focused offline validation: **58 passed** in `tests/test_llm_proxy.py` and `tests/test_hermes_pool.py`. These cover numeric/date/invalid hints, streaming and nonstreaming errors, context re-cap errors, exhausted failover, capacity limits, and the existing prohibition on replaying a partial tool stream. Runtime deployment and improved throughput require a later observation; this document does not claim either from unit tests alone.

## Status handoff repair

The MCP `set_request_status` tool previously advertised solver-credit fields as unconstrained strings, while the HTTP server enforces service/system/verified_by/run_id limits of 80 characters, model of 160, and verification of 1–2000. This mismatch directly explains the observed #1371 closure 422.

The tool now advertises those exact limits and checks solver credit before sending the HTTP mutation. An oversized reviewer label produces an actionable correction: use a concise identity and put the complete test evidence in `verification` or `note`. Longer verification belongs in `note` or `reply_request`. The tool does not silently truncate supplied evidence, infer acceptance, or automatically close a request. Solver credit remains valid only with an explicit `done` request; existing server acceptance guards still apply.

Focused offline validation: **29 passed** in `tests/test_mcp_requests.py`. The regression submits the actual oversized reviewer-label case and confirms no HTTP mutation occurs, then submits a corrected label with the full 2000-character verification and a longer note through the real HTTP server and checks persistence. This demonstrates a usable completion handoff after the caller supplies verified evidence, not independent verification of an arbitrary task.

Source entry points: `gbox/llm_proxy.py`, `gbox/hermes_pool.py`, `gbox/hermes_work_queue.py`, `gbox/hermes_result_review.py`, `gbox/hermes_delivery.py`, and the request status route in `gbox/server.py`. Deployed proxy source SHA256 observed during the audit: `199f8c16099cf4d5d6f156059c01565083206b3cf0c9b51a82befc55b2a3f0c6` (file mtime Oct 20 00:15:04 UTC). Deployed queue source mtime was Oct 21 15:29:53 UTC; a file timestamp alone does not prove when a running process loaded the file.

## Productive task packaging

The dedicated-host task prompt already specified a bounded milestone and a handoff reserve, but the large-task reserve named only tests and a checkpoint. The proxy's near-budget reminder also omitted publication. This could leave passing source in the workspace while the final response reported an unfinished handoff, as observed for #2969.

The large-task prompt now asks the agent to reuse the existing workspace, patch, published commit and pending job IDs; resume the first missing acceptance step; and identify one bounded deliverable plus its exact verification before new investigation. Passing source is published with explicit file paths and test-path strings before optional exploration. Research work retains a verified evidence artifact. Reserved calls cover verification, publication and a checkpoint containing actual results, returned receipts, exact pending jobs and the next acceptance step. The proxy's existing near-budget reminder now repeats that delivery sequence while tools are still available. A final response without a publication receipt leaves publication pending; partial work stays in progress.

This changes prompt packaging only: models, concurrency/admission settings, total tool budgets, handoff reserve sizes and the final-checkpoint cutoff are unchanged. Focused prompt/dispatch/budget verification: **54 passed** across `test_hermes_local_dispatch.py`, `test_second_spark.py`, and `test_hermes_run_budget.py`. These checks establish the dispatched and near-cutoff instructions and their tool availability; improved completion rates still require later observed runs.

## Preserved operational guidance and historical records

The dated audit above supersedes earlier throughput snapshots, active route/capacity observations, and its own initial incomplete outcome count. The operational guidance and historical experiments below are retained. Older dates describe their recorded state, not the current provider configuration or a new instruction to change it. In particular, the earlier Spark2 compression trial and rollback remain relevant evidence; the newer interrupted streams have not yet been individually correlated to a cause.

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
in `/home/ehm_eckx/gBox_alt/gbox-hermes-tasks`. Its repository is the tracked clone at
`/home/ehm_eckx/gBox_alt/gbox-hermes-repo`. Dirty patches survive subsequent attempts.
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
Dated agent handoffs (`context.handoff = "YYYY-MM-DD"`, `author = "agent"`) also
remain actionable when their request ID or number is explicitly in the operator's
priority list. This admits resumed work filed with `automated = true`, including
the October 21 handoff tickets, without treating a game's priority or an ordinary
automated reminder as an instruction to run it. Ownership, retry, review and
worker admission checks still apply.
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

## Spark2 compression time budget

On October 21, proxy interruptions near 600 seconds correlated with Hermes
`Context compression reached its total ceiling` warnings while tokens were
still arriving. The compression route was explicitly Qwen3-Coder-Next-FP8 on
Spark2, with a 300-second auxiliary timeout. Hermes's separate host ceiling
defaulted to 600 seconds; the auxiliary stream already allowed up to 1200.

The bounded live trial at 15:26:07 UTC raised this ceiling to 1200. Hermes
adopted it without restarting, and the first summary continued producing tokens
past 600 and 900 seconds. At 15:46:32 it still hit the new ceiling:
`agent.log` recorded attempt `d186a621e4b04a889747987b92b8f175` as aborted with
`commit_fence_cancelled` after 1,200,016 ms; the proxy recorded a 1200.22-second
interruption. The following committed result was Hermes's deterministic
fallback, not a completed model summary. This trial did not establish a
throughput improvement, so the explicit override was removed at 15:47:44 UTC,
restoring the original 600-second default while preserving all other settings.
Keep that default until further evidence supports another bounded trial.

`python scripts/configure_hermes_compression.py ~/.hermes/config.yaml ~/.hermes/hermes-agent`
previews the supported 1200-second trial for future diagnosis. Add `--apply`
only for a deliberately observed trial; it writes a private, byte-exact backup
and uses atomic replacement. The tool
requires the measured route and supported runtime setting, preserves custom
timeout overrides, and prints no config credentials. Only
`compression.context_total_ceiling_seconds` changes. Effective idle protection
stays at 300 seconds; capacity, provider, auxiliary timeout and spend limits
remain as configured. Hermes reads this setting for subsequent compression
attempts; no model or worker restart is needed.

Verify subsequent compression commits and proxy interruption rates before
further tuning. A longer ceiling permits useful summaries to finish but does
not itself prove improved throughput. To roll back, restore the prior value
(600, or remove this key if previously absent) while preserving newer settings;
the backup records the original configuration.
