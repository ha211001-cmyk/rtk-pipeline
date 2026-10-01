def set_gga_rate_5hz(ser):  
    """F9PのGGA出力周期を5Hzに設定 (UBXプロトコル)"""
    # UBX-CFG-MSG (GGA, rate=5) コマンド (UART1)
    # UBXパケット: B5 62 06 01 08 00 F0 00 05 00 00 00 00 00 08 23
    ubx_cfg_msg = bytes.fromhex('B5 62 06 01 08 00 F0 00 05 00 00 00 00 00 08 23')
    ser.write(ubx_cfg_msg)
    print("GGA出力周期を5Hzに設定コマンド送信")
    time.sleep(0.2)
#!/usr/bin/env python3
"""
イチミル (ntrip.ales-corp.co.jp) 接続用シンプルRTK検証プログラム
COM6 の F9P とシリアル通信し、NTRIPサーバーとRTK補正データをやり取りします。
"""


import sys
import time
import socket
import base64
import serial
import struct
import threading
from serial.tools import list_ports
from pynmeagps import NMEAReader
from pyubx2 import UBXReader
import numpy as np
import csv
import datetime

def ubx_checksum(data):
    """UBXチェックサム計算"""
    ck_a = ck_b = 0
    for b in data:
        ck_a = (ck_a + b) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return bytes([ck_a, ck_b])

def make_ubx(cls, msg_id, payload):
    """UBXパケット生成"""
    inner = bytes([cls, msg_id]) + struct.pack('<H', len(payload)) + payload
    return bytes([0xB5, 0x62]) + inner + ubx_checksum(inner)

