#!/usr/bin/env python3
"""metrics.py — Phase 4 実飛行試験の定量評価ロジック（標準ライブラリのみ）

Phase 4（実飛行試験）では、地上で確立した RTK-FIXED を飛行中も維持できるかを、
EKF/フェイルセーフ設定（2e8a3）が有効な状態で定量的に評価する。本モジュールは
その判定ロジックを純粋関数として提供し、実ハードウェアなしの単体テストを可能にする。

評価対象（要件との対応）:
  (1) fix_type 時系列・位置精度（hdop/vdop・EKF 位置分散）の記録 → recorder.py
  (2) RTK-FIXED 維持率・FLOAT 遷移          → gcs.fix_metrics.compute_metrics を再利用
  (2) EKF との整合性（fix_type と EKF フラグ/位置精度の一致） → compute_ekf_consistency
  (3) 測位劣化時のフェイルセーフ動作確認      → detect_degradations + confirm_failsafe
  (4) 次フェーズへの課題整理                 → next_phase_issues

fix_type は MAVLink の GPS_FIX_TYPE（0..6）に正規化する:
    0/1 = NO_FIX, 2 = 2D_FIX, 3 = 3D_FIX, 4 = DGPS, 5 = RTK_FLOAT, 6 = RTK_FIXED

本モジュールは標準ライブラリのみで動作する。MAVLink 通信は recorder.py が担う。
"""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence

# 実行位置に依存しない import（リポジトリルートを sys.path に追加）
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# 既存資産の再利用（既存ファイルは無改変）
#   - fix_type 定量判定（Phase 1）: RTK-FIXED 維持率・FLOAT 遷移・TTFF
#   - EKF 健全判定（2e8a3 相当）  : EKF_STATUS_REPORT.flags のビット判定
from gcs.fix_metrics import FIXED, FLOAT, compute_metrics, fix_name  # noqa: E402
from gcs.ekf_failsafe.checklist import ekf_position_healthy  # noqa: E402

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_SKIP = "SKIP"
STATUS_INFO = "INFO"

# RTK とみなす fix_type（FLOAT=5 / FIXED=6）
RTK_TYPES = (FLOAT, FIXED)

# フェイルセーフ（FS）を誘発し得る「重度」劣化とみなす閾値・種別
#   - gps_loss      : fix_type が 0/1（No Fix）へ落ちる → FS_GPS_ENABLE の対象
#   - ekf_unhealthy : EKF フラグが位置・速度・姿勢を失う → FS_EKF_ACTION の対象
#   - rtk_loss      : RTK(5,6) → 非RTK(2..4)。位置は残るため FS 対象外（精度劣化）
#   - hdop_high     : HDOP が閾値超え（精度劣化。FS 対象外）
FS_MODES = {"RTL", "LAND"}


def _num(v: Any, default: Optional[float] = None) -> Optional[float]:
    """文字列/None を float に変換（失敗時は default）。"""
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _finite(values: Sequence[Any]) -> List[float]:
    """数値列から None / 非有限値を除いたリストを返す。"""
    out: List[float] = []
    for v in values:
        f = _num(v)
        if f is None or not math.isfinite(f):
            continue
        out.append(f)
    return out


def _mean(values: Sequence[float]) -> Optional[float]:
    vals = _finite(values)
    if not vals:
        return None
    return statistics.fmean(vals)


def _max(values: Sequence[float]) -> Optional[float]:
    vals = _finite(values)
    return max(vals) if vals else None


@dataclass(frozen=True)
class FlightSpec:
    """Phase 4 実飛行試験の判定基準（仮置き・要定義）。

    本値は「地上で確立した RTK-FIXED を飛行中も維持する」を前提とした仮の基準値。
    機体・運用要件が確定したら必ず見直すこと（要定義）。
    """

    label: str = "Phase 4 実飛行試験 判定基準（仮・要定義）"
    fixed_rate_pct_min: float = 80.0       # FIXED 維持率（初回 FIXED 以降）下限 [%]
    max_float_transitions: int = 5         # FLOAT 遷移回数 上限
    ekf_consistency_pct_min: float = 95.0  # FIXED 時に EKF 位置健全である割合 下限 [%]
    ekf_horiz_err_max_m: float = 0.10      # FIXED 時の EKF 水平位置誤差(1σ) 上限 [m]
    ekf_vert_err_max_m: float = 0.20       # FIXED 時の EKF 垂直位置誤差(1σ) 上限 [m]
    hdop_max_m: float = 1.4                # HDOP（位置精度の代理指標）上限 [m]
    max_severe_degradations: int = 3       # 重度劣化（FS 対象）の許容回数 上限
    require_failsafe_evidence: bool = True  # 重度劣化時に FS 発動の証跡を必須とするか

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

