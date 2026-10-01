#!/usr/bin/env python3
"""
NTRIP RTKクライアント

ArduPilot (Pixhawk) からMAVLinkでGPS位置情報 (GPS_RAW_INT) を受信し、
NMEA-0183 $GNGGA形式に変換してichimill NTRIPサーバーに送信する。
サーバーからRTCM補正データを受信し、バイナリログに保存する。

使用方法:
    source ~/Mavlink_venv/bin/activate
    python3 ntrip_rtk_client.py
"""

import sys
import os
import json
import time
import socket
import base64
import threading
import datetime

# --- 設定読み込み ---
def load_config(config_path=None):
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

config = load_config()

MAVLINK_PORT = config["mavlink"]["port"]
MAVLINK_BAUD = config["mavlink"]["baud"]
MAVLINK_RTSCTS = config["mavlink"]["rtscts"]

NTRIP_SERVER = config["ntrip"]["server"]
NTRIP_PORT = config["ntrip"]["port"]
NTRIP_MOUNT_POINT = config["ntrip"]["mount_point"]
NTRIP_USERNAME = config["ntrip"]["username"]
NTRIP_PASSWORD = config["ntrip"]["password"]

GGA_SEND_INTERVAL = config.get("gga_send_interval", 1.0)

# --- pymavlinkインポート ---
try:
    from pymavlink import mavutil
except ImportError:
    print("エラー: pymavlinkがインストールされていません")
    print("  source ~/Mavlink_venv/bin/activate")
    sys.exit(1)

# --- GPS Fix状態定義 ---
GPS_FIX_TYPE = {
    0: "NO_FIX",
    1: "NO_FIX",
    2: "2D_FIX",
    3: "3D_FIX",
    4: "DGPS_FIX",
    5: "RTK_FLOAT",
    6: "RTK_FIXED",
}

# MAVLink fix_type → NMEA GGA quality indicator マッピング
# 0=invalid, 1=GPS fix, 2=DGPS, 4=RTK fixed, 5=RTK float
FIX_TO_GGA_QUALITY = {
    0: 0,  # NO_FIX
    1: 0,  # NO_FIX
    2: 1,  # 2D_FIX → GPS fix
    3: 1,  # 3D_FIX → GPS fix
    4: 2,  # DGPS_FIX → DGPS
    5: 5,  # RTK_FLOAT → float RTK
    6: 4,  # RTK_FIXED → RTK fixed
}

# --- 共有状態 ---
class SharedState:
    """MAVLink受信スレッドとNTRIP送信スレッド間で共有する最新GPS位置"""
    def __init__(self):
        self.lock = threading.Lock()
        self.lat = None          # 10進数度
        self.lon = None          # 10進数度
        self.alt = None          # メートル (MSL)
        self.fix_type = 0        # MAVLink fix_type
        self.satellites = 0      # 衛星数
        self.eph = None          # 水平精度 (m)
        self.epv = None          # 垂直精度 (m)
        self.updated = False     # 位置が更新されたか

    def update(self, lat, lon, alt, fix_type, satellites, eph, epv):
        with self.lock:
            self.lat = lat
            self.lon = lon
            self.alt = alt
            self.fix_type = fix_type
            self.satellites = satellites
            self.eph = eph
            self.epv = epv
            self.updated = True

    def get(self):
        with self.lock:
            return {
                "lat": self.lat,
                "lon": self.lon,
                "alt": self.alt,
                "fix_type": self.fix_type,
                "satellites": self.satellites,
                "eph": self.eph,
                "epv": self.epv,
                "updated": self.updated,
            }

shared = SharedState()

# --- 統計情報 ---
stats = {
    "mavlink_connected": False,
    "ntrip_connected": False,
    "gps_raw_count": 0,
    "gga_sent_count": 0,
    "rtcm_chunk_count": 0,
    "rtcm_bytes": 0,
    "error_msg": "",
}


