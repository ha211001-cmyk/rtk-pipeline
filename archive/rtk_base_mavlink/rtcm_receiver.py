#!/usr/bin/env python3
"""
RTCM Receiver - F9P基地局からのRTCM3データ受信モジュール

ZED-F9PのUSBポートからシリアル経由でRTCM3補正データを受信し、
フレーム解析とログ保存を行う。

Usage:
    from rtcm_receiver import RtcmReceiver

    receiver = RtcmReceiver("/dev/ttyACM2", baudrate=115200, log_dir="logs")
    receiver.start()
    # receiver.get_frame_queue() からRTCMフレームを取得
    receiver.stop()
"""

import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from queue import Queue
from typing import Optional

import serial


class RtcmReceiver:
    """F9P基地局からのRTCM3データ受信クラス

    シリアルポートからRTCM3バイナリデータを受信し、
    フレーム解析、キュー投入、ログ保存を行う。

    Args:
        serial_port: F9Pのシリアルポートパス (例: /dev/ttyACM2)
        baudrate: シリアル通信ボーレート (デフォルト: 115200)
        log_dir: RTCMログ保存ディレクトリ
        logger: ロガーインスタンス
    """

    def __init__(self, serial_port: str, baudrate: int = 115200,
                 log_dir: str = "logs", logger: Optional[logging.Logger] = None):
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.log_dir = Path(log_dir)
        self.log = logger or logging.getLogger("RtcmReceiver")

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._frame_queue: Queue = Queue()
        self._rtcm_log_file = None
        self._rtcm_log_path: Optional[str] = None

        # 統計情報
        self.stats = {
            'bytes_read': 0,
            'frames_received': 0,
            'read_errors': 0,
            'last_read_time': None,
        }

    def start(self) -> None:
        """RTCM受信を開始する"""
        self._running = True

        # ログディレクトリ作成
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # RTCM raw log file を開く
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = self.log_dir / f"rtcm_raw_{timestamp}.rtcm3"
        self._rtcm_log_file = open(str(log_path), "wb")
        self._rtcm_log_path = str(log_path)
        self.log.info(f"RTCMログファイル: {self._rtcm_log_path}")

        # 受信スレッド起動
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        self.log.info(f"RTCM受信開始: {self.serial_port} @ {self.baudrate}bps")

    def stop(self) -> None:
        """RTCM受信を停止する"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)

        # RTCMログファイルを閉じる
        if self._rtcm_log_file is not None:
            try:
                self._rtcm_log_file.close()
            except Exception:
                pass
            self.log.info(f"RTCMログファイルを閉じました: {self._rtcm_log_path}")
            self._rtcm_log_file = None

        self.log.info(f"RTCM受信停止: bytes={self.stats['bytes_read']}, "
                      f"frames={self.stats['frames_received']}, "
                      f"errors={self.stats['read_errors']}")

    def get_frame_queue(self) -> Queue:
        """RTCMフレームキューを取得する

        Returns:
            RTCM3フレーム(bytes)が投入されるQueue
        """
        return self._frame_queue

    def _parse_rtcm3_frame(self, buffer: bytearray) -> Optional[bytes]:
        """バッファからRTCM3フレームを1つ抽出する

        RTCM3フレーム構造:
          Byte 0:     0xD3 (プリアンブル)
          Byte 1-2:   [6bit reserved][10bit message_length]
          Byte 3..:   data (message_length bytes)
          Last 3:     CRC-24Q

        フレーム全体長 = 3 + message_length + 3 = message_length + 6

        Args:
            buffer: 受信データバッファ (破壊的操作あり)

        Returns:
            完全なRTCM3フレーム、または不完全な場合はNone
        """
        if len(buffer) < 6:
            return None

        # プリアンブル検索
        if buffer[0] != 0xD3:
            buffer.pop(0)
            return None

        # reserved bits チェック (0であるべき)
        reserved = buffer[1] >> 2
        if reserved != 0:
            buffer.pop(0)
            return None

        # メッセージ長抽出 (10ビット)
        frame_len = ((buffer[1] & 0x03) << 8) | buffer[2]
        if frame_len > 1023:
            buffer.pop(0)
            return None

        total_len = 6 + frame_len
        if len(buffer) < total_len:
            return None

        # 完全なフレームを抽出
        frame = bytes(buffer[:total_len])
        del buffer[:total_len]
        return frame

    def _read_loop(self) -> None:
        """シリアル受信ループ（別スレッドで実行）

        ポートが存在しない場合（F9P再起動中など）は、ポートが再出現するまで
        再試行する。
        """
        buffer = bytearray()
        loop_count = 0

        while self._running:
            ser = None
            try:
                ser = serial.Serial(
                    port=self.serial_port,
                    baudrate=self.baudrate,
                    timeout=0
                )
                self.log.info(f"シリアルポートオープン: {self.serial_port}")

                while self._running:
                    try:
                        if ser.in_waiting == 0:
                            time.sleep(0.01)
                            loop_count += 1
                            if loop_count % 500 == 0:
                                self.log.debug(
                                    f"データ待機中... (bytes={self.stats['bytes_read']}, "
                                    f"frames={self.stats['frames_received']}, "
                                    f"buffer={len(buffer)})")
                            continue

                        data = ser.read(ser.in_waiting)
                        if not data:
                            continue

                        buffer.extend(data)
                        self.stats['bytes_read'] += len(data)
                        self.stats['last_read_time'] = time.time()

                        # RTCM3フレーム抽出（インライン解析）
                        while len(buffer) >= 6:
                            if buffer[0] != 0xD3:
                                buffer.pop(0)
                                continue

                            reserved = buffer[1] >> 2
                            if reserved != 0:
                                buffer.pop(0)
                                continue

                            frame_len = ((buffer[1] & 0x03) << 8) | buffer[2]
                            if frame_len > 1023:
                                buffer.pop(0)
                                continue

                            total_len = 6 + frame_len
                            if len(buffer) < total_len:
                                break

                            frame = bytes(buffer[:total_len])
                            del buffer[:total_len]

                            # キューに投入
                            self._frame_queue.put(frame)
                            self.stats['frames_received'] += 1

                            # ログファイルに保存
                            if self._rtcm_log_file is not None:
                                try:
                                    self._rtcm_log_file.write(frame)
                                    self._rtcm_log_file.flush()
                                except Exception:
                                    pass

                    except (serial.SerialException, OSError, ValueError) as e:
                        self.log.warning(f"シリアル読み取りエラー: {e}")
                        self.stats['read_errors'] += 1
                        time.sleep(1.0)
                        # 内側ループを抜けてポート再接続を試みる
                        break

            except serial.SerialException as e:
                self.log.warning(f"シリアルポートオープン失敗: {e}（再試行中...）")
                self.stats['read_errors'] += 1
            except Exception as e:
                self.log.error(f"受信ループ予期せぬエラー: {type(e).__name__}: {e}")

            # ポートを閉じる
            if ser and ser.is_open:
                try:
                    ser.close()
                except Exception:
                    pass

            # 再試行待機
            if self._running:
                # ポートが再出現するまで2秒間隔で再試行
                time.sleep(2)

        self.log.info("受信ループ終了")
