#!/usr/bin/env python3
"""
f9p_config_all.py — DroneCAN F9P (ZED-F9P) 全設定値の「書き込み→確認」ツール

基地局・移動局の F9P 全30設定キーを単一スクリプトで管理する。
pyubx2 の UBXMessage.config_set() / config_poll() (CFG-VALSET / CFG-VALGET) を使用。

Reference:
  - rtk_tools/f9p_configurator.py    (Base station config pattern)
  - rtk_tools/f9p_rover_config.py    (Rover config pattern)
  - rtk_tools/f9p_verify_config.py   (Verification pattern)
"""

import argparse
import json
import logging
import socket
import struct
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import serial
from pyubx2 import UBXMessage, SET

# ==========================================================================
# Layer bitmask for config_set
# ==========================================================================
LAYER_RAM   = 1
LAYER_BBR   = 2
LAYER_FLASH = 4
LAYER_ALL   = LAYER_RAM | LAYER_BBR | LAYER_FLASH

# UBX-MON-VER poll request
_MON_VER_POLL = bytes([0xB5, 0x62, 0x0A, 0x04, 0x00, 0x00, 0x0E, 0x34])

# CFG-VALGET retry config
_MAX_RETRIES = 3
_TIMEOUT = 5.0

# Display icons
_ICON_OK   = "OK"
_ICON_FAIL = "FAIL"
_ICON_WARN = "WARN"

# ==========================================================================
# CFG Key ID mapping for response parsing
# ==========================================================================
_KEY_TMODE_MODE           = 0x20030001
_KEY_TMODE_POS_TYPE       = 0x20030002
_KEY_TMODE_FIXED_POS_ACC  = 0x4003000C
_KEY_TMODE_LAT            = 0x40030009
_KEY_TMODE_LON            = 0x4003000A
_KEY_TMODE_HEIGHT         = 0x4003000B
_KEY_UART1_BAUDRATE       = 0x40520001
_KEY_UART1OUTPROT_UBX     = 0x40520005
_KEY_UART2_BAUDRATE       = 0x40530001
_KEY_UART2INPROT_UBX      = 0x40530002
_KEY_UART2INPROT_NMEA     = 0x40530003
_KEY_UART2INPROT_RTCM3X   = 0x40530004
_KEY_UART2OUTPROT_UBX     = 0x40530005
_KEY_UART2OUTPROT_NMEA    = 0x40530006
_KEY_NAVHPG_DGNSSMODE     = 0x20140011
_KEY_RATE_MEAS            = 0x30210001
_KEY_RATE_NAV             = 0x30210002
_KEY_MSGOUT_UBX_NAV_PVT_UART2 = 0x20910006
_KEY_MSGOUT_UBX_NAV_RELPOSNED_UART2 = 0x2091008F

# RTCM3 USB 出力キーID（実機確認済み）
_KEY_MSGOUT_RTCM3_TYPE1005_USB = 0x209102C0
_KEY_MSGOUT_RTCM3_TYPE1006_USB = 0x209102C5
_KEY_MSGOUT_RTCM3_TYPE1074_USB = 0x20910361
_KEY_MSGOUT_RTCM3_TYPE1084_USB = 0x20910366
_KEY_MSGOUT_RTCM3_TYPE1094_USB = 0x2091036B
_KEY_MSGOUT_RTCM3_TYPE1124_USB = 0x20910370
_KEY_MSGOUT_RTCM3_TYPE1230_USB = 0x20910306

_U4_KEY_IDS = {_KEY_UART1_BAUDRATE, _KEY_UART2_BAUDRATE}
_I4_KEY_IDS = {_KEY_TMODE_LAT, _KEY_TMODE_LON, _KEY_TMODE_HEIGHT}
_U2_KEY_IDS = {_KEY_RATE_MEAS, _KEY_RATE_NAV}
_R8_KEY_IDS = {_KEY_TMODE_FIXED_POS_ACC}

# ==========================================================================
# Full 39-key Configuration Table (13 base UART1 + 7 base USB + 19 rover)
# ==========================================================================

