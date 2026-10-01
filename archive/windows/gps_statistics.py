#!/usr/bin/env python3
"""
GPS位置データの標準偏差と最大誤差を求めるプログラム

機能:
  - リアルタイムでGPS位置データを取得（NMEA-GGA）
  - 位置データの平均値をリファレンスとして計算
  - 標準偏差、最大誤差、実行時間を記録
  - Ctrl+C で終了時に結果を表示
  - RTK補正信号の使用/未使用を切り替え可能
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
import csv
import json
import os
from datetime import datetime
from queue import Queue
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
# 出力設定（生データCSV・統計結果の保存先）
# ============================================================
# スクリプト直下の log/ に保存する（.gitignore で除外済み）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(SCRIPT_DIR, 'log')

# 緯度1度あたりの距離（メートル）。経度は cos(平均緯度) を掛けて換算する
METERS_PER_DEG_LAT = 111320.0

# 生データCSVのヘッダ
CSV_HEADER = [
    'receive_time', 'utc_time', 'latitude', 'longitude', 'altitude_m',
    'quality', 'quality_name', 'num_satellites', 'hdop', 'raw_nmea',
]

# ============================================================
# グローバル変数（NTRIP接続状態）
# ============================================================
ntrip_connected = False
ntrip_socket = None
rtcm_data_received = 0  # 受信したRTCM信号のバイト数


def gga_sender_thread(gga_queue):
    """
    GGAキューから定期的にGGAメッセージを取得し、NTRIPサーバーに送信するスレッド
    
    【改善】シリアルポート直接アクセスではなく、キューを使用してデータ競合を回避
    """
    global ntrip_connected, ntrip_socket
    print("[GGA送信] スレッド開始")
    last_gga_send = 0
    gga_count = 0
    
    while ntrip_connected:
        try:
            # キューからGGAメッセージを取得（タイムアウト付き）
            line = gga_queue.get(timeout=1.0)
            if line:
                now = time.time()
                gga_count += 1
                
                # 5秒ごとにサーバーに送信
                if now - last_gga_send > 5.0:
                    try:
                        ntrip_socket.sendall(line)
                        last_gga_send = now
                        if gga_count % 10 == 0:
                            print(f"  [GGA送信] {gga_count} 件送信")
                    except Exception as e:
                        print(f"[GGA送信エラー] {e}")
                        ntrip_connected = False
                        break
        except:
            # キューが空の場合は待機
            continue
    
    print(f"[GGA送信] スレッド終了（合計 {gga_count} 件）")


def ntrip_receive_thread(sock, ser):
    """
    NTRIP サーバーから補正信号を受け取り、シリアルに送信するスレッド
    
    ★修正: すべてのデータをそのままF9Pに送信（ichimile_nolog.py と同じロジック）
    RTCMデータはバイナリなので、フィルタリングは不要
    """
    global ntrip_connected, rtcm_data_received
    print("[NTRIP] 受信スレッド開始")
    try:
        # 受信タイムアウトなし（ブロッキングモード）
        sock.setblocking(True)
        # ★修正: タイムアウトを長めに設定（30秒）
        sock.settimeout(30.0)
        
        while ntrip_connected:
            try:
                data = sock.recv(4096)
                if data:
                    ser.write(data)
                    rtcm_data_received += len(data)
                    # 進捗表示（100KB受信するごとに表示）
                    if rtcm_data_received % 102400 < 4096:
                        print(f"  [NTRIP] {rtcm_data_received} bytes 受信・送信済み")
                else:
                    print("[NTRIP] サーバーから切断されました")
                    ntrip_connected = False
                    break
            except socket.timeout:
                # タイムアウトしても続行（サーバー側で一時的にデータなしの可能性）
                continue
            except Exception as e:
                if ntrip_connected:
                    print(f"[NTRIP Error] {e}")
                    ntrip_connected = False
                break
    finally:
        print(f"[NTRIP] 受信スレッド終了 (合計 {rtcm_data_received} bytes 受信・送信)")



def connect_ntrip_server(ser):
    """
    NTRIP サーバーに接続して補正信号の受信を開始
    
    ★修正: Connection: close を削除し、HTTP/1.0で暗黙的にkeep-aliveを使用する
        これにより、ヘッダ受信後もサーバーがRTCMデータを送信し続ける
    """
    global ntrip_connected, ntrip_socket
    
    try:
        print(f"\n[NTRIP接続] {NTRIP_SERVER}:{NTRIP_PORT} へ接続中...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((NTRIP_SERVER, NTRIP_PORT))
        sock.settimeout(None)
        
        # NTRIP ハンドシェイク（Basic認証）
        auth_str = f"{NTRIP_USER}:{NTRIP_PASS}"
        auth_bytes = base64.b64encode(auth_str.encode()).decode()
        
        # ★修正: Connection ヘッダを削除（ichimile_nolog.py と同じロジック）
        request = (
            f"GET /{NTRIP_MOUNTPOINT} HTTP/1.0\r\n"
            f"User-Agent: NTRIP SimpleRTK/1.0\r\n"
            f"Authorization: Basic {auth_bytes}\r\n"
            f"Accept: */*\r\n"
            f"\r\n"
        )
        sock.sendall(request.encode('ascii'))
        print("[NTRIP接続] リクエスト送信完了")
        
        # HTTPレスポンスヘッダを受け取る（簡潔なロジック）
        head = sock.recv(1024)
        print("[NTRIP接続] サーバー応答:")
        print(head.decode('ascii', errors='ignore').strip())
        
        if b"200 OK" not in head and b"ICY 200" not in head:
            print("✗ NTRIPサーバーから正常なレスポンスが得られませんでした。")
            ntrip_connected = False
            sock.close()
            return False
            
        print("[NTRIP接続] ✓ NTRIPマウント成功")
        print("[NTRIP接続] RTCM補正信号受信開始...")
        ntrip_connected = True
        ntrip_socket = sock
        
        # NTRIP受信スレッドを開始
        thread = threading.Thread(target=ntrip_receive_thread, args=(sock, ser), daemon=True)
        thread.start()
        return True
            
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
        
        # 標本標準偏差（分母 n-1）で計算する。
        # 参考: rtk_base_mavlink/position_observer.py, base_station_verify/rtcm_compare/standalone_obs.py
        #       の statistics.stdev による実装
        dof = self.n - 1
        std_lat = math.sqrt(self.M2_lat / dof) if dof > 0 else 0.0
        std_lon = math.sqrt(self.M2_lon / dof) if dof > 0 else 0.0
        std_alt = math.sqrt(self.M2_alt / dof) if dof > 0 else 0.0

        # 標準偏差のメートル換算
        #   緯度1度 ≒ 111320 m、経度1度 ≒ 111320 m × cos(平均緯度)
        cos_mean_lat = math.cos(math.radians(self.mean_lat))
        std_lat_m = std_lat * METERS_PER_DEG_LAT
        std_lon_m = std_lon * METERS_PER_DEG_LAT * cos_mean_lat
        
        # すべてのサンプルに対して距離を計算
        distances = []
        max_error = 0
        
        for lat, lon, alt in self.positions:
            distance = self.calculate_error_distance(lat, lon, self.mean_lat, self.mean_lon)
            distances.append(distance)
            max_error = max(max_error, distance)
        
        # 距離の統計
        mean_distance = sum(distances) / len(distances) if distances else 0
        var_distance = sum((x - mean_distance)**2 for x in distances) / dof if dof > 0 and distances else 0
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
            'std_lat_m': std_lat_m,
            'std_lon_m': std_lon_m,
            'std_distance': std_distance,
            'max_error': max_error,
            'valid_samples': self.n,
            'duration_seconds': duration
        }


QUALITY_NAMES = {0: 'No Fix', 1: 'GPS', 2: 'DGPS', 4: 'RTK Fixed', 5: 'RTK Float'}


def quality_name(quality):
    """GPS品質コードを可読名に変換する"""
    return QUALITY_NAMES.get(quality, f'Unknown({quality})')


def generate_csv_path(output_dir=None):
    """タイムスタンプ付きの生データCSVパスを生成する"""
    if output_dir is None:
        output_dir = LOG_DIR
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    return os.path.join(output_dir, f'gps_log_{ts}.csv')


class CSVLogger:
    """受信したGGAをCSVへ逐次書き出すロガー"""

    def __init__(self, path):
        self.path = path
        self.file = open(path, 'w', newline='', encoding='utf-8')
        self.writer = csv.writer(self.file)
        self.writer.writerow(CSV_HEADER)
        self.file.flush()
        self.row_count = 0

    def write_row(self, row):
        self.writer.writerow(row)
        self.file.flush()
        self.row_count += 1

    def close(self):
        try:
            if self.file is not None:
                self.file.flush()
                self.file.close()
                self.file = None
        except Exception:
            pass


def build_results_dict(stats, results):
    """統計結果をファイル出力用の辞書にまとめる"""
    quality_counts = {}
    quality_breakdown = {}
    for q, c in sorted(stats.quality_counts.items()):
        key = str(int(q))
        quality_counts[key] = c
        quality_breakdown[f"{key} ({quality_name(int(q))})"] = c

    data = {
        'mean_lat_deg': results['mean_lat'],
        'mean_lon_deg': results['mean_lon'],
        'mean_alt_m': results['mean_alt'],
        'std_lat_deg': results['std_lat'],
        'std_lon_deg': results['std_lon'],
        'std_alt_m': results['std_alt'],
        'std_lat_m': results['std_lat_m'],
        'std_lon_m': results['std_lon_m'],
        'std_distance_m': results['std_distance'],
        'max_error_m': results['max_error'],
        'valid_samples': results['valid_samples'],
        'duration_seconds': results['duration_seconds'],
        'max_satellites': stats.max_satellites,
        'rtk_fix_samples': stats.rtk_fix_samples,
        'rtk_float_samples': stats.rtk_float_samples,
        'quality_counts': quality_counts,
        'quality_breakdown': quality_breakdown,
    }
    if stats.start_time is not None:
        data['start_time'] = datetime.fromtimestamp(stats.start_time).strftime('%Y-%m-%d %H:%M:%S')
    if stats.end_time is not None:
        data['end_time'] = datetime.fromtimestamp(stats.end_time).strftime('%Y-%m-%d %H:%M:%S')
    return data


def format_results_text(data):
    """統計結果をテキスト形式に整形する"""
    lines = []
    lines.append("=" * 70)
    lines.append("GPS 位置データ統計分析結果（ファイル出力）")
    lines.append("=" * 70)
    lines.append("")
    lines.append("【取得データ情報】")
    lines.append(f"  有効サンプル数:      {data['valid_samples']} サンプル")
    lines.append(f"  実行時間:           {data['duration_seconds']:.2f} 秒")
    lines.append(f"  最大衛星数:         {data['max_satellites']} 衛星")
    if 'start_time' in data:
        lines.append(f"  開始時刻:           {data['start_time']}")
    if 'end_time' in data:
        lines.append(f"  終了時刻:           {data['end_time']}")
    lines.append("")
    lines.append("【GPS品質の内訳】")
    for label, count in data['quality_breakdown'].items():
        pct = (count / data['valid_samples']) * 100 if data['valid_samples'] else 0
        lines.append(f"  {label:20s}: {count:4d} サンプル ({pct:5.1f}%)")
    lines.append("")
    lines.append("【平均位置（リファレンス）】")
    lines.append(f"  平均緯度:  {data['mean_lat_deg']:.8f}°")
    lines.append(f"  平均経度:  {data['mean_lon_deg']:.8f}°")
    lines.append(f"  平均高度:  {data['mean_alt_m']:.2f} m")
    lines.append("")
    lines.append("【標準偏差（角度）】")
    lines.append(f"  緯度の標準偏差: {data['std_lat_deg']:.8f}°")
    lines.append(f"  経度の標準偏差: {data['std_lon_deg']:.8f}°")
    lines.append("")
    lines.append("【標準偏差（メートル換算）】")
    lines.append(f"  緯度の標準偏差: {data['std_lat_m']:.6f} m")
    lines.append(f"  経度の標準偏差: {data['std_lon_m']:.6f} m")
    lines.append(f"  高度の標準偏差: {data['std_alt_m']:.6f} m")
    lines.append("")
    lines.append("【標準偏差（距離）】")
    lines.append(f"  距離の標準偏差: {data['std_distance_m']:.6f} m")
    lines.append("")
    lines.append("【誤差（平均位置との距離）】")
    lines.append(f"  最大誤差: {data['max_error_m']:.6f} m")
    lines.append("")
    lines.append("=" * 70)
    return "\n".join(lines) + "\n"


def save_results(stats, results, output_dir=None):
    """統計結果をJSONとテキストへ保存する"""
    if results is None:
        return None
    if output_dir is None:
        output_dir = LOG_DIR
    os.makedirs(output_dir, exist_ok=True)

    data = build_results_dict(stats, results)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    json_path = os.path.join(output_dir, f'gps_statistics_{ts}.json')
    txt_path = os.path.join(output_dir, f'gps_statistics_{ts}.txt')

    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n[保存] 統計結果(JSON): {json_path}")
    except Exception as e:
        print(f"\n[保存エラー] JSON: {e}")
        json_path = None

    try:
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(format_results_text(data))
        print(f"[保存] 統計結果(TXT) : {txt_path}")
    except Exception as e:
        print(f"[保存エラー] TXT: {e}")
        txt_path = None

    return json_path, txt_path


def finalize(stats, csv_logger=None):
    """終了処理: CSVを閉じ、統計結果を表示・保存する"""
    if csv_logger is not None:
        csv_logger.close()
    results = stats.calculate_statistics()
    if results is None:
        print("\n[警告] 十分なサンプルデータがありません")
        return
    print_results(stats, results)
    save_results(stats, results)


def print_results(stats, results=None):
    """測定結果を表示"""
    if results is None:
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

    print(f"\n【標準偏差（メートル換算）】")
    print(f"  緯度の標準偏差: {results['std_lat_m']:.6f} m ({results['std_lat_m']*1000:.3f} mm)")
    print(f"  経度の標準偏差: {results['std_lon_m']:.6f} m ({results['std_lon_m']*1000:.3f} mm)")
    print(f"  高度の標準偏差: {results['std_alt']:.6f} m")
    
    print(f"\n【標準偏差（距離）】")
    print(f"  距離の標準偏差: {results['std_distance']:.6f} m")
    print(f"  距離の標準偏差: {results['std_distance']*1000:.4f} mm")
    
    print(f"\n【誤差（平均位置との距離）】")
    print(f"  最大誤差: {results['max_error']:.6f} m")
    print(f"  最大誤差: {results['max_error']*1000:.4f} mm")
    
    print("="*70)


def main():
    global ntrip_connected, ntrip_socket
    print("GPS 位置データ統計分析プログラム")
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
    gga_queue = Queue()  # GGAメッセージ送信用キュー
    
    if RTK == 1:
        # F9Pの設定を確認・修正（基地局モードを無効化）
        disable_tmode3(ser)
        time.sleep(1.0)
        
        if connect_ntrip_server(ser):
            # NTRIP接続成功時、GGA送信スレッドを開始
            # （RTCM受信スレッドはconnect_ntrip_server内で既に開始されている）
            t_gga = threading.Thread(target=gga_sender_thread, args=(gga_queue,), daemon=True)
            t_gga.start()
            time.sleep(0.5)
        else:
            print("[警告] NTRIP接続に失敗しましたが、単独GPSで続行します")

    # 生データCSVロガー（タイムスタンプ付きファイルに逐次書き出す）
    csv_path = generate_csv_path()
    csv_logger = CSVLogger(csv_path)
    print(f"[記録] 生データCSV: {csv_path}\n")
    
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
                    
                    # GGAメッセージをキューに追加（NTRIP送信用）
                    if RTK == 1:
                        try:
                            gga_queue.put(raw_data, block=False)
                        except:
                            pass  # キューがいっぱいの場合はスキップ
                    
                    # 位置情報を抽出
                    lat = msg.lat if hasattr(msg, 'lat') else None
                    lon = msg.lon if hasattr(msg, 'lon') else None
                    alt = msg.alt if hasattr(msg, 'alt') else None
                    quality = msg.quality if hasattr(msg, 'quality') else 0
                    numSV = msg.numSV if hasattr(msg, 'numSV') else 0
                    hdop = msg.HDOP if hasattr(msg, 'HDOP') else None
                    utc_time = msg.time if hasattr(msg, 'time') else ''

                    # 受信したGGA全行をCSVへ記録（実験後の再解析用の生データ）
                    if isinstance(raw_data, (bytes, bytearray)):
                        raw_str = raw_data.decode('ascii', errors='replace').strip()
                    else:
                        raw_str = str(raw_data)
                    csv_logger.write_row([
                        datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f'),
                        utc_time,
                        f"{lat:.8f}" if lat is not None else '',
                        f"{lon:.8f}" if lon is not None else '',
                        f"{alt:.3f}" if alt is not None else '',
                        quality,
                        quality_name(quality),
                        numSV,
                        f"{hdop:.3f}" if hdop is not None else '',
                        raw_str,
                    ])
                    
                    # 緯度経度の両方が有効な場合のみ追加
                    if lat is not None and lon is not None:
                        if stats.add_sample(lat, lon, alt, quality, numSV):
                            # 進捗表示（10サンプルごと）
                            if gga_count % 10 == 0:
                                print(f"  サンプル数: {stats.n:4d}, "
                                      f"品質: {quality_name(quality):12s}, "
                                      f"衛星: {numSV:2d}, "
                                      f"時刻: {datetime.now().strftime('%H:%M:%S')}")
                
                message_count += 1
    
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"[エラー] {e}")
    finally:
        if RTK == 1 and ntrip_connected:
            ntrip_connected = False
            if ntrip_socket:
                try:
                    ntrip_socket.close()
                except:
                    pass
        ser.close()
        finalize(stats, csv_logger)


if __name__ == '__main__':
    main()
