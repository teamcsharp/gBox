# Finished-result delivery

Workers save finished output, logs and artifact bytes under their local runtime's
`worker-results` directory before sending a result. The directory is scoped to
the server and worker name; credentials are not stored there. Files and newly
created directory entries are synced on supported POSIX filesystems before
transport. Windows uses file synchronization and atomic replacement.

Delivery retries send the identical result for the original job and worker ID.
They never execute the tool again. A result leaves the pending queue only when
the server returns its matching digest, job ID, worker ID and durable receipt.
Transient failures use bounded attempts with backoff. Rejections remain visible
as pending results requiring review. Unverified legacy responses also remain
pending; a terminal job or HTTP 409 alone does not prove delivery.

The control plane admits the pending job and provisional receipt in one SQLite
transaction. A Store lock serializes result delivery with registration and
cancellation. Matching completed retries reuse the receipt and do not repeat
acceptance or follow-up scheduling. Interrupted acceptance stays running with
`result_acceptance: pending`; only known local callbacks can be resumed. Native
launch recovery preserves an existing matching session and never resurrects an
ended session. Conflicting session identity needs review.

Workers retain their busy count until acknowledgement and advertise
`pending_results`. A separate delivery lock keeps network waits out of heartbeat
inventory and newly finished result persistence. On restart, the old identity's
saved results are drained before a new worker registers. Pending or rejected
delivery blocks activation. A surviving owned emulator PID also blocks startup;
startup does not kill or reattach that process. Unknown ownership blocks rather
than declaring a game preserved or ended.

The desktop Control panel shows the worker's last exit reason and offers
Reconnect for a stopped worker. Reconnect makes at most four reconciliation
attempts using the exact retained result bytes, including previously refused
results. The command-line equivalent is `gbox worker --reconcile-results` with
the usual server, configuration and worker-name arguments. Ordinary startup
and watchdog retries do not reconcile refusals. A refused record is copied to
`refused-evidence` before a reconciliation attempt, and only a matching durable
acknowledgement releases it. Upgrade the control plane before attempting this
recovery; an old server response or HTTP 409 does not prove delivery.

Reconnect never terminates a running worker or its games. An existing worker,
a worker already starting, standalone mode, or a surviving owned native process
holds reconnection and explains why. The panel's process status alone is not
proof of a fresh server heartbeat.

Deploy the compatible control-plane and worker changes together during an
approved idle interval. A source update does not reload cached Python modules.
This mechanism cannot reconstruct a finished result already lost by an older
worker. Such live sessions need independently verified inventory recovery; their
missing central records are never permission to kill the emulator.

The outbox retains acknowledged payloads and artifacts for review. Automatic
deletion is intentionally absent. Storage exhaustion prevents durable delivery
and keeps the executing worker busy; no result is posted before persistence.
