#!/usr/bin/env python3
"""direct_inject.py — 基地局F9P → Pixhawk(USB MAVLink) → DroneCAN → ローバーF9P へ直接 RTCM 注入

Pi を経由せず、Mac から Pixhawk の USB MAVLink ポートへ GPS_RTCM_DATA を直接注入する。
あわせて GPS_RAW_INT を受信して FIX 状態を監視する。

Usage:
    python3 direct_inject.py [--base /dev/cu.usbmodem312301] [--pixhawk /dev/cu.usbmodem103]
"""

import argparse
import serial
import time

from pymavlink import mavutil

DEFAULT_BASE = "/dev/cu.usbmodem312301"
DEFAULT_PIXHAWK = "/dev/cu.usbmodem103"
BAUD = 115200

FIX_NAMES = {1: "NO_FIX", 2: "2D", 3: "3D", 4: "DGPS", 5: "RTK_FLOAT", 6: "RTK_FIXED"}


def extract_rtcm_frames(buf: bytearray):
    """バッファから RTCM3 フレーム（0xD3 始まり）を yield する"""
    while len(buf) >= 6:
        if buf[0] != 0xD3:
            buf.pop(0)
            continue
        if (buf[1] >> 2) != 0:
            buf.pop(0)
            continue
        frame_len = ((buf[1] & 0x03) << 8) | buf[2]
        if frame_len > 1023:
            buf.pop(0)
            continue
        total = 6 + frame_len
        if len(buf) < total:
            break
        yield bytes(buf[:total])
        del buf[:total]


def main() -> None:
    p = argparse.ArgumentParser(description="基地局F9P → Pixhawk USB 直接 RTCM 注入")
    p.add_argument("--base", default=DEFAULT_BASE, help="基地局F9P のシリアルポート")
    p.add_argument("--pixhawk", default=DEFAULT_PIXHAWK, help="Pixhawk の MAVLink ポート")
    p.add_argument("--baud", type=int, default=BAUD)
    args = p.parse_args()

    # Pixhawk MAVLink
    m = mavutil.mavlink_connection(args.pixhawk, baud=args.baud)
    m.wait_heartbeat(timeout=5)
    print("[INFO] Pixhawk 接続: sysid=%d compid=%d" % (m.target_system, m.target_component))

    # GPS_RAW_INT (24) を 10Hz で要求
    m.mav.command_long_send(m.target_system, m.target_component,
                            mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
                            0, 24, 100000, 0, 0, 0, 0, 0)
    print("[INFO] GPS_RAW_INT を 10Hz で要求")

    # 基地局 F9P
    ser = serial.Serial(args.base, args.baud, timeout=0.1)
    print("[INFO] 基地局F9P 接続: %s" % args.base)

    buf = bytearray()
    seq = 0
    frames = 0
    last_fix = None
    fix_counts = {}
    last_status = time.time()

    print("RTCM 注入 + FIX 監視を開始 (Ctrl+C で終了)")
    try:
        while True:
            # RTCM 読み取り → 注入
            try:
                data = ser.read(4096)
            except Exception:
                data = b""
            if data:
                buf.extend(data)
                for frame in extract_rtcm_frames(buf):
                    fl = len(frame)
                    if fl <= 180:
                        flags = (seq << 3) | 0
                        m.mav.gps_rtcm_data_send(flags, fl, list(frame) + [0] * (180 - fl))
                    else:
                        nfrag = (fl + 179) // 180
                        if nfrag <= 4:
                            for fid in range(nfrag):
                                s = fid * 180
                                e = min(s + 180, fl)
                                frag = frame[s:e]
                                flags = (seq << 3) | (fid << 1) | 1
                                m.mav.gps_rtcm_data_send(flags, len(frag),
                                                         list(frag) + [0] * (180 - len(frag)))
                    seq = (seq + 1) % 32
                    frames += 1

            # GPS_RAW_INT 収集
            while True:
                msg = m.recv_match(type='GPS_RAW_INT', blocking=False)
                if msg is None:
                    break
                fix = msg.fix_type
                sats = msg.satellites_visible
                fix_counts[fix] = fix_counts.get(fix, 0) + 1
                last_fix = (fix, sats)

            # ステータス表示（5秒ごと）
            if time.time() - last_status >= 5:
                fn = FIX_NAMES.get(last_fix[0], "?") if last_fix else "?"
                sn = last_fix[1] if last_fix else "?"
                dist = " ".join("%s=%d" % (FIX_NAMES.get(k, k), v) for k, v in sorted(fix_counts.items()))
                print("[STATUS] frames=%d | GPS:%s sats=%s | %s" % (frames, fn, sn, dist))
                last_status = time.time()
    except KeyboardInterrupt:
        print("\n[INFO] 終了")
    finally:
        ser.close()
        m.close()


if __name__ == "__main__":
    main()
