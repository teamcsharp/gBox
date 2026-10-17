# Legacy inspection reservation recovery

Older running services compare an inspection job's normalized input digest with
its reservation. Earlier reservations stored the sparse recipe digest, so the
same reviewed recipe can remain queued even though current source accepts it.
The normal submission and claim compatibility fix already prevents this after
activation. This maintenance command recovers one existing reservation while
that activation is waiting for queued work.

Run from a reviewed checkout. The default opens the existing database read-only:

```sh
python -m gbox.inspection_recovery --database /path/gbox.sqlite3 \
  --job-id EXACT_JOB --expected-run EXACT_RUN --expected-digest EXACT_LEGACY_DIGEST \
  --source-root /path/to/installed/system
```

Review the full before/after evidence, then add `--apply` to perform the exact
correction. It accepts only an unclaimed queued inspection cast-swap job with
launch explicitly false. The current plan must be enabled and reviewed, match
the reservation revision and original writer hashes, and acknowledge all current
operator feedback. The same pinned worker must have a fresh heartbeat and the
matching writer hashes. The job must exactly equal the validated reviewed
recipe; its own digest alone never establishes authority.

Only the reservation's `input_digest` changes. The job, worker, recipe, feedback,
parent request and resources remain untouched. Normal worker admission still
checks them before any claim. The command does not launch a game or mark the
request completed. Correction and immutable before/after audit evidence commit
in one transaction. Audit failure rolls back the correction; changed or already
normalized reservations are refused. No database or schema is created.

Check the same job ID for its eventual build result and native inspection proof.
A successful normalization is queue recovery, not successful game completion.