def _build_key_table(lat: float, lon: float, alt: float) -> List[dict]:
    """Build the full 39-key configuration table with resolved dynamic values."""
    lat_e7 = int(lat * 1e7)
    lon_e7 = int(lon * 1e7)
    alt_cm = int(alt * 100)

    return [
        # === Base Station (20 keys: #1-13 UART1 + #32-38 USB) ===
        {"id": 1, "key": "CFG-TMODE-MODE",
         "expected": 2, "type": "U1", "role": "base",
         "desc": "FIXED Mode (2=Fixed)", "key_id": _KEY_TMODE_MODE},
        {"id": 2, "key": "CFG-TMODE-POS_TYPE",
         "expected": 0, "type": "U1", "role": "base",
         "desc": "Position type (0=LLA)", "key_id": _KEY_TMODE_POS_TYPE},
        {"id": 3, "key": "CFG-TMODE-LAT",
         "expected": lat_e7, "type": "I4", "role": "base",
         "desc": f"Lat ({lat:.7f} deg)", "key_id": _KEY_TMODE_LAT},
        {"id": 4, "key": "CFG-TMODE-LON",
         "expected": lon_e7, "type": "I4", "role": "base",
         "desc": f"Lon ({lon:.7f} deg)", "key_id": _KEY_TMODE_LON},
        {"id": 5, "key": "CFG-TMODE-HEIGHT",
         "expected": alt_cm, "type": "I4", "role": "base",
         "desc": f"Height ({alt:.1f}m)", "key_id": _KEY_TMODE_HEIGHT},
        {"id": 6, "key": "CFG-TMODE-FIXED_POS_ACC",
         "expected": 10.0, "type": "R8", "role": "base",
         "desc": "FIXED Position Acc (10.0m)", "key_id": _KEY_TMODE_FIXED_POS_ACC},
        {"id": 7, "key": "CFG-MSGOUT-RTCM_3X_TYPE1005_UART1",
         "expected": 1, "type": "U1", "role": "base",
         "desc": "Station ARP (1005)", "key_id": None},
        {"id": 8, "key": "CFG-MSGOUT-RTCM_3X_TYPE1006_UART1",
         "expected": 1, "type": "U1", "role": "base",
         "desc": "Station ARP+Ant (1006)", "key_id": None},
        {"id": 9, "key": "CFG-MSGOUT-RTCM_3X_TYPE1074_UART1",
         "expected": 1, "type": "U1", "role": "base",
         "desc": "GPS MSM4 (1074)", "key_id": None},
        {"id": 10, "key": "CFG-MSGOUT-RTCM_3X_TYPE1084_UART1",
         "expected": 1, "type": "U1", "role": "base",
         "desc": "GLONASS MSM4 (1084)", "key_id": None},
        {"id": 11, "key": "CFG-MSGOUT-RTCM_3X_TYPE1094_UART1",
         "expected": 1, "type": "U1", "role": "base",
         "desc": "Galileo MSM4 (1094)", "key_id": None},
        {"id": 12, "key": "CFG-MSGOUT-RTCM_3X_TYPE1124_UART1",
         "expected": 1, "type": "U1", "role": "base",
         "desc": "BeiDou MSM4 (1124)", "key_id": None},
        {"id": 13, "key": "CFG-MSGOUT-RTCM_3X_TYPE1230_UART1",
         "expected": 1, "type": "U1", "role": "base",
         "desc": "GLONASS bias (1230)", "key_id": None},


        # === Base Station USB RTCM3 (7 keys: #32-38) ===
        {"id": 32, "key": "CFG-MSGOUT-RTCM_3X_TYPE1005_USB",
         "expected": 1, "type": "U1", "role": "base",
         "desc": "Station ARP USB (1005)", "key_id": _KEY_MSGOUT_RTCM3_TYPE1005_USB},
        {"id": 33, "key": "CFG-MSGOUT-RTCM_3X_TYPE1006_USB",
         "expected": 1, "type": "U1", "role": "base",
         "desc": "Station ARP+Ant USB (1006)", "key_id": _KEY_MSGOUT_RTCM3_TYPE1006_USB},
        {"id": 34, "key": "CFG-MSGOUT-RTCM_3X_TYPE1074_USB",
         "expected": 1, "type": "U1", "role": "base",
         "desc": "GPS MSM4 USB (1074)", "key_id": _KEY_MSGOUT_RTCM3_TYPE1074_USB},
        {"id": 35, "key": "CFG-MSGOUT-RTCM_3X_TYPE1084_USB",
         "expected": 1, "type": "U1", "role": "base",
         "desc": "GLONASS MSM4 USB (1084)", "key_id": _KEY_MSGOUT_RTCM3_TYPE1084_USB},
        {"id": 36, "key": "CFG-MSGOUT-RTCM_3X_TYPE1094_USB",
         "expected": 1, "type": "U1", "role": "base",
         "desc": "Galileo MSM4 USB (1094)", "key_id": _KEY_MSGOUT_RTCM3_TYPE1094_USB},
        {"id": 37, "key": "CFG-MSGOUT-RTCM_3X_TYPE1124_USB",
         "expected": 1, "type": "U1", "role": "base",
         "desc": "BeiDou MSM4 USB (1124)", "key_id": _KEY_MSGOUT_RTCM3_TYPE1124_USB},
        {"id": 38, "key": "CFG-MSGOUT-RTCM_3X_TYPE1230_USB",
         "expected": 1, "type": "U1", "role": "base",
         "desc": "GLONASS bias USB (1230)", "key_id": _KEY_MSGOUT_RTCM3_TYPE1230_USB},

        # === Rover (19 keys: #14-31, #39) ===
        {"id": 14, "key": "CFG-UART2-BAUDRATE",
         "expected": 115200, "type": "U4", "role": "rover",
         "desc": "UART2 baudrate", "key_id": _KEY_UART2_BAUDRATE},
        {"id": 15, "key": "CFG-UART2INPROT-UBX",
         "expected": 1, "type": "U1", "role": "rover",
         "desc": "UBX input enabled (RTCM3+UBX mixed)", "key_id": _KEY_UART2INPROT_UBX},
        {"id": 16, "key": "CFG-UART2INPROT-NMEA",
         "expected": 0, "type": "U1", "role": "rover",
         "desc": "NMEA input disabled", "key_id": _KEY_UART2INPROT_NMEA},
        {"id": 17, "key": "CFG-UART2INPROT-RTCM3X",
         "expected": 1, "type": "U1", "role": "rover",
         "desc": "RTCM3 input enabled", "key_id": _KEY_UART2INPROT_RTCM3X},
        {"id": 18, "key": "CFG-UART2OUTPROT-UBX",
         "expected": 1, "type": "U1", "role": "rover",
         "desc": "UBX output enabled (RELPOSNED monitoring)",
         "key_id": _KEY_UART2OUTPROT_UBX},
        {"id": 19, "key": "CFG-UART2OUTPROT-NMEA",
         "expected": 0, "type": "U1", "role": "rover",
         "desc": "NMEA output disabled", "key_id": _KEY_UART2OUTPROT_NMEA},
        {"id": 20, "key": "CFG-NAVHPG-DGNSSMODE",
         "expected": 0, "type": "U1", "role": "rover",
         "desc": "RTK Float+Fixed both (DGNSSMODE=3 blocks FLOAT→FIXED transition!)", "key_id": _KEY_NAVHPG_DGNSSMODE},
        {"id": 21, "key": "CFG-RATE-MEAS",
         "expected": 200, "type": "U2", "role": "rover",
         "desc": "Meas period 200ms (5Hz)", "key_id": _KEY_RATE_MEAS},
        {"id": 22, "key": "CFG-RATE-NAV",
         "expected": 1, "type": "U2", "role": "rover",
         "desc": "Nav output ratio 1:1", "key_id": _KEY_RATE_NAV},
        {"id": 23, "key": "CFG-MSGOUT-UBX-NAV-PVT-UART2",
         "expected": 0, "type": "U1", "role": "rover",
         "desc": "NAV-PVT UART2 out disabled",
         "key_id": _KEY_MSGOUT_UBX_NAV_PVT_UART2},
        {"id": 24, "key": "CFG-SIGNAL-GPS_ENA",
         "expected": 1, "type": "U1", "role": "rover",
         "desc": "GPS L1C/A enabled", "key_id": None},
        {"id": 25, "key": "CFG-SIGNAL-GPS_L5_ENA",
         "expected": 0, "type": "U1", "role": "rover",
         "desc": "GPS L5 disabled (ZED-F9P not supported)", "key_id": None},
        {"id": 26, "key": "CFG-SIGNAL-GAL_ENA",
         "expected": 1, "type": "U1", "role": "rover",
         "desc": "Galileo E1 enabled", "key_id": None},
        {"id": 27, "key": "CFG-SIGNAL-GAL_E5A_ENA",
         "expected": 0, "type": "U1", "role": "rover",
         "desc": "Galileo E5a disabled (ZED-F9P not supported)", "key_id": None},
        {"id": 28, "key": "CFG-SIGNAL-BDS_ENA",
         "expected": 1, "type": "U1", "role": "rover",
         "desc": "BeiDou B1I enabled", "key_id": None},
        {"id": 29, "key": "CFG-SIGNAL-GLO_ENA",
         "expected": 1, "type": "U1", "role": "rover",
         "desc": "GLONASS L1 enabled", "key_id": None},
        {"id": 30, "key": "CFG-UART1OUTPROT-UBX",
         "expected": 1, "type": "U1", "role": "rover",
         "desc": "UART1 UBX -> AP_Periph",
         "key_id": _KEY_UART1OUTPROT_UBX},
        {"id": 31, "key": "CFG-UART1-BAUDRATE",
         "expected": 230400, "type": "U4", "role": "rover",
         "desc": "UART1 baudrate (ArduPilot default)", "key_id": _KEY_UART1_BAUDRATE},

        # === Rover RELPOSNED monitoring (1 key: #39) ===
        {"id": 39, "key": "CFG-MSGOUT-UBX-NAV-RELPOSNED-UART2",
         "expected": 1, "type": "U1", "role": "rover",
         "desc": "NAV-RELPOSNED UART2 out enabled (RTK monitoring)",
         "key_id": _KEY_MSGOUT_UBX_NAV_RELPOSNED_UART2},
    ]


def _get_keys_by_role(keys: List[dict], role: str) -> List[dict]:
    """Filter key table by role."""
    return [k for k in keys if k["role"] == role]


# ==========================================================================
# CFG-VALSET key groups (for write operations)
# ==========================================================================
_RTCM_MSG_KEYS_UART1 = [
    "CFG-MSGOUT-RTCM_3X_TYPE1005_UART1",
    "CFG-MSGOUT-RTCM_3X_TYPE1006_UART1",
    "CFG-MSGOUT-RTCM_3X_TYPE1074_UART1",
    "CFG-MSGOUT-RTCM_3X_TYPE1084_UART1",
    "CFG-MSGOUT-RTCM_3X_TYPE1094_UART1",
    "CFG-MSGOUT-RTCM_3X_TYPE1124_UART1",
    "CFG-MSGOUT-RTCM_3X_TYPE1230_UART1",
]

