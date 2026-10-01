#!/usr/bin/env bash
# =============================================================================
# can_setup_raspi.sh — MCP2515 CAN インターフェース自動セットアップ
# =============================================================================
#
# 本スクリプトは Raspberry Pi 5 上で root 権限で実行する
#
# 処理内容:
#   1. /boot/firmware/config.txt に SPI 有効化 + MCP2515 dtoverlay を追加
#   2. systemd-networkd 用 CAN ネットワーク設定を配置
#   3. systemd-networkd を再起動・永続化
#   4. 必要に応じて再起動を促す
#
# Usage:
#   chmod +x gcs/deploy/can_setup_raspi.sh
#   sudo ./gcs/deploy/can_setup_raspi.sh
#
# 注意:
#   - Raspberry Pi 5 では config.txt のパスが /boot/firmware/config.txt
#   - Pi 4 以前の場合は --legacy-boot オプションを使用 (/boot/config.txt)
# =============================================================================

set -euo pipefail

# ── デフォルト値 ──────────────────────────────────────────
MODE="listen-only"
BOOT_CONFIG="/boot/firmware/config.txt"
NETWORK_CONF_DIR="/etc/systemd/network"
USE_INTERFACES=false
ASK_REBOOT=true

# ── スクリプトの場所を基準にプロジェクトルートを特定 ────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# ── 引数解析 ─────────────────────────────────────────────
for arg in "$@"; do
    case "$arg" in
        --interfaces)
            USE_INTERFACES=true ;;
        --no-reboot)
            ASK_REBOOT=false ;;
        --listen-only)
            MODE="listen-only" ;;
        --normal)
            MODE="normal" ;;
        --legacy-boot)
            BOOT_CONFIG="/boot/config.txt" ;;
        --help|-h)
            echo "Usage: sudo $0 [OPTIONS]"
            echo "Options:"
            echo "  --interfaces    Use /etc/network/interfaces.d/can0"
            echo "  --no-reboot     Skip reboot prompt"
            echo "  --listen-only   CAN listen-only mode (default, recommended)"
            echo "  --normal        CAN normal mode (TX enabled)"
            echo "  --legacy-boot   Use /boot/config.txt (RPi 4 or older)"
            exit 0 ;;
        *)
            echo "Unknown option: $arg"; exit 1 ;;
    esac
done

# ── root 権限チェック ────────────────────────────────────
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: This script must be run as root (sudo)."
    exit 1
fi

echo "===================================================="
echo "  MCP2515 CAN Interface Setup for Raspberry Pi"
echo "===================================================="
echo ""
echo "  Boot config    : ${BOOT_CONFIG}"
echo "  CAN mode       : ${MODE}"
echo "  Network method : $([ "$USE_INTERFACES" = true ] && echo 'ifupdown (/etc/network/interfaces.d)' || echo 'systemd-networkd')"
echo ""

# ── 1. /boot/firmware/config.txt の編集 ──────────────────
echo "[1/4] Updating ${BOOT_CONFIG} ..."

# SPI 有効化
if grep -q "^dtparam=spi=on" "$BOOT_CONFIG" 2>/dev/null; then
    echo "  ✓ dtparam=spi=on already configured"
else
    echo "dtparam=spi=on" >> "$BOOT_CONFIG"
    echo "  + dtparam=spi=on added"
fi

# MCP2515 dtoverlay
if grep -q "^dtoverlay=mcp2515-can0" "$BOOT_CONFIG" 2>/dev/null; then
    echo "  ✓ dtoverlay=mcp2515-can0 already configured"
else
    cat >> "$BOOT_CONFIG" <<'DTEOF'

# CAN Interface (MCP2515 on SPI0.0) — DroneCAN monitoring
dtoverlay=mcp2515-can0,oscillator=16000000,interrupt=25,spimaxfrequency=10000000
DTEOF
    echo "  + dtoverlay=mcp2515-can0 added"
fi

echo ""

# ── 2. network 設定の配置 ─────────────────────────────────
echo "[2/4] Installing CAN network configuration ..."

