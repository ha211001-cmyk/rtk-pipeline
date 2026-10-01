#!/usr/bin/env python3
"""
RTK Fix Client - ichimill NTRIP + ArduPilot GPS_RTCM_DATA注入

ArduPilot (Pixhawk6C) からMAVLinkでGPS位置情報を受信し、
NMEA-0183 $GNGGA形式に変換してichimill NTRIPサーバーに送信。
サーバーから受信したRTCM3補正データをMAVLink GPS_RTCM_DATA (ID:233)
としてArduPilotに注入し、DroneCAN経由でH-RTK F9PのRTK Fixを実現する。

アーキテクチャ:
  [H-RTK F9P] ←DroneCAN→ [Pixhawk6C] ←MAVLink→ [本プログラム] ←NTRIP→ [ichimill]

使用方法:
    source ~/Mavlink_venv/bin/activate
    pip install pyrtcm  # 初回のみ
    python3 rtk_fix_client.py
"""

import sys
import os
import json
import time
import socket
import base64
import threading
import datetime
from collections import deque

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

RTCM_MAX_PACKET_SIZE = config["rtcm_inject"]["max_packet_size"]      # 180
RTCM_MAX_FRAGMENTS = config["rtcm_inject"]["max_fragments"]          # 4
RTCM_TARGET_SYSTEM = config["rtcm_inject"]["target_system"]          # 1
RTCM_TARGET_COMPONENT = config["rtcm_inject"]["target_component"]    # 1

RTCM_MAX_FRAME_SIZE = RTCM_MAX_PACKET_SIZE * RTCM_MAX_FRAGMENTS      # 720

# --- pymavlinkインポート ---
try:
    from pymavlink import mavutil
except ImportError:
    print("エラー: pymavlinkがインストールされていません")
    print("  source ~/Mavlink_venv/bin/activate")
    sys.exit(1)

# --- pyrtcmインポート（オプション） ---
try:
    from pyrtcm import RTCMReader, RTCMMessageError, RTCMParseError
    PYRTCM_AVAILABLE = True
except ImportError:
    PYRTCM_AVAILABLE = False
    print("⚠️ pyrtcmがインストールされていません（RTCM解析ログはスキップされます）")
    print("  pip install pyrtcm")

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

# MAVLink fix_type → NMEA GGA quality indicator
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
        self.last_update_time = 0

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
            self.last_update_time = time.time()

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
                "last_update_time": self.last_update_time,
            }

    def has_3d_fix(self):
        """3D Fix以上（fix_type >= 3）を取得しているか"""
        with self.lock:
            return self.fix_type >= 3 and self.updated

shared = SharedState()

# --- RTCMフレームキュー（NTRIP受信 → GPS_RTCM_DATA送信） ---
rtcm_frame_queue = deque()
rtcm_queue_lock = threading.Lock()
rtcm_queue_maxlen = 100  # 最大キュー長（メモリ保護）


# --- 統計情報 ---
class Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.mavlink_connected = False
        self.ntrip_connected = False
        self.gps_raw_count = 0
        self.gga_sent_count = 0
        self.rtcm_bytes_received = 0
        self.rtcm_frames_parsed = 0
        self.rtcm_frames_dropped = 0      # 720バイト超過でドロップ
        self.rtcm_packets_sent = 0         # GPS_RTCM_DATA送信数
        self.rtcm_fragments_sent = 0       # 分割パケット数
        self.error_msg = ""
        self.last_status_print = 0

    def set_error(self, msg):
        with self.lock:
            self.error_msg = msg

stats = Stats()


# =============================================================================
# NMEA変換関数
# =============================================================================

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


# =============================================================================
# RTCM3フレームパーサー
# =============================================================================

