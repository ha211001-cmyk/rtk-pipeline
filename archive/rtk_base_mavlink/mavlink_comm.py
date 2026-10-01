#!/usr/bin/env python3
"""
MAVLink Communication - ArduPilotとのMAVLink通信モジュール

Pixhawk6CからGPS位置情報を受信し、GPS_RTCM_DATAでRTCM補正データを送信する。

Usage:
    from mavlink_comm import MavlinkComm

    mav = MavlinkComm("/dev/ttyAMA0", baud=921600, rtscts=True)
    mav.connect()
    mav.start_gps_stream()
    pos = mav.get_gps_position()
    mav.send_rtcm_data(flags, length, data)
    mav.disconnect()
"""

import logging
import math
import sys
import threading
import time
from typing import Optional

try:
    from pymavlink import mavutil
except ImportError:
    print("エラー: pymavlinkがインストールされていません")
    print("  source ~/Mavlink_venv/bin/activate")
    sys.exit(1)


# GPS Fix状態定義
GPS_FIX_TYPE = {
    0: "NO_FIX",
    1: "NO_FIX",
    2: "2D_FIX",
    3: "3D_FIX",
    4: "DGPS_FIX",
    5: "RTK_FLOAT",
    6: "RTK_FIXED",
}


class MavlinkComm:
    """ArduPilotとのMAVLink通信クラス

    GPS位置情報の受信とRTCM補正データの送信を行う。

    Args:
        port: MAVLink接続ポート (例: /dev/ttyAMA0)
        baud: ボーレート (デフォルト: 921600)
        rtscts: RTS/CTSフロー制御の有効/無効
        logger: ロガーインスタンス
    """

    def __init__(self, port: str, baud: int = 921600, rtscts: bool = True,
                 logger: Optional[logging.Logger] = None):
        self.port = port
        self.baud = baud
        self.rtscts = rtscts
        self.log = logger or logging.getLogger("MavlinkComm")

        self._master = None
        self._connected = False
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # 共有GPS位置情報
        self._lock = threading.Lock()
        self._lat: Optional[float] = None
        self._lon: Optional[float] = None
        self._alt: Optional[float] = None
        self._fix_type: int = 0
        self._satellites: int = 0
        self._eph: Optional[float] = None
        self._epv: Optional[float] = None
        self._updated: bool = False
        self._last_update_time: float = 0.0

        # RTK 詳細（GPS_RTK メッセージ由来）
        self._baseline_m: Optional[float] = None
        self._rtk_health: int = -1
        self._rtk_nsats: int = 0

        # 統計情報
        self.stats = {
            'gps_raw_count': 0,
            'rtcm_packets_sent': 0,
            'rtcm_fragments_sent': 0,
        }

    def connect(self) -> bool:
        """MAVLink接続を確立する

        Returns:
            接続成功ならTrue
        """
        try:
            self._master = mavutil.mavlink_connection(
                self.port, baud=self.baud, rtscts=self.rtscts
            )
            self._master.wait_heartbeat(timeout=10)
            self._connected = True
            self.log.info(f"MAVLink接続完了: {self.port} @ {self.baud}bps "
                          f"(system={self._master.target_system}, "
                          f"component={self._master.target_component})")
            return True
        except Exception as e:
            self.log.error(f"MAVLink接続エラー: {e}")
            self._connected = False
            return False

    def disconnect(self) -> None:
        """MAVLink接続を切断する"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._master:
            try:
                self._master.close()
            except Exception:
                pass
        self._connected = False
        self.log.info("MAVLink切断")

    def start_gps_stream(self) -> None:
        """GPSデータストリームの受信を開始する

        GPS_RAW_INT (ID=24) と GLOBAL_POSITION_INT (ID=33) を10Hzで要求し、
        受信スレッドを起動する。
        """
        if not self._connected or not self._master:
            self.log.error("MAVLink未接続")
            return

        # GPS_RAW_INT (ID=24) を10Hzで要求
        self._master.mav.command_long_send(
            self._master.target_system,
            self._master.target_component,
            mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
            0,
            24,          # GPS_RAW_INT
            100000,      # 10Hz (100000us)
            0, 0, 0, 0, 0
        )
        time.sleep(0.2)

        # GLOBAL_POSITION_INT (ID=33) を10Hzで要求
        self._master.mav.command_long_send(
            self._master.target_system,
            self._master.target_component,
            mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
            0,
            33,          # GLOBAL_POSITION_INT
            100000,      # 10Hz
            0, 0, 0, 0, 0
        )
        time.sleep(0.2)

        # REQUEST_DATA_STREAMでも要求
        self._master.mav.request_data_stream_send(
            self._master.target_system,
            self._master.target_component,
            mavutil.mavlink.MAV_DATA_STREAM_POSITION,
            10,
            1  # START
        )
        time.sleep(0.2)

        # GPS_RTK (ID=127) を要求（基線長・RTK状態の取得用）
        self._master.mav.command_long_send(
            self._master.target_system,
            self._master.target_component,
            mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
            0,
            127,          # GPS_RTK
            500000,       # 2Hz
            0, 0, 0, 0, 0
        )
        time.sleep(0.2)

        # 受信スレッド起動
        self._running = True
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()
        self.log.info("GPSデータストリーム受信開始 (10Hz)")

    def _receive_loop(self) -> None:
        """MAVLinkメッセージ受信ループ（別スレッドで実行）"""
        if not self._master:
            return

        while self._running:
            try:
                msg = self._master.recv_match(
                    type=['GPS_RAW_INT', 'GPS_RTK', 'GLOBAL_POSITION_INT', 'STATUSTEXT'],
                    blocking=True,
                    timeout=2.0
                )
            except KeyboardInterrupt:
                break
            except Exception as e:
                self.log.warning(f"MAVLink受信エラー（再試行します）: {e}")
                time.sleep(0.5)
                continue

            if msg is None:
                continue

            msg_type = msg.get_type()

            if msg_type == 'GPS_RAW_INT':
                self.stats['gps_raw_count'] += 1
                lat = msg.lat / 1e7
                lon = msg.lon / 1e7
                alt = msg.alt / 1000
                fix_type = msg.fix_type
                satellites = msg.satellites_visible
                eph = msg.eph / 100 if msg.eph != 65535 else None
                epv = msg.epv / 100 if msg.epv != 65535 else None

                with self._lock:
                    self._lat = lat
                    self._lon = lon
                    self._alt = alt
                    self._fix_type = fix_type
                    self._satellites = satellites
                    self._eph = eph
                    self._epv = epv
                    self._updated = True
                    self._last_update_time = time.time()

                # デバッグ表示 (10回に1回)
                if self.stats['gps_raw_count'] % 10 == 1:
                    fix_status = GPS_FIX_TYPE.get(fix_type, f"UNKNOWN({fix_type})")
                    self.log.debug(
                        f"GPS: {fix_status} | 衛星: {satellites} | "
                        f"lat={lat:.7f} lon={lon:.7f} alt={alt:.1f}m "
                        f"EPH={eph:.2f}m" if eph else f"GPS: {fix_status}")

            elif msg_type == 'GLOBAL_POSITION_INT':
                # GLOBAL_POSITION_INTも受信したら共有状態を更新
                lat = msg.lat / 1e7
                lon = msg.lon / 1e7
                alt = msg.alt / 1000
                if not self._updated:
                    with self._lock:
                        self._lat = lat
                        self._lon = lon
                        self._alt = alt

            elif msg_type == 'GPS_RTK':
                # 基線長・RTK状態を取得
                bc = msg.baseline_coords  # [N,E,D] (mm)
                try:
                    baseline_m = math.sqrt(bc[0] ** 2 + bc[1] ** 2 + bc[2] ** 2) / 1000.0
                except (TypeError, IndexError):
                    baseline_m = None
                with self._lock:
                    self._baseline_m = baseline_m
                    self._rtk_health = msg.rtk_health
                    self._rtk_nsats = msg.nsats

            elif msg_type == 'STATUSTEXT':
                text = msg.text.rstrip('\x00')
                self.log.info(f"[ArduPilot] {text}")

    def get_gps_position(self) -> dict:
        """最新のGPS位置情報を取得する

        Returns:
            {
                'lat': float or None,      # 緯度 (10進数度)
                'lon': float or None,      # 経度 (10進数度)
                'alt': float or None,      # 高度 (m, MSL)
                'fix_type': int,           # MAVLink fix_type
                'fix_name': str,           # 人間可読なfix状態
                'satellites': int,         # 衛星数
                'eph': float or None,      # 水平精度 (m)
                'epv': float or None,      # 垂直精度 (m)
                'updated': bool,           # 位置が更新されたか
                'last_update_time': float, # 最終更新時刻
            }
        """
        with self._lock:
            return {
                'lat': self._lat,
                'lon': self._lon,
                'alt': self._alt,
                'fix_type': self._fix_type,
                'fix_name': GPS_FIX_TYPE.get(self._fix_type, f"UNKNOWN({self._fix_type})"),
                'satellites': self._satellites,
                'eph': self._eph,
                'epv': self._epv,
                'updated': self._updated,
                'last_update_time': self._last_update_time,
                'baseline_m': self._baseline_m,
                'rtk_health': self._rtk_health,
                'rtk_nsats': self._rtk_nsats,
            }

    def has_3d_fix(self) -> bool:
        """3D Fix以上（fix_type >= 3）を取得しているか

        Returns:
            3D Fix以上ならTrue
        """
        with self._lock:
            return self._fix_type >= 3 and self._updated

    def send_rtcm_data(self, flags: int, length: int, data: list) -> None:
        """GPS_RTCM_DATA (MAVLink ID:233) を送信する

        Args:
            flags: フラグバイト
                   Bit 0 (LSB): Is_Fragmented (分割あり=1, なし=0)
                   Bit 1-2:     Fragment_ID (0〜3)
                   Bit 3-7:     Sequence_ID (0〜31)
            length: 有効データ長 (バイト)
            data: 180バイトのデータ配列 (パディング含む)
        """
        if not self._connected or not self._master:
            self.log.error("MAVLink未接続のためRTCMデータ送信不可")
            return

        try:
            self._master.mav.gps_rtcm_data_send(flags, length, data)
        except Exception as e:
            self.log.error(f"GPS_RTCM_DATA送信エラー: {e}")

    @property
    def is_connected(self) -> bool:
        """MAVLink接続状態を返す"""
        return self._connected

    @property
    def target_system(self) -> int:
        """ターゲットシステムIDを返す"""
        return self._master.target_system if self._master else 0

    @property
    def target_component(self) -> int:
        """ターゲットコンポーネントIDを返す"""
        return self._master.target_component if self._master else 0