def reset_tmode3(ser):
    """TMODE3をDisabledにリセット（基地局モード解除）"""
    payload = struct.pack('<BBHiiibbbBIIIII', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    pkt = make_ubx(0x06, 0x71, payload)
    ser.reset_input_buffer()
    ser.write(pkt)
    time.sleep(0.5)
    buf = ser.read(ser.in_waiting)
    if b'\xB5\x62\x05\x01' in buf:
        print("[OK] TMODE3 reset to Disabled (Rover mode)")
    else:
        print("[WARN] TMODE3 reset ACK not found, continuing anyway")

# イチミルの接続情報


SERVER = "ntrip.ales-corp.co.jp"
PORT = 2101
MOUNTPOINT = "RTCM32MSM7"  # F9P推奨。もし繋がらなければ RTCM31 に変更
USER = "6y8swddj"
PASS = "xxu2w5"
BAUD = 38400
COM_PORT = "COM7"



connected = True

def ntrip_to_serial(sock, ser):
    """NTRIPから受け取ったRTCMデータをシリアル(F9P)へ流し込む"""
    global connected
    print("[NTRIP] 受信スレッド開始")
    while connected:
        try:
            # サーバーからRTCMデータを受信
            data = sock.recv(4096)
            if data:
                # F9Pへ流し込む
                ser.write(data)
                # print(f"[NTRIP->F9P] 送信: {len(data)} bytes")
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
    mapping = {0: 'No Fix (未測位)', 1: 'GPS Fix (単独測位)', 2: 'DGPS (ディファレンシャル)', 4: 'RTK Fixed (RTK固定解 - cm精度!)', 5: 'RTK Float (RTK浮動解 - 10~20cm)'}
    return mapping.get(quality, f"Unknown ({quality})")

def serial_to_ntrip(sock, ser, csvfile=None):
    """F9PからのNMEA/UBXを解析し、GGAメッセージをNTRIP(VRS)へ送信する"""
    global connected
    print("[F9P] データ受信およびGGA送信スレッド開始")
    
    last_gga_send = 0
    cnt_gga = 0
    last_status_print = 0
    
    # 時間計測用
    gga_times = []  # GGA受信時刻のリスト
    # 標準偏差計算用
    lat_history = []  # (時刻, 緯度)
    lon_history = []  # (時刻, 経度)
    alt_history = []  # (時刻, 高度)
    csv_writer = None
    if csvfile is not None:
        csv_writer = csv.writer(csvfile, lineterminator='\n')
        csv_writer.writerow(["timestamp", "lat", "lon", "alt", "status"])
    
    while connected:
        try:
            line = ser.readline()
            if not line:
                continue
            
            # GGAメッセージを探してVRSサーバーに送る
            if line.startswith(b'$') and b'GGA' in line:
                now = time.time()
                
                # 時間計測用：GGA受信時刻を記録
                gga_times.append(now)
                # 直近1秒以内のGGA受信データのみを保持
                gga_times = [t for t in gga_times if now - t < 1.0]
                
                try:
                    line_str = line.decode('ascii', errors='ignore').strip()
                    parts = line_str.split(',')
                    if len(parts) > 6:
                        # 緯度・経度・高度のパース
                        lat = parts[2]
                        lon = parts[4]
                        alt = parts[9] if len(parts) > 9 else ''
                        if lat and lon:
                            lat_deg = float(lat[:2]) + float(lat[2:])/60.0
                            lon_deg = float(lon[:3]) + float(lon[3:])/60.0
                        else:
                            lat_deg, lon_deg = 0.0, 0.0
                        try:
                            alt_m = float(alt)
                        except Exception:
                            alt_m = 0.0

                        quality = int(parts[6]) if parts[6].isdigit() else 0
                        sats = parts[7]

                        hz_count = len(gga_times)
                        # 標準偏差用履歴に追加
                        lat_history.append((now, lat_deg))
                        lon_history.append((now, lon_deg))
                        alt_history.append((now, alt_m))
                        # 直近10秒間のみ保持
                        lat_history = [item for item in lat_history if now - item[0] < 10.0]
                        lon_history = [item for item in lon_history if now - item[0] < 10.0]
                        alt_history = [item for item in alt_history if now - item[0] < 10.0]
                        # 標準偏差計算
                        lat_vals = [item[1] for item in lat_history]
                        lon_vals = [item[1] for item in lon_history]
                        alt_vals = [item[1] for item in alt_history]
                        lat_std = np.std(lat_vals) if len(lat_vals) > 1 else 0.0
                        lon_std = np.std(lon_vals) if len(lon_vals) > 1 else 0.0
                        alt_std = np.std(alt_vals) if len(alt_vals) > 1 else 0.0
                        # メートル換算
                        lat_std_m = lat_std * 111000
                        mean_lat = np.mean(lat_vals) if len(lat_vals) > 0 else lat_deg
                        lon_std_m = lon_std * 111000 * np.cos(np.radians(mean_lat))
                        # 高度はそのままm単位
                        alt_std_m = alt_std
                        print(f"[GPS] 緯度:{lat_deg:.7f} 経度:{lon_deg:.7f} 高度:{alt_m:.3f}m | 状態: {format_fix(quality):<20} | 衛星数: {sats} | [Hz計測: {hz_count} msg/s] | [10秒間 標準偏差] 緯度:{lat_std_m:.3f}m 経度:{lon_std_m:.3f}m 高度:{alt_std_m:.3f}m")
                        
                        # CSVに記録
                        if csv_writer is not None:
                            # ステータスを英語のみ、RTKFixed/Otherで記録
                            status_simple = "RTKFixed" if quality == 4 else "Other"
                            csv_writer.writerow([now, lat_deg, lon_deg, alt_m, status_simple])
                            csvfile.flush()
                            
                        # もしRTK Fixedになったら特別に通知
                        if quality == 4:
                            pass # We are already printing it 
                            
                except Exception:
                    pass

                # 5秒に1回、GGAをNTRIPサーバーに送信する（VRS方式に必須）
                if now - last_gga_send > 5.0:
                    sock.sendall(line)
                    cnt_gga += 1
                    # print(f"[F9P->NTRIP] GGA位置情報送信 #{cnt_gga}")
                    last_gga_send = now

        except Exception as e:
            if connected:
                print(f"[Serial Error] {e}")
                connected = False
            break


def main():
    global connected
    print(f"=== イチミル RTK 確認プログラム ===")
    # シリアルポート設定
    print(f"対象ポート: {COM_PORT}")
    print(f"サーバー: {SERVER}:{PORT} / {MOUNTPOINT}")

    # CSVファイル名自動生成（windows/log/ichimile_log/ に保存）
    import os
    dtstr = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "log", "ichimile_log"
    )
    os.makedirs(log_dir, exist_ok=True)
    csv_filename = os.path.join(log_dir, f"gpslog_{dtstr}.csv")
    csvfile = open(csv_filename, "w", encoding="utf-8", newline="")

    # 1. シリアルポート(rtk-pipeline)のオープン
    try:
        ser = serial.Serial(COM_PORT, BAUD, timeout=0.5)
        print(f"[OK] F9Pに接続しました ({COM_PORT})")
        reset_tmode3(ser)
        set_gga_rate_5hz(ser)
    except Exception as e:
        print(f"[ERR] F9Pポート({COM_PORT})のオープンに失敗しました: {e}")
        return

    # 2. NTRIPサーバーへの接続
    try:
        print(f"NTRIPサーバーへ接続中... ({SERVER}:{PORT})")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((SERVER, PORT))
        sock.settimeout(None)
        print(f"[OK] NTRIPサーバーに接続しました ({SERVER})")
        
        # NTRIPの認証・要求ヘッダ送信
        auth_bytes = f"{USER}:{PASS}".encode('utf-8')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
        
        req = (
            f"GET /{MOUNTPOINT} HTTP/1.0\r\n"
            f"User-Agent: NTRIP SimpleRTK/1.0\r\n"
            f"Authorization: Basic {auth_b64}\r\n"
            f"Accept: */*\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        )
        sock.sendall(req.encode('ascii'))
        
        # 応答ヘッダの確認 (ICY 200 OK など)
        head = sock.recv(1024)
        print("[NTRIP] サーバー応答:")
        print(head.decode('ascii', errors='ignore').strip())
        
        if b"200 OK" not in head and b"ICY 200" not in head:
            print("[ERR] NTRIPサーバーから正常なレスポンスが得られませんでした。")
            connected = False
            return
            
        print("[OK] NTRIPマウントされた。RTCM配信待機状態になりました。")
        
    except socket.timeout:
        print(f"[ERR] NTRIPサーバー({SERVER}:{PORT})への接続がタイムアウトしました（10秒）")
        print("\n  【原因と対処】")
        print("  1. ルーターがポート2101のアウトバウンドをブロックしている")
        print("     → ルーター管理画面でアウトバウンドポート2101を許可")
        print("  2. ISPがポート2101を制限している → ISPに問い合わせ")
        print("  3. スマホのテザリング(モバイル回線)でテスト")
        ser.close()
        return
    except Exception as e:
        print(f"[ERR] NTRIP接続エラー: {type(e).__name__}: {e}")
        ser.close()
        return

    # 3. データ送受信スレッドの開始
    t_rx = threading.Thread(target=ntrip_to_serial, args=(sock, ser), daemon=True)
    t_tx = threading.Thread(target=serial_to_ntrip, args=(sock, ser, csvfile), daemon=True)
    
    t_rx.start()
    t_tx.start()
    
    # メインスレッドでは監視と終了の受付
    try:
        while connected:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[User] Ctrl+C が押されました。終了します。")
        connected = False

    finally:
        sock.close()
        ser.close()
        if 'csvfile' in locals():
            csvfile.close()
        print("[OK] 切断処理完了")

if __name__ == "__main__":
    main()
