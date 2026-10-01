#!/usr/bin/env python3
"""TMODE3の現在の設定を読み取る（CFG-VALGET）"""
import serial
import time
from pyubx2 import UBXMessage, GET

COM_PORT = "COM7"
BAUD = 38400

print("=" * 60)
print("TMODE3 Current Settings (CFG-VALGET)")
print("=" * 60)

ser = serial.Serial(COM_PORT, BAUD, timeout=1.0)
print(f"[OK] Connected to {COM_PORT}")

# CFG-VALGETでTMODE3設定を読み取る
cfg_keys = [
    "CFG_TMODE_MODE",
    "CFG_TMODE_POS_TYPE",
    "CFG_TMODE_LAT",
    "CFG_TMODE_LON",
    "CFG_TMODE_HEIGHT",
    "CFG_TMODE_ECEF_X",
    "CFG_TMODE_ECEF_Y",
    "CFG_TMODE_ECEF_Z",
    "CFG_TMODE_FIXED_POS_ACC",
]

msg = UBXMessage.config_get(cfgData=cfg_keys)
ser.reset_input_buffer()
ser.write(msg.serialize())
time.sleep(1.0)

buf = ser.read(ser.in_waiting)
print(f"\nRaw response ({len(buf)} bytes):")
print(f"  {buf.hex(' ').upper()}")

# CFG-VALGET応答を解析
if b'\xB5\x62\x05\x0B' in buf:
    print("\n[OK] CFG-VALGET response found")
    # 応答を解析
    idx = buf.find(b'\xB5\x62\x05\x0B')
    if idx != -1 and len(buf) >= idx + 8:
        payload = buf[idx+6:-2]  # ペイロード部分
        print(f"  Payload: {payload.hex(' ').upper()}")
else:
    print("\n[WARN] CFG-VALGET response not found")

# pyubx2でパースしてみる
from pyubx2 import UBXReader
ser.reset_input_buffer()
ser.write(msg.serialize())
time.sleep(1.0)

ubr = UBXReader(ser)
while True:
    try:
        raw, parsed = ubr.read()
        if raw is None:
            break
        if hasattr(parsed, 'identity') and parsed.identity == "CFG-VALGET":
            print(f"\n[PARSED] CFG-VALGET:")
            for attr in dir(parsed):
                if not attr.startswith('_') and attr not in ('identity', 'payload', 'transport', 'msg_cls', 'msg_id', 'length', 'checksum'):
                    try:
                        val = getattr(parsed, attr)
                        if val is not None and not callable(val):
                            print(f"  {attr}: {val}")
                    except:
                        pass
            break
    except Exception:
        break

ser.close()
print("\n[OK] Port closed")