if [ "$USE_INTERFACES" = true ]; then
    INTERFACES_DIR="/etc/network/interfaces.d"
    mkdir -p "$INTERFACES_DIR"
    CAN0_IF="${PROJECT_DIR}/deploy/interfaces.d/can0"
    if [ -f "$CAN0_IF" ]; then
        cp "$CAN0_IF" "${INTERFACES_DIR}/can0"
        echo "  ✓ ${INTERFACES_DIR}/can0 installed"
    else
        cat > "${INTERFACES_DIR}/can0" <<'IFEOF'
auto can0
iface can0 inet manual
    pre-up /sbin/ip link set can0 type can bitrate 1000000 listen-only on
    up /sbin/ip link set up can0
    down /sbin/ip link set down can0
IFEOF
        echo "  ✓ ${INTERFACES_DIR}/can0 created"
    fi
    systemctl restart networking 2>/dev/null || true
else
    mkdir -p "$NETWORK_CONF_DIR"
    LISTEN_ONLY_STR="true"
    [ "$MODE" = "normal" ] && LISTEN_ONLY_STR="false"

    NET_SRC="${PROJECT_DIR}/deploy/can0.network"
    LINK_SRC="${PROJECT_DIR}/deploy/can0.link"

    if [ -f "$NET_SRC" ]; then
        cp "$NET_SRC" "${NETWORK_CONF_DIR}/80-can0.network"
    else
        cat > "${NETWORK_CONF_DIR}/80-can0.network" <<NETEOF
[Match]
Name=can0

[CAN]
Bitrate=1000000
ListenOnly=${LISTEN_ONLY_STR}
RestartSec=100ms
NETEOF
    fi
    echo "  ✓ ${NETWORK_CONF_DIR}/80-can0.network installed"

    if [ -f "$LINK_SRC" ]; then
        cp "$LINK_SRC" "${NETWORK_CONF_DIR}/80-can0.link"
    else
        cat > "${NETWORK_CONF_DIR}/80-can0.link" <<LINKEOF
[Match]
OriginalName=can0

[Link]
ActivationPolicy=always-up
LINKEOF
    fi
    echo "  ✓ ${NETWORK_CONF_DIR}/80-can0.link installed"
fi
echo ""

# ── 3. ネットワークサービスの再起動 ─────────────────────
echo "[3/4] Enabling & restarting network service ..."
if [ "$USE_INTERFACES" != true ]; then
    systemctl enable systemd-networkd 2>/dev/null || true
    if systemctl is-active --quiet systemd-networkd 2>/dev/null; then
        systemctl restart systemd-networkd
        echo "  ✓ systemd-networkd restarted"
    else
        systemctl restart networking 2>/dev/null || true
        echo "  ✓ networking.service restarted (fallback)"
    fi
else
    systemctl restart networking 2>/dev/null || true
    echo "  ✓ networking.service restarted"
fi
echo ""

# ── 4. サマリ ────────────────────────────────────────────
echo "[4/4] Configuration summary ..."
echo ""
echo "  ${BOOT_CONFIG} additions:"
grep -E "dtparam=spi|dtoverlay=mcp2515" "$BOOT_CONFIG" 2>/dev/null || true
echo ""

if ! command -v candump &>/dev/null; then
    echo "  NOTE: can-utils not installed. Run: sudo apt install -y can-utils"
fi

echo ""
echo "===================================================="
echo "  Setup complete!"
echo "===================================================="
echo ""

if [ "$ASK_REBOOT" = true ]; then
    echo "  A reboot is REQUIRED for the device tree overlay to take effect."
    echo "  Reboot now? [y/N]"
    read -r REBOOT_ANSWER
    case "$REBOOT_ANSWER" in
        [Yy]|[Yy][Ee][Ss]) echo "Rebooting..."; reboot ;;
        *) echo "  Please reboot manually with: sudo reboot" ;;
    esac
else
    echo "  Remember to reboot: sudo reboot"
fi