# --- NMEA変換関数 ---
def convert_to_nmea_format(lat, lon):
    """10進数の度をNMEA DDMM.MMMM形式に変換"""
    # 緯度
    lat_abs = abs(lat)
    lat_deg = int(lat_abs)
    lat_min = (lat_abs - lat_deg) * 60
    lat_nmea = f"{lat_deg:02d}{lat_min:07.4f}"
    lat_dir = "N" if lat >= 0 else "S"

    # 経度
    lon_abs = abs(lon)
    lon_deg = int(lon_abs)
    lon_min = (lon_abs - lon_deg) * 60
    lon_nmea = f"{lon_deg:03d}{lon_min:07.4f}"
    lon_dir = "E" if lon >= 0 else "W"

    return lat_nmea, lat_dir, lon_nmea, lon_dir


def generate_gga(lat, lon, alt, fix_type, satellites, eph):
    """
    MAVLink GPS_RAW_INTデータから $GNGGA センテンスを生成する。
    lat/lon: 10進数度, alt: メートル, fix_type: MAVLink fix_type
    """
    lat_nmea, lat_dir, lon_nmea, lon_dir = convert_to_nmea_format(lat, lon)

    # UTCタイムスタンプ (hhmmss.ss)
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%H%M%S.00")

    # fix_type → GGA quality indicator
    quality = FIX_TO_GGA_QUALITY.get(fix_type, 0)

    # HDOP: eph (m) から概算 (eph * 1.5 程度)
    hdop = f"{eph * 1.5:.1f}" if eph is not None else "1.0"

    # 高度 (MSL)
    alt_str = f"{alt:.1f}" if alt is not None else "0.0"

    # GGAボディ: 品質, 衛星数, HDOP, 高度, ジオイド高(0.0)
    body = f"GNGGA,{timestamp},{lat_nmea},{lat_dir},{lon_nmea},{lon_dir},{quality},{satellites},{hdop},{alt_str},M,0.0,M,,"

    # XORチェックサム計算
    checksum = 0
    for char in body:
        checksum ^= ord(char)

    # CRLF終端付きで返す
    gga_sentence = f"${body}*{checksum:02X}\r\n"
    return gga_sentence.encode('ascii')


# --- MAVLink受信スレッド ---
def mavlink_thread():
    """ArduPilotからGPS_RAW_INTを受信し、共有状態を更新する"""
    global stats

    print(f"\n📡 MAVLink接続中: {MAVLINK_PORT} @ {MAVLINK_BAUD}bps (RTS/CTS: {MAVLINK_RTSCTS})")

    try:
        master = mavutil.mavlink_connection(MAVLINK_PORT, baud=MAVLINK_BAUD, rtscts=MAVLINK_RTSCTS)
        master.wait_heartbeat(timeout=10)
        print(f"✅ MAVLink接続完了 (システム: {master.target_system}, コンポーネント: {master.target_component})")
        stats["mavlink_connected"] = True
    except Exception as e:
        stats["error_msg"] = f"MAVLink接続エラー: {e}"
        print(f"❌ MAVLink接続エラー: {e}")
        return

    # MAVLinkストリームレート設定
    print("📡 MAVLinkストリームレート設定中...")

    # GPS_RAW_INT (ID=24) を10Hzで要求
    master.mav.command_long_send(
        master.target_system,
        master.target_component,
        mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
        0,
        24,          # GPS_RAW_INT
        100000,      # 10Hz
        0, 0, 0, 0, 0
    )
    time.sleep(0.2)

    # GLOBAL_POSITION_INT (ID=33) を10Hzで要求
    master.mav.command_long_send(
        master.target_system,
        master.target_component,
        mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
        0,
        33,          # GLOBAL_POSITION_INT
        100000,      # 10Hz
        0, 0, 0, 0, 0
    )
    time.sleep(0.2)

    # REQUEST_DATA_STREAMでも要求
    master.mav.request_data_stream_send(
        master.target_system,
        master.target_component,
        mavutil.mavlink.MAV_DATA_STREAM_POSITION,
        10,
        1  # START
    )
    time.sleep(0.2)

    print("📡 GPSデータ受信開始...")

    try:
        while True:
            msg = master.recv_match(type=['GPS_RAW_INT', 'GLOBAL_POSITION_INT', 'STATUSTEXT'], blocking=True, timeout=2.0)

            if msg is None:
                continue

            msg_type = msg.get_type()

            if msg_type == 'GPS_RAW_INT':
                stats["gps_raw_count"] += 1
                lat = msg.lat / 1e7
                lon = msg.lon / 1e7
                alt = msg.alt / 1000
                fix_type = msg.fix_type
                satellites = msg.satellites_visible
                eph = msg.eph / 100
                epv = msg.epv / 100

                shared.update(lat, lon, alt, fix_type, satellites, eph, epv)

                # デバッグ表示 (1秒に1回程度)
                if stats["gps_raw_count"] % 10 == 1:
                    fix_status = GPS_FIX_TYPE.get(fix_type, f"UNKNOWN({fix_type})")
                    print(f"  📍 GPS_RAW_INT: {fix_status} | 衛星: {satellites} | "
                          f"緯度: {lat:.7f} | 経度: {lon:.7f} | 高度: {alt:.1f}m | EPH: {eph:.2f}m")

            elif msg_type == 'GLOBAL_POSITION_INT':
                # GLOBAL_POSITION_INTも受信したら共有状態を更新 (より正確な高度)
                lat = msg.lat / 1e7
                lon = msg.lon / 1e7
                alt = msg.alt / 1000
                # fix_typeはGPS_RAW_INTから取得するため、ここでは更新しない
                # ただし、GPS_RAW_INTがまだ来ていない場合は位置だけ更新
                if not shared.updated:
                    shared.update(lat, lon, alt, 0, 0, None, None)

            elif msg_type == 'STATUSTEXT':
                text = msg.text.rstrip('\x00')
                print(f"  [STATUSTEXT] {text}")

    except KeyboardInterrupt:
        print("\nMAVLink受信スレッド停止")
    except Exception as e:
        stats["error_msg"] = f"MAVLink受信エラー: {e}"
        print(f"❌ MAVLink受信エラー: {e}")
    finally:
        stats["mavlink_connected"] = False


