#!/usr/bin/env python3
"""
GPS位置データの標準偏差と最大誤差を求めるプログラム（デバッグ版）

機能:
  - リアルタイムでGPS位置データを取得（NMEA-GGA）
  - 位置データの平均値をリファレンスとして計算
  - 標準偏差、最大誤差、実行時間を記録
  - Ctrl+C で終了時に結果を表示
  - RTK補正信号の使用/未使用を切り替え可能
  - **デバッグ版**: 詳細なNTRIP受信ログ
"""

import sys
import time
import serial
import signal
import math
import socket
import base64
import threading
import struct
from datetime import datetime
from pynmeagps import NMEAReader

# ============================================================
# 設定
# ============================================================
COM_PORT = 'COM6'
BAUD = 38400

# ============ RTK 設定 ============
# RTK = 0: RTKなし（単独GPS）
# RTK = 1: NTRIPサーバーから補正信号を受け取る
RTK = 1

# NTRIP サーバー設定（ichimile_nolog.py から取得）
NTRIP_SERVER = "ntrip.ales-corp.co.jp"
NTRIP_PORT = 2101
NTRIP_MOUNTPOINT = "RTCM32MSM5"
NTRIP_USER = "6y8swddj"
NTRIP_PASS = "xxu2w5"

# ============================================================
# グローバル変数（NTRIP接続状態）
# ============================================================
ntrip_connected = False
ntrip_socket = None
rtcm_data_received = 0  # 受信したRTCM信号のバイト数
rtcm_first_byte_log = []  # 最初の100バイトのログ


def ntrip_receive_thread(sock, ser):
    """
    NTRIP サーバーから補正信号を受け取り、シリアルに送信するスレッド
    【デバッグ版】: 詳細ログ出力
    """
    global ntrip_connected, rtcm_data_received, rtcm_first_byte_log
    print("[NTRIP] 受信スレッド開始")
    recv_count = 0
    skip_count = 0
    
    try:
        # ソケットをブロッキングモードに設定
        sock.setblocking(True)
        sock.settimeout(2.0)
        
        while ntrip_connected:
            try:
                data = sock.recv(4096)
                recv_count += 1
                
                if data:
                    # ========================
                    # 【デバッグ】最初の20受信をログ出力
                    # ========================
                    if recv_count <= 20:
                        print(f"    [DEBUG-RECV-{recv_count}] 受信サイズ: {len(data)} bytes")
                        if len(data) > 0:
                            first_10 = ' '.join(f'{b:02X}' for b in data[:min(10, len(data))])
                            print(f"    [DEBUG-HEX] {first_10}")
                            # 0xD3 チェック
                            if data[0:1] == b'\xd3':
                                print(f"    [DEBUG] ✓ 0xD3で始まる")
                            else:
                                print(f"    [DEBUG] ✗ 0xD3ではない (最初のバイト: 0x{data[0]:02X})")
                    
                    # RTCMデータはバイナリ形式で、0xD3で始まる
                    if len(data) > 0 and (data[0:1] == b'\xd3' or rtcm_data_received > 0):
                        ser.write(data)
                        rtcm_data_received += len(data)
                        print(f"  [NTRIP] RTCMデータ送信: {len(data)} bytes (合計: {rtcm_data_received} bytes)")
                    else:
                        # データを受け取ったが0xD3ではなく、まだRTCMを受信していない
                        skip_count += 1
                        if skip_count <= 10:
                            first_20 = ' '.join(f'{b:02X}' for b in data[:min(20, len(data))])
                            print(f"  [NTRIP WARNING] スキップされたデータ({skip_count}): {len(data)} bytes")
                            print(f"    → {first_20}")
                else:
                    print("[NTRIP] サーバーから切断されました")
                    ntrip_connected = False
                    break
            except socket.timeout:
                # タイムアウトしても続行
                if recv_count <= 20:
                    print(f"    [DEBUG] socket.timeout (受信{recv_count}回目)")
                continue
            except Exception as e:
                if ntrip_connected:
                    print(f"[NTRIP Error] {e}")
                    ntrip_connected = False
                break
    finally:
        print(f"[NTRIP] 受信スレッド終了 (受信{recv_count}回, スキップ{skip_count}回, 合計 {rtcm_data_received} bytes)")


