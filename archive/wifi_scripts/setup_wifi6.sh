#!/bin/bash
set -e
pkill -f "wpa_supplicant.*wlan0" 2>/dev/null || true
sleep 1

NEW_PSK=$(wpa_passphrase 'だるま雪2' '123456789' | grep -v '#psk' | grep psk | tr -d ' \t' | cut -d= -f2)
echo "PSK=$NEW_PSK"

cat > /tmp/wpa_daruma.conf << WPAEOF
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
country=JP
network={
    ssid="だるま雪2"
    psk=${NEW_PSK}
    key_mgmt=WPA-PSK
}
WPAEOF

ip link set wlan0 up
wpa_supplicant -B -i wlan0 -c /tmp/wpa_daruma.conf -f /tmp/wpa_daruma.log
sleep 10
wpa_cli -i wlan0 status

if ! wpa_cli -i wlan0 status | grep -q "wpa_state=COMPLETED"; then
    echo "!!! 接続失敗 - ログ ==="; tail -20 /tmp/wpa_daruma.log; exit 1
fi

echo "=== DHCP ==="
dhclient -v wlan0 2>&1 | grep -E "bound|DHCPACK|error" | head -5
sleep 2
ip -br addr show

echo "=== ルート ==="
ip route show

NTRIP_IP=$(getent hosts ntrip.ales-corp.co.jp | awk '{print $1}' | head -1)
WLAN_GW=$(ip route show dev wlan0 | grep default | awk '{print $3}')
echo "NTRIP IP=$NTRIP_IP  GW=$WLAN_GW"
if [ -n "$NTRIP_IP" ] && [ -n "$WLAN_GW" ]; then
    ip route replace "$NTRIP_IP" via "$WLAN_GW" dev wlan0
    echo "ルート追加完了"
fi

echo "=== ntrip.ales-corp.co.jp:2101 到達テスト ==="
echo "QUIT" | nc -w 5 ntrip.ales-corp.co.jp 2101 | head -3 && echo "OK" || echo "NG"
echo "=== 完了 ==="
