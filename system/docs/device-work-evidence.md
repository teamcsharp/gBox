# Device work evidence

`GET /api/tasks/device-work?window=today|7d` is authenticated and read-only.
It does not invoke task inventory, create worker jobs, query GitHub, probe model
servers, or start inference. It reads local execution/session databases, retained
model-call logs, publication receipts, request state, and cached GitHub observations.
The response is cached for five seconds per window. All active Hermes executions
are included; ended history is bounded to 2,000 rows with an explicit coverage note.
Today uses the configured Hermes log timezone. Timestamps are epoch seconds.

Each run has a human-readable request title, current action, times, ticket links,
device attribution, and independently typed outcomes. A successful inference call
is not a completed task. An ended scheduler execution is not a resolved request.
Maintenance executions without model evidence remain explicitly unattributed.
Multiple observed inference devices share a separate lane instead of giving sole
credit to the last provider. An active assignment without a successful response is
labelled assignment-only. A model name alone never identifies a device.

Metrics cover returned evidence in the selected window. Run wall seconds are
window-clipped, summed elapsed execution time, including overlapping tasks; they
are not GPU time. Peak concurrency derives from these intervals. Call counts,
tokens, and mean successful-call duration come from the local proxy ledger, not
lifetime counters. Proxy duration includes handling/wait time. Missing token or
duration measurements are null. Token throughput is deliberately not inferred.
Ended-run delivery rate counts ended runs with observed delivery outcomes; it is
not a gameplay or acceptance-quality score. Retention, bounds and missing provenance
remain visible in `coverage`.

Outcome kinds:

- `pr_published`: exact pushed commit and open GitHub PR confirmed by the publisher.
- `pr_merged`: recorded GitHub merge to main whose head exactly matches that commit.
  This credits contribution, not the reviewer or merger's work.
- `pr_reviewed_merge`: the same PR merged at another head; context only, no merge
  credit without ancestry evidence.
- `request_resolved`: an exact paired tool response records a new status transition
  to done, with a server audit sequence, and the request is still done.
- `request_status`: done was acknowledged, but a new resolving transition is
  unproved; this includes legacy replies and idempotent calls. No completion credit.

Request status changes now serialize read/modify/write and return a transition
receipt (`previous`, `status`, `changed`, `at`, `audit_seq`). Repeating done preserves
the original completion timestamp and solver. Reopening and completing again is a
new transition, preserving the existing rule that old solver credit is not reused.

New PR descriptions record request-linked observed inference devices, providers,
models and run IDs, separately from the validation execution host. They never use
the current global model configuration to describe historical authorship. Each
published commit gets an immutable `hermes-dispatch/publications/PR-COMMIT.json`
receipt; future runs cannot overwrite its provenance. Legacy records with missing
evidence remain unknown. The existing merge reconciler stores exact GitHub
observations and backfills at most 20 previously posted notices per pass without
reposting them. The dashboard does not trigger this work.

Validation: focused API, attribution, publishing, merge, provider and solver tests
cover overlapping windows, mixed devices sharing one model, unpaired/failed tool
responses, no-op and concurrent done calls, reopened requests, changed merge heads,
all active runs beyond the history cap, and read-only endpoint caching.