# ---------------------------------------------------------------------------
# (2) EKF との整合性
# ---------------------------------------------------------------------------
def compute_ekf_consistency(series: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """fix_type 時系列と EKF フラグ・位置精度の整合性を評価する（要件 (2)）。

    Returns:
        dict:
          fixed_samples / fixed_with_ekf / fixed_ekf_healthy /
          fixed_ekf_consistency_pct / overall_ekf_healthy_pct /
          fixed_horiz_err_mean_m / fixed_horiz_err_max_m /
          fixed_vert_err_mean_m / fixed_vert_err_max_m /
          hdop_mean_m / hdop_max_m / sats_mean / has_ekf_flags / has_accuracy
    """
    rows = list(series)
    fixed_samples = [r for r in rows if int(_num(r.get("fix_type"), -1) or -1) == FIXED]
    fixed_with_ekf = [r for r in fixed_samples if r.get("ekf_flags") is not None]
    fixed_healthy = [r for r in fixed_with_ekf
                     if ekf_position_healthy(r.get("ekf_flags")) is True]

    all_with_ekf = [r for r in rows if r.get("ekf_flags") is not None]
    all_healthy = [r for r in all_with_ekf
                   if ekf_position_healthy(r.get("ekf_flags")) is True]

    horiz = [r.get("ekf_pos_horiz_m") for r in fixed_samples]
    vert = [r.get("ekf_pos_vert_m") for r in fixed_samples]
    hdop = [r.get("hdop") for r in rows]
    sats = [r.get("sats") for r in rows]

    consistency = (len(fixed_healthy) / len(fixed_with_ekf) * 100.0
                   if fixed_with_ekf else None)
    overall_healthy = (len(all_healthy) / len(all_with_ekf) * 100.0
                       if all_with_ekf else None)

    return {
        "fixed_samples": len(fixed_samples),
        "fixed_with_ekf": len(fixed_with_ekf),
        "fixed_ekf_healthy": len(fixed_healthy),
        "fixed_ekf_consistency_pct": consistency,
        "overall_ekf_healthy_pct": overall_healthy,
        "fixed_horiz_err_mean_m": _mean(horiz),
        "fixed_horiz_err_max_m": _max(horiz),
        "fixed_vert_err_mean_m": _mean(vert),
        "fixed_vert_err_max_m": _max(vert),
        "hdop_mean_m": _mean(hdop),
        "hdop_max_m": _max(hdop),
        "sats_mean": _mean(sats),
        "has_ekf_flags": len(all_with_ekf) > 0,
        "has_accuracy": _finite(horiz) != [],
    }


# ---------------------------------------------------------------------------
# (3) 測位劣化の検出
# ---------------------------------------------------------------------------
def detect_degradations(series: Sequence[Dict[str, Any]],
                        spec: Optional[FlightSpec] = None) -> Dict[str, Any]:
    """fix_type / EKF フラグ / HDOP の時系列から「測位劣化イベント」を検出する。

    Returns:
        dict:
          events（onset のみ） / rtk_loss_count / gps_loss_count /
          ekf_unhealthy_count / hdop_high_count / severe_count（= gps + ekf）
    """
    spec = spec or FlightSpec()
    events: List[Dict[str, Any]] = []
    prev_fix: Optional[int] = None
    prev_ekf_healthy: Optional[bool] = None
    prev_hdop_high: bool = False

    for i, r in enumerate(series):
        t = _num(r.get("t"), float(i))
        ts = r.get("ts") or ""
        ft_raw = _num(r.get("fix_type"))
        ft = int(ft_raw) if ft_raw is not None else None
        flags = r.get("ekf_flags")
        ekf_h = ekf_position_healthy(flags) if flags is not None else None
        hdop = r.get("hdop")
        hdop_high = (hdop is not None
                     and float(hdop) > float(spec.hdop_max_m))

        # RTK(5,6) → 非RTK(2..4) の脱落、RTK(5,6) → 0/1 の GPS 喪失
        if prev_fix is not None and ft is not None and ft != prev_fix:
            if prev_fix in RTK_TYPES and ft not in RTK_TYPES:
                kind = "gps_loss" if ft in (0, 1) else "rtk_loss"
                events.append({"t": t, "ts": ts, "kind": kind,
                               "from_fix": prev_fix, "to_fix": ft,
                               "from": fix_name(prev_fix), "to": fix_name(ft)})
        # EKF が健全 → 不健全 へ遷移
        if prev_ekf_healthy is True and ekf_h is False:
            events.append({"t": t, "ts": ts, "kind": "ekf_unhealthy",
                           "from_fix": ft, "to_fix": ft,
                           "from": "EKF healthy", "to": "EKF unhealthy"})
        # HDOP が正常 → 閾値超え へ遷移
        if not prev_hdop_high and hdop_high:
            events.append({"t": t, "ts": ts, "kind": "hdop_high",
                           "from_fix": ft, "to_fix": ft,
                           "from": "HDOP ok", "to": "HDOP high (%.2f m)" % float(hdop)})

        prev_fix = ft
        prev_ekf_healthy = ekf_h
        prev_hdop_high = hdop_high

    def _count(kind: str) -> int:
        return sum(1 for e in events if e["kind"] == kind)

    gps_loss = _count("gps_loss")
    ekf_unhealthy = _count("ekf_unhealthy")
    return {
        "events": events,
        "rtk_loss_count": _count("rtk_loss"),
        "gps_loss_count": gps_loss,
        "ekf_unhealthy_count": ekf_unhealthy,
        "hdop_high_count": _count("hdop_high"),
        "severe_count": gps_loss + ekf_unhealthy,
    }

# ---------------------------------------------------------------------------
# (3) フェイルセーフ（FS）動作確認
# ---------------------------------------------------------------------------
FS_TEXT_KINDS = {
    "gps": ["gps glitch", "gps lost", "gps failsafe", "gps: glitch",
            "gps: lost", "no gps"],
    "ekf": ["ekf", "inertial nav", "dcm"],
    "gcs": ["gcs", "telemetry lost", "radio failsafe"],
    "failsafe": ["failsafe"],
}


def classify_failsafe_text(text: str) -> Optional[str]:
    """STATUSTEXT の内容からフェイルセーフ種別（gps/ekf/gcs/failsafe）を推定する。"""
    if not text:
        return None
    low = text.lower()
    for kind, needles in FS_TEXT_KINDS.items():
        for needle in needles:
            if needle in low:
                return kind
    return None


def confirm_failsafe(series: Sequence[Dict[str, Any]],
                     failsafe_ok: bool,
                     failsafe_events: Optional[Sequence[Dict[str, Any]]] = None,
                     mode_events: Optional[Sequence[Dict[str, Any]]] = None,
                     spec: Optional[FlightSpec] = None) -> Dict[str, Any]:
    """測位劣化時のフェイルセーフ（FS）動作を確認する（要件 (3)）。

    Args:
        series: fix_type 時系列（detect_degradations の入力と同一スキーマ）。
        failsafe_ok: 2e8a3（EKF/FS golden）が有効か（evaluate_failsafe().is_pass()）。
        failsafe_events: STATUSTEXT 由来の FS 証跡（{t, ts, kind, text} の列）。
        mode_events: HEARTBEAT 由来のモード遷移（{t, ts, mode} の列）。RTL/LAND を補助証跡に使う。
        spec: 判定基準。

    Returns:
        dict: checks / severe_count / fs_triggered / fs_evidence / ok / summary
    """
    spec = spec or FlightSpec()
    degrad = detect_degradations(series, spec)
    severe = int(degrad["severe_count"])

    fs_events = list(failsafe_events or [])
    modes = [str((m.get("mode") or "").upper()) for m in (mode_events or [])]
    fs_mode_hit = any(m in FS_MODES for m in modes)
    fs_triggered = bool(fs_events) or fs_mode_hit

    checks: List[Dict[str, Any]] = []

    def _check(name: str, ok: bool, expected: Any = None, actual: Any = None,
               message: str = "") -> Dict[str, Any]:
        return {"name": name, "ok": bool(ok), "expected": expected,
                "actual": actual, "message": message}

    checks.append(_check(
        "failsafe_golden_enabled", bool(failsafe_ok),
        expected=True, actual=bool(failsafe_ok),
        message="2e8a3（EKF/FS golden）が有効（FS が働く前提）"))
    checks.append(_check(
        "severe_degradation_bound", severe <= spec.max_severe_degradations,
        expected="<= %d 回" % spec.max_severe_degradations,
        actual="%d 回" % severe,
        message="重度劣化（GPS 喪失 / EKF 不健全）回数"))

    if not failsafe_ok:
        ok = False
        summary = "フェイルセーフ golden（2e8a3）が無効のため評価できません"
    elif severe == 0:
        checks.append(_check(
            "failsafe_not_needed", True, expected="発動不要", actual="RTK-FIXED 維持",
            message="FS を要する重度劣化が観測されず（RTK-FIXED を維持）"))
        ok = all(c["ok"] for c in checks)
        summary = ("重度劣化なし（FS 発動不要）。RTK-FIXED を飛行中も維持できました"
                   if ok else "基準を満たしませんでした")
    else:
        if spec.require_failsafe_evidence:
            checks.append(_check(
                "failsafe_triggered", fs_triggered,
                expected="FS 発動の証跡あり", actual="あり" if fs_triggered else "なし",
                message="重度劣化に対する FS 発動（STATUSTEXT / RTL・LAND）"))
            if not fs_triggered:
                ok = False
                summary = "重度劣化 %d 回が発生しましたが、FS 発動を確認できませんでした" % severe
            else:
                ok = all(c["ok"] for c in checks)
                summary = "重度劣化 %d 回に対し FS 動作を確認しました" % severe
        else:
            checks.append(_check(
                "failsafe_triggered", True, expected=None,
                actual="あり" if fs_triggered else "なし",
                message="FS 発動証跡（参考。必須ではない）"))
            ok = all(c["ok"] for c in checks)
            summary = "重度劣化 %d 回（FS 証跡 %s）" % (
                severe, "あり" if fs_triggered else "なし")

    return {
        "checks": checks,
        "severe_count": severe,
        "fs_triggered": fs_triggered,
        "failsafe_events": len(fs_events),
        "fs_evidence": {"failsafe_events": fs_events,
                        "mode_events": list(mode_events or []),
                        "fs_mode_hit": fs_mode_hit},
        "ok": bool(ok),
        "summary": summary,
    }

# ---------------------------------------------------------------------------
# (4) 次フェーズへの課題整理
# ---------------------------------------------------------------------------
def next_phase_issues(series: Sequence[Dict[str, Any]],
                      rtk: Dict[str, Any],
                      ekf: Dict[str, Any],
                      degrad: Dict[str, Any],
                      failsafe: Dict[str, Any],
                      spec: Optional[FlightSpec] = None) -> List[Dict[str, Any]]:
    """飛行試験結果から次フェーズ（Phase 5 以降）への課題を自動整理する（要件 (4)）。

    定量基準からの乖離を自動で課題化し、加えて実飛行ならではの定性的課題
    （アンテナ環境・マルチパス・サンプルレート・PPK クロスチェック等）を
    常設の「検討項目」として添える。
    """
    spec = spec or FlightSpec()
    issues: List[Dict[str, Any]] = []
    seq = 0

    def _add(severity: str, category: str, title: str, detail: str,
             action: str) -> None:
        nonlocal seq
        seq += 1
        issues.append({
            "id": "PH4-%02d" % seq,
            "severity": severity,
            "category": category,
            "title": title,
            "detail": detail,
            "suggested_action": action,
        })

    reached = bool(rtk.get("reached_fixed"))
    fixed_rate = float(rtk.get("fixed_rate_after_first_pct", 0.0) or 0.0)
    float_cnt = int(rtk.get("float_transition_count", 0) or 0)
    fixed_drop = int(rtk.get("fixed_to_float_count", 0) or 0)

    if not reached:
        _add("high", "RTK-FIXED", "飛行中に RTK-FIXED 未到達",
             "地上では確立した RTK-FIXED を飛行中に再現できませんでした。",
             "アンテナ視界・マルチパス・基地局リンク（RTCM age/CRC）を確認し、"
             "飛行前 FIXED 確立の手順（gcs/preflight）を再検証する。")
    if reached and fixed_rate < spec.fixed_rate_pct_min:
        _add("high", "RTK-FIXED", "RTK-FIXED 維持率が基準未達",
             "初回 FIXED 以降の維持率が %.1f %%（基準 %.1f %%）でした。"
             % (fixed_rate, spec.fixed_rate_pct_min),
             "FLOAT/DGPS へ脱落する区間と機動（旋回・加速）・距離の相関を解析する。")
    if float_cnt > spec.max_float_transitions:
        _add("medium", "RTK-FLOAT", "FLOAT 遷移が多発",
             "FLOAT 遷移 %d 回（基準 %d 回）/ FIXED→FLOAT 脱落 %d 回。"
             % (float_cnt, spec.max_float_transitions, fixed_drop),
             "脱落タイミングを fix_type 時系列で特定し、基地局距離・電波環境と突き合わせる。")

    consistency = ekf.get("fixed_ekf_consistency_pct")
    horiz_max = ekf.get("fixed_horiz_err_max_m")
    if consistency is not None and consistency < spec.ekf_consistency_pct_min:
        _add("medium", "EKF", "EKF との整合性に乖離",
             "FIXED 時に EKF 位置健全である割合が %.1f %%（基準 %.1f %%）でした。"
             % (consistency, spec.ekf_consistency_pct_min),
             "fix_type=6 なのに EKF が不健全になる区間を特定し、"
             "EKF ソース設定（2e8a3）と観測遅延を確認する。")
    if horiz_max is not None and horiz_max > spec.ekf_horiz_err_max_m:
        _add("medium", "EKF", "FIXED 時の EKF 水平位置誤差が過大",
             "FIXED 時の EKF 水平位置誤差(1σ)の最大値が %.3f m（基準 %.3f m）でした。"
             % (horiz_max, spec.ekf_horiz_err_max_m),
             "RTK 解の精度低下 or EKF 融合ゲインの影響を切り分ける。")

    if failsafe.get("ok") is False:
        _add("high", "フェイルセーフ", "測位劣化時のフェイルセーフ確認が未達",
             failsafe.get("summary", "FS 動作を確認できませんでした"),
             "FS golden（2e8a3）の有効化を再確認し、劣化シナリオ（GPS/RTCM 断）を"
             "意図的に再現する試験を計画する。")
    elif failsafe.get("severe_count", 0) > 0:
        _add("low", "フェイルセーフ", "FS 発動時の機体挙動を記録・精査",
             "重度劣化 %d 回に対し FS 発動を確認。機体の Land/RTL 遷移を精査する。"
             % int(failsafe.get("severe_count", 0)),
             "FS 発動前後の高度・速度・モード遷移をログから再構成し、安全性を評価する。")

    # 実飛行ならではの定性的検討項目（常設）
    _add("info", "検討項目", "PPK 後処理とのクロスチェック",
         "飛行中の RTK 軌跡を PPK（RTKLIB 等）で後処理し、独立正解値と突き合わせる。",
         "RAWX ログ（ppk_logger）を取得し、Phase 2.5 のクロスチェック手法を流用する。")
    _add("info", "検討項目", "アンテナ配置・マルチパスの影響評価",
         "機体への移動局アンテナ搭載位置が RTK 精度に与える影響は未評価。",
         "アンテナ接地・マウント・遮蔽の影響を比較飛行で定量化する。")
    _add("info", "検討項目", "サンプルレート・観測項目の拡充",
         "現状は MAVLink GPS_RAW_INT / EKF_STATUS_REPORT ベース。",
         "必要に応じ UBX-NAV-PVT（hAcc/vAcc）や RELPOSNED を併用し精度指標を精緻化する。")

    return issues


__all__ = [
    "STATUS_PASS", "STATUS_FAIL", "STATUS_SKIP", "STATUS_INFO",
    "RTK_TYPES", "FS_MODES",
    "FlightSpec",
    "compute_ekf_consistency",
    "detect_degradations",
    "classify_failsafe_text",
    "confirm_failsafe",
    "next_phase_issues",
    "compute_metrics", "fix_name", "FIXED", "FLOAT", "ekf_position_healthy",
]