class RTCM3FrameParser:
    """
    RTCM3バイナリストリームから完全なフレームを抽出するパーサー。

    RTCM3フレーム構造:
      Byte 0:     0xD3 (プリアンブル)
      Byte 1-2:   [6bit reserved][10bit message_length]
      Byte 3..:   data (message_length bytes)
      Last 3:     CRC-24Q

    フレーム全体長 = 3 + message_length + 3 = message_length + 6
    """

    def __init__(self):
        self.buffer = bytearray()
        self.frame_count = 0

    def feed(self, data: bytes) -> list:
        """
        バイナリデータをフィードし、完全なRTCM3フレームのリストを返す。
        不完全なデータは内部バッファに保持される。
        """
        self.buffer.extend(data)
        frames = []

        while len(self.buffer) >= 6:  # 最小フレームサイズ
            # プリアンブル検索
            preamble_idx = self.buffer.find(0xD3)
            if preamble_idx < 0:
                # プリアンブルが見つからない → バッファクリア
                self.buffer.clear()
                break

            if preamble_idx > 0:
                # プリアンブル前のゴミデータを破棄
                self.buffer = self.buffer[preamble_idx:]

            if len(self.buffer) < 6:
                break

            # メッセージ長の抽出（10ビット）
            # Byte 1: bits 7-2 = reserved, bits 1-0 = message_length[9:8]
            # Byte 2: bits 7-0 = message_length[7:0]
            byte1 = self.buffer[1]
            byte2 = self.buffer[2]
            message_length = ((byte1 & 0x03) << 8) | byte2

            total_frame_length = message_length + 6  # 3 header + message_length + 3 CRC

            if total_frame_length > RTCM_MAX_FRAME_SIZE:
                # 720バイト超過 → このフレームをスキップ
                # 次のプリアンブルを探す
                next_preamble = self.buffer.find(0xD3, 1)
                if next_preamble > 0:
                    self.buffer = self.buffer[next_preamble:]
                else:
                    self.buffer.clear()
                continue

            if len(self.buffer) < total_frame_length:
                # フレームが不完全 → 次のデータを待つ
                break

            # 完全なフレームを抽出
            frame = bytes(self.buffer[:total_frame_length])
            self.buffer = self.buffer[total_frame_length:]
            self.frame_count += 1
            frames.append(frame)

        # バッファが大きくなりすぎないように制限
        if len(self.buffer) > RTCM_MAX_FRAME_SIZE * 4:
            # 異常に大きいバッファ → 次のプリアンブルまでスキップ
            next_preamble = self.buffer.find(0xD3, 1)
            if next_preamble > 0:
                self.buffer = self.buffer[next_preamble:]
            else:
                self.buffer.clear()

        return frames


# =============================================================================
# MAVLink受信スレッド
# =============================================================================

def mavlink_thread(master):
    """ArduPilotからGPS_RAW_INTを受信し、共有状態を更新する"""
    global stats

    print(f"\n📡 MAVLink接続中: {MAVLINK_PORT} @ {MAVLINK_BAUD}bps (RTS/CTS: {MAVLINK_RTSCTS})")

    try:
        master.wait_heartbeat(timeout=10)
        print(f"✅ MAVLink接続完了 (システム: {master.target_system}, コンポーネント: {master.target_component})")
        stats.mavlink_connected = True
    except Exception as e:
        stats.set_error(f"MAVLink接続エラー: {e}")
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
        100000,      # 10Hz (100000us)
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
            msg = master.recv_match(
                type=['GPS_RAW_INT', 'GLOBAL_POSITION_INT', 'GPS_RTCM_DATA', 'STATUSTEXT'],
                blocking=True,
                timeout=2.0
            )

            if msg is None:
                continue

            msg_type = msg.get_type()

            if msg_type == 'GPS_RAW_INT':
                stats.gps_raw_count += 1
                lat = msg.lat / 1e7
                lon = msg.lon / 1e7
                alt = msg.alt / 1000
                fix_type = msg.fix_type
                satellites = msg.satellites_visible
                eph = msg.eph / 100
                epv = msg.epv / 100

                shared.update(lat, lon, alt, fix_type, satellites, eph, epv)

                # デバッグ表示 (1秒に1回程度)
                if stats.gps_raw_count % 10 == 1:
                    fix_status = GPS_FIX_TYPE.get(fix_type, f"UNKNOWN({fix_type})")
                    print(f"  📍 GPS_RAW_INT: {fix_status} | 衛星: {satellites} | "
                          f"緯度: {lat:.7f} | 経度: {lon:.7f} | 高度: {alt:.1f}m | EPH: {eph:.2f}m")

            elif msg_type == 'GLOBAL_POSITION_INT':
                # GLOBAL_POSITION_INTも受信したら共有状態を更新 (より正確な高度)
                lat = msg.lat / 1e7
                lon = msg.lon / 1e7
                alt = msg.alt / 1000
                if not shared.updated:
                    shared.update(lat, lon, alt, 0, 0, None, None)

            elif msg_type == 'STATUSTEXT':
                text = msg.text.rstrip('\x00')
                print(f"  [STATUSTEXT] {text}")

    except KeyboardInterrupt:
        print("\nMAVLink受信スレッド停止")
    except Exception as e:
        stats.set_error(f"MAVLink受信エラー: {e}")
        print(f"❌ MAVLink受信エラー: {e}")
    finally:
        stats.mavlink_connected = False