def connect_ntrip_server(ser):
    """
    NTRIP サーバーに接続して補正信号の受信を開始
    【デバッグ版】: 詳細ログ出力
    """
    global ntrip_connected, ntrip_socket
    
    try:
        print(f"\n[NTRIP接続] {NTRIP_SERVER}:{NTRIP_PORT} へ接続中...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((NTRIP_SERVER, NTRIP_PORT))
        sock.settimeout(None)
        print("[NTRIP接続] ✓ ソケット接続成功")
        
        # NTRIP ハンドシェイク（Basic認証）
        auth_str = f"{NTRIP_USER}:{NTRIP_PASS}"
        auth_bytes = base64.b64encode(auth_str.encode()).decode()
        
        request = (
            f"GET /{NTRIP_MOUNTPOINT} HTTP/1.0\r\n"
            f"Host: {NTRIP_SERVER}:{NTRIP_PORT}\r\n"
            f"Authorization: Basic {auth_bytes}\r\n"
            f"Connection: close\r\n"
            f"User-Agent: NTRIPCLIENT\r\n"
            f"\r\n"
        )
        print("[NTRIP接続] リクエスト送信:")
        print(request)
        sock.sendall(request.encode())
        print("[NTRIP接続] ✓ リクエスト送信完了")
        
        # HTTPレスポンスを受け取る（ヘッダ + \r\n\r\n まで）
        response = b''
        header_end = False
        chunk_count = 0
        while not header_end:
            chunk = sock.recv(1024)
            chunk_count += 1
            print(f"[DEBUG-HEADER] chunk {chunk_count}: {len(chunk)} bytes")
            if not chunk:
                print("[NTRIP接続] ✗ ソケット接続が閉じた")
                break
            response += chunk
            if b'\r\n\r\n' in response:
                header_end = True
                print(f"[NTRIP接続] ✓ ヘッダ終了検出")
        
        # HTTPステータスラインを取得
        response_str = response.decode('latin-1', errors='ignore')
        status_line = response_str.split('\r\n')[0]
        print(f"[DEBUG-HEADER] ステータス: {status_line}")
        
        # レスポンスの詳細ログ
        print(f"[DEBUG-HEADER] レスポンス全体 ({len(response)} bytes):")
        print(response_str[:500])
        
        # ヘッダの後のバイナリデータがあるかチェック
        header_end_pos = response.find(b'\r\n\r\n')
        if header_end_pos != -1:
            trailing_data = response[header_end_pos + 4:]
            print(f"[DEBUG-HEADER] ヘッダ後のデータ: {len(trailing_data)} bytes")
            if len(trailing_data) > 0:
                hex_preview = ' '.join(f'{b:02X}' for b in trailing_data[:min(20, len(trailing_data))])
                print(f"    → {hex_preview}")
        
        if '200' in status_line:
            print(f"[NTRIP接続] ✓ 接続成功（{status_line}）")
            print("[NTRIP接続] RTCM補正信号受信開始...")
            ntrip_connected = True
            ntrip_socket = sock
            
            # NTRIP受信スレッドを開始（既にヘッダ受信済みなのでそのままスレッド開始）
            thread = threading.Thread(target=ntrip_receive_thread, args=(sock, ser), daemon=True)
            thread.start()
            return True
        else:
            print(f"[NTRIP接続] ✗ エラー: {status_line}")
            sock.close()
            return False
            
    except socket.timeout:
        print(f"[NTRIP接続] ✗ 接続タイムアウト ({NTRIP_SERVER}:{NTRIP_PORT})")
        print("  【原因と対処】")
        print("  1. ルーターがポート2101のアウトバウンドをブロックしている")
        print("     → ルーター管理画面でアウトバウンドポート2101を許可")
        print("  2. ISPがポート2101を制限している → ISPに問い合わせ")
        return False
    except Exception as e:
        print(f"[NTRIP接続] ✗ 接続失敗: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


def ubx_checksum(data: bytes) -> bytes:
    """UBX チェックサム（CLASS, ID, LEN, PAYLOAD に対して計算）"""
    ck_a = ck_b = 0
    for b in data:
        ck_a = (ck_a + b) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return bytes([ck_a, ck_b])


def make_ubx(cls_id: int, msg_id: int, payload: bytes) -> bytes:
    """UBX パケット組み立て"""
    inner = bytes([cls_id, msg_id]) + struct.pack('<H', len(payload)) + payload
    return bytes([0xB5, 0x62]) + inner + ubx_checksum(inner)


def disable_tmode3(ser):
    """
    F9P の TMODE3 (基地局モード) を無効化
    RTK移動局として動作するようにする
    """
    try:
        print("\n[F9P設定] TMODE3 無効化（RTK移動局モードに切り替え中）...")
        # TMODE3 無効化：flags=0
        payload = struct.pack(
            '<BBHiiibbBBIII',
            0,       # version
            0,       # reserved0
            0,       # flags: 0 = 無効化
            0, 0, 0, 0, 0, 0, 0,  # 座標（無視）
            100,     # fixedPosAcc
            0, 0
        )
        packet = make_ubx(0x06, 0x71, payload)
        ser.write(packet)
        ser.flush()
        print("[F9P設定] TMODE3 無効化コマンド送信完了")
        time.sleep(0.5)
        return True
    except Exception as e:
        print(f"[F9P設定] エラー: {e}")
        return False


# ============================================================
# GPS 統計計算クラス
# ============================================================
class GPSStatistics:
    def __init__(self):
        # Welfordのアルゴリズムの状態変数
        # （メモリ効率的にリアルタイム計算する）
        self.n = 0  # サンプル数
        self.mean_lat = 0.0
        self.mean_lon = 0.0
        self.mean_alt = 0.0
        self.M2_lat = 0.0  # 緯度の平方和（分散計算用）
        self.M2_lon = 0.0  # 経度の平方和（分散計算用）
        self.M2_alt = 0.0  # 高度の平方和（分散計算用）
        
        # 位置データはすべて保持（距離計算とfix状態確認に必要）
        self.positions = []  # [(lat, lon, alt), ...]
        
        # GPS品質統計
        self.quality_counts = {}  # {品質値: カウント}
        self.max_satellites = 0
        self.rtk_fix_samples = 0
        self.rtk_float_samples = 0
        
        # タイミング情報
        self.start_time = None
        self.end_time = None
        
    def add_sample(self, lat, lon, alt, quality=0, numSV=0):
        """
        Welfordのアルゴリズムで平均・分散をリアルタイム更新
        メモリ効率: O(n) で統計値を計算可能
        """
        if lat is None or lon is None:
            return False
        
        self.n += 1
        self.positions.append((lat, lon, alt))
        
        # GPS品質を記録
        if quality not in self.quality_counts:
            self.quality_counts[quality] = 0
        self.quality_counts[quality] += 1
        
        # RTK統計
        if quality == 4:
            self.rtk_fix_samples += 1
        elif quality == 5:
            self.rtk_float_samples += 1
        
        # 最大衛星数を記録
        self.max_satellites = max(self.max_satellites, numSV)
        
        # Welfordのアルゴリズム（数値安定性が高い）
        # 緯度
        delta_lat = lat - self.mean_lat
        self.mean_lat += delta_lat / self.n
        delta_lat2 = lat - self.mean_lat
        self.M2_lat += delta_lat * delta_lat2
        
        # 経度
        delta_lon = lon - self.mean_lon
        self.mean_lon += delta_lon / self.n
        delta_lon2 = lon - self.mean_lon
        self.M2_lon += delta_lon * delta_lon2
        
        # 高度
        if alt is not None:
            delta_alt = alt - self.mean_alt
            self.mean_alt += delta_alt / self.n
            delta_alt2 = alt - self.mean_alt
            self.M2_alt += delta_alt * delta_alt2
        
        if self.start_time is None:
            self.start_time = time.time()
        
        return True
    
    def calculate_error_distance(self, lat, lon, ref_lat, ref_lon):
        """
        2点間の距離をハバーサイン公式で計算（メートル）
        lat, lon: 現在位置（度）
        ref_lat, ref_lon: 基準位置（度）
        """
        R = 6371000  # 地球の半径（メートル）
        
        lat1_rad = math.radians(lat)
        lon1_rad = math.radians(lon)
        lat2_rad = math.radians(ref_lat)
        lon2_rad = math.radians(ref_lon)
        
        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad
        
        a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        distance = R * c
        
        return distance
    
    def calculate_statistics(self):
        """
        Welfordのアルゴリズムで計算した統計値と
        すべてのサンプルを使った距離統計を結合
        
        戻り値: {
            'mean_lat': 平均緯度,
            'mean_lon': 平均経度,
            'mean_alt': 平均高度,
            'std_lat': 緯度の標準偏差,
            'std_lon': 経度の標準偏差,
            'std_alt': 高度の標準偏差,
            'std_distance': 距離の標準偏差,
            'max_error': 最大誤差,
            'valid_samples': 有効サンプル数,
            'duration_seconds': 実行時間（秒）
        }
        """
        if self.n < 1:
            return None
        
        if self.n == 1:
            print("\n[警告] サンプルが1つのみです（標準偏差は計算不可）")
        
        # Welfordのアルゴリズムで計算した標準偏差
        std_lat = math.sqrt(self.M2_lat / self.n) if self.n > 0 else 0
        std_lon = math.sqrt(self.M2_lon / self.n) if self.n > 0 else 0
        std_alt = math.sqrt(self.M2_alt / self.n) if self.n > 0 else 0
        
        # すべてのサンプルに対して距離を計算
        distances = []
        max_error = 0
        
        for lat, lon, alt in self.positions:
            distance = self.calculate_error_distance(lat, lon, self.mean_lat, self.mean_lon)
            distances.append(distance)
            max_error = max(max_error, distance)
        
        # 距離の統計
        mean_distance = sum(distances) / len(distances) if distances else 0
        var_distance = sum((x - mean_distance)**2 for x in distances) / len(distances) if distances else 0
        std_distance = math.sqrt(var_distance)
        
        # 実行時間
        self.end_time = time.time()
        duration = self.end_time - self.start_time if self.start_time else 0
        
        return {
            'mean_lat': self.mean_lat,
            'mean_lon': self.mean_lon,
            'mean_alt': self.mean_alt,
            'std_lat': std_lat,
            'std_lon': std_lon,
            'std_alt': std_alt,
            'std_distance': std_distance,
            'max_error': max_error,
            'valid_samples': self.n,
            'duration_seconds': duration
        }


def print_results(stats):
    """測定結果を表示"""
    results = stats.calculate_statistics()
    
    if results is None:
        print("\n[警告] 十分なサンプルデータがありません")
        return
    
    print("\n" + "="*70)
    print("GPS 位置データ統計分析結果")
    print("="*70)
    
    print(f"\n【取得データ情報】")
    print(f"  有効サンプル数:      {results['valid_samples']} サンプル")
    print(f"  実行時間:           {results['duration_seconds']:.2f} 秒")
    print(f"  最大衛星数:         {stats.max_satellites} 衛星")
    sys.stdout.flush()
    
    # GPS品質統計
    print(f"\n【GPS品質の内訳】")
    quality_names = {0: 'No Fix', 1: 'GPS', 2: 'DGPS', 4: 'RTK Fixed', 5: 'RTK Float'}
    for quality_val in sorted(stats.quality_counts.keys()):
        count = stats.quality_counts[quality_val]
        percentage = (count / results['valid_samples']) * 100
        quality_name = quality_names.get(quality_val, f'Unknown({quality_val})')
        print(f"  {quality_name:15s}: {count:4d} サンプル ({percentage:5.1f}%)")
    
    sys.stdout.flush()
    
    if stats.rtk_fix_samples > 0:
        print(f"\n[成功] RTK Fixed を獲得！ ({stats.rtk_fix_samples} サンプル)")
    elif stats.rtk_float_samples > 0:
        print(f"\n[部分成功] RTK Float を獲得 ({stats.rtk_float_samples} サンプル)")
        print("  → Fixed解を得るまで、さらに多くの衛星が必要です")
    else:
        print(f"\n[失敗] RTK Fixed/Float を獲得できませんでした")
        print("  → F9Pの設定を確認してください")
    
    print(f"\n【平均位置（リファレンス）】")
    print(f"  平均緯度:  {results['mean_lat']:.8f}°")
    print(f"  平均経度:  {results['mean_lon']:.8f}°")
    if results['mean_alt'] is not None:
        print(f"  平均高度:  {results['mean_alt']:.2f} m")
    
    print(f"\n【標準偏差（角度）】")
    print(f"  緯度の標準偏差: {results['std_lat']:.8f}°")
    print(f"  経度の標準偏差: {results['std_lon']:.8f}°")
    
    print(f"\n【標準偏差（距離）】")
    print(f"  距離の標準偏差: {results['std_distance']:.6f} m")
    print(f"  距離の標準偏差: {results['std_distance']*1000:.4f} mm")
    
    print(f"\n【誤差（平均位置との距離）】")
    print(f"  最大誤差: {results['max_error']:.6f} m")
    print(f"  最大誤差: {results['max_error']*1000:.4f} mm")
    
    print("="*70)


def main():
    print("GPS 位置データ統計分析プログラム（デバッグ版）")
    print(f"ポート: {COM_PORT}, ボーレート: {BAUD}")
    if RTK == 1:
        print(f"RTK: 有効 (NTRIPサーバー: {NTRIP_SERVER})")
    else:
        print("RTK: 無効 (単独GPS)")
    print("Ctrl+C で終了します...\n")
    
    stats = GPSStatistics()
    
    try:
        ser = serial.Serial(COM_PORT, BAUD, timeout=1)
        print(f"[成功] {COM_PORT} を開きました\n")
    except serial.SerialException as e:
        print(f"[エラー] シリアルポートを開けません: {e}")
        sys.exit(1)
    
    # RTK接続
    if RTK == 1:
        # F9Pの設定を確認・修正（基地局モードを無効化）
        disable_tmode3(ser)
        time.sleep(1.0)
        
        if not connect_ntrip_server(ser):
            print("[警告] NTRIP接続に失敗しましたが、単独GPSで続行します")
    
    def signal_handler(signum, frame):
        """Ctrl+C で呼ばれるハンドラー"""
        global ntrip_connected, ntrip_socket
        print("\n\n[停止] Ctrl+C されました")
        
        # NTRIP接続を切断
        if RTK == 1 and ntrip_connected:
            ntrip_connected = False
            if ntrip_socket:
                try:
                    ntrip_socket.close()
                except:
                    pass
            time.sleep(0.2)
        
        ser.close()
        print_results(stats)
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        nmea_reader = NMEAReader(ser)
        message_count = 0
        gga_count = 0
        
        print("データ取得中...\n")
        
        for raw_data, msg in nmea_reader:
            # GGAメッセージのみを処理
            if msg is not None:
                msg_id = msg.msgID if hasattr(msg, 'msgID') else None
                if msg_id == 'GGA':
                    gga_count += 1
                    
                    # 位置情報を抽出
                    lat = msg.lat if hasattr(msg, 'lat') else None
                    lon = msg.lon if hasattr(msg, 'lon') else None
                    alt = msg.alt if hasattr(msg, 'alt') else None
                    quality = msg.quality if hasattr(msg, 'quality') else 0
                    numSV = msg.numSV if hasattr(msg, 'numSV') else 0
                    
                    # 緯度経度の両方が有効な場合のみ追加
                    if lat is not None and lon is not None:
                        if stats.add_sample(lat, lon, alt, quality, numSV):
                            # 進捗表示（10サンプルごと）
                            if gga_count % 10 == 0:
                                quality_map = {0: 'No Fix', 1: 'GPS', 2: 'DGPS', 4: 'RTK Fix', 5: 'RTK Float'}
                                quality_str = quality_map.get(quality, f'Unknown({quality})')
                                print(f"  サンプル数: {stats.n:4d}, "
                                      f"品質: {quality_str:12s}, "
                                      f"衛星: {numSV:2d}, "
                                      f"時刻: {datetime.now().strftime('%H:%M:%S')}")
                
                message_count += 1
    
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"[エラー] {e}")
    finally:
        global ntrip_connected, ntrip_socket
        if RTK == 1 and ntrip_connected:
            ntrip_connected = False
            if ntrip_socket:
                try:
                    ntrip_socket.close()
                except:
                    pass
        ser.close()
        print_results(stats)


if __name__ == '__main__':
    main()
