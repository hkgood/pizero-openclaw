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
# ─────────────────────────────────────────────────────────────────────────────

set -e

echo "==> Syncing to ${PI_HOST}:${PI_PATH} ..."
rsync -avz --delete \
    --exclude='__pycache__' \
    --exclude='.lgd-*' \
    --exclude='.venv' \
    --exclude='*.pyc' \
    ./ "${PI_HOST}:${PI_PATH}/"

echo "==> Reloading systemd and restarting ${SERVICE_NAME} ..."
ssh "$PI_HOST" "
  sudo cp ${PI_PATH}/${SERVICE_NAME}.service /etc/systemd/system/ &&
  sudo systemctl daemon-reload &&
  sudo systemctl enable ${SERVICE_NAME} &&
  sudo systemctl restart ${SERVICE_NAME} &&
  sleep 2 &&
  sudo journalctl -u ${SERVICE_NAME} -n 30 --no-pager
"
