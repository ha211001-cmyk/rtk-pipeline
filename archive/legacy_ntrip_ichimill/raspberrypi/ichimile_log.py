#!/usr/bin/env python3
"""
イチミル (ntrip.ales-corp.co.jp) 接続用シンプルRTK検証プログラム
/dev/ttyACM0 の F9P とシリアル通信し、NTRIPサーバーとRTK補正データをやり取りします。
【Raspberry Pi 5 対応版】
"""

import sys
import time
import socket
import base64
import serial
import threading
import os
import csv
import datetime
from serial.tools import list_ports
from pynmeagps import NMEAReader
from pyubx2 import UBXReader
import numpy as np

# イチミルの接続情報
SERVER = "ntrip.ales-corp.co.jp"
PORT = 2101
MOUNTPOINT = "RTCM32MSM7"  # F9P推奨。もし繋がらなければ RTCM31 に変更
USER = "6y8swddj"
PASS = "xxu2w5"
BAUD = 38400
# Raspberry Pi では F9P は通常 /dev/ttyACM0 として認識される
# USB-シリアル変換アダプタ使用時は /dev/ttyUSB0 の場合もある
SERIAL_PORT = "/dev/ttyACM0"

connected = True


def set_gga_rate_5hz(ser):
    """F9PのGGA出力周期を5Hzに設定 (UBXプロトコル)"""
    # UBX-CFG-MSG (GGA, rate=5) コマンド (UART1)
    ubx_cfg_msg = bytes.fromhex('B562060108 00F00005000000000823'.replace(' ', ''))
    ser.write(ubx_cfg_msg)
    print("GGA出力周期を5Hzに設定コマンド送信")
    time.sleep(0.2)


def ntrip_to_serial(sock, ser):
    """NTRIPから受け取ったRTCMデータをシリアル(F9P)へ流し込む"""
    global connected
    print("[NTRIP] 受信スレッド開始")
    while connected:
        try:
            data = sock.recv(4096)
            if data:
                ser.write(data)
            else:
                print("[NTRIP] サーバーから切断されました")
                connected = False
                break
        except Exception as e:
            if connected:
                print(f"[NTRIP Error] {e}")
                connected = False
            break


def format_fix(quality):
    mapping = {
        0: 'No Fix (未測位)',
        1: 'GPS Fix (単独測位)',
        2: 'DGPS (ディファレンシャル)',
        4: 'RTK Fixed (RTK固定解 - cm精度!)',
        5: 'RTK Float (RTK浮動解 - 10~20cm)'
    }
    return mapping.get(quality, f"Unknown ({quality})")


def serial_to_ntrip(sock, ser, csvfile=None):
    """F9PからのNMEA/UBXを解析し、GGAメッセージをNTRIP(VRS)へ送信する"""
    global connected
    print("[F9P] データ受信およびGGA送信スレッド開始")

    last_gga_send = 0
    cnt_gga = 0
    gga_times = []
    lat_history = []
    lon_history = []
    alt_history = []
    csv_writer = None

    if csvfile is not None:
        csv_writer = csv.writer(csvfile, lineterminator='\n')
        csv_writer.writerow(["timestamp", "lat", "lon", "alt", "status"])

    while connected:
        try:
            line = ser.readline()
            if not line:
                continue

            if line.startswith(b'$') and b'GGA' in line:
                now = time.time()
                gga_times.append(now)
                gga_times = [t for t in gga_times if now - t < 1.0]

                try:
                    line_str = line.decode('ascii', errors='ignore').strip()
                    parts = line_str.split(',')
                    if len(parts) > 6:
                        lat = parts[2]
                        lon = parts[4]
                        alt = parts[9] if len(parts) > 9 else ''
                        if lat and lon:
                            lat_deg = float(lat[:2]) + float(lat[2:]) / 60.0
                            lon_deg = float(lon[:3]) + float(lon[3:]) / 60.0
                        else:
                            lat_deg, lon_deg = 0.0, 0.0
                        try:
                            alt_m = float(alt)
                        except Exception:
                            alt_m = 0.0

                        quality = int(parts[6]) if parts[6].isdigit() else 0
                        sats = parts[7]
                        hz_count = len(gga_times)

                        lat_history.append((now, lat_deg))
                        lon_history.append((now, lon_deg))
                        alt_history.append((now, alt_m))
                        lat_history = [item for item in lat_history if now - item[0] < 10.0]
                        lon_history = [item for item in lon_history if now - item[0] < 10.0]
                        alt_history = [item for item in alt_history if now - item[0] < 10.0]

                        lat_vals = [item[1] for item in lat_history]
                        lon_vals = [item[1] for item in lon_history]
                        alt_vals = [item[1] for item in alt_history]
                        lat_std = np.std(lat_vals) if len(lat_vals) > 1 else 0.0
                        lon_std = np.std(lon_vals) if len(lon_vals) > 1 else 0.0
                        alt_std = np.std(alt_vals) if len(alt_vals) > 1 else 0.0
                        lat_std_m = lat_std * 111000
                        mean_lat = np.mean(lat_vals) if len(lat_vals) > 0 else lat_deg
                        lon_std_m = lon_std * 111000 * np.cos(np.radians(mean_lat))
                        alt_std_m = alt_std

                        print(
                            f"[GPS] 緯度:{lat_deg:.7f} 経度:{lon_deg:.7f} 高度:{alt_m:.3f}m"
                            f" | 状態: {format_fix(quality):<20}"
                            f" | 衛星数: {sats}"
                            f" | [Hz計測: {hz_count} msg/s]"
                            f" | [10秒間 標準偏差] 緯度:{lat_std_m:.3f}m 経度:{lon_std_m:.3f}m 高度:{alt_std_m:.3f}m"
                        )

                        if csv_writer is not None:
                            status_simple = "RTKFixed" if quality == 4 else "Other"
                            csv_writer.writerow([now, lat_deg, lon_deg, alt_m, status_simple])
                            csvfile.flush()

                except Exception:
                    pass

                # 5秒に1回、GGAをNTRIPサーバーに送信（VRS方式に必須）
                if now - last_gga_send > 5.0:
                    sock.sendall(line)
                    cnt_gga += 1
                    last_gga_send = now

        except serial.SerialException as e:
            # デバイス一時不応答は無視してリトライ
            if "returned no data" in str(e):
                time.sleep(0.05)
                continue
            if connected:
                print(f"[Serial Error] {e}")
                connected = False
            break
        except Exception as e:
            if connected:
                print(f"[Serial Error] {e}")
                connected = False
            break