# --- NTRIP受信スレッド ---
def ntrip_receiver_thread(sock):
    """NTRIPサーバーからRTCMデータを受信し、バイナリログに保存する"""
    global stats

    try:
        # ログディレクトリ作成
        log_dir = os.path.join(os.path.dirname(__file__), "logs")
        os.makedirs(log_dir, exist_ok=True)

        # セッションログファイル名
        session_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(log_dir, f"rtcm_{session_time}.rtcm3")

        # HTTPヘッダーを読み飛ばす (\r\n\r\nまで)
        header_data = b""
        while b"\r\n\r\n" not in header_data:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("サーバーがハンドシェイク中に接続を閉じました")
            header_data += chunk

        # ヘッダー以降のRTCMペイロードを抽出
        stream_start_idx = header_data.find(b"\r\n\r\n") + 4
        initial_rtcm = header_data[stream_start_idx:]

        print(f"✅ NTRIP接続確立。RTCMログ: {filename}")

        # バイナリログに保存
        with open(filename, "ab") as f:
            if initial_rtcm:
                f.write(initial_rtcm)
                stats["rtcm_chunk_count"] += 1
                stats["rtcm_bytes"] += len(initial_rtcm)

            while stats["ntrip_connected"]:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                f.write(chunk)
                f.flush()
                stats["rtcm_chunk_count"] += 1
                stats["rtcm_bytes"] += len(chunk)

    except Exception as e:
        stats["error_msg"] = f"NTRIP受信エラー: {e}"
        print(f"❌ NTRIP受信エラー: {e}")
    finally:
        stats["ntrip_connected"] = False


# --- NTRIP送信スレッド ---
def ntrip_sender_thread(sock):
    """共有状態から最新GPS位置を取得し、$GNGGAとして送信する"""
    global stats

    try:
        # 接続直後に最初のGGAを送信
        pos = shared.get()
        if pos["lat"] is not None and pos["lon"] is not None:
            gga = generate_gga(
                pos["lat"], pos["lon"], pos["alt"],
                pos["fix_type"], pos["satellites"], pos["eph"]
            )
            sock.sendall(gga)
            stats["gga_sent_count"] += 1
            print(f"  📤 GGA送信: {gga.decode('ascii').strip()}")

        while stats["ntrip_connected"]:
            time.sleep(GGA_SEND_INTERVAL)

            pos = shared.get()
            if pos["lat"] is None or pos["lon"] is None:
                # GPS位置がまだ取得できていない場合はスキップ
                continue

            gga = generate_gga(
                pos["lat"], pos["lon"], pos["alt"],
                pos["fix_type"], pos["satellites"], pos["eph"]
            )
            sock.sendall(gga)
            stats["gga_sent_count"] += 1

    except Exception as e:
        stats["error_msg"] = f"NTRIP送信エラー: {e}"
        print(f"❌ NTRIP送信エラー: {e}")
        stats["ntrip_connected"] = False


