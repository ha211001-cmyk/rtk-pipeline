#!/usr/bin/env python3
"""
[PPK デバッグ] RXM-RAWX 属性ダンプ
====================================
trkStat などの X1 型属性の実際の値と型を確認するためのデバッグスクリプト。
test_02 で搬送波位相が全て「無効」になった場合に使用。

使い方:
  python3 debug_rawx_attrs.py
"""

import sys
import time

try:
    import serial
except ImportError:
    print("pip install pyserial")
    sys.exit(1)

try:
    from pyubx2 import UBXReader, UBXMessage, UBX_PROTOCOL, NMEA_PROTOCOL, SET_LAYER_RAM, TXN_NONE
except ImportError:
    print("pip install pyubx2")
    sys.exit(1)

SERIAL_PORT = "/dev/ttyACM0"
BAUD = 38400

ser = serial.Serial(SERIAL_PORT, BAUD, timeout=1)

# RAWX 有効化
cfg = [
    ("CFG_USBOUTPROT_UBX",           1),
    ("CFG_MSGOUT_UBX_RXM_RAWX_USB",  1),
    ("CFG_MSGOUT_UBX_RXM_SFRBX_USB", 1),
]
msg = UBXMessage.config_set(SET_LAYER_RAM, TXN_NONE, cfg)
ser.write(msg.serialize())
time.sleep(1.5)

print("=== parsebitfield=0 (生バイト) ===")
ubr0 = UBXReader(ser, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL, parsebitfield=0)
deadline = time.time() + 30
found = False
while time.time() < deadline and not found:
    try:
        _, p = ubr0.read()
        if p and hasattr(p, "identity") and p.identity == "RXM-RAWX":
            num = getattr(p, "numMeas", 0)
            print(f"numMeas={num}")
            for i in range(1, min(num + 1, 8)):
                ts   = getattr(p, f"trkStat_{i:02d}", None)
                cno  = getattr(p, f"cno_{i:02d}",     None)
                gnss = getattr(p, f"gnssId_{i:02d}",  None)
                sv   = getattr(p, f"svId_{i:02d}",    None)
                prS  = getattr(p, f"prStdev_{i:02d}", None)
                cpS  = getattr(p, f"cpStdev_{i:02d}", None)
                print(f"  [{i:02d}] gnss={gnss} sv={sv:3} cno={cno}"
                      f" trkStat={repr(ts)} ({type(ts).__name__})"
                      f" prStdev={repr(prS)} cpStdev={repr(cpS)}")
                if isinstance(ts, (bytes, bytearray)) and len(ts) > 0:
                    val = ts[0]
                    print(f"         trkStat bits: {val:08b}  "
                          f"prValid={bool(val&0x01)} cpValid={bool(val&0x02)} halfCyc={bool(val&0x04)}")
                elif isinstance(ts, int):
                    val = ts
                    print(f"         trkStat bits: {val:08b}  "
                          f"prValid={bool(val&0x01)} cpValid={bool(val&0x02)} halfCyc={bool(val&0x04)}")
            found = True
    except Exception as e:
        print(f"err: {e}")

if not found:
    print("RAWX を受信できませんでした")
    ser.close()
    sys.exit(1)

# parsebitfield=1 (デフォルト) でも確認
print("\n=== parsebitfield=1 (ビットフラグ展開) ===")
ser.reset_input_buffer()
ubr1 = UBXReader(ser, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL, parsebitfield=1)
deadline = time.time() + 15
found = False
while time.time() < deadline and not found:
    try:
        _, p = ubr1.read()
        if p and hasattr(p, "identity") and p.identity == "RXM-RAWX":
            num = getattr(p, "numMeas", 0)
            print(f"numMeas={num}")
            for i in range(1, min(num + 1, 4)):
                sv = getattr(p, f"svId_{i:02d}", None)
                # parsebitfield=1 の場合, X1 は個別ビット属性に展開される
                # trkStat 属性一覧を探す
                attrs_of_interest = [
                    a for a in dir(p)
                    if f"_{i:02d}" in a and ("trkStat" in a.lower() or "cno" in a.lower() or "cpstdev" in a.lower())
                ]
                print(f"  [{i:02d}] sv={sv}  attrs: {attrs_of_interest}")
                for a in attrs_of_interest:
                    print(f"         {a} = {repr(getattr(p, a, None))}")
            found = True
    except Exception as e:
        print(f"err: {e}")

ser.close()
print("\n完了")