def main():
    global connected
    print("=== イチミル RTK 確認プログラム [Raspberry Pi 5版] ===")
    print(f"対象ポート: {SERIAL_PORT}")
    print(f"サーバー: {SERVER}:{PORT} / {MOUNTPOINT}")

    # CSVファイル名自動生成（スクリプトと同じディレクトリの log/ に保存）
    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(script_dir, "log")
    os.makedirs(log_dir, exist_ok=True)
    dtstr = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_filename = os.path.join(log_dir, f"gpslog_{dtstr}.csv")
    csvfile = open(csv_filename, "w", encoding="utf-8", newline="")

    # 1. シリアルポート(rtk-pipeline)のオープン
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD, timeout=0.5)
        print(f"✓ F9Pに接続しました ({SERIAL_PORT})")
        set_gga_rate_5hz(ser)
    except Exception as e:
        print(f"✗ F9Pポート({SERIAL_PORT})のオープンに失敗しました: {e}")
        print("ヒント: ls /dev/ttyACM* または ls /dev/ttyUSB* でポートを確認してください")
        print("       sudo usermod -aG dialout $USER でシリアルポート権限を付与できます")
        csvfile.close()
        return

    # 2. NTRIPサーバーへの接続
    try:
        print(f"NTRIPサーバーへ接続中... ({SERVER}:{PORT})")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((SERVER, PORT))
        sock.settimeout(None)
        print(f"✓ NTRIPサーバーに接続しました ({SERVER})")

        auth_bytes = f"{USER}:{PASS}".encode('utf-8')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')

        req = (
            f"GET /{MOUNTPOINT} HTTP/1.0\r\n"
            f"Host: {SERVER}:{PORT}\r\n"
            f"Ntrip-Version: Ntrip/1.0\r\n"
            f"User-Agent: NTRIP SimpleRTK/1.0\r\n"
            f"Authorization: Basic {auth_b64}\r\n"
            f"Accept: */*\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        )
        sock.sendall(req.encode('ascii'))

        head = sock.recv(1024)
        print("[NTRIP] サーバー応答:")
        print(head.decode('ascii', errors='ignore').strip())

        if b"200 OK" not in head and b"ICY 200" not in head:
            print("✗ NTRIPサーバーから正常なレスポンスが得られませんでした。")
            connected = False
            ser.close()
            csvfile.close()
            return

        print("✓ NTRIPマウントされた。RTCM配信待機状態になりました。")

    except socket.timeout:
        print(f"✗ NTRIPサーバー({SERVER}:{PORT})への接続がタイムアウトしました（10秒）")
        print("\n  【原因と対処】")
        print("  1. ルーターがポート2101のアウトバウンドをブロックしている")
        print("     → ルーター管理画面 http://192.168.11.1 でアウトバウンドポート2101を許可")
        print("  2. ISPがポート2101を制限している → ISPに問い合わせ")
        print("  3. スマホのテザリング(モバイル回線)でラズパイを接続してテスト")
        ser.close()
        csvfile.close()
        return
    except Exception as e:
        print(f"✗ NTRIP接続エラー: {type(e).__name__}: {e}")
        ser.close()
        csvfile.close()
        return

    # 3. データ送受信スレッドの開始
    t_rx = threading.Thread(target=ntrip_to_serial, args=(sock, ser), daemon=True)
    t_tx = threading.Thread(target=serial_to_ntrip, args=(sock, ser, csvfile), daemon=True)

    t_rx.start()
    t_tx.start()

    try:
        while connected:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[User] Ctrl+C が押されました。終了します。")
        connected = False

    finally:
        sock.close()
        ser.close()
        csvfile.close()
        print("✓ 切断処理完了")
        print(f"✓ CSVファイルに保存しました: {csv_filename}")


if __name__ == "__main__":
    main()
