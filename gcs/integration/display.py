#!/usr/bin/env python3
"""display.py — GCS バックエンドの機体状態 → 表示行 変換（純関数・GUI 非依存）。

Phase 0 統合計画（§6 / §7 Phase 4 後処理）に基づき、旧 ``gcs/integration/gui.py``
（PyQt5）に同居していた「機体状態 dict → 一覧表示行」の純粋変換ロジックを
本モジュールへ分離した。GUI（``GcsMonitorWindow``）は ``gcs/_retired/`` へ退避し、
本モジュールは Qt に依存せず単体テスト可能な形で維持する（``test_runner.py`` が参照）。

``gcs.app.display``（Web ダッシュボードのペイロード変換）とは別物で、こちらは
``GcsBackend.snapshot()`` が返す flattened 車両状態の表形式行変換を担う。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

COLUMNS = [
    ("system_id", "機体ID"),
    ("type", "種別"),
    ("fix", "Fix"),
    ("sats", "衛星数"),
    ("mode", "フライトモード"),
    ("battery", "バッテリー"),
    ("armed", "ARM"),
    ("age", "最終更新"),
]


def format_vehicle_rows(vehicles: Dict[int, Dict[str, Any]],
                        now: Optional[float] = None) -> List[List[Any]]:
    """機体状態 dict を GUI 表示用の行リストへ変換する（テスト可能な純関数）。"""
    now = time.time() if now is None else now
    rows: List[List[Any]] = []
    for sid in sorted(vehicles):
        v = vehicles[sid]
        age = v.get("last_update")
        age_s = ("%.1fs" % (now - age)) if age is not None else "-"
        batt = v.get("battery_voltage_v")
        if batt is not None and v.get("battery_remaining_pct") is not None:
            batt_s = "%.1fV/%d%%" % (batt, v["battery_remaining_pct"])
        elif batt is not None:
            batt_s = "%.1fV" % batt
        else:
            batt_s = "-"
        rows.append([
            sid,
            v.get("vehicle_type_name") or v.get("vehicle_type") or "-",
            v.get("fix_name") or v.get("fix_type") or "-",
            v.get("satellites") if v.get("satellites") is not None else "-",
            v.get("flight_mode") or "-",
            batt_s,
            "ARM" if v.get("armed") else "DISARM",
            age_s,
        ])
    return rows


__all__ = ["COLUMNS", "format_vehicle_rows"]
