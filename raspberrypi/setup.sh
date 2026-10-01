#!/bin/bash
# ============================================================
# Raspberry Pi 5 向け rtk-pipeline セットアップスクリプト
# ============================================================
# 使い方:
#   chmod +x setup.sh
#   ./setup.sh

set -e

echo "======================================"
echo "rtk-pipeline Raspberry Pi 5 セットアップ"
echo "======================================"

# Python3 と pip の確認
if ! command -v python3 &>/dev/null; then
    echo "Python3 が見つかりません。インストールします..."
    sudo apt-get update
    sudo apt-get install -y python3 python3-pip python3-venv
else
    echo "✓ Python3: $(python3 --version)"
fi

# 必要なPythonパッケージをインストール
echo ""
echo "Pythonパッケージをインストール中..."
pip3 install --break-system-packages pyserial pynmeagps pyubx2 pyrtcm numpy 2>/dev/null \
    || pip3 install pyserial pynmeagps pyubx2 pyrtcm numpy

echo "✓ パッケージインストール完了"

# シリアルポート権限の設定
echo ""
echo "シリアルポート権限を設定中..."
if groups | grep -q dialout; then
    echo "✓ 既に dialout グループに所属しています"
else
    sudo usermod -aG dialout "$USER"
    echo "✓ dialout グループに追加しました（再ログインが必要です）"
fi

# /dev/serial0 (UART) の無効化は不要（USB接続のため）

# F9P デバイスの確認
echo ""
echo "接続されているシリアルデバイスを確認中..."
if ls /dev/ttyACM* 2>/dev/null; then
    echo "上記の /dev/ttyACM* デバイスが検出されました"
    echo "F9PをUSB接続している場合は通常 /dev/ttyACM0 です"
elif ls /dev/ttyUSB* 2>/dev/null; then
    echo "上記の /dev/ttyUSB* デバイスが検出されました"
    echo "USB-シリアル変換アダプタ経由の場合は /dev/ttyUSB0 を使用してください"
    echo "各スクリプトの SERIAL_PORT = \"/dev/ttyACM0\" を \"/dev/ttyUSB0\" に変更してください"
else
    echo "⚠ シリアルデバイスが見つかりません。F9PをUSBで接続してください"
fi

# logディレクトリの作成
echo ""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/log"
mkdir -p "$LOG_DIR"
echo "✓ ログディレクトリ: $LOG_DIR"

echo ""
echo "======================================"
echo "セットアップ完了！"
echo "======================================"
echo ""
echo "使い方:"
echo "  python3 gps_display.py       # NMEA表示"
echo "  python3 gps_statistics.py    # GPS統計計算"
echo "  python3 gps_statistics_debug.py  # GPS統計（デバッグ版）"
echo "  python3 base_station.py      # 基地局モード"
echo ""
echo "ポートが /dev/ttyACM0 でない場合は各スクリプト内の"
echo "  SERIAL_PORT = \"/dev/ttyACM0\""
echo "を適切なポート名に変更してください。"
echo ""
echo "注意: dialout グループへの追加後は再ログインが必要です"
echo "  logout して再度ログインするか、以下を実行してください:"
echo "  newgrp dialout"
