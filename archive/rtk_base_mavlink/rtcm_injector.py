#!/usr/bin/env python3
"""
RTCM Injector - RTCM3フレームをMAVLink GPS_RTCM_DATAとして注入するモジュール

RTCM受信キューからフレームを取り出し、180バイトずつ分割して
MAVLink GPS_RTCM_DATA (ID:233) でArduPilotに送信する。

Usage:
    from rtcm_injector import RtcmInjector

    injector = RtcmInjector(mavlink_comm, max_packet_size=180, max_fragments=4)
    injector.inject_frame(frame)
"""

import logging
import time
from typing import Optional


class RtcmInjector:
    """RTCM3フレームをMAVLink GPS_RTCM_DATAとして注入するクラス

    RTCM3フレームを180バイトずつ分割し、MAVLink GPS_RTCM_DATA (ID:233)
    メッセージとしてArduPilotに送信する。
    ArduPilotがCAN1経由でH-RTK F9Pに自動転送し、RTK Fixを実現する。

    flags (1バイト) のビット構成:
      Bit 0 (LSB): Is_Fragmented  (分割あり=1, なし=0)
      Bit 1-2:     Fragment_ID    (0〜3)
      Bit 3-7:     Sequence_ID    (0〜31、フレームごとに+1)

    Args:
        mavlink_comm: MavlinkCommインスタンス
        max_packet_size: 1パケットの最大サイズ (デフォルト: 180)
        max_fragments: 最大分割数 (デフォルト: 4)
        logger: ロガーインスタンス
    """

    def __init__(self, mavlink_comm, max_packet_size: int = 180,
                 max_fragments: int = 4, logger: Optional[logging.Logger] = None):
        self._mav = mavlink_comm
        self.max_packet_size = max_packet_size
        self.max_fragments = max_fragments
        self.max_frame_size = max_packet_size * max_fragments  # 720
        self.log = logger or logging.getLogger("RtcmInjector")

        self._sequence_id = 0

        # 統計情報
        self.stats = {
            'frames_injected': 0,
            'frames_dropped': 0,
            'packets_sent': 0,
            'fragments_sent': 0,
        }

    def inject_frame(self, frame: bytes) -> bool:
        """RTCM3フレームをGPS_RTCM_DATAとして注入する

        Args:
            frame: RTCM3フレームのバイト列

        Returns:
            注入成功ならTrue、ドロップならFalse
        """
        frame_len = len(frame)

        # 最大フレームサイズ超過チェック
        if frame_len > self.max_frame_size:
            self.stats['frames_dropped'] += 1
            self.log.warning(
                f"RTCMフレームドロップ: {frame_len}バイト "
                f"(最大{self.max_frame_size}バイト超過)")
            return False

        if frame_len <= self.max_packet_size:
            # 分割不要
            flags = (self._sequence_id << 3) | 0  # Is_Fragmented=0, Fragment_ID=0
            data = list(frame) + [0] * (self.max_packet_size - frame_len)

            self._mav.send_rtcm_data(flags, frame_len, data)
            self.stats['packets_sent'] += 1
        else:
            # 分割送信
            num_fragments = (frame_len + self.max_packet_size - 1) // self.max_packet_size

            if num_fragments > self.max_fragments:
                self.stats['frames_dropped'] += 1
                self.log.warning(
                    f"フレーム分割数超過: {num_fragments} > {self.max_fragments} (ドロップ)")
                return False

            for frag_id in range(num_fragments):
                start = frag_id * self.max_packet_size
                end = min(start + self.max_packet_size, frame_len)
                frag_data = frame[start:end]
                frag_len = len(frag_data)

                flags = (self._sequence_id << 3) | (frag_id << 1) | 1  # Is_Fragmented=1

                data = list(frag_data) + [0] * (self.max_packet_size - frag_len)

                self._mav.send_rtcm_data(flags, frag_len, data)
                self.stats['fragments_sent'] += 1
                time.sleep(0.005)  # 分割パケット間の微小ディレイ

            self.stats['packets_sent'] += 1

        # Sequence ID更新（0〜31を巡回）
        self._sequence_id = (self._sequence_id + 1) % 32
        self.stats['frames_injected'] += 1
        return True