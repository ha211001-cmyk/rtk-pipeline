#!/usr/bin/env bash
# start_raspi_services.sh
# Raspi側で実行: mavlink-router + rtk_forwarder の起動（systemd を使わない手動版）
#
# 常駐起動は systemd を推奨（deploy/install_all_services.sh）。本スクリプトは
# デバッグ・動作確認用の手動起動版です。
#
# 前提条件:
#   1. mavlink-router がインストール済み（apt install mavlink-router）
#   2. /dev/ttyAMA0 が有効化済み（config.txt: enable_uart=1）
#   3. /dev/ttyAMA4 が有効化済み（dtoverlay=uart4 で追加UART有効）
#   4. rtk_forwarder用のPython仮想環境が準備済み（deploy/setup_raspi.sh）
#   5. gcs/config/rtk_forwarder.yml の host が Mac の Tailscale IP に設定されていること
#
# Usage:
#   chmod +x gcs/deploy/start_raspi_services.sh
#   ./gcs/deploy/start_raspi_services.sh [MAC_TAILSCALE_IP]
#
#   引数で MAC_TAILSCALE_IP を指定すると、rtk_forwarder.yml の host を自動置換します。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_DIR="${SCRIPT_DIR}"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"   # gcs/
INSTALL_DIR="$(dirname "$PROJECT_DIR")"  # リポジトリルート
CONFIG_DIR="${PROJECT_DIR}/config"
LOG_DIR="${PROJECT_DIR}/logs"

cd "$INSTALL_DIR"

echo "================================================"
echo "  Raspi Side: Service Startup"
echo "================================================"

# ── UART確認 ──────────────────────────────────────
echo ""
echo "[0/3] Checking UART devices..."

if [ -e /dev/ttyAMA0 ]; then
    echo "  ✓ /dev/ttyAMA0  (Pixhawk TELEM1) found"
else
    echo "  ✗ /dev/ttyAMA0  NOT FOUND — check config.txt (enable_uart=1)"
    exit 1
fi

if [ -e /dev/ttyAMA4 ]; then
    echo "  ✓ /dev/ttyAMA4 (F9P Rover UART) found"
else
    echo "  ✗ /dev/ttyAMA4 NOT FOUND — check dtoverlay=uart4"
    exit 1
fi

# ── MAC_TAILSCALE_IP 設定 ──────────────────────────
FORWARDER_CONFIG="${CONFIG_DIR}/rtk_forwarder.yml"

if [ $# -ge 1 ]; then
    MAC_IP="$1"
    echo ""
    echo "  Updating rtk_forwarder.yml host → ${MAC_IP}"
    sed -i "s/^  host: .*/  host: ${MAC_IP}/" "$FORWARDER_CONFIG"
    grep "^  host:" "$FORWARDER_CONFIG"
else
    MAC_IP=$(grep "^  host:" "$FORWARDER_CONFIG" | awk '{print $2}')
    echo ""
    echo "  Using existing rtk_forwarder.yml host: ${MAC_IP}"
fi

# ── 1. mavlink-router 起動 ─────────────────────────
echo ""
echo "[1/3] Starting mavlink-router (ttyAMA0 → TCP:5760)..."

# mavlink-router が既に動いていたら停止
sudo pkill mavlink-routerd 2>/dev/null || true
sleep 1

MAVLINK_CONF="${DEPLOY_DIR}/mavlink_router_raspi.conf"

if [ -f /etc/mavlink-router/main.conf ]; then
    # システムにインストール済みの設定を上書き
    sudo cp "$MAVLINK_CONF" /etc/mavlink-router/main.conf
    sudo systemctl restart mavlink-router
    echo "  ✓ mavlink-router restarted via systemd"
else
    # 手動起動
    mavlink-routerd --config "$MAVLINK_CONF" &
    MAVLINK_PID=$!
    echo "  ✓ mavlink-router started (PID: ${MAVLINK_PID})"
fi

sleep 2

# ── 2. rtk_forwarder 起動 ──────────────────────────
echo ""
echo "[2/3] Starting rtk_forwarder (Mac:${MAC_IP}:2101 → /dev/ttyAMA4)..."

# 既存プロセスをkill
pkill -f rtk_forwarder_service 2>/dev/null || true
sleep 1

mkdir -p "$LOG_DIR"

# Python仮想環境の python を優先（なければシステム python）
if [ -x "${INSTALL_DIR}/.venv/bin/python" ]; then
    PYTHON="${INSTALL_DIR}/.venv/bin/python"
else
    PYTHON="python3"
fi

nohup "${PYTHON}" -m gcs.rtk_tools.rtk_forwarder_service \
    --config "$FORWARDER_CONFIG" \
    > "${LOG_DIR}/rtk_forwarder.log" 2>&1 &

FORWARDER_PID=$!
echo "  ✓ rtk_forwarder started (PID: ${FORWARDER_PID})"
echo "  Log: ${LOG_DIR}/rtk_forwarder.log"

# ── 3. ステータス確認 ──────────────────────────────
echo ""
echo "[3/3] Status check..."

sleep 3

# プロセス確認
if pgrep -f rtk_forwarder_service > /dev/null; then
    echo "  ✓ rtk_forwarder: RUNNING"
else
    echo "  ✗ rtk_forwarder: NOT RUNNING — check ${LOG_DIR}/rtk_forwarder.log"
fi

if pgrep mavlink-routerd > /dev/null || systemctl is-active --quiet mavlink-router 2>/dev/null; then
    echo "  ✓ mavlink-router: RUNNING"
else
    echo "  ✗ mavlink-router: NOT RUNNING"
fi

# ポート確認
echo ""
echo "  Listening ports:"
echo "    TCP:"
ss -tlnp 2>/dev/null | grep -E '(5760|2101)' || echo "      (none or ss not available)"
echo "    UDP:"
ss -ulnp 2>/dev/null | grep '14550' || echo "      (none or ss not available)"

echo "================================================"
echo "  Raspi services started!"
echo "  MAVLink  : UDP:14550 (GCS connect here) + TCP:5760 (备用)"
echo "  RTCM IN  : Raw TCP from Mac:${MAC_IP}:2101 (no NTRIP handshake)"
echo "  RTCM OUT : /dev/ttyAMA4 → F9P Rover"
echo ""
echo "  Monitor:"
echo "    tail -f ${LOG_DIR}/rtk_forwarder.log"
echo "    journalctl -u mavlink-router -f"
echo ""
echo "  Verify:"
echo "    ss -ulnp | grep 14550   # UDP listen check"
echo "    ss -tlnp | grep 5760    # TCP listen check"
echo "================================================"
