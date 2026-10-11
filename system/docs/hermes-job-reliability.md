# Hermes job reliability repair

Date: 2026-10-10. Tracking report: gBox #1109 (`69b9ba86beca4a80`).

Codex implemented this repair. An independent Hermes run using Ollama Cloud
`kimi-k2.7-code` verified screenshot analysis followed by successful gBox MCP
calls: execution `a88daf7f82464174b587923c0451f108`, session
`cron_6c08dea1e61a_20261010_133940`.

## Observed failures and changes

* Google screenshot/tool history failed with HTTP 400, “Requests ending with a
  model turn are not supported.” Screenshot analysis now uses Hermes's auxiliary
  Google vision route through OpenRouter, returning text to the working agent.
  The original failing image and a real worker screenshot both passed analysis.
* Google investigations hit the account's 20-request-per-minute limit, and a
  pinned Z AI job exhausted its five-hour quota. Background work now uses
  Ollama Cloud Kimi, with connected-service fallbacks and two concurrent cloud
  jobs. Job pins are omitted so Hermes can use its configured fallback chain.
  Interactive Hermes keeps its existing local model. Existing intentional
  benchmark pins remain available.
* Failed incident jobs were returned indefinitely instead of retried. Genuine
  one-shot failures are rearmed through Hermes's atomic CLI operation. Exhausted
  legacy interval jobs get one identifiable replacement, preserving history.
  Pending and running occurrences suppress duplicate dispatch. Terminal
  `unknown` history does not block fresh work.
* Recent finished runs hid older live investigations. Tasks now prioritizes
  live runs and exposes their actual billing provider and token usage. Active
  runs include ticket IDs from progress replies and jobs; merely reading a
  ticket does not claim it. The gBox `list_tasks` MCP tool is enabled in Hermes.
* Agents repeatedly ran unrelated headless tests and attempted unavailable
  unattended tools. Prompts now select one unclaimed issue, preserve existing
  patches, use direct supported tools and focused checks, and reserve final
  turns for validation and reporting. The canonical Linux share has no `.git`;
  its workflow preserves patches and baseline hashes instead.
* A frame-capture request remained running for several minutes. Read-only
  `get_frame` requests now fail after 120 seconds, with an explicit missing-
  screenshot error. A conditional document update preserves concurrent results;
  late results cannot resurrect an expired capture. Launches, model changes,
  save-state operations and game processes are unaffected by this timeout.

## Verification and accounting

Nineteen focused tests passed on both Windows and Spark. They cover scheduling,
retry/deduplication, actual SQLite execution states, ticket ownership, live-run
visibility, MCP request/image/metrics round trips, idle deployment guards, and
expired captures with rejected late results. Existing FastAPI deprecation
warnings do not affect these results.

The independent cloud verifier completed with **37,618 input / 2,406 output
tokens**. Its screenshot/tool sequence completed without the original HTTP 400.
Readiness probes also succeeded for Ollama Cloud and OpenRouter Opus; DeepSeek
completed a real tool-using investigation. Z AI remains available as a fallback
when its quota resets. Actual session usage was posted once per session to the
corresponding reports; unavailable Codex token counts are explicitly recorded
as unavailable, not estimated.

Recovered runs posted concrete results for #1071, #1093 and #1081. #1071 is
marked done for its emulation recovery; this does not verify a character swap.
#1093 and #1081 retain pending deployment or visual acceptance checks. The
DeepSeek save-state investigation #1106 also retains its separate acceptance
criteria. A completed Hermes execution does not automatically complete a ticket.

## Finalized model usage

`hermes_accounting` reads ended cron executions, complete tool transcripts and
the `session_model_usage` ledger. The feedback supervisor and Z.AI availability
watcher share this implementation. Maintenance-only executions do not consume
the bounded inference-run scan. The accountant performs no inference, task
dispatch or provider change, and runs independently of provider cooldowns and
other active work.

Ticket ownership requires successful, call-ID-matched mutation receipts.
Reading a ticket, quoting its ID or attempting a rejected operation cannot
reserve it. Mixed ownership and incomplete transcripts defer accounting rather
than allocate tokens by guesswork. Hermes's empty primary-task label is
normalized to `primary`; helper tasks retain their own model and provider.
Input includes uncached, cache-read and cache-write tokens. Reasoning remains
part of output rather than being counted again.