# --- NTRIP接続 ---
def ntrip_connect():
    """NTRIPサーバーに接続し、ソケットを返す"""
    global stats

    print(f"\n📡 NTRIP接続中: {NTRIP_SERVER}:{NTRIP_PORT} (マウントポイント: {NTRIP_MOUNT_POINT})")

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10.0)

    auth_str = f"{NTRIP_USERNAME}:{NTRIP_PASSWORD}"
    encoded_auth = base64.b64encode(auth_str.encode()).decode()

    request = (
        f"GET /{NTRIP_MOUNT_POINT} HTTP/1.1\r\n"
        f"Host: {NTRIP_SERVER}\r\n"
        f"User-Agent: NTRIP PythonClient/1.0\r\n"
        f"Authorization: Basic {encoded_auth}\r\n"
        f"Connection: close\r\n\r\n"
    ).encode('ascii')

    s.connect((NTRIP_SERVER, NTRIP_PORT))
    s.sendall(request)
    s.settimeout(None)  # ブロッキングモードに戻す

    stats["ntrip_connected"] = True
    return s


# --- メイン ---
def main():
    print("=" * 60)
    print("NTRIP RTKクライアント")
    print("=" * 60)
    print(f"MAVLink: {MAVLINK_PORT} @ {MAVLINK_BAUD}bps")
    print(f"NTRIP: {NTRIP_SERVER}:{NTRIP_PORT}/{NTRIP_MOUNT_POINT}")
    print(f"GGA送信間隔: {GGA_SEND_INTERVAL}秒")
    print("=" * 60)

    # MAVLink受信スレッド開始
    t_mavlink = threading.Thread(target=mavlink_thread, daemon=True)
    t_mavlink.start()

    # MAVLink接続を待つ
    time.sleep(2)

    # NTRIP接続ループ
    while True:
        try:
            # MAVLinkが接続されていない場合は待機
            if not stats["mavlink_connected"]:
                print("⏳ MAVLink接続待機中...")
                time.sleep(2)
                continue

            # NTRIP接続
            sock = ntrip_connect()

            # 受信・送信スレッド開始
            t_recv = threading.Thread(target=ntrip_receiver_thread, args=(sock,), daemon=True)
            t_send = threading.Thread(target=ntrip_sender_thread, args=(sock,), daemon=True)
            t_recv.start()
            t_send.start()

            # 接続状態モニタリング
            while stats["ntrip_connected"]:
                pos = shared.get()
                fix_status = GPS_FIX_TYPE.get(pos["fix_type"], f"UNKNOWN({pos['fix_type']})")
                print(f"  📊 GPS: {fix_status} | 衛星: {pos['satellites']} | "
                      f"GGA送信: {stats['gga_sent_count']} | "
                      f"RTCM受信: {stats['rtcm_chunk_count']} chunks ({stats['rtcm_bytes']} bytes)")
                time.sleep(5)

            print(f"⚠️ NTRIP切断。理由: {stats['error_msg']}")
            sock.close()

        except KeyboardInterrupt:
            print("\n\n停止しました。")
            break
        except Exception as e:
            print(f"❌ NTRIP接続エラー: {e}")
            stats["error_msg"] = str(e)

        print("5秒後に再接続します...")
        time.sleep(5)

    # サマリー表示
    print("\n" + "=" * 60)
    print("  実行結果サマリー")
    print("=" * 60)
    print(f"  GPS_RAW_INT受信数: {stats['gps_raw_count']}")
    print(f"  GGA送信数: {stats['gga_sent_count']}")
    print(f"  RTCM受信: {stats['rtcm_chunk_count']} chunks ({stats['rtcm_bytes']} bytes)")
    print("=" * 60)


if __name__ == "__main__":
    main()