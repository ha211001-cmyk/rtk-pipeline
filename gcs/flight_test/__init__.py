#!/usr/bin/env python3
"""gcs.flight_test — Phase 4 実飛行試験

地上で確立した RTK-FIXED を飛行中も維持できるかを、EKF/フェイルセーフ設定（2e8a3）が
有効な状態で検証し、飛行試験結果をレポートとして残すモジュール群。

- ``metrics.py``  : 定量評価（RTK-FIXED維持率 / EKF整合性 / 劣化検知 / FS確認 / 課題整理）
- ``recorder.py`` : MAVLink 観測（fix_type 時系列・位置精度・FS/モードイベント）の記録
- ``report.py``   : ``FlightReport``（JSON / Markdown）
- ``runner.py``   : CLI（``--observe`` / ``--csv`` / ``--self-test``）

利用例:
    from gcs.flight_test.metrics import compute_ekf_consistency, confirm_failsafe
    from gcs.flight_test.report import FlightReport
    from gcs.flight_test.runner import FlightTestRunner
"""

from .metrics import (  # noqa: F401
    STATUS_PASS, STATUS_FAIL, STATUS_SKIP, STATUS_INFO,
    RTK_TYPES, FS_MODES,
    FlightSpec,
    compute_ekf_consistency,
    detect_degradations,
    classify_failsafe_text,
    confirm_failsafe,
    next_phase_issues,
)
from .recorder import (  # noqa: F401
    CSV_FIELDS,
    FlightRecorder,
    write_flight_csv,
    write_events_jsonl,
    load_flight_csv,
    load_events_jsonl,
)
from .report import FlightReport, utc_now_iso  # noqa: F401
from .runner import FlightTestRunner, DEFAULT_CONFIG, load_flight_config  # noqa: F401

__all__ = [
    "STATUS_PASS", "STATUS_FAIL", "STATUS_SKIP", "STATUS_INFO",
    "RTK_TYPES", "FS_MODES",
    "FlightSpec",
    "compute_ekf_consistency",
    "detect_degradations",
    "classify_failsafe_text",
    "confirm_failsafe",
    "next_phase_issues",
    "CSV_FIELDS", "FlightRecorder",
    "write_flight_csv", "write_events_jsonl",
    "load_flight_csv", "load_events_jsonl",
    "FlightReport", "utc_now_iso",
    "FlightTestRunner", "DEFAULT_CONFIG", "load_flight_config",
]
