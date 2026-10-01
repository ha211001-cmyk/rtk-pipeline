#!/usr/bin/env python3
"""
gcs — 補正データ連続監視（自作 GCS 統合用）パッケージ

RTCM 補正データが「静かに途切れる事故」を防ぐための監視ロジックを提供する。

利用例:
    from gcs import CorrectionMonitor

    mon = CorrectionMonitor(age_alert_threshold=10.0)
    mon.feed_rtcm3(rtcm3_bytes)   # 基地局ストリーム
    mon.feed_ubx(ubx_bytes)       # ローバー F9P の UBX バイト列
    snapshot = mon.snapshot()     # GCS に統合可能な dict
"""

from .rtcm_monitor import (  # noqa: F401
    UBX_SYNC_1,
    UBX_SYNC_2,
    UBX_RXM_RTCM_CLASS,
    UBX_RXM_RTCM_ID,
    RTCM3_PREAMBLE,
    KNOWN_RTCM_MSG_TYPES,
    MSG_USED_NAMES,
    ubx_checksum,
    rtcm3_crc24q,
    rtcm3_verify_frame,
    rtcm3_frame_msg_type,
    parse_rxm_rtcm,
    format_msg_used,
    UbxParser,
    Rtcm3StreamParser,
    RtkAgeMonitor,
    CrcErrorAggregator,
    RxmRtcmMonitor,
    CorrectionMonitor,
)

__all__ = [
    "UBX_SYNC_1",
    "UBX_SYNC_2",
    "UBX_RXM_RTCM_CLASS",
    "UBX_RXM_RTCM_ID",
    "RTCM3_PREAMBLE",
    "KNOWN_RTCM_MSG_TYPES",
    "MSG_USED_NAMES",
    "ubx_checksum",
    "rtcm3_crc24q",
    "rtcm3_verify_frame",
    "rtcm3_frame_msg_type",
    "parse_rxm_rtcm",
    "format_msg_used",
    "UbxParser",
    "Rtcm3StreamParser",
    "RtkAgeMonitor",
    "CrcErrorAggregator",
    "RxmRtcmMonitor",
    "CorrectionMonitor",
]
