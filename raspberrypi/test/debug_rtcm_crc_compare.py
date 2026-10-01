#!/usr/bin/env python3
"""
RTCM3 CRC24Q 検証デバッグ
- シリアル生データからRTCM3フレームを抽出
- 自前CRC実装と pyrtcm.calc_crc24q を比較
- 有効フレーム数と必須MSG出現を表示
"""

import time

import serial
from pyrtcm import calc_crc24q

PORT = "/dev/ttyACM0"
BAUD = 38400
DURATION_SEC = 12


def my_crc24q(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1864CFB
    return crc & 0xFFFFFF


def main():
    ser = serial.Serial(PORT, BAUD, timeout=1.0)
    buf = b""

    total = 0
    valid = 0
    crc_impl_mismatch = 0
    msg_stats = {}

    start = time.time()
    while time.time() - start < DURATION_SEC:
        chunk = ser.read(ser.in_waiting or 1)
        if not chunk:
            continue
        buf += chunk

        while len(buf) >= 3:
            idx = buf.find(b"\xD3")
            if idx == -1:
                buf = b""
                break
            if idx > 0:
                buf = buf[idx:]

            if len(buf) < 3:
                break

            length = ((buf[1] & 0x03) << 8) | buf[2]
            frame_len = 3 + length + 3
            if len(buf) < frame_len:
                break

            frame = buf[:frame_len]
            buf = buf[frame_len:]
            total += 1

            expected = int.from_bytes(frame[-3:], "big")
            mine = my_crc24q(frame[:-3])
            lib = calc_crc24q(frame[:-3])
            if mine != lib:
                crc_impl_mismatch += 1

            if mine == expected:
                valid += 1
                if length >= 2:
                    msg_num = (frame[3] << 4) | (frame[4] >> 4)
                    msg_stats[msg_num] = msg_stats.get(msg_num, 0) + 1

    ser.close()

    print("=== CRC 実装比較結果 ===")
    print(f"TOTAL               : {total}")
    print(f"VALID               : {valid}")
    print(f"INVALID             : {total - valid}")
    print(f"CRC_IMPL_MISMATCH   : {crc_impl_mismatch}")

    required = [1005, 1077, 1087, 1097, 1127, 1230]
    for msg in required:
        print(f"REQ_MSG {msg:4d}       : {msg_stats.get(msg, 0)}")


if __name__ == "__main__":
    main()
