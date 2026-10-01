#!/usr/bin/env python3
"""gcs.preflight — Phase 3 飛行前セルフテスト（飛行試験準備）

静的照合（Item 2 golden 差分）と動的健全性（Item 1 FIXED 率・Item 3 RTCM CRC/age・
基地局レート）を 1 コマンドで実行し、PASS/FAIL の一括レポート（飛行前チェックリスト）
を出力する。接続は DroneCAN Serial Forwarding の単一 TCP エンドポイントに統一する。

利用例:
    from gcs.preflight.checklist import PreflightReport, evaluate_item1
    from gcs.preflight.runner import PreflightRunner
    from gcs.preflight.session import TcpSession
"""

from .checklist import (  # noqa: F401
    ITEM1, ITEM2, ITEM3, BASE_RATE,
    STATUS_PASS, STATUS_FAIL, STATUS_SKIP,
    CheckItem, PreflightReport,
    evaluate_item1, evaluate_item2, evaluate_item3, evaluate_base_rate,
)
from .session import TcpSession  # noqa: F401
from .runner import PreflightRunner, DEFAULT_CONFIG, load_preflight_config  # noqa: F401

__all__ = [
    "ITEM1", "ITEM2", "ITEM3", "BASE_RATE",
    "STATUS_PASS", "STATUS_FAIL", "STATUS_SKIP",
    "CheckItem", "PreflightReport",
    "evaluate_item1", "evaluate_item2", "evaluate_item3", "evaluate_base_rate",
    "TcpSession", "PreflightRunner", "DEFAULT_CONFIG", "load_preflight_config",
]
