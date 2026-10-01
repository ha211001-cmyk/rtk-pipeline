#!/usr/bin/env python3
"""rtcm_caster.py — 基地局 RTCM を UDP で複数ドローンへファンアウトするキャスター。

本番構成:
  [基地局 F9P] --USB--> [GCS PC] --UDP--> [ローバー群 (Raspberry Pi / MAVProxy)]

``RtcmCaster`` は基地局（USB シリアル）から RTCM3 バイト列を読み、完全な
RTCM3 フレーム単位で、登録された複数の UDP エンドポイントへ一斉送信
（ファンアウト）する。送信先 IP:ポート は動的に追加・削除できる。

フレーム抽出は ``gcs.rtcm_monitor.Rtcm3StreamParser`` を再利用する
（0xD3 プリアンブル + 2byte ヘッダ + ペイロード + CRC-24Q）。
"""

from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.rtcm_monitor import Rtcm3StreamParser  # noqa: E402


class RtcmCaster:
    """基地局 RTCM3 を複数 UDP エンドポイントへ配信するクラス。

    Args:
        source_port: 基地局 F9P のシリアルポート（例: /dev/ttyACM0）。
            省略時はシリアル読取スレッドを起動せず ``feed()`` による
            手動投入モード（自己検証 / テスト用）として動作する。
        source_baud: シリアルボーレート。
        verify_crc: RTCM3 フレームの CRC-24Q を検証するか。
        socket_timeout: UDP ソケットのタイムアウト [秒]。
    """

    def __init__(self,
                 source_port: Optional[str] = None,
                 source_baud: int = 115200,
                 verify_crc: bool = True,
                 socket_timeout: float = 0.5):
        self.source_port = source_port
        self.source_baud = source_baud
        self.socket_timeout = socket_timeout
        self._parser = Rtcm3StreamParser(verify_crc=verify_crc)
        self._destinations: Dict[Tuple[str, int], None] = {}
        self._lock = threading.RLock()
        self._sock: Optional[socket.socket] = None
        self._ser: Any = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self.stats: Dict[str, int] = {
            "bytes_read": 0,
            "frames_read": 0,
            "frames_sent": 0,
            "bytes_sent": 0,
            "destinations": 0,
            "send_errors": 0,
        }

    # ------------------------------------------------------------------
    # 送信先管理（動的追加・削除）
    # ------------------------------------------------------------------
    def add_destination(self, host: str, port: int) -> bool:
        """送信先 UDP エンドポイントを追加する。既存なら False を返す。"""
        key = (str(host), int(port))
        with self._lock:
            if key in self._destinations:
                return False
            self._destinations[key] = None
        self.stats["destinations"] = len(self._destinations)
        return True

    def remove_destination(self, host: str, port: int) -> bool:
        """送信先 UDP エンドポイントを削除する。存在しなければ False。"""
        key = (str(host), int(port))
        with self._lock:
            if key not in self._destinations:
                return False
            del self._destinations[key]
        self.stats["destinations"] = len(self._destinations)
        return True

    def destinations(self) -> List[Tuple[str, int]]:
        """現在の送信先一覧（コピー）を返す。"""
        with self._lock:
            return list(self._destinations.keys())

    # ------------------------------------------------------------------
    # 送信
    # ------------------------------------------------------------------
    def _ensure_socket(self) -> None:
        if self._sock is None:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.settimeout(self.socket_timeout)

    def broadcast(self, frame: bytes) -> int:
        """1 つの RTCM3 フレームを登録済みの全送信先へ送る。

        Returns:
            送信に成功したエンドポイント数。
        """
        with self._lock:
            dests = list(self._destinations.keys())
        if not dests:
            return 0
        self._ensure_socket()
        sent = 0
        for host, port in dests:
            try:
                self._sock.sendto(frame, (host, port))
                sent += 1
                self.stats["bytes_sent"] += len(frame)
            except Exception:  # noqa: BLE001
                self.stats["send_errors"] += 1
        self.stats["frames_sent"] += 1
        return sent

    # ------------------------------------------------------------------
    # データ投入（シリアル読取スレッド / 手動 feed 共用）
    # ------------------------------------------------------------------
    def feed(self, data: bytes) -> int:
        """生バイト列を投入し、抽出された RTCM3 フレームを一斉送信する。

        Returns:
            送信に成功したエンドポイント数の合計。
        """
        self.stats["bytes_read"] += len(data)
        frames = self._parser.feed(data)
        sent = 0
        for frame in frames:
            self.stats["frames_read"] += 1
            sent += self.broadcast(frame)
        return sent

    # ------------------------------------------------------------------
    # シリアル読取スレッド
    # ------------------------------------------------------------------
    def _open_serial(self) -> Any:
        import serial  # noqa: PLC0415
        return serial.Serial(self.source_port, self.source_baud, timeout=1.0)

    def start(self) -> bool:
        """シリアル（設定時）を開き、読取スレッドを起動する。"""
        if self._running:
            return True
        self._ensure_socket()
        if self.source_port:
            try:
                self._ser = self._open_serial()
            except Exception as e:  # noqa: BLE001
                print("[rtcm] シリアルを開けません: %s" % e)
                return False
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True

    def _loop(self) -> None:
        while self._running:
            if self._ser is None:
                time.sleep(0.05)
                continue
            try:
                data = self._ser.read(4096)
            except Exception:  # noqa: BLE001
                time.sleep(0.02)
                continue
            if data:
                self.feed(data)
            else:
                time.sleep(0.02)

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:  # noqa: BLE001
                pass
            self._ser = None
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:  # noqa: BLE001
                pass
            self._sock = None

    def is_running(self) -> bool:
        return self._running


__all__ = ["RtcmCaster"]
