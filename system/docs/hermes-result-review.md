# Hermes result review and source delivery

The existing ZAI/GLM supervisor guides priorities and diagnoses stalled work.
The opt-in DeepSeek controller independently reviews terminal inbox/favorite
queue executions and open PRs. Spark workers retain implementation ownership.
The repository delivery branch is `main`.

`hermes_result_review` records every terminal occurrence belonging to the queue
in `hermes-dispatch/result-review.sqlite3`. It rescans terminal execution history,
so a running row that finishes after a newer row cannot fall behind a cursor.
The normal dispatcher also records results before advancing its last-run marker.
Repeated discovery is idempotent. Rows, transcripts, model responses, usage,
integration logs and worktrees are retained. This inventory covers queue-owned
executions, not unrelated maintenance scripts or arbitrary interactive chats.

Every subsequent dispatch waits for its preceding result's review. Fresh tasks
remain eligible. The next prompt includes the diagnosis, corrective step and
verification. Three consecutive identical retry diagnoses escalate instead of
looping indefinitely. New request evidence or ZAI guidance reopens held reviews;
the controller's own reports do not trigger another paid call. ZAI receives
review counts, unresolved errors and queue holds in its supervision snapshot.
Set `supervision_only: true` in `zai-availability.json` when ZAI's role is the
build supervisor. This mode keeps quota/probe evidence fresh even after its
legacy implementation job is removed, without rearming that job or rotating
the local implementation route.

DeepSeek uses the existing saved credential through Hermes's provider resolver
and the pinned `deepseek-v4-pro` route. A separate transport process checks the
live account balance before calling the official API. No tools or provider
fallbacks are available to that model. Network failures, insufficient credit,
invalid responses and interrupted reviews retain the result and back off.
The controller attempts at most three run reviews and one PR review per tick,
with one exclusive controller lock. Two run slots favor recent outcomes and
one services historical results. Reports use an idempotent outbox; failed report
delivery never requires repeating a paid review.

PR records identify both head and base commits. Integration runs in a new
detached worktree based on current `main`; the canonical checkout and task
branches are preserved. Automatic delivery requires all of:

- Complete supported Python/test/documentation evidence and focused test coverage.
- Passing real integration tests, retained log and JUnit receipt.
- A structured DeepSeek `approve_merge` verdict for the exact PR head/base.
- Unchanged GitHub head/base, mergeability, no requested changes, and successful
  published checks. GitHub branch protections still apply.
- The operator Tasks switch and automatic merge opt-in still enabled immediately
  before ready/merge operations. Merge uses `--match-head-commit`, never `--admin`.

PR acceptance follows the declared source milestone. A useful, fully tested
reader, diagnostic repair or regression-test change may merge while its larger
inbox request remains open. The reviewer must identify a defect or missing check
in that PR to hold it; unfinished later milestones alone do not block source
delivery. Task closure still requires its own full acceptance evidence.

Unsupported changes, absent coverage, failures, conflicts and oversized evidence
remain held for further work. The reviewer cannot mark a task complete. A source
merge does not establish deployed files, artifacts or gameplay acceptance.
GitHub's merge API pins the head, not the base: base identity is rechecked just
before merge, but strict atomic base protection requires a GitHub merge queue or
required up-to-date CI. The local review receipt is not a replacement for those
repository protections.

## Installation and operation

Deploy the reviewed source and transport helper together. From the Spark's gBox
`system` directory, using its environment with the normal test dependencies:

```sh
.venv-linux-aarch64/bin/python -m gbox.hermes_result_review --install --auto-merge
.venv-linux-aarch64/bin/python -m gbox.hermes_result_review --status
```

Installation registers the no-agent minute cron before enabling the retry gate.
It reserves one scheduler slot alongside the existing ZAI slot. It does not
change inference-node capacity, cancel running tasks, change provider policy or
rewrite global model routes. Check the actual scheduler script contract before
resuming an existing installation.

For an explicit re-review after new evidence:

```sh
.venv-linux-aarch64/bin/python -m gbox.hermes_result_review \
  --reopen 'run:EXACT_RUN_ID' --reason 'Describe the new corrective evidence'
```

Turning Tasks off stops new paid reviews and merges. Setting `enabled` false in
`result-review.json` additionally disables the retry gate; preserve the SQLite
ledger and report files. Do not delete records to clear a failure. Inspect the
recorded cause, repair the dependency or task, and re-review it.

## Validation and deployment status

The unit suite exercises lost delivery/merge acknowledgements, interrupted
review recovery, late-finishing execution discovery, retry gating and guidance,
repeat-failure escalation, new-evidence recovery, exact-commit merge checks,
missing/failed test evidence, and GitHub checks/change requests.

This change still requires live Spark deployment verification: fresh DeepSeek
balance/response, cron execution, queue throughput, exact-head PR integration,
and confirmed GitHub delivery. Local tests do not establish those live outcomes.
