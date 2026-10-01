#!/usr/bin/env python3
"""mavlink_bridge.py — Pixhawk シリアル (/dev/ttyAMA0) と Mac GCS (UDP:14550) の中継
+ RTCM 注入 (TCP:2101 -> MAVLink)
+ 自動ロギング (.rtcm3 生ログ + RTK 状態 CSV)
+ 終了時「位置誤差の標準偏差 (std)」自動集計・出力
+ 起動時「フェイルセーフ安全チェック (FS_GCS_ENABLE)」自動実行
"""

import argparse
import csv
from datetime import datetime
import math
import os
os.environ["MAVLINK20"] = "1"
from pathlib import Path
import socket
import sys
import threading
import time
import serial
from pymavlink import mavutil

FIX_NAMES = {
    0: "NO_GPS",
    1: "NO_FIX",
    2: "2D_FIX",
    3: "3D_FIX",
    4: "DGPS",
    5: "RTK_FLOAT",
    6: "RTK_FIXED",
}
METERS_PER_DEG_LAT = 111320.0

def extract_rtcm_frames(buf: bytearray):
    """バッファから RTCM3 フレーム（0xD3 始まり）を取り出す"""
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

def print_statistics(csv_path: str):
    """CSV を解析して位置誤差の標準偏差・RTK 状態サマリーを表示する"""
    if not os.path.exists(csv_path):
        return

    rows = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    if not rows:
        print("[STATS] 記録データがありません。")
        return

    def _f(v):
        try:
            return float(v) if v is not None and v != "" else None
        except Exception:
            return None

    def _i(v):
        try:
            return int(float(v)) if v is not None and v != "" else 0
        except Exception:
            return 0

    secs = [_f(r.get("elapsed_sec")) for r in rows]
    fixes = [_i(r.get("fix_type")) for r in rows]
    lats = [_f(r.get("lat")) for r in rows]
    lons = [_f(r.get("lon")) for r in rows]
    alts = [_f(r.get("alt")) for r in rows]

    duration = (max(secs) - min(secs)) if len(secs) >= 2 and max(secs) is not None and min(secs) is not None else len(rows)

    print("\n" + "=" * 66)
    print(" 📊 実験ロギング & 位置精度解析サマリー")
    print("=" * 66)
    print(f"  CSV ログ      : {csv_path}")
    print(f"  総サンプル数  : {len(rows)} 点 ({duration:.1f} 秒間)")

    # FIX 比率
    fix_counts = {}
    for fix in fixes:
        fix_counts[fix] = fix_counts.get(fix, 0) + 1

    print("\n  [測位モード内訳]")
    for fix, count in sorted(fix_counts.items()):
        ratio = (count / len(rows)) * 100.0
        name = FIX_NAMES.get(fix, f"FIX_{fix}")
        mark = "⭐" if fix == 6 else ("⚡" if fix == 5 else "  ")
        print(f"  {mark} {name:<10}: {count:>4} 点 ({ratio:5.1f}%)")

    # 位置データの標準偏差 (RTK_FIXED のみを対象、なければ全体)
    fixed_indices = [i for i, fix in enumerate(fixes) if fix == 6]
    target_name = "RTK_FIXED 区間"
    target_idx = fixed_indices

    if len(target_idx) < 3:
        target_name = "全記録区間"
        target_idx = [i for i, la in enumerate(lats) if la is not None]

    pts = [(lats[i], lons[i], alts[i]) for i in target_idx if lats[i] is not None and lons[i] is not None]

    if len(pts) >= 3:
        la_ok = [p[0] for p in pts]
        lo_ok = [p[1] for p in pts]
        al_ok = [p[2] for p in pts if p[2] is not None]

        mean_lat = sum(la_ok) / len(la_ok)
        mean_lon = sum(lo_ok) / len(lo_ok)
        mean_alt = sum(al_ok) / len(al_ok) if al_ok else 0.0

        def std(vals, mean):
            return math.sqrt(sum((v - mean) ** 2 for v in vals) / (len(vals) - 1))

        cos_lat = math.cos(math.radians(mean_lat))
        std_lat_m = std(la_ok, mean_lat) * METERS_PER_DEG_LAT
        std_lon_m = std(lo_ok, mean_lon) * (METERS_PER_DEG_LAT * cos_lat)
        std_horiz_m = math.sqrt(std_lat_m ** 2 + std_lon_m ** 2)
        std_alt_m = std(al_ok, mean_alt) if len(al_ok) >= 3 else 0.0

        # 最大水平誤差
        max_horiz_err = 0.0
        for la, lo, _ in pts:
            dx = (lo - mean_lon) * METERS_PER_DEG_LAT * cos_lat
            dy = (la - mean_lat) * METERS_PER_DEG_LAT
            max_horiz_err = max(max_horiz_err, math.hypot(dx, dy))

        print(f"\n  [位置誤差の標準偏差 ({target_name}, {len(pts)} 点)]")
        print(f"  平均緯度 / 経度 : {mean_lat:.7f}, {mean_lon:.7f}")
        print(f"  平均高度 (MSL)  : {mean_alt:.2f} m")
        print(f"  --------------------------------------------------")
        print(f"  🎯 水平標準偏差 (1σ) : {std_horiz_m * 100:.1f} cm ({std_horiz_m:.4f} m)")
        print(f"     - 緯度方向 (1σ)   : {std_lat_m * 100:.1f} cm ({std_lat_m:.4f} m)")
        print(f"     - 経度方向 (1σ)   : {std_lon_m * 100:.1f} cm ({std_lon_m:.4f} m)")
        print(f"  🎯 垂直標準偏差 (1σ) : {std_alt_m * 100:.1f} cm ({std_alt_m:.4f} m)")
        print(f"  最大水平偏位         : {max_horiz_err * 100:.1f} cm ({max_horiz_err:.4f} m)")
    else:
        print("\n  [位置誤差の標準偏差]")
        print("  ※ 有効な位置サンプル数が不足しています。")

    print("=" * 66 + "\n")

