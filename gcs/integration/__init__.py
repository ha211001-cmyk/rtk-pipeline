#!/usr/bin/env python3
"""gcs.integration — GCS バックエンドコア（MAVLink 受信 + RTCM 送信 + GUI）

本番アーキテクチャ（DroneCAN + MAVLink + UDP）の GCS 側統合パッケージ:

- ``MavlinkTelemetryReader`` : ローバーから届く MAVLink を UDP で待ち受け、
  GPS_RAW_INT / HEARTBEAT / SYS_STATUS を機体（system_id）ごとに保持する。
- ``RtcmCaster``            : 基地局（USB）から RTCM3 を読み、複数 UDP エンド
  ポイントへファンアウトする。
- ``GcsBackend``            : 上記2つを並行スレッドで稼働させるバックエンド。
- ``display``               : 機体状態 → 表示行 の純粋変換（``format_vehicle_rows``）。

> 旧 PyQt5 GUI（``gcs.integration.gui``）は Phase 0 統合計画（§6）に基づき
> ``gcs/_retired/integration_gui_pyqt5/`` へ退避した。メイン UI は
> Web ダッシュボード（``python3 -m gcs.server``）に一本化している。

旧 Phase1 統合テスト（① コンフィグ自動診断 / ② RTK ステータス / ③ RTCM 健全性）
のレポート型（``report.py``）は後方互換のため残置する。

利用例:
    from gcs.integration.runner import GcsBackend

    backend = GcsBackend(mavlink_port=14550,
                         rtcm_source_port="/dev/ttyACM0",
                         rtcm_destinations=[("192.168.1.10", 14550)])
    backend.start()
    snapshot = backend.snapshot()
"""

from .report import (  # noqa: F401
    PHASE1,
    PHASE2,
    PHASE3,
    STATUS_PASS,
    STATUS_FAIL,
    STATUS_WARN,
    PhaseResult,
    IntegrationReport,
)

__all__ = [
    "PHASE1",
    "PHASE2",
    "PHASE3",
    "STATUS_PASS",
    "STATUS_FAIL",
    "STATUS_WARN",
    "PhaseResult",
    "IntegrationReport",
    "MavlinkTelemetryReader",
    "RtcmCaster",
    "GcsBackend",
]

# 遅延 export（パッケージ import 時に pymavlink / GUI を巻き込まない。
# これにより ``python3 -m gcs.integration.runner`` が安全に実行できる）
_LAZY_EXPORTS = {
    "MavlinkTelemetryReader": ("sources", "MavlinkTelemetryReader"),
    "RtcmCaster": ("rtcm_caster", "RtcmCaster"),
    "GcsBackend": ("runner", "GcsBackend"),
}


def __getattr__(name: str):
    if name in _LAZY_EXPORTS:
        import importlib
        modname, attr = _LAZY_EXPORTS[name]
        module = importlib.import_module("." + modname, __name__)
        value = getattr(module, attr)
        globals()[name] = value
        return value
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
