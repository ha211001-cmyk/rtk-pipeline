#!/usr/bin/env python3
"""TMODE3をDisabledにリセット（CFG-VALSET方式）"""
import serial
import time
from pyubx2 import UBXMessage, SET

COM_PORT = "COM7"
BAUD = 38400

print("=" * 60)
print("TMODE3 Reset (CFG-VALSET)")
print("=" * 60)

ser = serial.Serial(COM_PORT, BAUD, timeout=1.0)
print(f"[OK] Connected to {COM_PORT}")

# CFG-VALSET方式でTMODE3をDisabledに設定
msg = UBXMessage.config_set(
    layers=0x05,  # RAM + FLASH
    transaction=0,
    cfgData=[("CFG_TMODE_MODE", 0)]  # 0=Disabled
)
ser.reset_input_buffer()
ser.write(msg.serialize())
time.sleep(1.0)

buf = ser.read(ser.in_waiting)
if b'\xB5\x62\x05\x01' in buf:
    print("[OK] TMODE3 reset to Disabled (Rover mode)")
else:
    print("[WARN] ACK not found, but command sent")

ser.close()
print("[OK] Port closed - Rover mode ready")