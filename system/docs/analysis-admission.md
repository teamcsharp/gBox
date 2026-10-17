# Contradictory analysis routing

A job pinned to a Linux worker and also requiring Windows has no eligible
worker. API submission now rejects this intersection with HTTP 422. MCP checks
the worker identity before returning an existing job, and retry deduplication
includes `require_os`. Compatible explicit constraints stay intact.

For an already queued `analyze_binary` job, use the maintenance command from a
reviewed checkout. It opens the existing database directly without constructing
a Store, creating tables, running migrations, submitting work, or restarting a
service. Its default mode is read-only:

```sh
python -m gbox.job_routing --database /path/to/gbox.sqlite3 \
  --job-id EXACT_JOB_ID --expected-worker EXACT_WORKER_ID --expected-os windows
```

Review the printed before/after job and current worker identity. To deliberately
align only the OS constraint to the same worker, supply its OS and `--apply`:

```sh
python -m gbox.job_routing --database /path/to/gbox.sqlite3 \
  --job-id EXACT_JOB_ID --expected-worker EXACT_WORKER_ID --expected-os windows \
  --target-os linux --apply
```

Apply acquires a SQLite write transaction before rereading the job and worker.
It requires the exact expected routing, queued/unclaimed state, a worker
heartbeat within 30 seconds, and advertised `analyze_binary` capability. It
refuses started, completed, cancelled, inspection, and other-tool jobs. Only
`require_os` changes. The job ID, worker pin, inputs, request link, priority and
all admission controls are preserved. The normal worker claim path still runs.

The changed document and hash-chained `job.analysis_os_corrected` audit event
commit together. That event durably contains full before/after documents and
the observed worker identity. Output includes its audit sequence. If audit
insertion fails, the job correction rolls back. A repeated apply refuses the
now-mismatched expected routing instead of making another change.

This command does not prove the analysis succeeds or resolve its parent request.
Check the same job ID for its eventual artifact and validation receipt.
