#!/usr/bin/env python3
"""checklist.py — 飛行前セルフテストの Item 判定とチェックリスト整形（標準ライブラリのみ）

Phase 3（飛行試験準備）のセルフテストでは、以下の 4 項目を 1 コマンドで判定し、
PASS/FAIL を「飛行前チェックリスト」形式で一括レポートする。

  - Item 2 コンフィグ照合（golden 差分）   … 静的照合（F9pConfigGuard）
  - Item 1 RTK FIXED 率                    … 動的健全性（fix_metrics）
  - Item 3 RTCM リンク健全性（CRC/age）    … 動的健全性（CorrectionMonitor）
  - 基地局レート（RTCM 補正到達レート）    … 動的健全性（UBX-RXM-RTCM 到達 msg/s）

判定ロジックは純粋関数（``evaluate_item1/2/3`` / ``evaluate_base_rate``）として実装し、
実ハードウェア不要の単体テストを可能にする。レポート整形は ``PreflightReport`` が担う。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# 項目識別子（Item 2 → Item 1 → Item 3 → 基地局レート の順でレポートする）
# ---------------------------------------------------------------------------
ITEM1 = "item1_fixed_rate"      # Item 1: RTK FIXED 率
ITEM2 = "item2_config_golden"   # Item 2: コンフィグ golden 差分
ITEM3 = "item3_rtcm_health"     # Item 3: RTCM CRC / RTK age
BASE_RATE = "base_rate"         # 基地局レート（RTCM 補正到達レート）

ITEM_ORDER = (ITEM2, ITEM1, ITEM3, BASE_RATE)

ITEM_NAMES = {
    ITEM2: "Item 2 コンフィグ照合（golden差分）",
    ITEM1: "Item 1 RTK FIXED率",
    ITEM3: "Item 3 RTCMリンク健全性（CRC/age）",
    BASE_RATE: "基地局レート（RTCM補正到達レート）",
}

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_SKIP = "SKIP"

# F9pConfigGuard.run_check_and_fix() / check() の status のうち「合格」とみなす値
CONFIG_PASS_STATUSES = ("PASS", "FIXED")

# 飛行可否（pre-flight checklist の GO / NO-GO）
GO = "GO"
NO_GO = "NO-GO"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check(name: str, ok: bool, expected: Any = None, actual: Any = None,
           message: str = "") -> Dict[str, Any]:
    """判定項目を 1 件分の dict にする。"""
    return {
        "name": name,
        "ok": bool(ok),
        "expected": expected,
        "actual": actual,
        "message": message,
    }


class CheckItem:
    """1 項目分の判定結果。checks は判定項目のリスト、details は生データ。"""

    def __init__(self, item_id: str, name: str, status: str, summary: str = "",
                 checks: Optional[List[Dict[str, Any]]] = None,
                 details: Optional[Dict[str, Any]] = None):
        self.item_id = item_id
        self.name = name
        self.status = status
        self.summary = summary
        self.checks = checks or []
        self.details = details or {}

    def is_pass(self) -> bool:
        return self.status == STATUS_PASS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "name": self.name,
            "status": self.status,
            "summary": self.summary,
            "checks": self.checks,
            "details": self.details,
        }


# ---------------------------------------------------------------------------
# Item 判定ロジック
# ---------------------------------------------------------------------------
def evaluate_item2(config_result: Dict[str, Any]) -> CheckItem:
    """Item 2: F9pConfigGuard の照合結果（golden 差分）から合否を判定する。

    status が PASS（修正不要）または FIXED（退行を自動修正済み）なら合格。
    checked の各 Golden 値も併せて判定項目に含める。
    """
    status = config_result.get("status", STATUS_FAIL)
    ok = status in CONFIG_PASS_STATUSES

    checks = [
        _check("config_guard_status", ok,
               expected="PASS|FIXED", actual=status,
               message=config_result.get("summary", "")),
    ]
    for name, item in (config_result.get("checked") or {}).items():
        key_display = item.get("key_display") or item.get("key") or name
        checks.append(_check(
            "golden:%s" % key_display,
            bool(item.get("ok")),
            expected=item.get("expected"),
            actual=item.get("actual"),
            message=item.get("label", ""),
        ))

    if ok:
        summary = config_result.get("summary") or "Golden 値は正常です"
    else:
        summary = config_result.get("summary") or "Golden 値に退行があります"

    details = {
        "guard_status": status,
        "checked": config_result.get("checked", {}),
        "fixed": config_result.get("fixed", []),
        "fix_failed": config_result.get("fix_failed", []),
        "transport": config_result.get("transport", {}),
    }
    return CheckItem(ITEM2, ITEM_NAMES[ITEM2], STATUS_PASS if ok else STATUS_FAIL,
                     summary, checks, details)


def evaluate_item1(metrics: Dict[str, Any], criteria: Dict[str, Any]) -> CheckItem:
    """Item 1: fix_metrics.compute_metrics() の戻り値から合否を判定する。

    FIXED 到達・維持率（FIXED 率）・FLOAT 遷移回数・TTFF を判定する。
    """
    reached = bool(metrics.get("reached_fixed"))
    fixed_rate = float(metrics.get("fixed_rate_pct", 0.0) or 0.0)
    float_cnt = int(metrics.get("float_transition_count", 0) or 0)
    ttff = metrics.get("ttff_sec")

    rate_min = float(criteria.get("fixed_rate_pct_min", 80.0))
    max_float = int(criteria.get("max_float_transitions", 5))
    ttff_max = float(criteria.get("ttff_sec_max", 120.0))

    checks = [
        _check("reached_fixed", reached,
               expected=True, actual=reached,
               message="RTK_FIXED 到達" if reached else "RTK_FIXED 未到達"),
        _check("fixed_rate_min", reached and fixed_rate >= rate_min,
               expected=">= %.1f %%" % rate_min,
               actual="%.1f %%" % fixed_rate,
               message="FIXED 率（全期間）"),
        _check("float_transition_max", float_cnt <= max_float,
               expected="<= %d 回" % max_float,
               actual="%d 回" % float_cnt,
               message="FLOAT 遷移回数"),
    ]

    if reached:
        checks.append(_check(
            "ttff_max",
            ttff is not None and float(ttff) <= ttff_max,
            expected="<= %.1f 秒" % ttff_max,
            actual=("n/a" if ttff is None else "%.1f 秒" % float(ttff)),
            message="TTFF（初回 FIXED）",
        ))

    ok = all(c["ok"] for c in checks)
    if not reached:
        summary = "RTK_FIXED に到達しませんでした"
    elif ok:
        summary = ("FIXED 率 %.1f%% / FLOAT 遷移 %d 回 / TTFF %.1f 秒"
                   % (fixed_rate, float_cnt, float(ttff or 0.0)))
    else:
        summary = "RTK_FIXED には到達したが定量基準を満たしませんでした"

    return CheckItem(ITEM1, ITEM_NAMES[ITEM1], STATUS_PASS if ok else STATUS_FAIL,
                     summary, checks, metrics)


def evaluate_item3(snapshot: Dict[str, Any], criteria: Dict[str, Any]) -> CheckItem:
    """Item 3: CorrectionMonitor.snapshot() の戻り値から合否を判定する。

    RTCM 到達（age が no_data/stale でない）・CRC エラー率・msgUsed 比率・
    クリティカルアラートの有無を判定する。
    """
    age = snapshot.get("rtk_age", {})
    age_state = age.get("state", "no_data")
    age_sec = age.get("age_sec")

    crc = snapshot.get("crc", {})
    ubx_crc = crc.get("ubx_rxm_rtcm", {})
    rtcm3_crc = crc.get("rtcm3_frame", {})
    rxm = snapshot.get("rxm_rtcm", {})
    alerts = snapshot.get("alerts", [])

    crc_rate_max = float(criteria.get("crc_alert_rate_pct", 5.0))
    used_ratio_min = float(criteria.get("used_alert_ratio_pct", 50.0))

    critical = [a for a in alerts if a.get("level") == "critical"]
    critical_codes = [a.get("code") for a in critical]

    checks = [
        _check("rtk_age_received", age_state != "no_data",
               expected="受信あり", actual=age_state,
               message="RTCM 補正データを受信したか"),
        _check("rtk_age_not_stale", age_state != "stale",
               expected="stale でない", actual=age_state,
               message="最終受信からの経過秒（RTK age）"),
        _check("ubx_crc_rate", float(ubx_crc.get("rate_pct", 0.0) or 0.0) <= crc_rate_max,
               expected="<= %.1f %%" % crc_rate_max,
               actual="%.2f %%" % float(ubx_crc.get("rate_pct", 0.0) or 0.0),
               message="UBX-RXM-RTCM CRC エラー率"),
        _check("rtcm3_crc_rate", float(rtcm3_crc.get("rate_pct", 0.0) or 0.0) <= crc_rate_max,
               expected="<= %.1f %%" % crc_rate_max,
               actual="%.2f %%" % float(rtcm3_crc.get("rate_pct", 0.0) or 0.0),
               message="RTCM3 フレーム CRC エラー率"),
        _check("no_critical_alerts", len(critical) == 0,
               expected="0 件", actual="%d 件" % len(critical),
               message="クリティカルアラート（%s）"
                       % (", ".join(critical_codes) if critical_codes else "なし")),
    ]

    if int(rxm.get("total", 0) or 0) > 0:
        used_ratio = float(rxm.get("used_ratio_pct", 0.0) or 0.0)
        checks.append(_check(
            "msg_used_ratio", used_ratio >= used_ratio_min,
            expected=">= %.1f %%" % used_ratio_min,
            actual="%.1f %%" % used_ratio,
            message="msgUsed=使用済み 比率",
        ))

    ok = all(c["ok"] for c in checks)
    summary = ("RTK age=%s"
               % (age_state if age_state != "ok" else "%.1f 秒" % (age_sec or 0.0))
               + " / UBX-RXM-RTCM total=%d" % int(rxm.get("total", 0) or 0)
               + " / CRC(UBX)=%.2f%%" % float(ubx_crc.get("rate_pct", 0.0) or 0.0))

    return CheckItem(ITEM3, ITEM_NAMES[ITEM3], STATUS_PASS if ok else STATUS_FAIL,
                     summary, checks, snapshot)


def evaluate_base_rate(snapshot: Dict[str, Any], duration_sec: float,
                       criteria: Dict[str, Any]) -> CheckItem:
    """基地局レート: ローバー UBX-RXM-RTCM の到達レート（msg/s）から合否を判定する。

    基地局からローバーへ届く RTCM 補正メッセージの到達レート（＝基地局出力の
    実効レート）を、観測時間あたりの UBX-RXM-RTCM 件数で評価する。
    """
    rxm = snapshot.get("rxm_rtcm", {})
    total = int(rxm.get("total", 0) or 0)
    rate_fps = (total / float(duration_sec)) if duration_sec > 0 else 0.0
    min_fps = float(criteria.get("base_rate_min_fps", 1.0))

    checks = [
        _check("base_rate_received", total > 0,
               expected="受信あり", actual="%d msg" % total,
               message="RTCM 補正メッセージ受信数"),
        _check("base_rate_min", total > 0 and rate_fps >= min_fps,
               expected=">= %.1f msg/s" % min_fps,
               actual="%.2f msg/s" % rate_fps,
               message="基地局 RTCM 補正到達レート"),
    ]

    ok = all(c["ok"] for c in checks)
    summary = "到達レート %.2f msg/s（%d msg / %.1f 秒）" % (rate_fps, total, duration_sec)

    details = {
        "total_msgs": total,
        "rate_fps": rate_fps,
        "duration_sec": duration_sec,
        "by_msg_type": rxm.get("by_msg_type", {}),
    }
    return CheckItem(BASE_RATE, ITEM_NAMES[BASE_RATE], STATUS_PASS if ok else STATUS_FAIL,
                     summary, checks, details)


# ---------------------------------------------------------------------------
# 一括レポート（飛行前チェックリスト）
# ---------------------------------------------------------------------------
class PreflightReport:
    """Item 2 / Item 1 / Item 3 / 基地局レート を束ねた飛行前チェックリスト。"""

    def __init__(self, items: List[CheckItem],
                 connection: Optional[Dict[str, Any]] = None,
                 started_at: Optional[str] = None,
                 finished_at: Optional[str] = None):
        self.items = {it.item_id: it for it in items}
        self.connection = connection or {}
        self.started_at = started_at or utc_now_iso()
        self.finished_at = finished_at or utc_now_iso()

    def overall_status(self) -> str:
        if any(not it.is_pass() for it in self.items.values()):
            return STATUS_FAIL
        return STATUS_PASS

    def verdict(self) -> str:
        """飛行可否（GO / NO-GO）。"""
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
        """人間可読な「飛行前チェックリスト」形式のテキストを返す。"""
        lines: List[str] = []
        bar = "=" * 70
        lines.append(bar)
        lines.append("飛行前セルフテスト チェックリスト（Phase 3 / 飛行試験準備）")
        conn = self.connection
        if conn:
            host = conn.get("host", "-")
            port = conn.get("port", "-")
            lines.append("接続: TCP %s:%s (DroneCAN Serial Forwarding)" % (host, port))
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
        verdict = self.verdict()
        if overall == STATUS_PASS:
            note = "GO（飛行可）"
        else:
            note = "NO-GO（飛行不可）"
        lines.append("総合判定: %s  →  %s" % (overall, note))
        lines.append(bar)
        return "\n".join(lines)


__all__ = [
    "ITEM1", "ITEM2", "ITEM3", "BASE_RATE", "ITEM_ORDER", "ITEM_NAMES",
    "STATUS_PASS", "STATUS_FAIL", "STATUS_SKIP",
    "CONFIG_PASS_STATUSES", "GO", "NO_GO",
    "CheckItem", "PreflightReport",
    "evaluate_item1", "evaluate_item2", "evaluate_item3", "evaluate_base_rate",
    "utc_now_iso",
]
