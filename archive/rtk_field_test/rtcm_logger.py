#!/usr/bin/env python3
"""
rtcm_logger.py — RTCM3 生フレームの .rtcm3 保存 + msgType 集計（base/rover 共用）

base_recorder.py / rover_recorder.py から共通利用する、RTCM ログ保存ヘルパー。
標準ライブラリのみで動作する。

使い方:
    from rtcm_logger import RtcmFrameLogger

    logger = RtcmFrameLogger(log_dir="logs", tag="base")
    logger.write(frame)
    ...
    logger.summary()   # msgType 別集計を表示
    logger.close()     # ファイルを閉じ、保存先パスを表示
"""

import os
from collections import Counter
from datetime import datetime
from typing import Optional

# RTCM3 メッセージ種別（1000番台の一般 RTK 補正メッセージ）。表示順の参照用。
KNOWN_RTCM_MSG_TYPES = [
    1001, 1002, 1003, 1004, 1005, 1006, 1007, 1008, 1009, 1010,
    1011, 1012, 1013, 1019, 1020, 1033,
    1074, 1075, 1077, 1084, 1085, 1087, 1094, 1095, 1097,
    1117, 1124, 1127, 1230,
]

RTCM_NAMES = {
    1005: "Station ARP",
    1006: "Station ARP+AH",
    1033: "Rx/Ant Descr",
    1074: "GPS MSM4", 1075: "GPS MSM5", 1077: "GPS MSM7",
    1084: "GLO MSM4", 1085: "GLO MSM5", 1087: "GLO MSM7",
    1094: "GAL MSM4", 1095: "GAL MSM5", 1097: "GAL MSM7",
    1114: "QZSS MSM4", 1115: "QZSS MSM5", 1117: "QZSS MSM7",
    1124: "BDS MSM4", 1125: "BDS MSM5", 1127: "BDS MSM7",
    1230: "GLO Bias",
}


def rtcm_message_type(frame: bytes) -> Optional[int]:
    """RTCM3 フレームの先頭 12bit からメッセージ種別を抽出する。

    フレーム構造:
        byte0:     0xD3 (preamble)
        byte1-2:   6bit reserved + 10bit length
        byte3-4(上位4bit): 12bit message type
    """
    if len(frame) < 5:
        return None
    if frame[0] != 0xD3:
        return None
    return (frame[3] << 4) | (frame[4] >> 4)


class RtcmFrameLogger:
    """RTCM3 生フレームを .rtcm3 ファイルへ追記し、msgType を集計する。"""

    def __init__(self, log_dir: str = "logs", tag: str = "rtcm"):
        self.log_dir = log_dir
        self.tag = tag
        self.counter = Counter()
        self.total_frames = 0
        self.total_bytes = 0
        os.makedirs(log_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = os.path.join(log_dir, "rtcm_%s_%s.rtcm3" % (tag, ts))
        self._fh = open(self.path, "wb")
        print("[LOG] RTCM 保存先: %s" % self.path)

    def write(self, frame: bytes) -> None:
        """RTCM3 フレームを追記保存し、msgType をカウントする。"""
        self._fh.write(frame)
        self._fh.flush()
        self.total_frames += 1
        self.total_bytes += len(frame)
        mt = rtcm_message_type(frame)
        if mt is not None:
            self.counter[mt] += 1

    def summary(self) -> None:
        """受信した RTCM の msgType 別集計を表示する。"""
        print("\n" + "=" * 60)
        print("[LOG] RTCM 受信集計（%s）" % self.tag)
        print("=" * 60)
        print("  フレーム数 : %d" % self.total_frames)
        print("  バイト数   : %d" % self.total_bytes)
        if self.counter:
            present = set(self.counter)
            order = [mt for mt in KNOWN_RTCM_MSG_TYPES if mt in present]
            order += sorted(mt for mt in present if mt not in KNOWN_RTCM_MSG_TYPES)
            print("\n  msgType 別 集計:")
            print("  %8s  %-14s  %8s" % ("msgType", "名称", "受信回数"))
            print("  " + "-" * 34)
            for mt in order:
                name = RTCM_NAMES.get(mt, "Unknown")
                print("  %8d  %-14s  %8d" % (mt, name, self.counter[mt]))

    def close(self) -> None:
        """ファイルを閉じ、保存先パスを表示する。"""
        try:
            self._fh.close()
        except Exception:
            pass
        print("[LOG] 保存完了: %s" % self.path)