Successful earlier metric snapshots and verified manual final records are
credited once. Per-model and aggregate markers preserve exact provenance.
Unknown historical credits are left unchanged. API writes first persist a
write intent, then verify the returned counters and markers. Lost responses
are resolved by reading the ticket; unresolved writes are not replayed blindly.
Tools, turns, elapsed time, ticket status and completion credit are unchanged.
Measured costs are distinct from estimates, and subscription credits are not
inferred from tokens. Accounting a run does not establish gameplay acceptance.

## Native capture and checkpoint failure feedback

The feedback scanner distinguishes a covered or unavailable emulator window
from a failed emulator. It keeps the rejected capture, refreshes session
identity, and requests one bounded retry using only the owned test window or
its current GPU surface. Desktop pixels cannot establish gameplay acceptance,
and occlusion checks remain enabled. The operator PC is protected.

Rejected, empty or unfinished checkpoint containers have a separate lesson:
preserve the original and its hash, validate the complete bounded container,
and obtain a separate completed native save only from a still-live owned test
session. An older checkpoint cannot be labelled the same reported moment.
These local failures do not create an inference-provider cooldown. Repeated
maintenance scans do not duplicate the lessons.

## Backend activation

The guard reads active worker jobs and Hermes claims from their canonical
read-only databases. It also checks gBox conversations, worker/session/PID
identity and enabled cron schedules that are overdue or due within 60 seconds.
Unknown or changing snapshots defer activation. It rechecks immediately before
the backend refresh, including after its progress reply. It does not call
`GET /api/tasks`, which can enqueue inventory jobs while collecting a snapshot.

These checks do not reserve admission to the scheduler: a new run can still
begin after the final observation. A separate external maintenance reservation
is required before using the activation function. Do not invoke it inside a
claimed Hermes cron execution; that execution deliberately blocks the guard.
Installing this source neither restarts the backend nor activates a Windows
worker. Existing games and tasks remain separate acceptance requirements.

Historical maintenance job `8e210aab9898` handled the earlier #1109 bridge
activation. Its original receipts, including a failed claim occurrence, remain
in the report. They do not prove activation of subsequent source changes.

Attached evidence includes the original screenshot regression, independent
verification screenshots, an allowlisted audit, exact source patch and actual
session metrics. No account credentials are included.

## Recurring review prompts

The Claude ledger hook recognizes only the exact observed six-line scheduled
review instruction. That reminder continues to run and discover app/gap issues,
but does not create another persistent inbox request. It resets the active
usage target and explicit claims for that turn, preserving the originating
operator request. A review can explicitly claim and meter a real issue.
Changed templates, operator requests for reviews, actual findings and automatic
issue reports retain their ordinary logging. This does not disable a schedule,
discard report history or mark a substantive request complete.

## Provider isolation for screenshot helpers

A cron job's main provider pin does not pin `vision_analyze`. The helper can
inherit a separate global provider and use its own fallback ladder. Read the
`session_model_usage` ledger as well as the main session counters; record helper
usage separately and do not treat an unpriced cost of zero as a measured bill.

`scripts/apply_hermes_strict_auxiliary_routes.py` installs an optional,
context-local vision policy on the supported Hermes runtime. An opted-in job
has `auxiliary_routes.vision` containing an explicit `provider`, `model` and
`strict: true`. The policy ignores unrelated global helper credentials and
routes, blocks automatic and cross-provider fallback, and preserves retries on
the chosen provider. Unsupported runtime functions or incomplete patches are
rejected before writing. Source backups and before/after hashes are produced.

Disable the target job before applying, then confirm it starts through a fresh
external cron worker before resuming. The external worker loads the patched
source without restarting the gateway or other active jobs. Cached in-process
workers need a controlled restart to activate it. Jobs without the optional
field retain their existing routing. The scope resets on completion or error
and propagates through the existing cron and tool thread contexts.

The portable fixture suite checks conflicting routes, unavailable clients,
quota errors, nested and concurrent contexts, worker propagation, attribution,
idempotence and rejection of unknown runtime source. A real image call and its
separate provider ledger must still verify the deployed task's route.
