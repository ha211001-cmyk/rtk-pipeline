#!/usr/bin/env python3
"""checklist.py — Phase 3（RTK→EKF 取り込み・フェイルセーフ）の Item 判定とチェックリスト整形

Phase 3（飛行試験準備）では、以下の 4 項目を 1 コマンドで判定し、PASS/FAIL を
「飛行前チェックリスト」形式で一括レポートする:

  - Item F9P golden（52eb5 コンフィグ照合） … 静的（gcs.preflight.checklist.evaluate_item2 を再利用）
  - Item RTK→EKF ソース golden（要件 (1)）   … 静的（ArduPilotParamGuard の ekf_sources 群）
  - Item フェイルセーフ golden（要件 (2)）    … 静的（ArduPilotParamGuard の failsafe 群）
  - Item RTK 喪失時挙動（要件 (2)）           … 動的（fix_type 時系列 + EKF フラグ）

判定ロジックは純粋関数（``evaluate_ekf_sources`` / ``evaluate_failsafe`` /
``evaluate_rtk_loss_behavior``）として実装し、実ハードウェア不要の単体テストを
可能にする。Item のスキーマは ``gcs.preflight.checklist.CheckItem``（43d9f）と
同一のクラスを再利用しており、既存の飛行前セルフテスト（``PreflightReport``）へ
そのまま混ぜられる。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# 実行位置に依存しない import
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# 43d9f（gcs/preflight）の CheckItem / status 語彙を再利用（既存ファイルは無改変）
from gcs.preflight.checklist import (  # noqa: E402
    CheckItem,
    STATUS_PASS,
    STATUS_FAIL,
    STATUS_SKIP,
    GO,
    NO_GO,
    CONFIG_PASS_STATUSES,
    evaluate_item2,
)

from gcs.ekf_failsafe.golden import (  # noqa: E402
    GROUP_EKF_SOURCES,
    GROUP_FAILSAFE,
    GROUP_ORDER,
    PARAM_GROUPS,
    GOLDEN_PARAMS,
    LABELS,
    decode_gnss_mode,
    param_value_repr,
)

# ---------------------------------------------------------------------------
# 項目識別子（表示順）
# ---------------------------------------------------------------------------
ITEM_F9P_GOLDEN = "item_f9p_golden"      # 52eb5: F9P レジスタ golden 照合
ITEM_EKF_SRC = "item_ekf_sources"        # 要件 (1): RTK→EKF ソース golden
ITEM_FAILSAFE = "item_failsafe"          # 要件 (2): フェイルセーフ golden
ITEM_RTK_LOSS = "item_rtk_loss_behavior"  # 要件 (2): RTK 喪失時の EKF/FS 挙動

ITEM_ORDER = (ITEM_F9P_GOLDEN, ITEM_EKF_SRC, ITEM_FAILSAFE, ITEM_RTK_LOSS)

ITEM_NAMES = {
    ITEM_F9P_GOLDEN: "Item F9P コンフィグ照合（52eb5）",
    ITEM_EKF_SRC: "Item RTK→EKF ソース golden（要件1）",
    ITEM_FAILSAFE: "Item フェイルセーフ golden（要件2）",
    ITEM_RTK_LOSS: "Item RTK 喪失時の EKF/FS 挙動（要件2）",
}

# EKF_STATUS_REPORT.flags の主要ビット（位置・速度・姿勢が健全か）
_EKF_ATTITUDE = 0x001
_EKF_VELOCITY_HORIZ = 0x002
_EKF_VELOCITY_VERT = 0x004
_EKF_POS_HORIZ_ABS = 0x010
_EKF_POS_VERT_ABS = 0x020
_EKF_POSITION_HEALTHY_MASK = (
    _EKF_ATTITUDE | _EKF_VELOCITY_HORIZ | _EKF_VELOCITY_VERT
    | _EKF_POS_HORIZ_ABS | _EKF_POS_VERT_ABS
)


def _check(name: str, ok: bool, expected: Any = None, actual: Any = None,
           message: str = "") -> Dict[str, Any]:
    return {"name": name, "ok": bool(ok), "expected": expected,
            "actual": actual, "message": message}


def _filter_checked(guard_result: Dict[str, Any], group: str) -> Dict[str, Any]:
    checked = guard_result.get("checked") or {}
    return {name: item for name, item in checked.items() if item.get("group") == group}


def ekf_position_healthy(flags: Optional[int]) -> Optional[bool]:
    """EKF フラグから「位置・速度・姿勢が健全」かを判定する（未観測なら None）。"""
    if flags is None:
        return None
    return (int(flags) & _EKF_POSITION_HEALTHY_MASK) == _EKF_POSITION_HEALTHY_MASK


def _analyze_rtk_loss(series: List[Dict[str, Any]]) -> Dict[str, Any]:
    """fix_type 時系列から RTK 喪失イベントを解析する。

    RTK は fix_type 5（RTK_FLOAT）または 6（RTK_FIXED）。RTK(5,6) → 非RTK(0..4)
    への遷移を「RTK 喪失（ドロップアウト）」として数え、最長継続時間も求める。
    """
    reached_fixed = any(s.get("fix_type") == 6 for s in series)
    dropouts = 0
    longest = 0.0
    dropout_start: Optional[float] = None
    prev: Optional[int] = None
    for s in series:
        ft = s.get("fix_type")
        t = float(s.get("t", 0.0))
        is_rtk = ft in (5, 6)
        if prev in (5, 6) and not is_rtk:
            dropouts += 1
            dropout_start = t
        if is_rtk and dropout_start is not None:
            longest = max(longest, t - dropout_start)
            dropout_start = None
        prev = ft
    if dropout_start is not None and series:
        longest = max(longest, float(series[-1].get("t", 0.0)) - dropout_start)
    return {
        "reached_fixed": reached_fixed,
        "rtk_dropout_count": dropouts,
        "longest_dropout_sec": longest,
        "has_ekf_flags": any(s.get("ekf_flags") is not None for s in series),
    }


# ---------------------------------------------------------------------------
# Item 判定ロジック
# ---------------------------------------------------------------------------
def _evaluate_group(guard_result: Dict[str, Any], group: str, item_id: str) -> CheckItem:
    """指定グループの golden 照合結果から合否を判定する（共通ロジック）。"""
    status = guard_result.get("status", STATUS_FAIL)
    items = _filter_checked(guard_result, group)
    ok = status in CONFIG_PASS_STATUSES and bool(items) and all(
        it.get("ok") for it in items.values())

    checks = [_check(
        "guard_status", ok,
        expected="PASS|FIXED", actual=status,
        message=guard_result.get("summary", ""),
    )]
    for name, item in items.items():
        checks.append(_check(
            "param:%s" % name,
            bool(item.get("ok")),
            expected=item.get("expected"),
            actual=item.get("actual"),
            message=item.get("label", ""),
        ))

    summary = guard_result.get("summary") or ("Golden 値が正常です" if ok else "Golden 値に退行があります")
    details = {
        "guard_status": status,
        "group": group,
        "checked": items,
        "fixed": guard_result.get("fixed", []),
        "fix_failed": guard_result.get("fix_failed", []),
        "transport": guard_result.get("transport", {}),
    }
    return CheckItem(item_id, ITEM_NAMES[item_id],
                     STATUS_PASS if ok else STATUS_FAIL, summary, checks, details)


def evaluate_f9p_golden(config_result: Dict[str, Any]) -> CheckItem:
    """52eb5: F9P レジスタ golden 照合の合否（item_id を本モジュール用に付け替える）。

    ``gcs.preflight.checklist.evaluate_item2()``（43d9f）を再利用しつつ、
    ``Phase3Report`` の ``ITEM_ORDER`` に載るよう item_id を ``ITEM_F9P_GOLDEN`` にする。
    """
    item = evaluate_item2(config_result)
    return CheckItem(ITEM_F9P_GOLDEN, ITEM_NAMES[ITEM_F9P_GOLDEN],
                     item.status, item.summary, item.checks, item.details)


def evaluate_ekf_sources(guard_result: Dict[str, Any]) -> CheckItem:
    """要件 (1): RTK 測位を EKF へ取り込むソース指定（ekf_sources 群）の合否。"""
    return _evaluate_group(guard_result, GROUP_EKF_SOURCES, ITEM_EKF_SRC)


def evaluate_failsafe(guard_result: Dict[str, Any]) -> CheckItem:
    """要件 (2): フェイルセーフ設定（failsafe 群）の合否。

    GPS_GNSS_MODE は「GLONASS 実験後の復元確認」としてビット解釈を summary に含める。
    """
    item = _evaluate_group(guard_result, GROUP_FAILSAFE, ITEM_FAILSAFE)
    gnss = item.details.get("checked", {}).get("GPS_GNSS_MODE")
    if gnss is not None:
        actual = gnss.get("actual")
        item.details["gnss_mode"] = decode_gnss_mode(actual)
        item.checks.append(_check(
            "gps_gnss_mode_restored",
            bool(gnss.get("ok")),
            expected=param_value_repr("GPS_GNSS_MODE", GOLDEN_PARAMS.get("GPS_GNSS_MODE")),
            actual=decode_gnss_mode(actual),
            message="GPS_GNSS_MODE（GLONASS 実験後の復元確認）",
        ))
    return item


def evaluate_rtk_loss_behavior(series: List[Dict[str, Any]],
                               failsafe_ok: bool,
                               criteria: Optional[Dict[str, Any]] = None) -> CheckItem:
    """要件 (2): RTK FLOAT/FIXED 喪失時の EKF/フェイルセーフ挙動の合否。

    Args:
        series: ``[{t, fix_type, ekf_flags}, ...]`` の時系列。
        failsafe_ok: フェイルセーフ golden（evaluate_failsafe）が PASS かどうか。
        criteria: ``max_rtk_dropouts`` / ``max_dropout_sec``（省略時は既定値）。
    """
    criteria = dict(criteria or {})
    max_dropouts = int(criteria.get("max_rtk_dropouts", 2))
    max_dropout_sec = float(criteria.get("max_dropout_sec", 30.0))

    analysis = _analyze_rtk_loss(series)
    reached = bool(analysis["reached_fixed"])
    dropouts = int(analysis["rtk_dropout_count"])
    longest = float(analysis["longest_dropout_sec"])

    checks = [
        _check("reached_fixed", reached, expected=True, actual=reached,
               message="RTK_FIXED 到達"),
        _check("rtk_dropout_max", dropouts <= max_dropouts,
               expected="<= %d 回" % max_dropouts, actual="%d 回" % dropouts,
               message="RTK 喪失（RTK→非RTK）回数"),
        _check("max_dropout_sec", longest <= max_dropout_sec,
               expected="<= %.1f 秒" % max_dropout_sec, actual="%.1f 秒" % longest,
               message="RTK 喪失の最長継続時間"),
        _check("failsafe_armed", bool(failsafe_ok), expected=True, actual=bool(failsafe_ok),
               message="フェイルセーフ golden が有効（FS が正しく働く前提）"),
    ]

    # EKF フラグが観測できた場合のみ「EKF が最終サンプルで測位を維持」を検証する
    ekf_note = ""
    if analysis["has_ekf_flags"]:
        last_flags = None
        for s in series:
            if s.get("ekf_flags") is not None:
                last_flags = s.get("ekf_flags")
        healthy = ekf_position_healthy(last_flags)
        checks.append(_check(
            "ekf_position_maintained", bool(healthy),
            expected=True, actual=(healthy if healthy is not None else None),
            message="EKF が位置・速度を維持（最終サンプル）",
        ))
        ekf_note = "（EKF フラグ観測あり）"

    ok = all(c["ok"] for c in checks)
    if not reached:
        summary = "RTK_FIXED に到達しませんでした"
    elif ok:
        summary = "RTK 喪失 %d 回 / 最長 %.1f 秒 / FS 有効%s" % (dropouts, longest, ekf_note)
    else:
        summary = "RTK 喪失時の挙動が基準を満たしませんでした（FS 有効=%s）" % failsafe_ok

    details = dict(analysis)
    details["criteria"] = {"max_rtk_dropouts": max_dropouts,
                           "max_dropout_sec": max_dropout_sec}
    details["failsafe_ok"] = bool(failsafe_ok)
    return CheckItem(ITEM_RTK_LOSS, ITEM_NAMES[ITEM_RTK_LOSS],
                     STATUS_PASS if ok else STATUS_FAIL, summary, checks, details)


# ---------------------------------------------------------------------------
# 一括レポート（飛行前チェックリスト）
# ---------------------------------------------------------------------------
class Phase3Report:
    """F9P golden / RTK→EKF / フェイルセーフ / RTK 喪失挙動 を束ねたチェックリスト。

    ``gcs.preflight.checklist.PreflightReport`` と同じ CheckItem を使うため、
    to_dict()/to_json()/format_checklist() の出力スキーマは互換。既存の
    飛行前セルフテスト（43d9f）のレポートへそのまま統合できる。
    """

    def __init__(self, items: List[CheckItem],
                 connection: Optional[Dict[str, Any]] = None,
                 started_at: Optional[str] = None,
                 finished_at: Optional[str] = None):
        self.items = {it.item_id: it for it in items}
        self.connection = connection or {}
        self.started_at = started_at or datetime.now(timezone.utc).isoformat()
        self.finished_at = finished_at or datetime.now(timezone.utc).isoformat()

    def overall_status(self) -> str:
        if any(not it.is_pass() for it in self.items.values()):
            return STATUS_FAIL
        return STATUS_PASS

    def verdict(self) -> str:
        return GO if self.overall_status() == STATUS_PASS else NO_GO

    def to_dict(self) -> Dict[str, Any]:
        ordered = [self.items[i] for i in ITEM_ORDER if i in self.items]
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "connection": self.connection,
            "overall": {"status": self.overall_status(), "verdict": self.verdict()},
            "items": [it.to_dict() for it in ordered],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, default=str)

    def format_checklist(self) -> str:
        lines: List[str] = []
        bar = "=" * 70
        lines.append(bar)
        lines.append("Phase 3 飛行前チェックリスト（RTK→EKF 取り込み・フェイルセーフ）")
        conn = self.connection
        if conn:
            lines.append("接続: %s" % (conn.get("connection", conn.get("host", "-"))))
        lines.append("開始: %s" % self.started_at)
        lines.append("終了: %s" % self.finished_at)
        lines.append(bar)

        ordered = [self.items[i] for i in ITEM_ORDER if i in self.items]
        for it in ordered:
            mark = "PASS" if it.is_pass() else "FAIL"
            lines.append("[%s] %s" % (mark, it.name))
            lines.append("     %s" % it.summary)
            for c in it.checks:
                cm = "✓" if c["ok"] else "✗"
                exp = "" if c["expected"] is None else "（期待: %s）" % c["expected"]
                act = "" if c["actual"] is None else " = %s" % c["actual"]
                msg = (" / " + c["message"]) if c["message"] else ""
                lines.append("       [%s] %-24s%s%s%s" % (cm, c["name"], exp, act, msg))

        lines.append("-" * 70)
        overall = self.overall_status()
        note = "GO（飛行可）" if overall == STATUS_PASS else "NO-GO（飛行不可）"
        lines.append("総合判定: %s  →  %s" % (overall, note))
        lines.append(bar)
        return "\n".join(lines)


__all__ = [
    "ITEM_F9P_GOLDEN", "ITEM_EKF_SRC", "ITEM_FAILSAFE", "ITEM_RTK_LOSS",
    "ITEM_ORDER", "ITEM_NAMES",
    "STATUS_PASS", "STATUS_FAIL", "STATUS_SKIP", "GO", "NO_GO",
    "CONFIG_PASS_STATUSES",
    "CheckItem", "Phase3Report",
    "evaluate_f9p_golden", "evaluate_ekf_sources", "evaluate_failsafe",
    "evaluate_rtk_loss_behavior",
    "ekf_position_healthy",
]
