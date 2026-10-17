# Historical publication evidence

`GET /api/tasks/device-work` includes a `contributions` array for publications
without a uniquely attributed retained execution. Each row has a stable
`pr:<number>:<published commit>` identity, request/ticket, publication time,
nullable `run_id`, observed device attribution, and the existing outcome schema.
There are no invented start/end times, run counts, durations or activity states.
The frontend renders these records separately from the execution timeline.

The normal merge reconciler backfills at most 20 publisher joins and 20 GitHub
commit comparisons per pass. Publisher joins use read-only SQLite snapshots,
at most 100 overlapping sessions, 250 messages per session and 4 MiB total
transcript fields per publication. A unique successful publication tool response
must match the exact request, PR URL/number, published commit and timestamp.
Only successful served-model calls in that session before publication can
identify its inference contributors. Session billing fields, the current global
model, a legacy local-model label and assistant prose are not evidence.
Missing, ambiguous or oversized histories remain unknown. Backfill results are
stored in `merges.json`; ordinary UI polls never query GitHub or perform these
transcript joins. An unknown backfill result is retained rather than rescanned
on every poll or reconciler pass.

Exact publisher evidence overrides an overlapping request execution. If the
session later used another inference device and the whole run's attribution
differs, the publication stays separate under its observed publication-time
contributor. Historical immutable provenance is accepted only for successful
call observations preceding publication. Reused workspaces no longer copy a
legacy `local_model` claim into a new publication with unknown or remote-only
provenance; draft creation behavior is unchanged.

`pr_merged` counts an exact published head observed merged to main.
`pr_reviewed_merge` with `status=merged_after_review` and `verified=true` means
GitHub's exact commit graph proves the published commit is an ancestor of a
different reviewed head. This proof is bound to repository, PR, published SHA,
reviewed head, merge commit and main. It increments the separate
`prs_reviewed_contributions` metric. Without that proof the same outcome has
`status=merged_at_different_head` and `verified=false`.

PR counts deduplicate URLs across linked executions and historical records.
Historical records never increment run counters or the ended-run delivery rate.
Publication, reviewed contribution, exact-head merge, live deployment, gameplay
acceptance and a newly accepted request completion remain separate facts.
