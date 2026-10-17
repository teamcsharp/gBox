# Hermes queue run budgets

The local proxy's existing `hermes.local.tool_budget` policy reserves the last
six calls for tests, publication and a durable handoff. At the configured limit
the next model response must be a factual final checkpoint; the scheduler keeps
that report for the next run. This change does not change those settings or mark
an inbox request complete. The observed Spark2 setting on 2026-10-17 was 45.

Counting only messages sent to the model reset that budget after Hermes context
compaction. The state database retains historical calls, including multiple
copies of the same calls written while compacting. `hermes_run_budget.measure`
therefore counts distinct outer call IDs, and counts the individual attempts in
a `tool_call` batch once. Repeating the same arguments under a new call ID is a
new attempt. A copied call with the same ID and arguments is not.

Durable evidence is accepted only when all of these agree:

* Exactly one active execution and its session start boundary.
* The request number and ID in the session's original assignment and incoming
  conversation.
* The session's recorded billing endpoint and the actual local proxy route.
* The recent incoming call IDs and arguments present in that same session.

Ended runs, another ticket, another endpoint, conflicting call IDs, ambiguous
sessions and missing evidence cannot supply a durable count. The visible-message
count remains the fallback. A new execution of the same ticket begins a separate
budget. Model names and mutable global provider selections establish no identity.

Reads use SQLite `mode=ro` and `query_only`, with no Store construction or schema
changes. They are limited to 128 active executions, indexed session lookups,
1,024 transcript rows, 256 KiB per call row and 2 MiB across matched transcripts.
They run off the API event loop. In the read-only native replay, matching an
active compacted run took about 13 ms; this is an observation, not a latency SLA.

The budget reminder is appended after context trimming, with space reserved for
it. This retains the latest tool-call/result group for the checkpoint instead
of making the reminder the only retained tail. The six-call warning still allows
tools for checks and publication; finalization requests a report containing
verified results, artifact/job IDs, tests, blockers and the next step. Pending
native jobs and workspace changes survive for the next run. No process is killed,
no claim is cancelled, and no request is automatically closed.

Validation:

```text
python -m pytest -q tests/test_hermes_run_budget.py tests/test_llm_proxy.py
```

The integration tests cover compaction, duplicate history, batches, new-run
boundaries, ambiguous/foreign identity, read bounds, no database creation/writes,
the test/publication reserve, and preserving failed-test evidence in the final
checkpoint. Read-only replay is not evidence that a live task has completed.
