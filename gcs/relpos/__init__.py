#!/usr/bin/env python3
"""gcs.relpos — 複数ローバーの UBX-NAV-RELPOSNED ペアリング（協調搬送用）

協調搬送に向けた自作 GCS 拡張。複数ローバーの RELPOSNED を同一 iTOW
（GPS 時刻エポック）でペアリングして機体間相対位置（相対距離・相対方位・
相対位置精度・エポック整合状態）を算出・可視化・ログ記録する。

利用例:
    from gcs.relpos.pairing import RelposPairingBuffer, RelposnedSample
    from gcs.relpos.reader import UbxRelposReader

構成:
  - pairing.py  : 中核ロジック（標準ライブラリのみ・ペアリング/誤差伝播/ロールオーバー）
  - reader.py   : UBX-NAV-RELPOSNED のシリアル読み取り（pyubx2 利用）
  - monitor.py  : 2 ローバーのライブ表示＋CSV 記録ドライバ（CLI）
"""

from .pairing import (  # noqa: F401
    ITOW_PER_WEEK_MS,
    ITOW_HALF_WEEK_MS,
    PAIRED_CSV_FIELDS,
    PairedRelpos,
    RelposnedSample,
    RelposPairingBuffer,
    compute_relative,
    itow_diff_ms,
    normalize_bearing_deg,
    propagate_accuracy,
    signed_heading_delta_deg,
)

__all__ = [
    "ITOW_PER_WEEK_MS",
    "ITOW_HALF_WEEK_MS",
    "PAIRED_CSV_FIELDS",
    "PairedRelpos",
    "RelposnedSample",
    "RelposPairingBuffer",
    "compute_relative",
    "itow_diff_ms",
    "normalize_bearing_deg",
    "propagate_accuracy",
    "signed_heading_delta_deg",
]
