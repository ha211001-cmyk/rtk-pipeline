#!/usr/bin/env bash
# =============================================================================
# install_rtk_uart4_service.sh — rtk-uart4-inject.service を systemd へ導入
# =============================================================================
# サービステンプレート内の @INSTALL_DIR@ / @GCS_USER@ を自動置換し、
# /etc/systemd/system/ へインストールして enable します。
#
# 使い方（gcs/deploy/ ディレクトリから）:
#   ./install_rtk_uart4_service.sh
#
# 実行ユーザー・導入先は環境変数で上書き可能:
#   GCS_USER=pi ./install_rtk_uart4_service.sh
# =============================================================================

set -euo pipefail

SERVICE_NAME="rtk-uart4-inject.service"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE="${SCRIPT_DIR}/${SERVICE_NAME}"
TARGET="/etc/systemd/system/${SERVICE_NAME}"

# 導入先（リポジトリルート = gcs/ の親）。deploy/ の 2 階層上。
INSTALL_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# 実行ユーザー（sudo 時は SUDO_USER を優先）
if [ -n "${SUDO_USER:-}" ]; then
    GCS_USER="${GCS_USER:-$SUDO_USER}"
else
    GCS_USER="${GCS_USER:-$(whoami)}"
fi

if [ ! -f "${TEMPLATE}" ]; then
    echo "ERROR: ${TEMPLATE} not found. Run this script from the gcs/deploy/ directory." >&2
    exit 1
fi

if [ ! -x "${INSTALL_DIR}/.venv/bin/python" ]; then
    echo "WARNING: Python venv が見つかりません: ${INSTALL_DIR}/.venv/bin/python" >&2
    echo "         先に deploy/setup_raspi.sh で venv + 依存導入を行うか、手動で作成してください。" >&2
fi

echo "Installing ${SERVICE_NAME} ..."
echo "  install_dir = ${INSTALL_DIR}"
echo "  user        = ${GCS_USER}"

sed -e "s|@INSTALL_DIR@|${INSTALL_DIR}|g" \
    -e "s|@GCS_USER@|${GCS_USER}|g" \
    "${TEMPLATE}" | sudo tee "${TARGET}" > /dev/null
sudo chmod 644 "${TARGET}"

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"

echo ""
echo "Done. Service installed and enabled."
echo ""
echo "  Start now:       sudo systemctl start ${SERVICE_NAME}"
echo "  Check status:    systemctl status ${SERVICE_NAME}"
echo "  Follow logs:     journalctl -u ${SERVICE_NAME} -f"
