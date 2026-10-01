#!/usr/bin/env python3
"""電源入れ直し後、Flash保存設定が保持されているかRTCMデータを確認"""
import serial
import time
from pyrtcm import RTCMReader

COM_PORT = "COM7"
BAUD = 38400

print("=" * 60)
print("RTCM Data Check (Flash Persistence Test)")
print("=" * 60)

ser = serial.Serial(COM_PORT, BAUD, timeout=1.0)
print(f"[OK] Connected to {COM_PORT}")

rtr = RTCMReader(ser)
cnt = 0
stats = {}
start = time.time()
deadline = start + 10

print("Listening for RTCM messages (10 seconds)...\n")

while time.time() < deadline:
    try:
        raw, parsed = rtr.read()
        if raw is None:
            continue
        cnt += 1
        mid = parsed.identity
        stats[mid] = stats.get(mid, 0) + 1
        print(f"[RTCM] #{cnt:4d} | {mid:8s} | {len(raw)-6:4d} bytes")
    except Exception:
        continue

elapsed = time.time() - start
print(f"\n=== Result ({elapsed:.1f}s) ===")
print(f"Total frames: {cnt}")
for k, v in sorted(stats.items()):
    print(f"  {k}: {v}")

ser.close()
print("\n[OK] Port closed")