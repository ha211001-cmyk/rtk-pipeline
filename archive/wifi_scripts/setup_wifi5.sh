#!/bin/bash
set -e

# NM から wlan0 を切り離す
nmcli dev set wlan0 managed no 2>/dev/null || true

# 既存の wpa_supplicant (wlan0用) を停止
pkill -f "wpa_supplicant.*wlan0" 2>/dev/null || true
sleep 1

# PSK ハッシュ済みの設定ファイルを作成
cat > /tmp/wpa_daruma.conf << 'WPAEOF'
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
country=JP
network={
    ssid="だるま雪2"
    psk=79bb645fb9d8e55f11de6a7cb0c9d91c6ec88f13481b2807842aa3b8924b5e85
    key_mgmt=WPA-PSK
}
WPAEOF

echo "=== wpa_supplicant 設定ファイル ==="
cat /tmp/wpa_daruma.conf

# wlan0 を up
ip link set wlan0 up
sleep 1

# wpa_supplicant 起動
echo "=== wpa_supplicant 起動 ==="
wpa_supplicant -B -i wlan0 -c /tmp/wpa_daruma.conf -f /tmp/wpa_daruma.log
sleep 8

echo "=== wpa_cli status ==="
wpa_cli -i wlan0 status

if ! wpa_cli -i wlan0 status | grep -q "wpa_state=COMPLETED"; then
    echo "!!! 接続失敗 - ログ ==="
    cat /tmp/wpa_daruma.log | tail -30
    exit 1
fi

echo "=== DHCP で IP 取得 ==="
dhclient -v wlan0 2>&1 | tail -10
sleep 2

echo "=== 接続後の状態 ==="
ip -br addr show

echo "=== ルーティングテーブル ==="
ip route show

# NTRIP サーバーの IP を取得して wlan0 経由のルートを追加
NTRIP_IP=$(getent hosts ntrip.ales-corp.co.jp | awk '{print $1}' | head -1)
WLAN_GW=$(ip route show dev wlan0 | grep default | awk '{print $3}')
echo "NTRIP IP: $NTRIP_IP  /  wlan0 GW: $WLAN_GW"
if [ -n "$NTRIP_IP" ] && [ -n "$WLAN_GW" ]; then
    ip route replace "$NTRIP_IP" via "$WLAN_GW" dev wlan0
    echo "ルート追加: $NTRIP_IP via $WLAN_GW dev wlan0"
fi

echo "=== ntrip.ales-corp.co.jp:2101 到達テスト ==="
timeout 10 bash -c "$(printf 'echo QUIT | nc -w 5 ntrip.ales-corp.co.jp 2101')" 2>&1 | head -3 \
    && echo "ポート2101 到達OK" || echo "ポート2101 到達NG (タイムアウトまたは拒否)"

echo "=== 完了 ==="
