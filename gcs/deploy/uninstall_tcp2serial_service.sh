#!/usr/bin/env bash
# =============================================================================
# uninstall_tcp2serial_service.sh — tcp2serial.service を停止・無効化・削除
# =============================================================================

set -euo pipefail

SERVICE_NAME="tcp2serial.service"
TARGET="/etc/systemd/system/${SERVICE_NAME}"

if [ ! -f "${TARGET}" ]; then
    echo "Service file ${TARGET} does not exist. Nothing to uninstall."
    exit 0
fi

echo "Stopping and disabling ${SERVICE_NAME} ..."
sudo systemctl stop "${SERVICE_NAME}" || true
sudo systemctl disable "${SERVICE_NAME}" || true

echo "Removing ${TARGET} ..."
sudo rm -f "${TARGET}"

sudo systemctl daemon-reload

echo ""
echo "Done. Service stopped, disabled, and removed."
