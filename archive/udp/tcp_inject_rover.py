#!/usr/bin/env python3
"""tcp_inject_rover.py — Macリレー(TCP:2102) → MAVLink GPS_RTCM_DATA 注入

ichimill A/B テスト用。
Mac の ntrip_relay (TCP:2102) から RTCM を取得し、
Pixhawk へ MAVLink GPS_RTCM_DATA (ID:233) として注入する。

Usage (ラズパイ側):
    python3 tcp_inject_rover.py [--relay-host 100.75.83.95] [--relay-port 2102]
"""

import argparse
import socket
import sys
import time
from pathlib import Path

# rtk_base_mavlink を import パスに追加
_REPO = Path(__file__).resolve().parent.parent
_MAVLINK_DIR = _REPO / "rtk_base_mavlink"
if _MAVLINK_DIR.is_dir():
    sys.path.insert(0, str(_MAVLINK_DIR))

from mavlink_comm import MavlinkComm
from rtcm_injector import RtcmInjector


def extract_rtcm_frames(buf: bytearray):
    """バッファから RTCM3 フレーム（0xD3 始まり）を1つずつ yield する"""
    while len(buf) >= 6:
        if buf[0] != 0xD3:
            buf.pop(0)
            continue
        if (buf[1] >> 2) != 0:  # reserved bits must be 0
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
    p = argparse.ArgumentParser(description="Macリレー(TCP) → MAVLink GPS_RTCM_DATA 注入")
    p.add_argument("--relay-host", default="100.75.83.95", help="Mac リレーのホスト(Tailscale IP)")
    p.add_argument("--relay-port", type=int, default=2102, help="Mac リレーのポート")
    p.add_argument("--mavlink-port", default="/dev/ttyAMA0", help="MAVLink接続ポート")
    p.add_argument("--baud", type=int, default=921600, help="MAVLinkボーレート")
    args = p.parse_args()

    mavlink = MavlinkComm(port=args.mavlink_port, baud=args.baud, rtscts=True)
    if not mavlink.connect():
        print("[ERROR] MAVLink接続失敗")
        sys.exit(1)

    # PL011 UART の受信ハングアップ対策
    try:
        import termios
        _fd = mavlink._master.port.fd
        _attrs = termios.tcgetattr(_fd)
        _attrs[2] |= termios.CLOCAL
        termios.tcsetattr(_fd, termios.TCSANOW, _attrs)
        print("[INFO] CLOCAL 設定済み")
    except Exception as _e:
        print("[WARN] CLOCAL 設定失敗: %s" % _e)

    mavlink.start_gps_stream()
    time.sleep(1)
    injector = RtcmInjector(mavlink_comm=mavlink, max_packet_size=180, max_fragments=4)

    print("[INFO] Mac リレー %s:%d に接続中..." % (args.relay_host, args.relay_port))
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    try:
        sock.connect((args.relay_host, args.relay_port))
    except Exception as e:
        print("[ERROR] リレー接続失敗: %r" % e)
        sys.exit(1)
    print("[INFO] リレー接続完了")

    buf = bytearray()
    last_status = time.time()
    last_frame = time.time()
    bytes_recv = 0

    # RTCM 生データ保存（ichimill の GLONASS 配信確認用）
    import os
    _logdir = str(Path(__file__).resolve().parent / "logs")
    os.makedirs(_logdir, exist_ok=True)
    rtcm_log = open(os.path.join(
        _logdir, "rtcm_ichimill_%s.rtcm3" % time.strftime("%Y%m%d_%H%M%S")), "wb")
    print("[INFO] RTCM保存先: %s" % rtcm_log.name)
    try:
        while True:
            try:
                data = sock.recv(4096)
            except socket.timeout:
                data = b""
            except Exception as e:
                print("[TCP Error] %r" % e)
                time.sleep(1)
                continue
            if data:
                rtcm_log.write(data)
                rtcm_log.flush()
                bytes_recv += len(data)
                buf.extend(data)
                for frame in extract_rtcm_frames(buf):
                    injector.inject_frame(frame)
                    last_frame = time.time()
            if time.time() - last_status >= 5:
                pos = mavlink.get_gps_position()
                print("[STATUS] injected=%d dropped=%d bytes=%d | GPS:%s sats=%s | 最終RTCMから%.1f秒" % (
                    injector.stats["frames_injected"],
                    injector.stats["frames_dropped"],
                    bytes_recv,
                    pos.get("fix_name", "?"),
                    pos.get("satellites", 0),
                    time.time() - last_frame,
                ))
                last_status = time.time()
    except KeyboardInterrupt:
        print("\n[INFO] 終了")
    finally:
        try:
            rtcm_log.close()
        except Exception:
            pass
        sock.close()
        mavlink.disconnect()


if __name__ == "__main__":
    main()
