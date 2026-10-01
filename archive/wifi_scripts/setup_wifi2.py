#!/usr/bin/env python3
import os, subprocess

conf = """[connection]
id=だるま雪2
type=wifi
interface-name=wlan0

[wifi]
mode=infrastructure
ssid=だるま雪2

[wifi-security]
auth-alg=open
key-mgmt=wpa-psk
psk=1234546789
psk-flags=0

[ipv4]
method=auto
route-metric=200

[ipv6]
method=ignore

[proxy]
"""

path = "/etc/NetworkManager/system-connections/daruma.nmconnection"
with open(path, "w") as f:
    f.write(conf)
os.chmod(path, 0o600)
print(f"Written: {path}")
print("--- file content ---")
print(open(path).read())

# リロードして接続
subprocess.run(["nmcli", "con", "reload"], check=True)
print("Reloaded")
r = subprocess.run(["nmcli", "con", "up", "だるま雪2"], capture_output=True, text=True)
print("STDOUT:", r.stdout)
print("STDERR:", r.stderr)
print("RC:", r.returncode)
