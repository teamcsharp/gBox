#!/usr/bin/env bash
# Install / update G-Box on a Linux node (DGX Spark): venv, Python deps, system deps (gbox setup), systemd service.
# Idempotent: safe to re-run after every update. Needs passwordless sudo for apt/mount/systemd steps.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO/.venv-linux-$(uname -m)"
CONFIG="$REPO/gbox.toml"

echo "== python venv: $VENV"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -e "$REPO[test]"

echo "== system dependencies (gbox setup)"
"$VENV/bin/python" -m gbox --config "$CONFIG" setup || echo "!! some setup steps failed (see above); continuing"

echo "== systemd service"
sudo -n tee /etc/systemd/system/gbox.service >/dev/null <<UNIT
[Unit]
Description=G-Box control plane + worker
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
sudo -n systemctl restart gbox.service
sleep 3
systemctl is-active gbox.service && curl -sf "http://127.0.0.1:8765/api/health" && echo && echo "== G-Box running on http://$(hostname -I | awk '{print $1}'):8765"
