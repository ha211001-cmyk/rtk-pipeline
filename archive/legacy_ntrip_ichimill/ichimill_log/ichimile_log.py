#!/usr/bin/env python3
"""
イチミル (ntrip.ales-corp.co.jp) 接続用シンプルRTK検証プログラム【macOS 対応版】

Mac に USB 直結した F9P（/dev/cu.usbmodem* など）とシリアル通信し、
イチミルの NTRIP サーバーから RTCM3 補正データを受信して F9P へ流し込みます。
F9P の NMEA GGA を解析して RTK Float / Fixed 状態を表示・CSV 記録します。

使い方:
    python3 macos/ichimile_log.py
    python3 macos/ichimile_log.py --port /dev/cu.usbmodem112301 --max-duration 600
"""

import argparse
import base64
import csv
import datetime
import glob
import os
import socket
import sys
import threading
import time

import serial
from pyubx2 import UBXMessage


# イチミルの接続情報
SERVER = "ntrip.ales-corp.co.jp"
PORT = 2101
MOUNTPOINT = "RTCM32MSM7"  # F9P推奨。もし繋がらなければ RTCM31 に変更
USER = "6y8swddj"
PASS = "xxu2w5"
BAUD = 38400

connected = True


def parse_args():
    p = argparse.ArgumentParser(
        description="イチミルNTRIP → F9P注入 → RTK状態表示・ログ記録（macOS版）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--port", default=None,
                   help="F9Pのシリアルポート（省略時は自動検出）")
    p.add_argument("--baudrate", type=int, default=BAUD,
                   help="F9Pのボーレート")
    p.add_argument("--mountpoint", default=MOUNTPOINT,
                   help="NTRIPマウントポイント")
    p.add_argument("--max-duration", type=int, default=600,
                   help="RTK Fixed 未達時の最大実行秒数（到達時は自動終了）")
    p.add_argument("--post-fix-duration", type=int, default=10,
                   help="RTK Fixed 到達後、安定解を記録する追加秒数")
    return p.parse_args()


def detect_serial_port():
    """F9P のシリアルポートを自動検出する（macOS / Linux 対応）"""
    for pat in ("/dev/cu.usbmodem*", "/dev/tty.usbmodem*",
                "/dev/ttyACM*", "/dev/ttyUSB*"):
        m = sorted(glob.glob(pat))
        if m:
            return m[0]
    return None


def configure_rover(ser):
    """F9P を移動局（Rover）モードに設定する

    - TMODE3 無効化（基地局モード解除）
    - NMEA GGA / RMC を USB ポートへ出力（1Hz）
    """
    cfg = [
        ("CFG_TMODE_MODE", 0),                # 基地局モード解除
        ("CFG_USBOUTPROT_NMEA", 1),           # USB への NMEA 出力許可
        ("CFG_MSGOUT_NMEA_ID_GGA_USB", 1),    # GGA を USB に 1Hz 出力
        ("CFG_MSGOUT_NMEA_ID_RMC_USB", 1),    # RMC を USB に 1Hz 出力
        ("CFG_USBINPROT_RTCM3X", 1),          # USB からの RTCM3 入力許可（補正受信用）
    ]
    try:
        ser.write(UBXMessage.config_set(1, 0, cfg).serialize())
        ser.flush()
        print("[OK] TMODE3解除 + NMEA GGA/RMC 有効化（Rover モード）")
    except Exception as e:
        print(f"[WARN] Rover 設定に失敗しました（続行します）: {e}")
    time.sleep(0.5)


def extract_rtcm_frames(buf):
    """バッファから RTCM3 フレーム（0xD3 始まり）を1つずつ取り出す"""
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


RTCM_NAMES = {
    1005: "Station ARP", 1006: "Station ARP+AH", 1033: "Rx/Ant Descr",
    1074: "GPS MSM4", 1075: "GPS MSM5", 1077: "GPS MSM7",
    1084: "GLO MSM4", 1085: "GLO MSM5", 1087: "GLO MSM7",
    1094: "GAL MSM4", 1095: "GAL MSM5", 1097: "GAL MSM7",
    1114: "QZSS MSM4", 1115: "QZSS MSM5", 1117: "QZSS MSM7",
    1124: "BDS MSM4", 1125: "BDS MSM5", 1127: "BDS MSM7",
    1230: "GLO Bias",
}