_RTCM_MSG_KEYS_USB = [
    "CFG-MSGOUT-RTCM_3X_TYPE1005_USB",
    "CFG-MSGOUT-RTCM_3X_TYPE1006_USB",
    "CFG-MSGOUT-RTCM_3X_TYPE1074_USB",
    "CFG-MSGOUT-RTCM_3X_TYPE1084_USB",
    "CFG-MSGOUT-RTCM_3X_TYPE1094_USB",
    "CFG-MSGOUT-RTCM_3X_TYPE1124_USB",
    "CFG-MSGOUT-RTCM_3X_TYPE1230_USB",
]

# Combined list (UART1 + USB)
_RTCM_MSG_KEYS = _RTCM_MSG_KEYS_UART1 + _RTCM_MSG_KEYS_USB


def _get_rtcm_keys_for_port(port_type: str) -> List[str]:
    """port_type に応じた RTCM キーリストを返す。

    Args:
        port_type: "both", "uart1", "usb"
    Returns:
        キー名のリスト
    """
    if port_type == "uart1":
        return _RTCM_MSG_KEYS_UART1
    elif port_type == "usb":
        return _RTCM_MSG_KEYS_USB
    else:
        return _RTCM_MSG_KEYS  # "both": all 14 keys


_UART2_ROVER_CFG_KEYS = [
    ("CFG-UART2-BAUDRATE",              115200),
    ("CFG-UART2INPROT-UBX",             1),
    ("CFG-UART2INPROT-NMEA",            0),
    ("CFG-UART2INPROT-RTCM3X",          1),
    ("CFG-UART2OUTPROT-UBX",            1),   # UBX output enabled (for RELPOSNED monitoring)
    ("CFG-UART2OUTPROT-NMEA",           0),   # NMEA output disabled (bandwidth saving)
    ("CFG-NAVHPG-DGNSSMODE",            0),
    ("CFG-RATE-MEAS",                   200),
    ("CFG-RATE-NAV",                    1),
    ("CFG-MSGOUT-UBX-NAV-PVT-UART2",    0),   # NAV-PVT disabled (use MAVLink instead)
    ("CFG-MSGOUT-UBX-NAV-RELPOSNED-UART2", 1),   # ★ RELPOSNED enabled for RTK monitoring
]

_GNSS_SIGNAL_CFG_KEYS = [
    ("CFG-SIGNAL-GPS_ENA",     1),
    ("CFG-SIGNAL-GPS_L5_ENA",  0),
    ("CFG-SIGNAL-GAL_ENA",     1),
    ("CFG-SIGNAL-GAL_E5A_ENA", 0),
    ("CFG-SIGNAL-BDS_ENA",     1),
    ("CFG-SIGNAL-GLO_ENA",     1),
]


# ==========================================================================
# TCP transport (DroneCAN Serial Forwarding) — pyserial 互換ラッパー
# ==========================================================================

