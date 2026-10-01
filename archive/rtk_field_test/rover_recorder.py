#!/usr/bin/env python3
"""
rover_recorder.py — 移動局側（ラズパイ）: UDP受信 → MAVLink注入 + .rtcm3保存 + RTK状態CSV

基地局から UDP で送られてくる RTCM3 を受信し、MAVLink GPS_RTCM_DATA で
ArduPilot（Pixhawk）へ注入しつつ、RTCM を .rtcm3 に保存し、
RTK 状態（fix/sats/nsats/基線長/位置/最終RTCM秒）を CSV に 1 秒毎記録する。

rtk_base_mavlink/ の MavlinkComm / RtcmInjector を再利用する。

使い方:
    python3 rover_recorder.py --rtscts --log-dir logs --status-csv logs/rtk_status.csv
"""

import argparse
import csv
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

# rtk_base_mavlink を import パスに追加
_REPO_ROOT = Path(__file__).resolve().parent.parent
_MAVLINK_DIR = _REPO_ROOT / "rtk_base_mavlink"
if _MAVLINK_DIR.is_dir():
    sys.path.insert(0, str(_MAVLINK_DIR))

from mavlink_comm import MavlinkComm  # noqa: E402
from rtcm_injector import RtcmInjector  # noqa: E402

from rtcm_logger import RtcmFrameLogger  # noqa: E402

DEFAULT_UDP_PORT = 50010
DEFAULT_MAVLINK_PORT = "/dev/ttyAMA0"
DEFAULT_MAVLINK_BAUD = 921600


def extract_rtcm_frames(buf: bytearray):
    """バッファから RTCM3 フレーム（0xD3 始まり）を1つずつ yield する。"""
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
    p = argparse.ArgumentParser(
        description="UDP受信 → MAVLink注入 + RTCM/RTK状態記録",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--port", type=int, default=DEFAULT_UDP_PORT, help="UDP受信ポート")
    p.add_argument("--mavlink-port", default=DEFAULT_MAVLINK_PORT, help="Pixhawk MAVLinkポート")
    p.add_argument("--baud", type=int, default=DEFAULT_MAVLINK_BAUD, help="MAVLinkボーレート")
    p.add_argument("--rtscts", action=argparse.BooleanOptionalAction, default=True,
                   help="RTS/CTSフロー制御（既定: 有効。--no-rtscts で無効化）")
    p.add_argument("--max-packet-size", type=int, default=180)
    p.add_argument("--max-fragments", type=int, default=4)
    p.add_argument("--log-dir", default="logs", help="RTCM/CSV保存先ディレクトリ")
    p.add_argument("--tag", default="rover", help="RTCMログファイル名の識別子")
    p.add_argument("--status-csv", default=None,
                   help="RTK状態CSV出力先（省略時: <log-dir>/rtk_status_<ts>.csv）")
    p.add_argument("--status-interval", type=float, default=1.0, help="CSV記録間隔(秒)")
    args = p.parse_args()

    # CSV 出力先
    Path(args.log_dir).mkdir(parents=True, exist_ok=True)
    if args.status_csv is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.status_csv = str(Path(args.log_dir) / ("rtk_status_%s.csv" % ts))

    csv_fh = open(args.status_csv, "w", newline="")
    writer = csv.writer(csv_fh)
    writer.writerow(["utc_time", "elapsed_sec", "fix_type", "fix_name", "sats",
                     "nsats", "baseline_m", "lat", "lon", "alt", "eph", "epv",
                     "rtcm_elapsed_sec"])
    csv_fh.flush()
    print("[LOG] RTK状態CSV: %s" % args.status_csv)

    mavlink = MavlinkComm(port=args.mavlink_port, baud=args.baud, rtscts=args.rtscts)
    if not mavlink.connect():
        print("[ERROR] MAVLink接続に失敗しました。Pixhawkの電源・接続・ボーレートを確認してください")
        csv_fh.close()
        sys.exit(1)

    # PL011 UART の受信ハングアップ対策として CLOCAL を設定
    try:
        import termios
        _fd = mavlink._master.port.fd
        _attrs = termios.tcgetattr(_fd)
        _attrs[2] |= termios.CLOCAL
        termios.tcsetattr(_fd, termios.TCSANOW, _attrs)
        print("[INFO] CLOCAL 設定済み（受信ハングアップ対策）")
    except Exception:
        pass

    mavlink.start_gps_stream()
    time.sleep(1)

    injector = RtcmInjector(mavlink_comm=mavlink,
                            max_packet_size=args.max_packet_size,
                            max_fragments=args.max_fragments)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", args.port))
    except OSError as e:
        print("[ERROR] UDPポート %d の bind に失敗: %s" % (args.port, e))
        mavlink.disconnect()
        csv_fh.close()
        sys.exit(1)

    logger = RtcmFrameLogger(log_dir=args.log_dir, tag=args.tag)

    print("=" * 60)
    print("UDP受信待機中: 0.0.0.0:%d" % args.port)
    print("Ctrl+C で終了")
    print("=" * 60)

    bytes_received = 0
    start_time = time.time()
    last_frame_time = start_time
    last_status = 0.0

    try:
        while True:
            try:
                sock.settimeout(0.5)
                data, _addr = sock.recvfrom(65535)
                if data:
                    bytes_received += len(data)
                    for frame in extract_rtcm_frames(bytearray(data)):
                        logger.write(frame)
                        injector.inject_frame(frame)
                        last_frame_time = time.time()
            except socket.timeout:
                pass

            now = time.time()
            if now - last_status >= args.status_interval:
                pos = mavlink.get_gps_position()
                elapsed = now - last_frame_time
                writer.writerow([
                    datetime.now().strftime("%H:%M:%S"),
                    round(now - start_time, 2),
                    pos.get("fix_type", 0),
                    pos.get("fix_name", "?"),
                    pos.get("satellites", 0),
                    pos.get("rtk_nsats", 0),
                    pos.get("baseline_m"),
                    pos.get("lat"),
                    pos.get("lon"),
                    pos.get("alt"),
                    pos.get("eph"),
                    pos.get("epv"),
                    round(elapsed, 2),
                ])
                csv_fh.flush()
                last_status = now

                base = pos.get("baseline_m")
                base_s = "%.1fm" % base if base is not None else "?"
                print("[STATUS %s] injected=%d dropped=%d | GPS:%s sats=%s "
                      "nsats=%s base=%s | 最終RTCMから%.1f秒" %
                      (datetime.now().strftime("%H:%M:%S"),
                       injector.stats["frames_injected"],
                       injector.stats["frames_dropped"],
                       pos.get("fix_name", "?"),
                       pos.get("satellites", 0),
                       pos.get("rtk_nsats", 0),
                       base_s,
                       elapsed))
    except KeyboardInterrupt:
        print("\n[INFO] Ctrl+C で終了します")
    finally:
        logger.summary()
        logger.close()
        csv_fh.close()
        sock.close()
        mavlink.disconnect()
        print("[INFO] 終了（injected=%d dropped=%d bytes=%d）" %
              (injector.stats["frames_injected"],
               injector.stats["frames_dropped"],
               bytes_received))


if __name__ == "__main__":
    main()
