#!/usr/bin/env bash
# =============================================================================
# setup_raspi.sh — Raspberry Pi 側の単一セットアップスクリプト
# =============================================================================
# 本スクリプトは、Raspberry Pi（Rover 側）で以下をまとめて実行します:
#   1. Python venv の作成（.venv）
#   2. 依存ライブラリの導入（requirements.txt + deploy/requirements_raspi.txt）
#   3. systemd サービス（rtk-uart4-inject / tcp2serial）のインストール
#   4. （オプション --can）MCP2515 CAN インターフェース設定（要 sudo）
#
# 使い方:
#   ./deploy/setup_raspi.sh          # venv + 依存 + サービス導入
#   sudo ./deploy/setup_raspi.sh --can   # 上記 + CAN 設定
#
# 注意:
#   - 事前に /dev/ttyAMA0（Pixhawk TELEM1）と /dev/ttyAMA4（F9P UART）を
#     config.txt で有効化しておいてください。
#   - NTRIP 認証情報は環境変数（NTRIP_USER / NTRIP_PASSWORD）で渡してください。
#     YAML には平文のシークレットを書きません。
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VENV_DIR="${INSTALL_DIR}/.venv"
DO_CAN=false

for arg in "$@"; do
    case "$arg" in
        --can) DO_CAN=true ;;
        --help|-h)
            echo "Usage: $0 [--can]"
            exit 0 ;;
        *) echo "Unknown option: $arg"; exit 1 ;;
    esac
done

echo "=============================================="
echo "  rtk-pipeline gcs — Raspberry Pi Setup"
echo "=============================================="
echo "  install_dir = ${INSTALL_DIR}"
echo ""

# ── 1. venv 作成 ─────────────────────────────────────
echo "[1/4] Creating Python venv ..."
if [ ! -x "${VENV_DIR}/bin/python" ]; then
    python3 -m venv "${VENV_DIR}"
    echo "  ✓ venv created: ${VENV_DIR}"
else
    echo "  ✓ venv already exists: ${VENV_DIR}"
fi

# ── 2. 依存導入 ──────────────────────────────────────
echo ""
echo "[2/4] Installing dependencies ..."
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"
if [ -f "${SCRIPT_DIR}/requirements_raspi.txt" ]; then
    "${VENV_DIR}/bin/pip" install -r "${SCRIPT_DIR}/requirements_raspi.txt"
fi
echo "  ✓ dependencies installed"

# ── 3. サービス導入 ──────────────────────────────────
echo ""
echo "[3/4] Installing systemd services ..."
"${SCRIPT_DIR}/install_rtk_uart4_service.sh"
"${SCRIPT_DIR}/install_tcp2serial_service.sh"
echo "  ✓ services installed"

# ── 4. （任意）CAN 設定 ──────────────────────────────
if [ "$DO_CAN" = true ]; then
    echo ""
    echo "[4/4] Setting up MCP2515 CAN interface ..."
    sudo "${SCRIPT_DIR}/can_setup_raspi.sh" --no-reboot
else
    echo ""
    echo "[4/4] Skipped CAN setup (use --can to enable)."
fi

echo ""
echo "=============================================="
echo "  Setup complete!"
echo ""
echo "  Next steps:"
echo "    1. 設定を確認: gcs/config/rtk_forwarder.yml / tcp2serial.yml"
echo "    2. サービス起動:"
echo "         sudo systemctl start rtk-uart4-inject.service tcp2serial.service"
echo "    3. 状態確認:"
echo "         systemctl status rtk-uart4-inject.service tcp2serial.service"
echo "    4. ログ確認:"
echo "         journalctl -u rtk-uart4-inject.service -f"
echo "=============================================="
