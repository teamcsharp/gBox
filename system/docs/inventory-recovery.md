# Overdue read-only inventory recovery

`gbox.inventory_recovery` can preview and retire one exact `tasks` request whose
input is `{"op":"list","pid":null}`. It does not call the tasks tool, cancel a
job, stop a process, restart a worker, resubmit work or manufacture a success
receipt. The result is a delivery timeout, not proof that an old thread exited.

The request must be running for at least five minutes, pinned to the same
claimed worker, have the exact expected stored-body SHA-256, and have only its
original submit/claim audit records. Any result, receipt, late-result record,
cancellation or acceptance-in-progress prevents retirement. The worker must
have a fresh heartbeat with zero active jobs and zero pending durable results;
a second fresh identity for that host prevents recovery.

Heartbeat counters alone are insufficient. Run `observe` on the worker host
using its exact runtime, configuration, server/name and actual interpreter PID.
The collector checks the configured runtime (including the host overlay),
reads Python process identities, and requires one actual worker plus at most
its launcher ancestors. It reads every existing result namespace, including
target acknowledged/rejected/refused-evidence records and temporary files.
Symlinks, junctions and unexpected nested directories prevent observation. Any
deliverable pending file or target result blocks retirement. Unrelated temporary
atomic-write files are retained as separate evidence only when their bounded
contents, result digest, job ID, filename and namespace agree, and their creation
and modification precede this claim. Unknown, recent or changing temporary files
block recovery. Their hashes and identities are recorded; no files are deleted
or altered. Historical refusals for other jobs remain untouched.

```sh
python -m gbox.inventory_recovery observe \
  --runtime WORKER_RUNTIME --config WORKER_CONFIG \
  --server CONTROL_PLANE_URL --name WORKER_HOST --worker-id EXACT_WORKER \
  --job-id EXACT_JOB --expected-pid ACTUAL_INTERPRETER_PID
```

Save that JSON as evidence and transfer it to the control-plane host. Evidence
and heartbeat must each be at most 30 seconds old (with five seconds of future
clock tolerance), so recollect immediately before preview or apply. Evidence
is a trusted operator observation, not a remotely signed attestation. It is
bound to the job, worker, host, configured runtime and process creation time.

```sh
python -m gbox.inventory_recovery retire \
  --database EXACT_DATABASE --job-id EXACT_JOB --expected-worker EXACT_WORKER \
  --expected-job-sha256 SHA256_OF_STORED_JOB_BODY --evidence FRESH_OBSERVATION.json
```

The default opens the database read-only and rolls back its read transaction.
`--apply` is explicit. Apply uses `BEGIN IMMEDIATE`, rereads all conditions,
compares the exact stored body, and changes only failure/finish/error and
inventory-timeout evidence metadata. The audit event and job change commit
together or both roll back. It does not set a cancellation flag.

A late worker response follows the existing late-result path: its exact bytes
are retained and its delivery can settle, while the job remains failed. Tests
exercise this through the actual API, including a late successful inventory
response. No game, session, emulator, save or build is changed by this recovery.

This is an explicit maintenance command, not a new automatic scheduler rule.
A fresh observation can become stale or a result can arrive after it; the
transaction protects server admission and late results remain evidence only.
