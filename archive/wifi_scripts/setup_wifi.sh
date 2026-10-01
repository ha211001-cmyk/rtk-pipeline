#!/bin/bash
# Wi-Fi セットアップスクリプト
# SSID: だるま雪2, wlan0

set -e

SSID="だるま雪2"
PSK="1234546789"

echo "=== nmcli でWi-Fi接続試行 ==="
sudo nmcli dev wifi connect "$SSID" password "$PSK" ifname wlan0 2>&1 || {
    echo "nmcli connect 失敗。スキャン結果を確認..."
    sudo nmcli dev wifi list ifname wlan0 2>&1 | head -20
    exit 1
}

echo ""
echo "=== 接続後のネットワーク状態 ==="
ip -br addr show

echo ""
echo "=== wlan0 の gateway を取得 ==="
WLAN_GW=$(ip route show dev wlan0 | grep default | awk '{print $3}')
echo "wlan0 gateway: $WLAN_GW"

echo ""
echo "=== ntrip.ales-corp.co.jp のIPを解決 ==="
NTRIP_IP=$(getent hosts ntrip.ales-corp.co.jp | awk '{print $1}' | head -1)
echo "NTRIP IP: $NTRIP_IP"

echo ""
echo "=== NTRIP IPへのルートを wlan0 経由に追加 ==="
if [ -n "$WLAN_GW" ] && [ -n "$NTRIP_IP" ]; then
    sudo ip route replace "$NTRIP_IP" via "$WLAN_GW" dev wlan0
    echo "ルート追加完了: $NTRIP_IP via $WLAN_GW dev wlan0"
else
    echo "WARNING: gateway または NTRIP IP が取得できませんでした"
fi

echo ""
echo "=== ルーティングテーブル確認 ==="
ip route show

echo ""
echo "=== wlan0 経由での ping テスト (Google DNS) ==="
ping -c 3 -I wlan0 8.8.8.8 2>&1 || echo "WARN: wlan0 ping 失敗"

echo ""
echo "=== ntrip.ales-corp.co.jp:2101 への到達性テスト ==="
timeout 5 bash -c "echo 'GET / HTTP/1.0\r\n\r\n' | nc -w 5 ntrip.ales-corp.co.jp 2101" 2>&1 | head -5 && echo "ポート2101 到達OK" || echo "ポート2101 到達NG"

echo ""
echo "=== 完了 ==="
