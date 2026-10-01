#!/usr/bin/env bash
# =============================================================================
# uninstall_rtk_uart4_service.sh — rtk-uart4-inject.service を停止・無効化・削除
# =============================================================================

set -euo pipefail

SERVICE_NAME="rtk-uart4-inject.service"
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
