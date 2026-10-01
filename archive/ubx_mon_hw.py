#!/usr/bin/env python3
"""
rtk-pipeline UBX MON-HW/EXTENDED モニタリング
F9Pの内部負荷率やバッファ余裕などをUBXバイナリで取得
"""
import serial
import sys
from pyubx2 import UBXReader, UBXMessage, POLL, UBX_PROTOCOL
from time import sleep

def print_mon_hw(msg):
    print("\n[UBX-MON-HW] ハードウェア情報:")
    print(f"  Noise Per MS: {msg.noisePerMS}")
    print(f"  AGC: {msg.agcCnt}")
    print(f"  Jamming Indicator: {msg.jamInd}")
    # bytes型は16進数文字列に変換
    def fmt(val):
        if isinstance(val, (bytes, bytearray)):
            return val.hex()
        return val
    print(f"  Pin Status: {fmt(getattr(msg, 'pinSel', ''))}")
    print(f"  Pin Bank: {fmt(getattr(msg, 'pinBank', ''))}")
    print(f"  Antenna Status: {getattr(msg, 'antennaStatus', 'N/A')}")
    print(f"  Antenna Power: {getattr(msg, 'antennaPower', 'N/A')}")
    print(f"  Reserved: {fmt(getattr(msg, 'reserved1', ''))}")
    print(f"  Used Mask: {fmt(getattr(msg, 'usedMask', ''))}")
    print(f"  VP: {fmt(getattr(msg, 'vp', ''))}")
    print(f"  Jam Status: {fmt(getattr(msg, 'jamStatus', ''))}")
    print(f"  Pin IRQ: {fmt(getattr(msg, 'pinIrq', ''))}")
    print(f"  Pull H: {fmt(getattr(msg, 'pullH', ''))}")
    print(f"  Pull L: {fmt(getattr(msg, 'pullL', ''))}")
    print(f"  Spare: {fmt(getattr(msg, 'spare', ''))}")
    print(f"  Used Mask2: {fmt(getattr(msg, 'usedMask2', ''))}")
    print(f"  VP2: {fmt(getattr(msg, 'vp2', ''))}")
    print(f"  Jam Status2: {fmt(getattr(msg, 'jamStatus2', ''))}")
    print(f"  Reserved2: {fmt(getattr(msg, 'reserved2', ''))}")

def print_mon_hw2(msg):
    print("\n[UBX-MON-HW2] 拡張ハードウェア情報:")
    print(f"  Pin IRQ: {msg.pinIrq:08X}")
    print(f"  Pull H: {msg.pullH:08X}")
    print(f"  Pull L: {msg.pullL:08X}")
    print(f"  Noise Per MS: {msg.noisePerMS}")
    print(f"  AGC: {msg.agcCnt}")
    print(f"  Jam Status: {msg.jamStatus}")
    print(f"  Reserved: {msg.reserved1}")
    print(f"  Used Mask: {msg.usedMask:08X}")
    print(f"  VP: {msg.vp}")
    print(f"  Jam Status2: {msg.jamStatus2}")
    print(f"  Reserved2: {msg.reserved2}")

def print_mon_io(msg):
    print("\n[UBX-MON-IO] 通信バッファ状況:")
    print(f"  RX Bytes Pending: {msg.rxPending}")
    print(f"  TX Bytes Pending: {msg.txPending}")
    print(f"  RX Usage: {msg.rxUsage}%")
    print(f"  TX Usage: {msg.txUsage}%")
    print(f"  RX Peak Usage: {msg.rxPeakUsage}%")
    print(f"  TX Peak Usage: {msg.txPeakUsage}%")
    print(f"  RX Overruns: {msg.rxOverrun}")
    print(f"  TX Overruns: {msg.txOverrun}")
    print(f"  RX Bytes: {msg.rxBytes}")
    print(f"  TX Bytes: {msg.txBytes}")
    print(f"  RX Frames: {msg.rxFrames}")
    print(f"  TX Frames: {msg.txFrames}")
    print(f"  RX Errors: {msg.rxErrs}")
    print(f"  TX Errors: {msg.txErrs}")
    print(f"  RX Drops: {msg.rxDrops}")
    print(f"  TX Drops: {msg.txDrops}")
    print(f"  RX Bytes Dropped: {msg.rxBytesDropped}")
    print(f"  TX Bytes Dropped: {msg.txBytesDropped}")

def poll_and_print(port='COM6', baudrate=38400):
    with serial.Serial(port, baudrate, timeout=2) as ser:
        print(f"✓ Connected to {port} for UBX MON polling")
        ubr = UBXReader(ser, protfilter=UBX_PROTOCOL)
        # MON-HW (class 0x0A, id 0x09)
        ser.write(UBXMessage(b'\x0a', b'\x09', POLL).serialize())
        sleep(0.2)
        for (raw, msg) in ubr:
            if getattr(msg, 'identity', '') == 'MON-HW':
                print_mon_hw(msg)
                break
        # MON-HW2 (class 0x0A, id 0x0B)
        ser.write(UBXMessage(b'\x0a', b'\x0b', POLL).serialize())
        sleep(0.2)
        for (raw, msg) in ubr:
            if getattr(msg, 'identity', '') == 'MON-HW2':
                print_mon_hw2(msg)
                break
        # MON-IO (class 0x0A, id 0x02)
        ser.write(UBXMessage(b'\x0a', b'\x02', POLL).serialize())
        sleep(0.2)
        for (raw, msg) in ubr:
            if getattr(msg, 'identity', '') == 'MON-IO':
                print_mon_io(msg)
                break

if __name__ == '__main__':
    port = 'COM6'
    baudrate = 38400
    if len(sys.argv) > 1:
        port = sys.argv[1]
    if len(sys.argv) > 2:
        try:
            baudrate = int(sys.argv[2])
        except ValueError:
            pass
    poll_and_print(port, baudrate)
