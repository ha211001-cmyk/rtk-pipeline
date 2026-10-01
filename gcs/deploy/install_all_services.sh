#!/usr/bin/env bash
# =============================================================================
# install_all_services.sh — systemd サービス群を一括インストール
# =============================================================================
# 以下を順番にインストールします:
#   1. rtk-uart4-inject.service（RTCM 転送 → F9P UART 注入）
#   2. tcp2serial.service      （TCP→シリアル橋渡し）
#
# 使い方（gcs/deploy/ ディレクトリから）:
#   ./install_all_services.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=============================================="
echo "  Install all GCS systemd services"
echo "=============================================="

"${SCRIPT_DIR}/install_rtk_uart4_service.sh"
"${SCRIPT_DIR}/install_tcp2serial_service.sh"

echo ""
echo "=============================================="
echo "  All services installed and enabled."
echo ""
echo "  Start now:       sudo systemctl start rtk-uart4-inject.service tcp2serial.service"
echo "  Check status:    systemctl status rtk-uart4-inject.service tcp2serial.service"
echo "=============================================="
