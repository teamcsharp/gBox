#!/usr/bin/env bash
# Install / update gBox on a Linux node (DGX Spark): venv, Python deps, system deps (gbox setup), systemd service.
# Idempotent: safe to re-run after every update. Needs passwordless sudo for apt/mount/systemd steps.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO/.venv-linux-$(uname -m)"
CONFIG="$REPO/gbox.toml"

# Updating dependencies or restarting this combined API/worker can terminate
# active Ghidra, extraction and gameplay work. Defer the entire live update.
if systemctl is-active --quiet gbox.service; then
  [ -x "$VENV/bin/python" ] || { echo "!! active gBox has no usable preflight interpreter; update deferred"; exit 1; }
  if "$VENV/bin/python" -m gbox.hermes_activation --check-idle "$REPO"; then
    :
  else
    status=$?
    [ "$status" -eq 75 ] && exit 0
    exit "$status"
  fi
fi

echo "== python venv: $VENV"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -e "$REPO[test]"

echo "== system dependencies (gbox setup)"
"$VENV/bin/python" -m gbox --config "$CONFIG" setup || echo "!! some setup steps failed (see above); continuing"

echo "== systemd service"
sudo -n tee /etc/systemd/system/gbox.service >/dev/null <<UNIT
[Unit]
Description=gBox control plane + worker
After=network-online.target remote-fs.target
Wants=network-online.target

[Service]
User=$(id -un)
WorkingDirectory=$REPO
Environment=GBOX_CONFIG=$CONFIG
ExecStart=$VENV/bin/python -m gbox --config $CONFIG serve --worker
Restart=on-failure
RestartSec=3
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
UNIT
sudo -n systemctl daemon-reload
sudo -n systemctl enable gbox.service >/dev/null
# Setup can take minutes; check again because work may have arrived meanwhile.
if systemctl is-active --quiet gbox.service; then
  if "$VENV/bin/python" -m gbox.hermes_activation --check-idle "$REPO"; then
    :
  else
    status=$?
    [ "$status" -eq 75 ] && exit 0
    exit "$status"
  fi
fi
sudo -n systemctl restart gbox.service
sleep 3
systemctl is-active gbox.service && curl -sf "http://127.0.0.1:8765/api/health" && echo && echo "== gBox running on http://$(hostname -I | awk '{print $1}'):8765"
