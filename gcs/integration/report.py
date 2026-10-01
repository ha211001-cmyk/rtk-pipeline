#!/usr/bin/env python3
"""report.py — 統合テストの PASS/FAIL 判定と一括レポート出力（標準ライブラリのみ）

Phase 1 ゴール「実機1台で地上 RTK-FIXED を安定確立」の合否を、①〜③の各フェーズ
結果から定量判定し、人間可読なコンソール出力と JSON（GCS 統合用）の両方を生成する。

判定は純粋関数（``evaluate_phase1/2/3``）として実装し、実ハードウェア不要の
単体テストを可能にする。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# フェーズ識別子
PHASE1 = "phase1_config"       # ① コンフィグ自動診断
PHASE2 = "phase2_rtk_status"   # ② RTKステータス監視
PHASE3 = "phase3_rtcm_health"  # ③ RTCMリンク健全性監視

# フェーズ名（人間向け）
PHASE_NAMES = {
    PHASE1: "① コンフィグ自動診断",
    PHASE2: "② RTKステータス監視（FIXED 定量判定）",
    PHASE3: "③ RTCMリンク健全性監視",
}

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_WARN = "WARN"

# ① F9pConfigGuard.run_check_and_fix() の status のうち「合格」とみなす値
CONFIG_PASS_STATUSES = ("PASS", "FIXED")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check(name: str, ok: bool, expected: Any = None, actual: Any = None,
           message: str = "") -> Dict[str, Any]:
    """判定項目を1件分の dict にする。"""
    return {
        "name": name,
        "ok": bool(ok),
        "expected": expected,
        "actual": actual,
        "message": message,
    }


class PhaseResult:
    """1フェーズ分の結果。checks は判定項目のリスト、details は生データ。"""

    def __init__(self, phase: str, status: str, summary: str = "",
                 checks: Optional[List[Dict[str, Any]]] = None,
                 details: Optional[Dict[str, Any]] = None):
        self.phase = phase
        self.name = PHASE_NAMES.get(phase, phase)
        self.status = status
        self.summary = summary
        self.checks = checks or []
        self.details = details or {}

    def is_pass(self) -> bool:
        return self.status == STATUS_PASS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase": self.phase,
            "name": self.name,
            "status": self.status,
            "summary": self.summary,
            "checks": self.checks,
            "details": self.details,
        }


# ---------------------------------------------------------------------------
# 判定ロジック
# ---------------------------------------------------------------------------
def evaluate_phase1(config_result: Dict[str, Any]) -> PhaseResult:
    """① F9pConfigGuard の戻り値から合否を判定する。

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
    return PhaseResult(PHASE1, STATUS_PASS if ok else STATUS_FAIL, summary,
                       checks, details)



def evaluate_phase2(metrics: Dict[str, Any], criteria: Dict[str, Any]) -> PhaseResult:
    """② fix_metrics.compute_metrics() の戻り値から合否を判定する。

    要件(2): FIXED 到達・維持率・FLOAT 遷移回数・TTFF。
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
               message="FIXED 維持率（全期間）"),
        _check("float_transition_max", float_cnt <= max_float,
               expected="<= %d 回" % max_float,
               actual="%d 回" % float_cnt,
               message="FLOAT 遷移回数"),
    ]

    # TTFF は FIXED 到達時のみ判定
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
        summary = ("FIXED 維持率 %.1f%% / FLOAT 遷移 %d 回 / TTFF %.1f 秒"
                   % (fixed_rate, float_cnt, float(ttff or 0.0)))
    else:
        summary = "RTK_FIXED には到達したが定量基準を満たしませんでした"

    # details には完全な metrics を格納（遷移一覧含む）
    return PhaseResult(PHASE2, STATUS_PASS if ok else STATUS_FAIL, summary,
                       checks, metrics)



def evaluate_phase3(snapshot: Dict[str, Any], criteria: Dict[str, Any]) -> PhaseResult:
    """③ CorrectionMonitor.snapshot() の戻り値から合否を判定する。

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

    # msgUsed=使用済み 比率は RXM-RTCM データがある場合のみ判定
    if int(rxm.get("total", 0) or 0) > 0:
        used_ratio = float(rxm.get("used_ratio_pct", 0.0) or 0.0)
        checks.append(_check(
            "msg_used_ratio", used_ratio >= used_ratio_min,
            expected=">= %.1f %%" % used_ratio_min,
            actual="%.1f %%" % used_ratio,
            message="msgUsed=使用済み 比率",
        ))

    ok = all(c["ok"] for c in checks)
    summary = ("RTK age=%s" % (age_state if age_state != "ok" else "%.1f 秒" % (age_sec or 0.0))
               + " / UBX-RXM-RTCM total=%d" % int(rxm.get("total", 0) or 0)
               + " / CRC(UBX)=%.2f%%" % float(ubx_crc.get("rate_pct", 0.0) or 0.0))

    return PhaseResult(PHASE3, STATUS_PASS if ok else STATUS_FAIL, summary,
                       checks, snapshot)



# ---------------------------------------------------------------------------
# 一括レポート
# ---------------------------------------------------------------------------
class IntegrationReport:
    """①〜③の結果を束ねた統合レポート。"""

    def __init__(self, phases: List[PhaseResult], config: Optional[Dict[str, Any]] = None,
                 started_at: Optional[str] = None, finished_at: Optional[str] = None):
        self.phases = {p.phase: p for p in phases}
        self.config = config or {}
        self.started_at = started_at or utc_now_iso()
        self.finished_at = finished_at or utc_now_iso()

    def overall_status(self) -> str:
        if any(not p.is_pass() for p in self.phases.values()):
            return STATUS_FAIL
        return STATUS_PASS

    def to_dict(self) -> Dict[str, Any]:
        ordered = [self.phases[p] for p in (PHASE1, PHASE2, PHASE3) if p in self.phases]
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "overall": {"status": self.overall_status()},
            "phases": [p.to_dict() for p in ordered],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, default=str)

    def format_console(self) -> str:
        lines: List[str] = []
        bar = "=" * 70
        lines.append(bar)
        lines.append("Phase 1 統合テスト結果（実機1台 RTK-FIXED 安定確立）")
        lines.append("  開始: %s" % self.started_at)
        lines.append("  終了: %s" % self.finished_at)
        lines.append(bar)
        ordered = [self.phases[p] for p in (PHASE1, PHASE2, PHASE3) if p in self.phases]
        for p in ordered:
            mark = "✅" if p.is_pass() else "❌"
            lines.append("%s %s: %s" % (mark, p.name, p.status))
            lines.append("   %s" % p.summary)
            for c in p.checks:
                cm = "✓" if c["ok"] else "✗"
                exp = "" if c["expected"] is None else " (期待: %s)" % c["expected"]
                act = "" if c["actual"] is None else " = %s" % c["actual"]
                msg = (" / " + c["message"]) if c["message"] else ""
                lines.append("     [%s] %-24s%s%s%s" % (cm, c["name"], exp, act, msg))
        lines.append(bar)
        overall = self.overall_status()
        note = "（全フェーズ合格）" if overall == STATUS_PASS else "（不合格フェーズあり）"
        lines.append("総合判定: %s%s" % (overall, note))
        lines.append(bar)
        return "\n".join(lines)


__all__ = [
    "PHASE1", "PHASE2", "PHASE3", "PHASE_NAMES",
    "STATUS_PASS", "STATUS_FAIL", "STATUS_WARN",
    "CONFIG_PASS_STATUSES", "PhaseResult",
    "evaluate_phase1", "evaluate_phase2", "evaluate_phase3",
    "IntegrationReport", "utc_now_iso",
]

