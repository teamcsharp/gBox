# Activate gBox during an acknowledged Hermes drain

The installed Hermes gateway supports `gateway.drain_control` external drains.
It watches `.drain_request.json` every second, refuses new gateway turns and holds
the built-in cron dispatcher while current runs continue. It stays running.
This does not change task-mode preferences, schedules, execution claims or games.

The marker contains `action`, `principal`, `requested_at`, `epoch`, and
`suppress_notification`. The installed protocol expires an unrenewed marker
after 3,600 seconds; its epoch is the machine boot ID plus PID 1 start ticks.
Use a 45-minute maintenance deadline and release normally on success or failure.
Do not begin while another deployment owns `/tmp/gbox-deploy.lock`; the older
deployment's task-mode EXIT trap must finish first.

Run from this revision's `system` directory using the installed Hermes Python.
Choose one unique owner and one new receipt path and reuse them unchanged:

```bash
# Managed interpreter verified on this host. Re-read the installed Hermes
# launcher's --print-runtime-command if its managed runtime has been upgraded.
HERMES_PY="$HOME/.hermes/tools/python-3.14.7+20260901-linux-arm64/bin/python3"
OWNER="gbox-deploy:<reviewed-commit>:<unique-nonce>"
RECEIPT="$HOME/gBox_alt/gbox-pr-audit-20261017/external-drain-receipt.json"

# Read-only; ensure no marker already exists before beginning.
"$HERMES_PY" -I scripts/hermes_drain_control.py --owner "$OWNER"
"$HERMES_PY" -I scripts/hermes_drain_control.py --begin --owner "$OWNER" --receipt "$RECEIPT"

# Poll until acknowledged=true; no active-work count is inferred from this.
"$HERMES_PY" -I scripts/hermes_drain_control.py --owner "$OWNER"

# Canonical idle check, using the live gBox databases and this exact drain owner.
# Active/unknown jobs, executions, chats and game ownership still block.
"$HOME/gBox/system/.venv-linux-aarch64/bin/python" -m gbox.hermes_activation \
  --check-idle "$HOME/gBox/system" --drain-owner "$OWNER"

# Release on completion, failure, or the 45-minute deadline. This command checks
# the exact saved marker first and refuses a changed operator/maintenance marker.
"$HERMES_PY" -I scripts/hermes_drain_control.py --release --owner "$OWNER" --receipt "$RECEIPT"
```

Only after the normal idle checks pass should the existing activation procedure
perform its final immediate recheck and service refresh. Keep the drain engaged
through that check and refresh. Verify health, loaded code and original game PIDs,
then release. If the marker was removed, do not recreate it automatically. If it
changed, respect the newer request. Release is the installed API's ordinary
read-then-clear operation, **not atomic compare-and-swap**; serialize maintenance
and reread ownership before releasing.

`--drain-owner` requires a fresh acknowledgment from the exact live gateway PID
and process start ticks, a matching built-in ticker heartbeat, and a live marker
for that owner and boot epoch with at least 60 seconds remaining. Multi-profile
or ambiguous evidence fails closed. Imminent schedules remain visible in the
snapshot as `held_by_external_drain`; their records are never altered. An
`active_agents: 0` status is not accepted as evidence that executions finished.
Without the explicit owner, existing idle-check behavior is unchanged.

The control script does not restart services, post messages, cancel work, or
close inbox requests. A crash may leave its marker until normal release or the
protocol's one-hour expiry; the saved receipt supports an ownership-checked
release after recovery.
