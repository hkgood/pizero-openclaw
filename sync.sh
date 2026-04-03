#!/bin/bash
# Deploy script: rsyncs to the Pi and restarts the systemd service.
#
# Usage:
#   ./sync.sh                        # defaults to pi@pizero.local
#   PI_HOST=rocky@pizero.local ./sync.sh
#
# ── Config ────────────────────────────────────────────────────────────────────
PI_HOST="${PI_HOST:-pi@pizero.local}"
PI_PATH="${PI_PATH:-/home/pi/pizero-openclaw}"
SERVICE_NAME="${SERVICE_NAME:-pizero-openclaw}"

# SSH 选项：自动接受 host key + 失败快速退出
SSH_OPTS="-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -o BatchMode=yes"

set -e

# ── Pre-flight：网络可达性检查 ───────────────────────────────────────────────
echo "==> Checking connectivity to ${PI_HOST} ..."
if ! ssh $SSH_OPTS "$PI_HOST" "echo 'connection ok'" 2>/dev/null; then
  echo "ERROR: Cannot reach ${PI_HOST} via SSH."
  echo "  - Is the Pi powered on and connected to the network?"
  echo "  - Is SSH server running on the Pi? (try: sudo systemctl enable sshd)"
  echo "  - Is the hostname/IP correct?"
  exit 1
fi
echo "==> ${PI_HOST} is reachable"

# ── 部署 ─────────────────────────────────────────────────────────────────────
echo "==> Syncing to ${PI_HOST}:${PI_PATH} ..."
rsync -avz --delete \
    -e "ssh $SSH_OPTS" \
    --exclude='__pycache__' \
    --exclude='.lgd-*' \
    --exclude='.venv' \
    --exclude='*.pyc' \
    ./ "${PI_HOST}:${PI_PATH}/"

echo "==> Reloading systemd and restarting ${SERVICE_NAME} ..."
ssh $SSH_OPTS "$PI_HOST" "
  sudo cp ${PI_PATH}/${SERVICE_NAME}.service /etc/systemd/system/ &&
  sudo systemctl daemon-reload &&
  sudo systemctl enable ${SERVICE_NAME} &&
  sudo systemctl restart ${SERVICE_NAME} &&
  sleep 2 &&
  sudo journalctl -u ${SERVICE_NAME} -n 30 --no-pager
"

echo "==> Deploy complete!"