def main():
    parser = argparse.ArgumentParser(description="Pixhawk Serial <-> GCS UDP Bridge + RTCM MAVLink Injector + Auto Logger")
    parser.add_argument("--serial", default="/dev/ttyAMA0", help="Pixhawk UART port (default: /dev/ttyAMA0)")
    parser.add_argument("--baud", type=int, default=921600, help="Baudrate (default: 921600)")
    parser.add_argument("--rtscts", action="store_true", default=True, help="Enable RTS/CTS hardware flow control (default: True)")
    parser.add_argument("--no-rtscts", action="store_false", dest="rtscts", help="Disable RTS/CTS hardware flow control")
    parser.add_argument("--target-host", default="100.80.225.4", help="Mac GCS Tailscale IP")
    parser.add_argument("--target-port", type=int, default=14550, help="GCS UDP port (default: 14550)")
    parser.add_argument("--rtcm-host", default="100.80.225.4", help="RTK Base Station TCP host")
    parser.add_argument("--rtcm-port", type=int, default=2101, help="RTK Base Station TCP port (default: 2101)")
    parser.add_argument("--log-dir", default="logs", help="Directory to save .rtcm3 and .csv logs")
    parser.add_argument("--auto-fix-fs", action="store_true", help="FS_GCS_ENABLE が 1 の場合に自動で 0 に設定する")
    args = parser.parse_args()

    # ログ保存先準備
    Path(args.log_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(args.log_dir, f"rtk_status_{ts}.csv")
    rtcm_path = os.path.join(args.log_dir, f"rtcm_rover_{ts}.rtcm3")

    csv_file = open(csv_path, "w", newline="")
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(["utc_time", "elapsed_sec", "fix_type", "fix_name", "sats", "lat", "lon", "alt", "eph", "epv"])
    csv_file.flush()

    rtcm_file = open(rtcm_path, "wb")

    print("=" * 66)
    print("  🚀 MAVLink Bridge + RTCM Injector + Realtime Logger")
    print("=" * 66)
    print(f"  Pixhawk Serial : {args.serial} @ {args.baud} bps (RTS/CTS: {args.rtscts})")
    print(f"  Mac GCS Target : {args.target_host}:{args.target_port} (UDP)")
    print(f"  Base Station   : {args.rtcm_host}:{args.rtcm_port} (TCP)")
    print(f"  📝 RTK CSVログ : {csv_path}")
    print(f"  📦 RTCM3 生ログ: {rtcm_path}")
    print("=" * 66)

    try:
        ser = serial.Serial(args.serial, args.baud, timeout=1.0, rtscts=args.rtscts)
    except Exception as e:
        print(f"[ERROR] Failed to open serial port {args.serial}: {e}")
        csv_file.close()
        rtcm_file.close()
        sys.exit(1)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", 0))

    mav_send = mavutil.mavlink.MAVLink(None, srcSystem=255, srcComponent=0)
    mav_parser = mavutil.mavlink.MAVLink(None)

    serial_lock = threading.Lock()
    start_time = time.time()
    last_log_time = 0.0

    # 起動時フェイルセーフ確認フラグ
    fs_checked = False

    def request_param(name: str):
        msg = mav_send.param_request_read_encode(1, 1, name.encode('ascii'), -1)
        with serial_lock:
            ser.write(msg.pack(mav_send))

    # 1. Serial -> UDP (Pixhawk -> Mac GCS) + Parse GPS_RAW_INT & PARAM_VALUE
    def serial_to_udp():
        nonlocal last_log_time, fs_checked
        target = (args.target_host, args.target_port)
        req_sent = False

        while True:
            try:
                # 起動後 1 秒待ってパラメータ要求
                if not req_sent and time.time() - start_time > 1.0:
                    request_param("FS_GCS_ENABLE")
                    req_sent = True

                data = ser.read(ser.in_waiting or 1)
                if data:
                    sock.sendto(data, target)
                    for b in data:
                        try:
                            msg = mav_parser.parse_char(bytes([b]))
                            if not msg:
                                continue
                            mtype = msg.get_type()

                            if mtype == 'GPS_RAW_INT':
                                now = time.time()
                                if now - last_log_time >= 1.0:
                                    last_log_time = now
                                    lat = msg.lat / 1e7
                                    lon = msg.lon / 1e7
                                    alt = msg.alt / 1000.0
                                    fix_type = msg.fix_type
                                    fix_name = FIX_NAMES.get(fix_type, f"FIX_{fix_type}")
                                    sats = msg.satellites_visible
                                    eph = msg.eph / 100.0 if msg.eph != 65535 else None
                                    epv = msg.epv / 100.0 if msg.epv != 65535 else None
                                    elapsed = round(now - start_time, 2)
                                    utc_str = datetime.now().strftime("%H:%M:%S")

                                    csv_writer.writerow([utc_str, elapsed, fix_type, fix_name, sats, lat, lon, alt, eph, epv])
                                    csv_file.flush()

                            elif mtype == 'PARAM_VALUE' and not fs_checked:
                                pid = msg.param_id
                                if pid == 'FS_GCS_ENABLE' or pid.startswith('FS_GCS_ENABLE'):
                                    val = int(msg.param_value)
                                    fs_checked = True
                                    if val == 0:
                                        print(f"\n🛡️ [SAFETY CHECK] FS_GCS_ENABLE = 0 (OK: 通信断でもプロポ操縦を維持)")
                                    else:
                                        print(f"\n⚠️ [SAFETY WARNING] FS_GCS_ENABLE = {val}! 通信断でRTL/着陸が発動します。")
                                        if args.auto_fix_fs:
                                            print("[SAFETY] --auto-fix-fs が指定されたため 0 に自動変更します...")
                                            set_msg = mav_send.param_set_encode(1, 1, b"FS_GCS_ENABLE", 0.0, mavutil.mavlink.MAV_PARAM_TYPE_REAL32)
                                            with serial_lock:
                                                ser.write(set_msg.pack(mav_send))
                                        else:
                                            print("[SAFETY] 0 に変更するには: python3 mavlink_param.py --set FS_GCS_ENABLE 0 を実行してください。\n")
                        except Exception:
                            pass
            except Exception as e:
                print(f"[Serial Error] {e}")
                time.sleep(0.1)

    # 2. UDP -> Serial (Mac GCS -> Pixhawk)
    def udp_to_serial():
        while True:
            try:
                data, addr = sock.recvfrom(4096)
                if data:
                    with serial_lock:
                        ser.write(data)
            except Exception as e:
                print(f"[UDP Error] {e}")
                time.sleep(0.1)

    # 3. TCP RTCM -> MAVLink GPS_RTCM_DATA -> Serial (Base -> Pixhawk) + Write .rtcm3
    def rtcm_tcp_to_mavlink():
        seq = 0
        injected_frames = 0
        MAX_SIZE = 180
        MAX_FRAGS = 4

        while True:
            try:
                print(f"[RTCM] Connecting to Base Station {args.rtcm_host}:{args.rtcm_port}...")
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_sock:
                    tcp_sock.settimeout(5.0)
                    tcp_sock.connect((args.rtcm_host, args.rtcm_port))
                    print(f"[RTCM] Connected! Starting MAVLink injection & logging...")
                    buf = bytearray()
                    while True:
                        chunk = tcp_sock.recv(4096)
                        if not chunk:
                            print("[RTCM] Connection closed by server.")
                            break
                        buf.extend(chunk)
                        for frame in extract_rtcm_frames(buf):
                            rtcm_file.write(frame)
                            rtcm_file.flush()

                            frame_len = len(frame)
                            if frame_len <= MAX_SIZE:
                                flags = (seq << 3) | 0
                                data = list(frame) + [0] * (MAX_SIZE - frame_len)
                                msg = mav_send.gps_rtcm_data_encode(flags, frame_len, data)
                                with serial_lock:
                                    ser.write(msg.pack(mav_send))
                            else:
                                nfrags = (frame_len + MAX_SIZE - 1) // MAX_SIZE
                                if nfrags <= MAX_FRAGS:
                                    for fid in range(nfrags):
                                        start = fid * MAX_SIZE
                                        end = min(start + MAX_SIZE, frame_len)
                                        fchunk = frame[start:end]
                                        flen = len(fchunk)
                                        flags = (seq << 3) | (fid << 1) | 1
                                        data = list(fchunk) + [0] * (MAX_SIZE - flen)
                                        msg = mav_send.gps_rtcm_data_encode(flags, flen, data)
                                        with serial_lock:
                                            ser.write(msg.pack(mav_send))
                                        time.sleep(0.003)
                            seq = (seq + 1) % 32
                            injected_frames += 1
                            if injected_frames % 50 == 1:
                                print(f"[RTCM Injected] Total {injected_frames} frames -> Pixhawk TELEM1 (Saved to .rtcm3)")
            except Exception as e:
                print(f"[RTCM Warning] {e}. Reconnecting in 3s...")
                time.sleep(3.0)

    t1 = threading.Thread(target=serial_to_udp, daemon=True)
    t2 = threading.Thread(target=udp_to_serial, daemon=True)
    t3 = threading.Thread(target=rtcm_tcp_to_mavlink, daemon=True)
    t1.start()
    t2.start()
    t3.start()

    print("[Bridge] Running! Press Ctrl+C when finished to view statistics.")
    try:
        t1.join()
    except KeyboardInterrupt:
        print("\n[Bridge] Stopping...")
    finally:
        csv_file.close()
        rtcm_file.close()
        ser.close()
        sock.close()
        print_statistics(csv_path)

if __name__ == "__main__":
    main()