def ntrip_to_serial(sock, ser, stats=None, rtcmfile=None):
    """NTRIPから受け取ったRTCMデータをシリアル(F9P)へ流し込み、同時にRTCMログを記録する"""
    global connected
    print("[NTRIP] 受信スレッド開始")
    last_report = time.time()
    buf = bytearray()
    while connected:
        try:
            data = sock.recv(4096)
            if data:
                ser.write(data)   # F9P へ即時注入（低遅延）
                buf.extend(data)

                # 完全なRTCM3フレームを抽出してログ保存 + タイプ集計
                for frame in extract_rtcm_frames(buf):
                    msg_type = (frame[3] << 4) | (frame[4] >> 4)
                    if rtcmfile is not None:
                        rtcmfile.write(frame)
                    if stats is not None:
                        stats["rtcm_bytes"] += len(frame)
                        stats["rtcm_frames"] += 1
                        stats["msg_types"][msg_type] = stats["msg_types"].get(msg_type, 0) + 1
                if rtcmfile is not None:
                    rtcmfile.flush()

                if stats is not None and time.time() - last_report >= 5.0:
                    print(f"[NTRIP] RTCM受信: {stats['rtcm_frames']} frame / "
                          f"{stats['rtcm_bytes']} bytes")
                    last_report = time.time()
            else:
                print("[NTRIP] サーバーから切断されました")
                connected = False
                break
        except Exception as e:
            if connected:
                print(f"[NTRIP Error] {e}")
                connected = False
            break
    print("[NTRIP] 受信スレッド終了")


def format_fix(quality):
    """GGA の quality 値を分かりやすい文字列に変換する"""
    mapping = {
        0: 'No Fix (未測位)',
        1: 'GPS Fix (単独測位)',
        2: 'DGPS (ディファレンシャル)',
        4: 'RTK Fixed (RTK固定解 - cm精度!)',
        5: 'RTK Float (RTK浮動解 - 10~20cm)',
    }
    return mapping.get(quality, f"Unknown ({quality})")


def fix_label(quality):
    """CSV記録用の英語ラベル"""
    mapping = {0: 'NO_FIX', 1: 'GPS_FIX', 2: 'DGPS', 4: 'RTK_FIXED', 5: 'RTK_FLOAT'}
    return mapping.get(quality, f"UNKNOWN_{quality}")


def serial_to_ntrip(sock, ser, csvfile=None, fix_event=None):
    """F9PからのGGAを解析し、表示・CSV記録・GGA送信(VRS)を行う"""
    global connected
    print("[F9P] データ受信およびGGA送信スレッド開始")

    last_gga_send = 0.0
    last_show = 0.0
    csv_writer = None
    if csvfile is not None:
        csv_writer = csv.writer(csvfile, lineterminator='\n')
        csv_writer.writerow(["timestamp", "lat", "lon", "alt_m", "quality", "status"])

    while connected:
        try:
            line = ser.readline()
            if not line:
                continue

            if line.startswith(b'$') and b'GGA' in line:
                now = time.time()

                try:
                    line_str = line.decode('ascii', errors='ignore').strip()
                    parts = line_str.split(',')
                    if len(parts) > 9:
                        lat_raw = parts[2]
                        lon_raw = parts[4]
                        alt = parts[9] if len(parts) > 9 else ''
                        if lat_raw and lon_raw:
                            lat_deg = float(lat_raw[:2]) + float(lat_raw[2:]) / 60.0
                            lon_deg = float(lon_raw[:3]) + float(lon_raw[3:]) / 60.0
                        else:
                            lat_deg, lon_deg = 0.0, 0.0
                        try:
                            alt_m = float(alt)
                        except Exception:
                            alt_m = 0.0

                        quality = int(parts[6]) if parts[6].isdigit() else 0
                        sats = parts[7]

                        # コンソール表示は1Hzに間引く
                        if now - last_show >= 1.0:
                            last_show = now
                            print(f"[GPS] 緯度:{lat_deg:.7f} 経度:{lon_deg:.7f} "
                                  f"高度:{alt_m:.3f}m | 状態: {format_fix(quality):<30} "
                                  f"| 衛星数: {sats}")

                        # CSVに記録（全GGA）
                        if csv_writer is not None:
                            csv_writer.writerow([now, lat_deg, lon_deg, alt_m,
                                                 quality, fix_label(quality)])
                            csvfile.flush()

                        # RTK Fixed 到達を通知
                        if quality == 4 and fix_event is not None:
                            fix_event.set()

                except Exception:
                    pass

                # 5秒に1回、GGAをNTRIPサーバーに送信する（VRS方式に必須）
                if now - last_gga_send > 5.0:
                    sock.sendall(line)
                    last_gga_send = now

        except Exception as e:
            if connected:
                print(f"[Serial Error] {e}")
                connected = False
            break
    print("[F9P] 受信スレッド終了")