# =============================================================================
# NTRIP接続・送受信スレッド
# =============================================================================

def ntrip_thread():
    """
    NTRIPサーバーに接続し、GGA送信とRTCM受信を行う。
    RTCM受信データはRTCM3FrameParserでフレームに分割し、キューに投入する。
    """
    global stats

    parser = RTCM3FrameParser()

    # ログディレクトリ作成
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(log_dir, exist_ok=True)
    session_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = os.path.join(log_dir, f"rtcm_{session_time}.rtcm3")

    while True:
        try:
            # GPS Fix待機
            if not shared.has_3d_fix():
                pos = shared.get()
                fix_status = GPS_FIX_TYPE.get(pos["fix_type"], f"UNKNOWN({pos['fix_type']})")
                print(f"⏳ GPS Fix待機中... (現在: {fix_status}, 衛星: {pos['satellites']})")
                time.sleep(2)
                continue

            # NTRIP接続
            print(f"\n📡 NTRIP接続中: {NTRIP_SERVER}:{NTRIP_PORT} (マウントポイント: {NTRIP_MOUNT_POINT})")

            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(10.0)

            auth_str = f"{NTRIP_USERNAME}:{NTRIP_PASSWORD}"
            encoded_auth = base64.b64encode(auth_str.encode()).decode()

            request = (
                f"GET /{NTRIP_MOUNT_POINT} HTTP/1.1\r\n"
                f"Host: {NTRIP_SERVER}\r\n"
                f"User-Agent: NTRIP RTKFixClient/1.0\r\n"
                f"Authorization: Basic {encoded_auth}\r\n"
                f"Connection: close\r\n\r\n"
            ).encode('ascii')

            s.connect((NTRIP_SERVER, NTRIP_PORT))
            s.sendall(request)
            s.settimeout(None)  # ブロッキングモードに戻す

            stats.ntrip_connected = True
            print(f"✅ NTRIP接続確立。RTCMログ: {log_filename}")

            # HTTPヘッダーを読み飛ばす (\r\n\r\nまで)
            header_data = b""
            while b"\r\n\r\n" not in header_data:
                chunk = s.recv(4096)
                if not chunk:
                    raise ConnectionError("サーバーがハンドシェイク中に接続を閉じました")
                header_data += chunk

            # ヘッダー以降のRTCMペイロードを抽出
            stream_start_idx = header_data.find(b"\r\n\r\n") + 4
            initial_rtcm = header_data[stream_start_idx:]

            # バイナリログファイルを開く
            log_file = open(log_filename, "ab")

            # 初期RTCMデータを処理
            if initial_rtcm:
                log_file.write(initial_rtcm)
                log_file.flush()
                stats.rtcm_bytes_received += len(initial_rtcm)

                frames = parser.feed(initial_rtcm)
                for frame in frames:
                    enqueue_rtcm_frame(frame)

            # 初回GGA送信
            pos = shared.get()
            if pos["lat"] is not None and pos["lon"] is not None:
                gga = generate_gga(
                    pos["lat"], pos["lon"], pos["alt"],
                    pos["fix_type"], pos["satellites"], pos["eph"]
                )
                s.sendall(gga)
                stats.gga_sent_count += 1
                print(f"  📤 初回GGA送信: {gga.decode('ascii').strip()}")

            last_gga_time = time.time()

            # 受信ループ
            while stats.ntrip_connected:
                # ソケットから受信（タイムアウト付き）
                s.settimeout(1.0)
                try:
                    chunk = s.recv(4096)
                except socket.timeout:
                    chunk = None
                s.settimeout(None)

                if chunk:
                    # RTCMデータをログに保存
                    log_file.write(chunk)
                    log_file.flush()
                    stats.rtcm_bytes_received += len(chunk)

                    # RTCMフレーム解析
                    frames = parser.feed(chunk)
                    for frame in frames:
                        enqueue_rtcm_frame(frame)

                # GGA定期送信
                now = time.time()
                if now - last_gga_time >= GGA_SEND_INTERVAL:
                    pos = shared.get()
                    if pos["lat"] is not None and pos["lon"] is not None:
                        gga = generate_gga(
                            pos["lat"], pos["lon"], pos["alt"],
                            pos["fix_type"], pos["satellites"], pos["eph"]
                        )
                        try:
                            s.sendall(gga)
                            stats.gga_sent_count += 1
                        except Exception:
                            break
                    last_gga_time = now

                # 切断検出
                if chunk is None or len(chunk) == 0:
                    # タイムアウトは無視、実際の切断のみ検出
                    pass

            log_file.close()
            s.close()
            stats.ntrip_connected = False
            print(f"⚠️ NTRIP切断。再接続します...")

        except KeyboardInterrupt:
            break
        except Exception as e:
            stats.set_error(f"NTRIPエラー: {e}")
            print(f"❌ NTRIPエラー: {e}")
            stats.ntrip_connected = False

        print("5秒後に再接続します...")
        time.sleep(5)


