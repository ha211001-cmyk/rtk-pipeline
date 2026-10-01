#!/usr/bin/env python3
"""
wpa_supplicant + dhclient で wlan0 を接続し、
NTRIP サーバーへのルートだけ wlan0 経由にする。
SSH (eth0) は維持したまま。
"""
import os, subprocess, socket, time

SSID = "だるま雪2"
PSK = "1234546789"
WPA_CONF = "/tmp/wpa_daruma.conf"

# --- 1. NM に wlan0 を unmanage させる ---
print("=== NM から wlan0 を unmanage ===")
subprocess.run(["nmcli", "dev", "set", "wlan0", "managed", "no"], check=False)
subprocess.run(["ip", "link", "set", "wlan0", "up"])
time.sleep(1)

# --- 2. wpa_supplicant.conf を生成 ---
wpa_conf = f"""ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=0
country=JP

network={{
    ssid="{SSID}"
    psk="{PSK}"
    key_mgmt=WPA-PSK
    proto=RSN
    pairwise=CCMP
    group=CCMP
}}
"""
with open(WPA_CONF, "w") as f:
    f.write(wpa_conf)
print(f"Written: {WPA_CONF}")

# --- 3. 既存の wpa_supplicant を wlan0 向けに停止 ---
subprocess.run(["pkill", "-f", f"wpa_supplicant.*wlan0"], capture_output=True)
time.sleep(1)

# --- 4. wpa_supplicant をバックグラウンド起動 ---
print("=== wpa_supplicant 起動 ===")
r = subprocess.run(
    ["wpa_supplicant", "-B", "-i", "wlan0", "-c", WPA_CONF, "-f", "/tmp/wpa_daruma.log"],
    capture_output=True, text=True
)
print("RC:", r.returncode, r.stdout, r.stderr)
time.sleep(5)

# --- 5. 接続状態確認 ---
print("=== wpa_cli status ===")
r = subprocess.run(["wpa_cli", "-i", "wlan0", "status"], capture_output=True, text=True)
print(r.stdout)

if "COMPLETED" not in r.stdout:
    print("!!! wpa_supplicant ログ !!!")
    try:
        print(open("/tmp/wpa_daruma.log").read()[-2000:])
    except:
        pass
    import sys
    sys.exit(1)

# --- 6. DHCP で IP 取得 ---
print("=== dhclient wlan0 ===")
subprocess.run(["dhclient", "-v", "wlan0"], capture_output=True, text=True, timeout=20)
time.sleep(2)

# --- 7. wlan0 の IP と gateway を確認 ---
print("=== ip addr / route ===")
subprocess.run(["ip", "-br", "addr", "show"])
r = subprocess.run(["ip", "route", "show"], capture_output=True, text=True)
print(r.stdout)

wlan_gw = None
for line in r.stdout.splitlines():
    if "default" in line and "wlan0" in line:
        parts = line.split()
        idx = parts.index("via")
        wlan_gw = parts[idx + 1]
        break

# wlan0 に default route がなければ link-scope から取得
if not wlan_gw:
    for line in r.stdout.splitlines():
        if "wlan0" in line and "via" in line:
            parts = line.split()
            idx = parts.index("via")
            wlan_gw = parts[idx + 1]
            break

print(f"wlan0 gateway: {wlan_gw}")

# --- 8. NTRIP IP を解決してルートを追加 ---
NTRIP_HOST = "ntrip.ales-corp.co.jp"
try:
    ntrip_ip = socket.gethostbyname(NTRIP_HOST)
    print(f"NTRIP IP: {ntrip_ip}")
    if wlan_gw:
        subprocess.run(["ip", "route", "replace", ntrip_ip, "via", wlan_gw, "dev", "wlan0"])
        print(f"Route added: {ntrip_ip} via {wlan_gw} dev wlan0")
    else:
        print("WARNING: wlan0 gateway not found, add route manually")
except Exception as e:
    print(f"DNS error: {e}")

# --- 9. 到達性テスト ---
print("\n=== ntrip.ales-corp.co.jp:2101 到達テスト ===")
try:
    s = socket.create_connection(("ntrip.ales-corp.co.jp", 2101), timeout=10)
    s.close()
    print("ポート2101 接続成功!")
except Exception as e:
    print(f"ポート2101 接続失敗: {e}")

print("\n=== 完了 ===")
print("次のステップ: gps_statistics.py を実行")