def main():
    global connected
    args = parse_args()

    port = args.port or detect_serial_port()
    if not port:
        print("[ERR] F9Pのシリアルポートを検出できませんでした")
        print("      --port /dev/cu.usbmodemXXXX で明示指定してください")
        sys.exit(1)

    print("=== イチミル RTK 確認プログラム [macOS版] ===")
    print(f"対象ポート: {port}")
    print(f"サーバー: {SERVER}:{PORT} / {args.mountpoint}")

    # CSVファイル名自動生成（macos/log/ に保存）
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(script_dir, "log")
    os.makedirs(log_dir, exist_ok=True)
    dtstr = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_filename = os.path.join(log_dir, f"gpslog_{dtstr}.csv")
    csvfile = open(csv_filename, "w", encoding="utf-8", newline="")
    rtcm_filename = os.path.join(log_dir, f"rtcm_{dtstr}.rtcm3")

    # 1. シリアルポート(EVK-F9P)のオープン
    try:
        ser = serial.Serial(port, args.baudrate, timeout=0.5)
        print(f"[OK] F9Pに接続しました ({port})")
        configure_rover(ser)
    except Exception as e:
        print(f"[ERR] F9Pポート({port})のオープンに失敗しました: {e}")
        csvfile.close()
        sys.exit(1)

    # 2. NTRIPサーバーへの接続
    try:
        print(f"NTRIPサーバーへ接続中... ({SERVER}:{PORT})")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((SERVER, PORT))
        print(f"[OK] NTRIPサーバーに接続しました ({SERVER})")

        auth_bytes = f"{USER}:{PASS}".encode('utf-8')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')

        req = (
            f"GET /{args.mountpoint} HTTP/1.0\r\n"
            f"Host: {SERVER}:{PORT}\r\n"
            f"Ntrip-Version: Ntrip/1.0\r\n"
            f"User-Agent: NTRIP SimpleRTK/1.0\r\n"
            f"Authorization: Basic {auth_b64}\r\n"
            f"Accept: */*\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        )
        sock.sendall(req.encode('ascii'))

        # ヘッダ受信はタイムアウト付き（その後は RTCM 受信用にブロッキングへ戻す）
        sock.settimeout(10)
        head = sock.recv(1024)
        print("[NTRIP] サーバー応答:")
        print(head.decode('ascii', errors='ignore').strip())

        if b"200 OK" not in head and b"ICY 200" not in head:
            print("[ERR] NTRIPサーバーから正常なレスポンスが得られませんでした。")
            connected = False
            ser.close()
            csvfile.close()
            sys.exit(1)

        sock.settimeout(None)
        print("[OK] NTRIPマウントされた。RTCM配信待機状態になりました。")

    except socket.timeout:
        print(f"[ERR] NTRIPサーバー({SERVER}:{PORT})への接続がタイムアウトしました（10秒）")
        print("\n  【原因と対処】")
        print("  1. ルーターがポート2101のアウトバウンドをブロックしている")
        print("  2. ISPがポート2101を制限している")
        print("  3. スマホのテザリング(モバイル回線)でテスト")
        ser.close()
        csvfile.close()
        sys.exit(1)
    except Exception as e:
        print(f"[ERR] NTRIP接続エラー: {type(e).__name__}: {e}")
        ser.close()
        csvfile.close()
        sys.exit(1)

    # 3. データ送受信スレッドの開始
    fix_event = threading.Event()
    stats = {"rtcm_bytes": 0, "rtcm_frames": 0, "msg_types": {}}
    rtcmfile = open(rtcm_filename, "wb")
    t_rx = threading.Thread(target=ntrip_to_serial, args=(sock, ser, stats, rtcmfile), daemon=True)
    t_tx = threading.Thread(target=serial_to_ntrip, args=(sock, ser, csvfile, fix_event), daemon=True)

    t_rx.start()
    t_tx.start()

    start_time = time.time()
    fix_time = None
    print(f"[INFO] 観測開始（RTK Fixed 到達後 {args.post_fix_duration}秒で自動終了 / "
          f"上限 {args.max_duration}秒）")

    try:
        while connected:
            if fix_event.is_set():
                if fix_time is None:
                    fix_time = time.time()
                    print("\n" + "=" * 60)
                    print("[RTK] ★★★ RTK FIXED 到達しました！ ★★★")
                    print(f"      （安定した Fixed 解を記録するため {args.post_fix_duration}秒継続）")
                    print("=" * 60)
                if time.time() - fix_time >= args.post_fix_duration:
                    break
            elapsed = time.time() - start_time
            if elapsed >= args.max_duration:
                print("\n" + "=" * 60)
                print(f"[RTK] {args.max_duration}秒経過。RTK Fixed は未達でした。")
                print("      （現在の状態はCSVログに記録済み）")
                print("=" * 60)
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[User] Ctrl+C が押されました。終了します。")

    finally:
        connected = False
        time.sleep(0.5)  # スレッド停止猶予
        try:
            sock.close()
        except Exception:
            pass
        try:
            ser.close()
        except Exception:
            pass
        try:
            csvfile.close()
        except Exception:
            pass
        try:
            rtcmfile.close()
        except Exception:
            pass
        print("[OK] 切断処理完了")
        if 'stats' in locals():
            print(f"[INFO] NTRIP RTCM受信: {stats['rtcm_frames']} frame / "
                  f"{stats['rtcm_bytes']} bytes")
            if stats["msg_types"]:
                print("[INFO] RTCMメッセージタイプ内訳:")
                for t in sorted(stats["msg_types"]):
                    name = RTCM_NAMES.get(t, "Unknown")
                    print(f"       Type {t:5d} {name:16s} = {stats['msg_types'][t]} frame")
        print(f"[OK] CSVファイルに保存しました: {csv_filename}")
        if 'rtcmfile' in locals():
            print(f"[OK] RTCMファイルに保存しました: {rtcm_filename}")


if __name__ == "__main__":
    main()