def enqueue_rtcm_frame(frame: bytes):
    """RTCMフレームをキューに投入（720バイト超過はドロップ）"""
    global stats

    if len(frame) > RTCM_MAX_FRAME_SIZE:
        stats.rtcm_frames_dropped += 1
        print(f"  ⚠️ RTCMフレームドロップ: {len(frame)}バイト (最大{RTCM_MAX_FRAME_SIZE}バイト超過)")
        return

    stats.rtcm_frames_parsed += 1

    with rtcm_queue_lock:
        rtcm_frame_queue.append(frame)
        # キューが溢れたら古いものを捨てる
        while len(rtcm_frame_queue) > rtcm_queue_maxlen:
            rtcm_frame_queue.popleft()
            stats.rtcm_frames_dropped += 1


# =============================================================================
# GPS_RTCM_DATA注入スレッド
# =============================================================================

def injector_thread(master):
    """
    RTCMフレームキューからフレームを取り出し、
    180バイトずつ分割してMAVLink GPS_RTCM_DATA (ID:233) でArduPilotに送信する。

    flags (1バイト) のビット構成:
      Bit 0 (LSB): Is_Fragmented  (分割あり=1, なし=0)
      Bit 1-2:     Fragment_ID    (0〜3)
      Bit 3-7:     Sequence_ID    (0〜31、フレームごとに+1)
    """
    global stats

    sequence_id = 0

    print("📡 GPS_RTCM_DATA注入スレッド開始")

    while True:
        try:
            # キューからフレームを取得
            frame = None
            with rtcm_queue_lock:
                if rtcm_frame_queue:
                    frame = rtcm_frame_queue.popleft()

            if frame is None:
                time.sleep(0.01)
                continue

            frame_len = len(frame)

            if frame_len <= RTCM_MAX_PACKET_SIZE:
                # 分割不要
                flags = (sequence_id << 3) | 0  # Is_Fragmented=0, Fragment_ID=0
                data = list(frame) + [0] * (RTCM_MAX_PACKET_SIZE - frame_len)

                master.mav.gps_rtcm_data_send(
                    flags,
                    len(frame),
                    data
                )
                stats.rtcm_packets_sent += 1

            else:
                # 分割送信
                num_fragments = (frame_len + RTCM_MAX_PACKET_SIZE - 1) // RTCM_MAX_PACKET_SIZE

                if num_fragments > RTCM_MAX_FRAGMENTS:
                    print(f"  ⚠️ フレーム分割数超過: {num_fragments} > {RTCM_MAX_FRAGMENTS} (ドロップ)")
                    stats.rtcm_frames_dropped += 1
                    continue

                for frag_id in range(num_fragments):
                    start = frag_id * RTCM_MAX_PACKET_SIZE
                    end = min(start + RTCM_MAX_PACKET_SIZE, frame_len)
                    frag_data = frame[start:end]
                    frag_len = len(frag_data)

                    flags = (sequence_id << 3) | (frag_id << 1) | 1  # Is_Fragmented=1

                    data = list(frag_data) + [0] * (RTCM_MAX_PACKET_SIZE - frag_len)

                    master.mav.gps_rtcm_data_send(
                        flags,
                        frag_len,
                        data
                    )
                    stats.rtcm_fragments_sent += 1
                    time.sleep(0.005)  # 分割パケット間の微小ディレイ

                stats.rtcm_packets_sent += 1

            # Sequence ID更新（0〜31を巡回）
            sequence_id = (sequence_id + 1) % 32

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"❌ GPS_RTCM_DATA送信エラー: {e}")
            time.sleep(0.1)


# =============================================================================
# ステータスモニタースレッド
# =============================================================================