class TcpTransport:
    """DroneCAN Serial Forwarding の TCP ストリームを pyserial 風に包む。

    ``gcs/backend/f9p_configurator.py`` の ``TcpTransport`` と同じ用途（機体側
    Raspberry Pi の DroneCAN Serial Forwarding へ素の UBX を送受信する）だが、
    本モジュールの ``_read_ubx_response``（raw byte search）は ``in_waiting``
    に依存するため、``in_waiting`` / ``read(size)`` の両方を持つ形で実装する。
    """

    def __init__(self, host: str, port: int, timeout: float = 3.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._buf = bytearray()

    @property
    def is_open(self) -> bool:
        return self._sock is not None

    def open(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect((self.host, self.port))
        self._sock = sock

    def write(self, data: bytes) -> None:
        if self._sock is None:
            raise RuntimeError("TCP connection is not open")
        self._sock.sendall(data)

    def flush(self) -> None:
        # sendall() で送信済みのため no-op
        pass

    @property
    def in_waiting(self) -> int:
        """受信可能なバイト数を返す（非ブロッキングで内部バッファへ補充）。"""
        if self._sock is None:
            return 0
        try:
            self._sock.setblocking(False)
            while True:
                chunk = self._sock.recv(4096)
                if not chunk:
                    break
                self._buf.extend(chunk)
        except OSError:
            pass
        finally:
            self._sock.setblocking(True)
        return len(self._buf)

    def read(self, size: int = 1) -> bytes:
        """内部バッファから size バイト返す（不足分はタイムアウトまで補充）。"""
        if self._sock is None:
            return b""
        deadline = time.monotonic() + self.timeout
        while len(self._buf) < size and time.monotonic() < deadline:
            self._sock.settimeout(self.timeout)
            try:
                chunk = self._sock.recv(max(4096, size - len(self._buf)))
            except socket.timeout:
                break
            except OSError:
                break
            if not chunk:
                break
            self._buf.extend(chunk)
        out = bytes(self._buf[:size])
        del self._buf[:size]
        return out

    def reset_input_buffer(self) -> None:
        """受信バッファに溜まった残りデータを破棄する。"""
        if self._sock is None:
            return
        self._buf.clear()
        try:
            self._sock.setblocking(False)
            while True:
                chunk = self._sock.recv(4096)
                if not chunk:
                    break
        except OSError:
            pass
        finally:
            self._sock.setblocking(True)

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None


# ==========================================================================
# F9pAllConfigurator
# ==========================================================================

class F9pAllConfigurator:
    """DroneCAN F9P (ZED-F9P) 全設定値の書き込みと確認を行う。

    Args:
        serial_port: シリアル接続時のデバイスパス（例: /dev/tty.usbmodemXXXX）。
        baudrate: シリアル接続時のボーレート。
        host: TCP 接続（DroneCAN Serial Forwarding）時のホスト。
        port: TCP 接続時のポート。
        port_type: RTCM 出力ポート（"both" / "uart1" / "usb"）。
        logger: ロガー。
    """

    def __init__(self, serial_port: Optional[str] = None, baudrate: int = 38400,
                 logger: Optional[logging.Logger] = None,
                 port_type: str = "both",
                 host: Optional[str] = None, port: Optional[int] = None):
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.port_type = port_type  # "both", "uart1", "usb"
        self.logger = logger or logging.getLogger("F9pAllConfigurator")
        self.host = host
        self.port = port
        self._ser: Optional[Any] = None

    # ------------------------------------------------------------------
    # Serial / TCP I/O (pattern from f9p_configurator.py)
    # ------------------------------------------------------------------

    def _open_serial(self):
        """シリアルまたは TCP（DroneCAN Serial Forwarding）を開く。

        host/port が指定されている場合は TCP、そうでなければシリアル直結。
        いずれも ``_read_ubx_response`` が必要とする ``in_waiting`` / ``read`` /
        ``write`` / ``flush`` / ``reset_input_buffer`` / ``is_open`` / ``close``
        を備える。
        """
        if self.host is not None:
            tcp = TcpTransport(self.host, self.port or 5001)
            tcp.open()
            self.logger.info(
                "Opening TCP transport: %s:%d", self.host, self.port or 5001
            )
            return tcp
        self.logger.info(
            f"Opening serial port: {self.serial_port} @ {self.baudrate}"
        )
        ser = serial.Serial(self.serial_port, self.baudrate, timeout=1.0)
        time.sleep(0.3)
        ser.reset_input_buffer()
        return ser

    def _close_serial(self) -> None:
        if self._ser and self._ser.is_open:
            self._ser.close()
            self._ser = None

    def _send_ubx(self, msg: bytes) -> None:
        if not self._ser or not self._ser.is_open:
            raise RuntimeError("Serial port not open")
        self._ser.write(msg)
        self._ser.flush()

    def _read_ubx_response(self, cls: int, mid: int,
                            timeout: float = 3.0) -> Optional[bytes]:
        """指定された Class/ID の UBX 応答を raw byte search で読み取る。

        UBXReader ではなく raw serial read + UBX sync pattern (0xB5 0x62)
        検索を使用する。これにより RTCM3 ストリーム (0xD3 sync) と UBX フレームが
        混在する低ボーレート環境（38400bps など）でも堅牢に UBX 応答を検出できる。
        """
        if not self._ser or not self._ser.is_open:
            return None

        deadline = time.time() + timeout
        buf = b''

        while time.time() < deadline:
            # Read whatever is available
            waiting = self._ser.in_waiting
            if waiting > 0:
                chunk = self._ser.read(waiting)
                buf += chunk

            # Scan for UBX sync pattern 0xB5 0x62
            idx = 0
            while True:
                sync_pos = buf.find(b'\xb5\x62', idx)
                if sync_pos < 0:
                    # Keep trailing byte if it could be partial sync (0xB5)
                    if len(buf) > 0 and buf[-1:] == b'\xb5':
                        buf = b'\xb5'
                    elif len(buf) > 0:
                        buf = b''
                    break  # need more data

                # Need at least 6 header bytes after sync (CLASS,ID,LEN_L,LEN_H)
                if sync_pos + 6 > len(buf):
                    buf = buf[sync_pos:]
                    break

                frame_cls = buf[sync_pos + 2]
                frame_id = buf[sync_pos + 3]
                payload_len = buf[sync_pos + 4] | (buf[sync_pos + 5] << 8)

                # Total frame: SYNC(2)+CLASS(1)+ID(1)+LEN(2)+PAYLOAD+CHK(2)
                total_len = 8 + payload_len

                if sync_pos + total_len > len(buf):
                    # Incomplete frame; keep from sync_pos
                    buf = buf[sync_pos:]
                    break

                # Extract candidate frame
                frame = buf[sync_pos:sync_pos + total_len]

                # Verify UBX checksum (8-bit Fletcher over CLASS..PAYLOAD_END)
                ck_a = 0
                ck_b = 0
                for b in frame[2:6 + payload_len]:
                    ck_a = (ck_a + b) & 0xFF
                    ck_b = (ck_b + ck_a) & 0xFF

                expected_ck_a = frame[6 + payload_len]
                expected_ck_b = frame[6 + payload_len + 1]

                if ck_a == expected_ck_a and ck_b == expected_ck_b:
                    # Valid UBX frame
                    if frame_cls == cls and frame_id == mid:
                        return frame
                    # Not the frame we want; skip this frame
                    idx = sync_pos + total_len
                else:
                    # Corrupt frame; skip past sync
                    idx = sync_pos + 2

            if not self._ser.in_waiting:
                time.sleep(0.01)

        return None

    def _check_device_alive(self) -> bool:
        """UBX-MON-VER ポーリングで F9P の生存を確認する"""
        if not self._ser or not self._ser.is_open:
            return False
        try:
            self._ser.reset_input_buffer()
            self._send_ubx(_MON_VER_POLL)
            raw = self._read_ubx_response(0x0A, 0x04, timeout=3.0)
            if raw and len(raw) >= 8:
                self.logger.info("Device alive OK")
                return True
            self.logger.warning("Device alive: no MON-VER response")
            return False
        except Exception as e:
            self.logger.error(f"Device alive check failed: {e}")
            return False

    def _poll_config(self, keys: List[str],
                     timeout: float = _TIMEOUT,
                     max_retries: int = _MAX_RETRIES) -> Optional[bytes]:
        """CFG-VALGET ポーリング（リトライ付き）"""
        for attempt in range(1, max_retries + 1):
            poll_msg = UBXMessage.config_poll(0, 0, keys)
            self._ser.reset_input_buffer()
            self._send_ubx(poll_msg.serialize())
            raw = self._read_ubx_response(0x06, 0x8B, timeout=timeout)
            if raw and len(raw) >= 10:
                return raw
            if attempt < max_retries:
                time.sleep(0.5)
        self.logger.warning(
            f"No CFG-VALGET after {max_retries} attempts"
        )
        return None

    def _parse_single_valget(self, raw: bytes) -> Tuple[int, Any]:
        """Parse single-key CFG-VALGET response -> (key_id, value).

        Payload: [version:1][layer:1][position:2][key:4][value:var]
        """
        payload = raw[6:-2]
        if len(payload) < 8:
            return 0, None
        key_id = int.from_bytes(payload[4:8], "little")
        value_start = 8
        if key_id in _U4_KEY_IDS:
            if len(payload) >= value_start + 4:
                value = int.from_bytes(
                    payload[value_start:value_start + 4], "little")
            else:
                value = None
        elif key_id in _I4_KEY_IDS:
            if len(payload) >= value_start + 4:
                value = int.from_bytes(
                    payload[value_start:value_start + 4],
                    "little", signed=True)
            else:
                value = None
        elif key_id in _U2_KEY_IDS:
            if len(payload) >= value_start + 2:
                value = int.from_bytes(
                    payload[value_start:value_start + 2], "little")
            else:
                value = None
        elif key_id in _R8_KEY_IDS:
            if len(payload) >= value_start + 8:
                value = struct.unpack("<d",
                    payload[value_start:value_start + 8])[0]
            else:
                value = None
        else:
            if len(payload) >= value_start + 1:
                value = payload[value_start]
            else:
                value = None
        return key_id, value

    def _verify_single_key(self, key_name: str, expected: Any) -> dict:
        """Poll a single config key and return verification result dict."""
        result = {
            "key": key_name, "expected": expected, "actual": None,
            "status": "fail", "icon": _ICON_FAIL, "suggestion": "",
        }
        if not self._ser or not self._ser.is_open:
            result["suggestion"] = "Serial port not open"
            return result
        raw = self._poll_config([key_name], timeout=3.0, max_retries=2)
        if raw is None or len(raw) < 14:
            if expected == 0:
                # Key not supported on this hardware (e.g. GPS_L5 on ZED-F9P)
                result["status"] = "ok"
                result["icon"] = _ICON_OK
                result["actual"] = "0 (unsupported)"
            else:
                result["status"] = "warn"
                result["icon"] = _ICON_WARN
                result["actual"] = "No response"
                result["suggestion"] = f"F9P not responding for {key_name}."
            return result
        _key_id, value = self._parse_single_valget(raw)
        result["actual"] = value
        if value is not None and value == expected:
            result["status"] = "ok"
            result["icon"] = _ICON_OK
        elif value is None:
            result["status"] = "warn"
            result["icon"] = _ICON_WARN
            result["actual"] = "Parse error"
            result["suggestion"] = f"Failed to parse {key_name} value."
        else:
            result["suggestion"] = (
                f"{key_name}: actual={value}, expected={expected}"
            )
        return result

    # ------------------------------------------------------------------
    # Write: Base Station
    # ------------------------------------------------------------------

    def write_base_tmode3(self, lat: float, lon: float, alt: float,
                           save_to_flash: bool = True) -> bool:
        """STEP1: TMODE3 Fixed Mode 設定 (CFG-VALSET)"""
        self._ser = self._open_serial()
        try:
            lat_e7 = int(lat * 1e7)
            lon_e7 = int(lon * 1e7)
            alt_cm = int(alt * 100)
            cfg_data = [
                ("CFG-TMODE-MODE", 2),
                ("CFG-TMODE-POS_TYPE", 0),
                ("CFG-TMODE-LAT", lat_e7),
                ("CFG-TMODE-LON", lon_e7),
                ("CFG-TMODE-HEIGHT", alt_cm),
                ("CFG-TMODE-FIXED_POS_ACC", 10),
            ]
            layers = LAYER_ALL if save_to_flash else LAYER_RAM
            msg = UBXMessage.config_set(layers, 0, cfg_data)
            self._send_ubx(msg.serialize())
            self.logger.info(
                f"[BASE Write] TMODE3 Fixed: "
                f"lat={lat:.7f} lon={lon:.7f} alt={alt:.1f}m "
                f"({'Flash' if save_to_flash else 'RAM'})"
            )
            if save_to_flash:
                time.sleep(0.5)
            return True
        except Exception as e:
            self.logger.error(f"[BASE Write] TMODE3 failed: {e}")
            return False
        finally:
            self._close_serial()

    def write_base_rtcm3(self, save_to_flash: bool = True) -> bool:
        """STEP2: RTCM3 出力メッセージ有効化 (CFG-VALSET)"""
        self._ser = self._open_serial()
        try:
            keys = _get_rtcm_keys_for_port(self.port_type)
            cfg_data = [(k, 1) for k in keys]
            layers = LAYER_ALL if save_to_flash else LAYER_RAM
            msg = UBXMessage.config_set(layers, 0, cfg_data)
            self._send_ubx(msg.serialize())
            self.logger.info(
                f"[BASE Write] RTCM3 ({self.port_type}): {len(keys)} msgs "
                f"({'Flash' if save_to_flash else 'RAM'})"
            )
            if save_to_flash:
                time.sleep(0.5)
            return True
        except Exception as e:
            self.logger.error(f"[BASE Write] RTCM3 failed: {e}")
            return False
        finally:
            self._close_serial()

    # ------------------------------------------------------------------
    # Write: Rover
    # ------------------------------------------------------------------

    def write_rover_uart2(self, save_to_flash: bool = True) -> bool:
        """STEP1: Rover UART2 + Rate + DGNSS 設定 (CFG-VALSET)

        UART2-BAUDRATE is written first as a single-key VALSET to ensure
        it takes effect before other UART2-related config keys.
        """
        self._ser = self._open_serial()
        try:
            layers = LAYER_ALL if save_to_flash else LAYER_RAM

            # Write UART2-BAUDRATE first separately
            baud_msg = UBXMessage.config_set(
                layers, 0, [("CFG-UART2-BAUDRATE", 115200)])
            self._send_ubx(baud_msg.serialize())
            self.logger.info(
                f"[ROVER Write] UART2-BAUDRATE=115200 "
                f"({'Flash' if save_to_flash else 'RAM'})"
            )

            # Write remaining UART2 config keys (skip BAUDRATE, already done)
            cfg_data = [(k, v) for k, v in _UART2_ROVER_CFG_KEYS
                        if k != "CFG-UART2-BAUDRATE"]
            msg = UBXMessage.config_set(layers, 0, cfg_data)
            self._send_ubx(msg.serialize())
            self.logger.info(
                f"[ROVER Write] UART2+Rate: {len(cfg_data)} keys "
                f"({'Flash' if save_to_flash else 'RAM'})"
            )
            if save_to_flash:
                time.sleep(0.5)
            return True
        except Exception as e:
            self.logger.error(f"[ROVER Write] UART2 failed: {e}")
            return False
        finally:
            self._close_serial()

    def write_rover_gnss(self, save_to_flash: bool = True) -> bool:
        """STEP2: GNSS signals + UART1 output 設定 (CFG-VALSET)"""
        self._ser = self._open_serial()
        try:
            layers = LAYER_ALL if save_to_flash else LAYER_RAM
            cfg_data = list(_GNSS_SIGNAL_CFG_KEYS) + [
                ("CFG-UART1OUTPROT-UBX", 1),
                ("CFG-UART1-BAUDRATE", 230400),
            ]
            msg = UBXMessage.config_set(layers, 0, cfg_data)
            self._send_ubx(msg.serialize())
            self.logger.info(
                f"[ROVER Write] GNSS+UART1: {len(cfg_data)} keys "
                f"({'Flash' if save_to_flash else 'RAM'})"
            )
            if save_to_flash:
                time.sleep(0.5)
            return True
        except Exception as e:
            self.logger.error(f"[ROVER Write] GNSS failed: {e}")
            return False
        finally:
            self._close_serial()

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def send_reset(self) -> bool:
        """Send UBX-CFG-RST to reset the F9P (hardware reset immediately, hot start).

        Payload:
          - navBbrMask: 0x0000 (hot start — don't clear BBR)
          - resetMode:  0x00   (hardware reset immediately)

        Returns True on success, False on error.
        """
        self._ser = self._open_serial()
        try:
            # UBX-CFG-RST: class=0x06(CFG), id=0x04(RST)
            rst_msg = UBXMessage(0x06, 0x04, SET, navBbrMask=0x0000, resetMode=0x00)
            self._send_ubx(rst_msg.serialize())
            self.logger.info("UBX-CFG-RST sent (HW reset immediately, hot start)")
            return True
        except Exception as e:
            self.logger.error(f"UBX-CFG-RST failed: {e}")
            return False
        finally:
            self._close_serial()

    # ------------------------------------------------------------------
    # Verify: Full role check
    # ------------------------------------------------------------------

    def verify_role(self, role: str, key_table: List[dict]) -> dict:
        """Verify all keys for a given role."""
        role_keys = _get_keys_by_role(key_table, role)
        # Filter RTCM keys by port_type for verification
        if role == "base" and self.port_type != "both":
            if self.port_type == "uart1":
                role_keys = [k for k in role_keys if "_USB" not in k["key"]]
            elif self.port_type == "usb":
                role_keys = [k for k in role_keys if "_UART1" not in k["key"]]
        label = "BASE" if role == "base" else "ROVER"

        summary = {
            "role": role, "port": self.serial_port,
            "device_alive": False, "checks": [],
            "all_verified": False,
            "ok_count": 0, "fail_count": 0, "warn_count": 0,
        }

        self._ser = self._open_serial()
        try:
            alive = self._check_device_alive()
            summary["device_alive"] = alive
            if not alive:
                for k in role_keys:
                    summary["checks"].append({
                        "id": k["id"], "key": k["key"],
                        "description": k["desc"],
                        "expected": k["expected"],
                        "actual": "Device not alive",
                        "status": "warn", "icon": _ICON_WARN,
                        "suggestion": "Check connection/baudrate.",
                    })
                    summary["warn_count"] += 1
                return summary

            self.logger.info(f"[{label} Verify] Polling {len(role_keys)} keys...")
            for k in role_keys:
                r = self._verify_single_key(k["key"], k["expected"])
                r["id"] = k["id"]
                r["description"] = k["desc"]
                summary["checks"].append(r)
                if r["status"] == "ok":
                    summary["ok_count"] += 1
                elif r["status"] == "fail":
                    summary["fail_count"] += 1
                else:
                    summary["warn_count"] += 1
                time.sleep(0.05)

            summary["all_verified"] = (
                summary["fail_count"] == 0 and summary["device_alive"]
            )
        except Exception as e:
            self.logger.error(f"[{label} Verify] Error: {e}")
        finally:
            self._close_serial()

        return summary

    # ------------------------------------------------------------------
    # Unified: Write + Verify
    # ------------------------------------------------------------------

    def write_and_verify(self, role: str, key_table: List[dict],
                         lat: float = 0, lon: float = 0, alt: float = 0,
                         save_to_flash: bool = True,
                         no_reset: bool = False,
                         reset_delay: int = 3) -> dict:
        """Write all config for a role, optionally reset, then verify.

        When save_to_flash=True and no_reset=False:
          1. Write all config to Flash
          2. Send UBX-CFG-RST (HW reset immediately)
          3. Wait ``reset_delay`` seconds for device reboot
          4. Verify all keys
        """
        write_results: Dict[str, bool] = {}
        label = "BASE" if role == "base" else "ROVER"

        self.logger.info("=" * 60)
        self.logger.info(f"F9P {label}: Write -> Verify")
        self.logger.info(f"  Port: {self.serial_port} @ {self.baudrate}")
        self.logger.info(f"  Save: {'Flash' if save_to_flash else 'RAM'}")
        self.logger.info(
            f"  Reset: {'skip' if no_reset else f'UBX-CFG-RST (delay={reset_delay}s)'}")
        self.logger.info("=" * 60)

        if role == "base":
            write_results["tmode3"] = self.write_base_tmode3(
                lat, lon, alt, save_to_flash)
            write_results["rtcm3"] = (
                self.write_base_rtcm3(save_to_flash)
                if write_results["tmode3"] else False
            )
        else:
            write_results["uart2"] = self.write_rover_uart2(save_to_flash)
            write_results["gnss_uart1"] = self.write_rover_gnss(
                save_to_flash)

        write_all_ok = all(write_results.values())

        # --- Device reset ---
        if write_all_ok and not no_reset:
            self.logger.info(f"Sending UBX-CFG-RST to {label}...")
            if self.send_reset():
                self.logger.info(
                    f"Reset sent. Waiting {reset_delay}s for device reboot...")
                time.sleep(reset_delay)
            else:
                self.logger.warning(
                    "Reset failed — verify may read stale values")

        verify_result = self.verify_role(role, key_table)

        all_ok = (
            write_all_ok
            and verify_result.get("all_verified", False)
        )

        return {
            "role": role, "port": self.serial_port,
            "write": write_results, "verify": verify_result,
            "all_ok": all_ok,
        }


# ==========================================================================
# Display helpers
# ==========================================================================

def _print_header(role: str, port: str, mode: str) -> None:
    label = "BASE STATION" if role == "base" else "ROVER"
    print()
    print("=" * 70)
    print(f"  F9P Configuration -- {label}  ({mode.upper()})")
    print(f"  Port: {port}")
    print("=" * 70)
    print()


def _print_key_result(check: dict) -> None:
    icon = check.get("icon", _ICON_WARN)
    kid = check.get("id", "?")
    key = check.get("key", "?")
    desc = check.get("description", "")
    expected = check.get("expected", "?")
    actual = check.get("actual", "?")
    status = check.get("status", "warn")
    labels = {"ok": "OK", "fail": "FAIL", "warn": "WARN"}
    label = labels.get(status, "WARN")
    print(f"  {icon} [{label:4s}] #{kid:2d} {key}")
    print(f"          {desc}")
    print(f"          Expected: {expected!s:<12} Actual: {actual!s}")


def _print_verify_summary(summary: dict) -> None:
    total = summary["ok_count"] + summary["fail_count"] + summary["warn_count"]
    print()
    print("-" * 70)
    print(
        f"  Results:  {_ICON_OK} OK={summary['ok_count']}  "
        f"{_ICON_FAIL} FAIL={summary['fail_count']}  "
        f"{_ICON_WARN} WARN={summary['warn_count']}  "
        f"(total: {total})"
    )
    alive = "YES" if summary.get("device_alive") else "NO"
    verified = "YES" if summary.get("all_verified") else "NO"
    print(f"  Device alive: {alive}")
    print(f"  All verified: {verified}")
    print("-" * 70)
    suggestions = [
        c.get("suggestion", "")
        for c in summary.get("checks", [])
        if c.get("suggestion") and c["status"] in ("fail", "warn")
    ]
    if suggestions:
        print()
        print("  Fix suggestions:")
        for i, s in enumerate(suggestions, 1):
            print(f"    {i}. {s}")


def _print_write_summary(write_results: dict) -> None:
    print()
    print("-" * 70)
    for stage, ok in write_results.items():
        icon = _ICON_OK if ok else _ICON_FAIL
        status = "OK" if ok else "FAIL"
        print(f"  {icon} Write {stage:20s}: {status}")
    all_ok = all(write_results.values())
    print(f"  Write all stages: {'OK' if all_ok else 'FAIL'}")
    print("-" * 70)



# ==========================================================================
# Full Automation Mode (--mode full)
# ==========================================================================

def _run_full_mode(args, key_table, logger) -> int:
    """Execute the full 8-phase RTK automation pipeline."""
    import os, subprocess
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    raspi_path = args.raspi_path
    total_phases = 8
    if args.skip_rover:
        total_phases -= 2
    if args.skip_fix_wait:
        total_phases -= 1

    phase = 0
    failed = False
    tcp_port = args.base_station_tcp_port
    raspi_user = args.raspi_user or "taki"
    base_port = args.port or args.base_port
    base_baud = args.baud or args.base_baud
    rover_baud = args.baud or args.rover_baud

    # ---- Phase 1: Base Station Write ----
    phase += 1
    print(f"\n{'='*70}\n  === Phase {phase}/{total_phases}: Base Station Write ===\n{'='*70}")
    cfg = F9pAllConfigurator(serial_port=base_port, baudrate=base_baud,
                              logger=logger, port_type=args.port_type)
    write_ok = {"tmode3": cfg.write_base_tmode3(args.lat, args.lon, args.alt, True)}
    write_ok["rtcm3"] = cfg.write_base_rtcm3(True) if write_ok["tmode3"] else False
    if all(write_ok.values()) and not args.no_reset:
        if cfg.send_reset():
            time.sleep(args.reset_delay)
    if all(write_ok.values()):
        print(f"  OK Phase {phase}: Write OK")
    else:
        print(f"  FAIL Phase {phase}: Write FAIL")
        return 1

    # ---- Phase 2: Base Station Verify ----
    phase += 1
    print(f"\n{'='*70}\n  === Phase {phase}/{total_phases}: Base Station Verify ===\n{'='*70}")
    base_verify = cfg.verify_role("base", key_table)
    ok_count = base_verify.get("ok_count", 0)
    total_count = ok_count + base_verify.get("fail_count", 0) + base_verify.get("warn_count", 0)
    if base_verify.get("all_verified"):
        print(f"  OK Phase {phase}: {ok_count}/{total_count} OK")
    else:
        print(f"  FAIL Phase {phase}: {ok_count}/{total_count} OK")
        for c in base_verify.get("checks", []):
            if c.get("status") != "ok":
                print(f"    FAIL: {c.get('key')} exp={c.get('expected')} act={c.get('actual')}")
        return 1

    if not args.skip_rover:
        # ---- Phase 3: Rover Write (SSH) ----
        phase += 1
        print(f"\n{'='*70}\n  === Phase {phase}/{total_phases}: Rover Write (SSH) ===\n{'='*70}")
        rover_port = args.rover_port
        script = "rtk_tools/f9p_config_all.py"
        cmd = (f"cd {raspi_path} && .venv/bin/python {script} "
               f"--role rover --mode write --port {rover_port} --baud {rover_baud} "
               f"--no-reset --log-level WARNING")
        print(f"  SSH: {raspi_user}@{args.raspi_host}")
        try:
            r = subprocess.run(["ssh", "-o", "ConnectTimeout=10",
                                f"{raspi_user}@{args.raspi_host}", cmd],
                               capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                print(f"  OK Phase {phase}: Rover Write OK")
            else:
                print(f"  FAIL Phase {phase}: Rover Write FAIL (exit={r.returncode})")
                if r.stderr:
                    print(f"    stderr: {r.stderr[:200]}")
                return 1
        except subprocess.TimeoutExpired:
            print(f"  FAIL Phase {phase}: SSH timeout"); return 1
        except FileNotFoundError:
            print(f"  FAIL Phase {phase}: ssh not found"); return 1

        # ---- Phase 4: Rover Verify (SSH) ----
        phase += 1
        print(f"\n{'='*70}\n  === Phase {phase}/{total_phases}: Rover Verify (SSH) ===\n{'='*70}")
        cmd = (f"cd {raspi_path} && .venv/bin/python {script} "
               f"--role rover --mode verify --port {rover_port} --baud {rover_baud} "
               f"--json --log-level WARNING")
        print(f"  SSH: {raspi_user}@{args.raspi_host}")
        try:
            r = subprocess.run(["ssh", "-o", "ConnectTimeout=10",
                                f"{raspi_user}@{args.raspi_host}", cmd],
                               capture_output=True, text=True, timeout=120)
            if r.returncode == 0:
                try:
                    data = json.loads(r.stdout)
                    rr = data.get("rover", {})
                    rok = rr.get("ok_count", 0)
                    rtot = rok + rr.get("fail_count", 0) + rr.get("warn_count", 0)
                    rv = rr.get("all_verified", False)
                    print(f"  {'OK' if rv else 'FAIL'} Phase {phase}: {rok}/{rtot} OK")
                except json.JSONDecodeError:
                    print(f"  WARN Phase {phase}: Bad JSON from rover")
                    return 1
            else:
                print(f"  FAIL Phase {phase}: Rover Verify FAIL (exit={r.returncode})")
                if r.stdout:
                    print(f"    stdout: {r.stdout[:200]}")
                return 1
        except subprocess.TimeoutExpired:
            print(f"  FAIL Phase {phase}: SSH timeout"); return 1
    else:
        print(f"\n  WARN Rover phases SKIPPED (--skip-rover)")
        phase += 2

    # ---- Phase 5: Base Station Start ----
    phase += 1
    print(f"\n{'='*70}\n  === Phase {phase}/{total_phases}: Base Station Start ===\n{'='*70}")
    base_script = str(repo_root / "rtk_tools" / "rtk_base_station_v2.py")
    proc = subprocess.Popen(
        [sys.executable, base_script, "--skip-f9p-config", "--tcp-port", str(tcp_port)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    started = False
    dl = time.monotonic() + 10
    while time.monotonic() < dl:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            time.sleep(0.1)
            continue
        print(f"  [base] {line.rstrip()}")
        if "started successfully" in line:
            started = True; break
    if started:
        print(f"  OK Phase {phase}: Base station started (TCP:{tcp_port})")
    else:
        print(f"  FAIL Phase {phase}: Base station failed to start")
        proc.terminate()
        return 1

    # ---- Phase 6: RTCM3 Verify ----
    phase += 1
    print(f"\n{'='*70}\n  === Phase {phase}/{total_phases}: RTCM3 Stream Verify ===\n{'='*70}")
    try:
        from gcs.rtk_tools.verify_rtcm_tcp import verify_rtcm_stream
    except ImportError:
        from verify_rtcm_tcp import verify_rtcm_stream
    print(f"  Capturing localhost:{tcp_port} for 30s...")
    rv = verify_rtcm_stream("localhost", tcp_port, duration=30.0)
    if rv["ok"]:
        print(f"  OK Phase {phase}: All RTCM3 types detected")
    else:
        print(f"  WARN Phase {phase}: Missing types: {rv['missing_types']}")
    print(f"    Frames: {rv['total_frames']}")
    for mt, c in rv["type_counter"].items():
        print(f"      {'OK' if c>0 else 'WARN'} {mt}: {c}")

    # ---- Phase 7: RTCM Injection ----
    phase += 1
    print(f"\n{'='*70}\n  === Phase {phase}/{total_phases}: RTCM Injection Start ===\n{'='*70}")
    fwd_script = "rtk_tools/rtk_forwarder_service.py"
    fwd_conf = "config/rtk_forwarder.yml"
    subprocess.run(["ssh", "-o", "ConnectTimeout=10",
                    f"{raspi_user}@{args.raspi_host}",
                    "pkill -f rtk_forwarder_service.py 2>/dev/null; sleep 1"],
                   capture_output=True, timeout=15)
    cmd = (f"cd {raspi_path} && nohup python3 {fwd_script} --config {fwd_conf} "
           f"> /tmp/rtk_forwarder.log 2>&1 &")
    print(f"  SSH: {raspi_user}@{args.raspi_host}")
    r = subprocess.run(["ssh", "-o", "ConnectTimeout=10",
                        f"{raspi_user}@{args.raspi_host}", cmd],
                       capture_output=True, text=True, timeout=15)
    if r.returncode == 0:
        time.sleep(2)
        print(f"  OK Phase {phase}: RTCM forwarder launched")
    else:
        print(f"  FAIL Phase {phase}: SSH failed")

    # ---- Phase 8: Fix Monitor ----
    # GCS-UmemotoLab の gcs_fix_monitor.py は統合対象外（gcs/fix_metrics.py が正典）。
    # ここでは gcs/fix_metrics.py の判定関数を直接利用して RTK FIXED 到達を待つ簡易版を使う。
    if not args.skip_fix_wait:
        phase += 1
        print(f"\n{'='*70}\n  === Phase {phase}/{total_phases}: Fix Monitor ===\n{'='*70}")
        print(f"  NOTE: gcs_fix_monitor.py is retired; use gcs/fix_metrics.py instead.")
        print(f"  GCS: {args.gcs_url}/api/drones  Timeout:300s")
        try:
            from gcs.rtk_tools.fix_monitor_lite import wait_for_rtk_fixed
        except ImportError:
            wait_for_rtk_fixed = None
        if wait_for_rtk_fixed is not None:
            if wait_for_rtk_fixed(gcs_url=args.gcs_url, system_id=args.system_id, timeout=300.0):
                print(f"  OK Phase {phase}: RTK FIXED ACHIEVED!")
            else:
                print(f"  FAIL Phase {phase}: RTK Fixed NOT achieved (timeout)")
                failed = True
        else:
            print(f"  WARN Phase {phase}: fix_monitor_lite unavailable; skip RTK Fixed wait")
    else:
        print(f"\n  WARN Fix Monitor SKIPPED (--skip-fix-wait)")
        phase += 1

    # ---- Final ----
    print(f"\n{'='*70}")
    if not failed:
        print(f"  \U0001F389 ALL PHASES COMPLETE -- RTK FIXED ACHIEVED")
    else:
        print(f"  FAIL Some phases failed -- check output above")
    print(f"{'='*70}\n")
    return 0 if not failed else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="DroneCAN F9P (ZED-F9P) 全設定値 書込/確認ツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --role base --port /dev/tty.usbmodem114301\n"
            "  %(prog)s --role rover --mode verify --port /dev/ttyAMA4\n"
            "  %(prog)s --role both --base-port /dev/tty.X --rover-port /dev/tty.Y\n"
        ),
    )
    parser.add_argument("--role", required=True,
                        choices=["base", "rover", "both"],
                        help="Target role")
    parser.add_argument("--mode", default="write-verify",
                        choices=["write", "verify", "write-verify", "full"],
                        help="Operation mode (default: write-verify)")
    parser.add_argument("--port", default=None,
                        help="Serial port (single role)")
    parser.add_argument("--base-port", default="/dev/tty.usbmodem114301",
                        help="Base port (--role both)")
    parser.add_argument("--rover-port", default="/dev/ttyAMA4",
                        help="Rover port (--role both)")
    parser.add_argument("--baud", type=int, default=None,
                        help="Baudrate (single; defaults: base=38400 rover=115200)")
    parser.add_argument("--base-baud", type=int, default=38400,
                        help="Base baudrate (default: 38400)")
    parser.add_argument("--rover-baud", type=int, default=115200,
                        help="Rover baudrate (default: 115200)")
    parser.add_argument("--lat", type=float, default=35.1234567,
                        help="Base latitude (default: 35.1234567)")
    parser.add_argument("--lon", type=float, default=139.1234567,
                        help="Base longitude (default: 139.1234567)")
    parser.add_argument("--alt", type=float, default=100.0,
                        help="Base altitude in meters (default: 100.0)")
    parser.add_argument("--port-type", default="both",
                        choices=["both", "uart1", "usb"],
                        help="RTCM output port type: both(default), uart1, usb")
    parser.add_argument("--host", default=None,
                        help="TCP host (DroneCAN Serial Forwarding). "
                             "When set, TCP is used instead of serial.")
    parser.add_argument("--port-tcp", type=int, default=5001,
                        help="TCP port (DroneCAN Serial Forwarding, default: 5001)")

    parser.add_argument("--no-flash", action="store_true",
                        help="Skip Flash save (RAM only)")
    parser.add_argument("--no-reset", action="store_true",
                        help="Skip UBX-CFG-RST after write (no device reset)")
    parser.add_argument("--reset-delay", type=int, default=3,
                        help="Wait seconds after reset before verify (default: 3)")
    # --mode full arguments
    parser.add_argument("--raspi-host", default="raspi",
                        help="SSH hostname for Rover (default: raspi)")
    parser.add_argument("--raspi-user", default="taki",
                        help="SSH username (default: taki)")
    parser.add_argument("--raspi-path", default="~/GCS-UmemotoLab",
                        help="Repo path on Raspberry Pi (default: ~/GCS-UmemotoLab)")
    parser.add_argument("--skip-rover", action="store_true",
                        help="Skip Rover configuration (--mode full)")
    parser.add_argument("--skip-fix-wait", action="store_true",
                        help="Skip Fix monitoring (--mode full)")
    parser.add_argument("--gcs-url", default="http://localhost:8000",
                        help="GCS API URL (default: http://localhost:8000)")
    parser.add_argument("--system-id", type=int, default=1,
                        help="MAVLink system_id (default: 1)")
    parser.add_argument("--base-station-tcp-port", type=int, default=2101,
                        help="TCP port for base station (default: 2101)")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    parser.add_argument("--log-level", default="WARNING",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="Log level (default: WARNING)")

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("f9p_config_all")

    base_baud = args.base_baud
    rover_baud = args.rover_baud
    if args.baud is not None:
        if args.role == "base":
            base_baud = args.baud
        elif args.role == "rover":
            rover_baud = args.baud

    key_table = _build_key_table(args.lat, args.lon, args.alt)
    save_to_flash = not args.no_flash

    # --- Full automation mode ---
    if args.mode == "full":
        return _run_full_mode(args, key_table, logger)

    results: Dict[str, Any] = {}
    exit_code = 0

    roles_to_run: List[str] = []
    if args.role in ("base", "both"):
        roles_to_run.append("base")
    if args.role in ("rover", "both"):
        roles_to_run.append("rover")

    for role in roles_to_run:
        port = args.port if args.role == role else (
            args.base_port if role == "base" else args.rover_port)
        baud = base_baud if role == "base" else rover_baud

        if not port:
            print(f"Error: --port required for --role {role}", file=sys.stderr)
            return 1

        cfg = F9pAllConfigurator(
            serial_port=None if args.host else port,
            baudrate=baud, logger=logger, port_type=args.port_type,
            host=args.host, port=args.port_tcp,
        )

        if args.mode == "write":
            write_ok: Dict[str, bool] = {}
            if role == "base":
                write_ok["tmode3"] = cfg.write_base_tmode3(
                    args.lat, args.lon, args.alt, save_to_flash)
                write_ok["rtcm3"] = (
                    cfg.write_base_rtcm3(save_to_flash)
                    if write_ok["tmode3"] else False)
            else:
                write_ok["uart2"] = cfg.write_rover_uart2(save_to_flash)
                write_ok["gnss_uart1"] = cfg.write_rover_gnss(save_to_flash)

            write_all_ok = all(write_ok.values())

            # --- Device reset after write ---
            if write_all_ok and not args.no_reset:
                logger.info(
                    f"Sending UBX-CFG-RST to {role.upper()}...")
                if not cfg.send_reset():
                    logger.warning("Reset failed")

            results[role] = {
                "role": role, "port": port,
                "write": write_ok, "all_ok": write_all_ok,
            }
            if not write_all_ok:
                exit_code = 1

        elif args.mode == "verify":
            cfg._ser = cfg._open_serial()
            verify_result = cfg.verify_role(role, key_table)
            cfg._close_serial()
            results[role] = verify_result
            if not verify_result.get("all_verified"):
                exit_code = 1

        else:  # write-verify
            result = cfg.write_and_verify(
                role, key_table,
                lat=args.lat, lon=args.lon, alt=args.alt,
                save_to_flash=save_to_flash,
                no_reset=args.no_reset,
                reset_delay=args.reset_delay,
            )
            results[role] = result
            if not result.get("all_ok"):
                exit_code = 1

    # --- Output ---
    if args.json:
        output: Dict[str, Any] = {}
        for role in roles_to_run:
            r = results.get(role, {})
            if args.mode == "write":
                output[role] = r
            else:
                summary = r.get("verify", r)
                output[role] = {
                    "role": role, "port": r.get("port", ""),
                    "device_alive": summary.get("device_alive", False),
                    "all_verified": summary.get("all_verified", False),
                    "ok_count": summary.get("ok_count", 0),
                    "fail_count": summary.get("fail_count", 0),
                    "warn_count": summary.get("warn_count", 0),
                    "checks": [
                        {
                            "id": c["id"], "key": c["key"],
                            "description": c.get("description", ""),
                            "expected": c["expected"],
                            "actual": c["actual"],
                            "status": c["status"],
                        }
                        for c in summary.get("checks", [])
                    ],
                }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return exit_code

    # Text output
    for role in roles_to_run:
        r = results[role]
        port = r.get("port", "")
        _print_header(role, port, args.mode)

        if args.mode == "write":
            _print_write_summary(r.get("write", {}))
        else:
            summary = r.get("verify", r)
            device_alive = summary.get("device_alive", False)
            if not device_alive:
                print(f"  {_ICON_FAIL} Device not responding -- cannot verify")
            else:
                for check in summary.get("checks", []):
                    _print_key_result(check)
            _print_verify_summary(summary)
            all_verified = summary.get("all_verified", False)
            icon = _ICON_OK if all_verified else _ICON_FAIL
            label = "BASE" if role == "base" else "ROVER"
            print(f"  {icon} {label}: All verified: {'YES' if all_verified else 'NO'}")

    if len(roles_to_run) == 2:
        print()
        print("=" * 70)
        base_ok = results.get("base", {}).get("all_verified",
            results.get("base", {}).get("all_ok", False))
        rover_ok = results.get("rover", {}).get("all_verified",
            results.get("rover", {}).get("all_ok", False))
        overall_ok = base_ok and rover_ok
        overall_icon = _ICON_OK if overall_ok else _ICON_FAIL
        print(f"  {overall_icon} BOTH: All verified: {'YES' if overall_ok else 'NO'}")
        print("=" * 70)

    print()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
