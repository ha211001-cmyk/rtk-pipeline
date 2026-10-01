#!/usr/bin/env python3
import os, subprocess, uuid, socket, time

# --- 正しい NM プロファイルを Buffalo と同じ形式で作成 ---
new_uuid = str(uuid.uuid4())
conf = f"""[connection]
id=だるま雪2
uuid={new_uuid}
type=wifi
interface-name=wlan0

[wifi]
mode=infrastructure
ssid=だるま雪2

[wifi-security]
auth-alg=open
key-mgmt=wpa-psk
psk=1234546789

[ipv4]
method=auto
route-metric=200

[ipv6]
addr-gen-mode=default
method=auto

[proxy]
"""

# 既存プロファイルを削除して新規作成
subprocess.run(["nmcli", "con", "delete", "だるま雪2"], capture_output=True)

path = "/etc/NetworkManager/system-connections/daruma.nmconnection"
with open(path, "w") as f:
    f.write(conf)
os.chmod(path, 0o600)
print(f"Written: {path} (uuid={new_uuid})")

# NM にリロードさせる
subprocess.run(["nmcli", "con", "reload"], check=True)
time.sleep(1)
print("Reloaded")

# 接続実行
print("=== nmcli con up ===")
r = subprocess.run(["nmcli", "con", "up", "だるま雪2"], capture_output=True, text=True, timeout=30)
print("STDOUT:", r.stdout)
print("STDERR:", r.stderr)
print("RC:", r.returncode)

if r.returncode != 0:
    # NM ジャーナルを確認
    print("\n=== NM journal (last 20 lines) ===")
    j = subprocess.run(
        ["journalctl", "-u", "NetworkManager", "-n", "20", "--no-pager"],
        capture_output=True, text=True
    )
    print(j.stdout[-3000:])
    import sys; sys.exit(1)

# --- 成功 ---
time.sleep(3)
print("\n=== ip addr show wlan0 ===")
subprocess.run(["ip", "-br", "addr", "show"])

# gateway 取得
r2 = subprocess.run(["ip", "route", "show"], capture_output=True, text=True)
print(r2.stdout)
wlan_gw = None
for line in r2.stdout.splitlines():
    if "default" in line and "wlan0" in line:
        parts = line.split()
        wlan_gw = parts[parts.index("via") + 1]
        break

# NTRIP ルート設定
NTRIP_HOST = "ntrip.ales-corp.co.jp"
try:
    ntrip_ip = socket.gethostbyname(NTRIP_HOST)
    print(f"NTRIP IP: {ntrip_ip}")
    if wlan_gw:
        subprocess.run(["ip", "route", "replace", ntrip_ip, "via", wlan_gw, "dev", "wlan0"])
        print(f"Route added: {ntrip_ip} via {wlan_gw} dev wlan0")
except Exception as e:
    print(f"DNS error: {e}")

# 到達性テスト
print("\n=== ntrip.ales-corp.co.jp:2101 到達テスト ===")
try:
    s = socket.create_connection(("ntrip.ales-corp.co.jp", 2101), timeout=10)
    s.close()
    print("ポート2101 接続成功!")
except Exception as e:
    print(f"ポート2101 接続失敗: {e}")

print("\n=== 完了 ===")