def status_monitor_thread():
    """定期的にステータスを表示する"""
    while True:
        try:
            time.sleep(5)

            pos = shared.get()
            fix_status = GPS_FIX_TYPE.get(pos["fix_type"], f"UNKNOWN({pos['fix_type']})")

            print(f"\n{'=' * 60}")
            print(f"  📊 ステータス [{datetime.datetime.now().strftime('%H:%M:%S')}]")
            print(f"  {'─' * 40}")
            print(f"  MAVLink: {'✅接続' if stats.mavlink_connected else '❌切断'}")
            print(f"  NTRIP:   {'✅接続' if stats.ntrip_connected else '❌切断'}")
            if pos['eph'] is not None:
                print(f"  GPS:     {fix_status} | 衛星: {pos['satellites']} | EPH: {pos['eph']:.2f}m")
            else:
                print(f"  GPS:     {fix_status} | 衛星: {pos['satellites']}")
            print(f"  {'─' * 40}")
            print(f"  GPS_RAW_INT受信:     {stats.gps_raw_count}")
            print(f"  GGA送信:             {stats.gga_sent_count}")
            print(f"  RTCM受信バイト:      {stats.rtcm_bytes_received}")
            print(f"  RTCMフレーム解析:    {stats.rtcm_frames_parsed}")
            print(f"  RTCMフレームドロップ: {stats.rtcm_frames_dropped}")
            print(f"  GPS_RTCM_DATA送信:   {stats.rtcm_packets_sent} フレーム "
                  f"({stats.rtcm_fragments_sent} 分割パケット)")
            print(f"  キュー長:            {len(rtcm_frame_queue)}")
            if stats.error_msg:
                print(f"  ⚠️ エラー: {stats.error_msg}")
            print(f"{'=' * 60}")

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"ステータス表示エラー: {e}")


# =============================================================================
# メイン
# =============================================================================

def main():
    print("=" * 60)
    print("RTK Fix Client - ichimill NTRIP + GPS_RTCM_DATA注入")
    print("=" * 60)
    print(f"MAVLink: {MAVLINK_PORT} @ {MAVLINK_BAUD}bps (RTS/CTS: {MAVLINK_RTSCTS})")
    print(f"NTRIP:   {NTRIP_SERVER}:{NTRIP_PORT}/{NTRIP_MOUNT_POINT}")
    print(f"GGA送信間隔: {GGA_SEND_INTERVAL}秒")
    print(f"RTCM最大パケット: {RTCM_MAX_PACKET_SIZE}バイト × {RTCM_MAX_FRAGMENTS}分割 = {RTCM_MAX_FRAME_SIZE}バイト")
    print(f"pyrtcm: {'✅利用可能' if PYRTCM_AVAILABLE else '❌未インストール'}")
    print("=" * 60)

    # MAVLink接続
    print(f"\n📡 MAVLink接続中: {MAVLINK_PORT} @ {MAVLINK_BAUD}bps (RTS/CTS: {MAVLINK_RTSCTS})")

    try:
        master = mavutil.mavlink_connection(MAVLINK_PORT, baud=MAVLINK_BAUD, rtscts=MAVLINK_RTSCTS)
    except Exception as e:
        print(f"❌ MAVLink接続エラー: {e}")
        sys.exit(1)

    # スレッド起動
    threads = []

    # MAVLink受信スレッド
    t_mavlink = threading.Thread(target=mavlink_thread, args=(master,), daemon=True)
    t_mavlink.start()
    threads.append(t_mavlink)

    # MAVLink接続を待つ
    time.sleep(2)

    if not stats.mavlink_connected:
        print("❌ MAVLinkに接続できませんでした。終了します。")
        sys.exit(1)

    # NTRIPスレッド
    t_ntrip = threading.Thread(target=ntrip_thread, daemon=True)
    t_ntrip.start()
    threads.append(t_ntrip)

    # GPS_RTCM_DATA注入スレッド
    t_injector = threading.Thread(target=injector_thread, args=(master,), daemon=True)
    t_injector.start()
    threads.append(t_injector)

    # ステータスモニタースレッド
    t_monitor = threading.Thread(target=status_monitor_thread, daemon=True)
    t_monitor.start()
    threads.append(t_monitor)

    # メインスレッドはキーボード割り込み待ち
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n🛑 停止シグナル受信。終了します...")

    # サマリー表示
    print("\n" + "=" * 60)
    print("  実行結果サマリー")
    print("=" * 60)
    print(f"  GPS_RAW_INT受信数:     {stats.gps_raw_count}")
    print(f"  GGA送信数:             {stats.gga_sent_count}")
    print(f"  RTCM受信バイト:        {stats.rtcm_bytes_received}")
    print(f"  RTCMフレーム解析:      {stats.rtcm_frames_parsed}")
    print(f"  RTCMフレームドロップ:  {stats.rtcm_frames_dropped}")
    print(f"  GPS_RTCM_DATA送信:     {stats.rtcm_packets_sent} フレーム "
          f"({stats.rtcm_fragments_sent} 分割パケット)")
    print("=" * 60)


if __name__ == "__main__":
    main()