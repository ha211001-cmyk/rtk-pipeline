#!/usr/bin/env python3
"""baseline.py — 機体間相対測位精度（RTK基線長）の統計・比較・合否判定（標準ライブラリのみ）

Phase 2.5「機体間相対測位精度の実測」の中核ロジック。

タスク63504（gcs/relpos）が出力するペアリング後 CSV の ``distance_3d_m`` を
「RTK 基線長」として扱い、以下を算出する:

  (1) 既知距離（メジャー実測値）との比較（バイアス・RMSE・最大誤差・合格率）
  (2) RTK 基線長の要約統計（平均・中央値・標準偏差・スパン）
  (3) PPK 後処理結果（独立正解値）とのクロスチェック
  (4) 協調搬送が要求する相対測位精度（想定精度）を満たすかの合否判定

通信層・ファイル I/O とは独立しており、loader.py が正規化した数値列を渡すだけで
利用できる（gcs/relpos/pairing.py と同じ「標準ライブラリのみ」の設計）。
"""

from __future__ import annotations

import bisect
import math
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"


@dataclass(frozen=True)
class AccuracySpec:
    """協調搬送が要求する相対測位精度の想定値（仮置き・要定義）。

    本値は「F9P RTK（1cm + 1ppm 級）＋機体間近接運用」を前提とした仮の想定値。
    プロジェクト側で想定精度が確定したら必ず見直すこと（要定義）。
    """

    label: str = "協調搬送 想定精度（仮・要定義）"
    tolerance_m: float = 0.10          # 単一サンプルの許容絶対誤差 [m]
    pass_rate_pct_min: float = 95.0    # 許容誤差内に収まる割合 [%]
    rmse_m_max: float = 0.05           # RMSE 上限 [m]
    bias_m_max: float = 0.03           # 平均誤差（バイアス）絶対値上限 [m]
    crosscheck_rmse_m_max: float = 0.05    # RTK vs PPK の RMSE 上限 [m]
    crosscheck_bias_m_max: float = 0.03    # RTK vs PPK のバイアス絶対値上限 [m]
    crosscheck_max_abs_m_max: float = 0.15 # RTK vs PPK の最大絶対差上限 [m]


@dataclass
class BaselineStats:
    """基線長（RTK / PPK）の要約統計。"""

    n: int = 0
    mean_m: float = 0.0
    std_m: float = 0.0
    min_m: float = 0.0
    max_m: float = 0.0
    median_m: float = 0.0
    p68_m: float = 0.0
    p95_m: float = 0.0
    span_m: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ErrorStats:
    """参照値に対する誤差（measured - reference）の統計。"""

    n: int = 0
    mean_error_m: float = 0.0    # バイアス（正 = 過大）
    std_m: float = 0.0
    rmse_m: float = 0.0
    max_abs_m: float = 0.0
    p68_abs_m: float = 0.0
    p95_abs_m: float = 0.0
    pass_count: int = 0
    pass_rate_pct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# 統計ユーティリティ
# ---------------------------------------------------------------------------

def _std(vals: Sequence[float]) -> float:
    """標本標準偏差（n<2 のとき 0）。"""
    if len(vals) < 2:
        return 0.0
    return statistics.stdev(vals)


def _quantile(sorted_vals: List[float], q: float) -> float:
    """昇順リストに対する分位点（線形補間）。空なら 0。"""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def _finite(values: Sequence[float]) -> List[float]:
    return [float(v) for v in values if v is not None and math.isfinite(float(v))]


def compute_baseline_stats(values: Sequence[float]) -> BaselineStats:
    """基線長の時系列から要約統計を算出する（要件 (2)）。"""
    vals = sorted(_finite(values))
    if not vals:
        return BaselineStats()
    return BaselineStats(
        n=len(vals),
        mean_m=statistics.fmean(vals),
        std_m=_std(vals),
        min_m=vals[0],
        max_m=vals[-1],
        median_m=_quantile(vals, 0.5),
        p68_m=_quantile(vals, 0.68),
        p95_m=_quantile(vals, 0.95),
        span_m=vals[-1] - vals[0],
    )


def compute_error_stats(errors: Sequence[float],
                        tolerance_m: Optional[float] = None) -> ErrorStats:
    """誤差列（measured - reference）から統計を算出する。"""
    errs = _finite(errors)
    if not errs:
        return ErrorStats()
    abs_errs = sorted(abs(e) for e in errs)
    rmse = math.sqrt(statistics.fmean([e * e for e in errs]))
    pass_count = 0
    if tolerance_m is not None:
        pass_count = sum(1 for a in abs_errs if a <= tolerance_m)
    return ErrorStats(
        n=len(errs),
        mean_error_m=statistics.fmean(errs),
        std_m=_std(errs),
        rmse_m=rmse,
        max_abs_m=abs_errs[-1],
        p68_abs_m=_quantile(abs_errs, 0.68),
        p95_abs_m=_quantile(abs_errs, 0.95),
        pass_count=pass_count,
        pass_rate_pct=(pass_count / len(errs) * 100.0)
        if tolerance_m is not None else 0.0,
    )


# ---------------------------------------------------------------------------
# 比較（要件 (1) / (3)）
# ---------------------------------------------------------------------------

def compare_to_reference(reference_m: float, values: Sequence[float],
                         tolerance_m: Optional[float] = None) -> ErrorStats:
    """既知距離 reference_m に対する基線長 values の誤差統計（要件 (1)）。"""
    return compute_error_stats([float(v) - float(reference_m) for v in values],
                               tolerance_m)


def compare_series(reference_vals: Sequence[float],
                   measured_vals: Sequence[float],
                   tolerance_m: Optional[float] = None) -> ErrorStats:
    """対応付け済み 2 系列の差（measured - reference）の誤差統計。"""
    return compute_error_stats(
        [float(m) - float(r) for r, m in zip(reference_vals, measured_vals)],
        tolerance_m)


def crosscheck_baseline(reference_values: Sequence[float],
                        measured_values: Sequence[float],
                        tolerance_m: Optional[float] = None) -> ErrorStats:
    """クロスチェック: measured（RTK基線長）と reference（PPK正解値）の差の統計。"""
    return compare_series(reference_values, measured_values, tolerance_m)


def align_series(series_a_times: Sequence[float],
                 series_a_values: Sequence[float],
                 series_b_times: Sequence[float],
                 series_b_values: Sequence[float],
                 tolerance_s: float = 1.0
                 ) -> Tuple[List[float], List[float], List[float]]:
    """series_a の各サンプルに、tolerance_s 内で最も近い series_b を対応付ける。

    Returns:
        (a_aligned, b_aligned, delta_s) — 対応が付いた組のみ（同長リスト）。
    """
    if not series_a_times or not series_b_times:
        return [], [], []
    b = sorted(zip(series_b_times, series_b_values))
    b_t = [x[0] for x in b]
    b_v = [x[1] for x in b]

    a_aligned: List[float] = []
    b_aligned: List[float] = []
    deltas: List[float] = []
    for t, v in zip(series_a_times, series_a_values):
        idx = bisect.bisect_left(b_t, t)
        best_v: Optional[float] = None
        best_dt: Optional[float] = None
        for j in (idx - 1, idx):
            if 0 <= j < len(b_t):
                dt = abs(b_t[j] - t)
                if dt <= tolerance_s and (best_dt is None or dt < best_dt):
                    best_dt = dt
                    best_v = b_v[j]
        if best_v is not None:
            a_aligned.append(v)
            b_aligned.append(best_v)
            deltas.append(float(best_dt))
    return a_aligned, b_aligned, deltas


# ---------------------------------------------------------------------------
# 合否判定（要件 (4)）
# ---------------------------------------------------------------------------

def _check(name: str, ok: bool, expected: Any = None, actual: Any = None,
           message: str = "") -> Dict[str, Any]:
    return {"name": name, "ok": bool(ok), "expected": expected,
            "actual": actual, "message": message}


def evaluate_known_distance(err: ErrorStats, spec: AccuracySpec,
                            reference_m: Optional[float] = None,
                            label: str = "既知距離との比較") -> Dict[str, Any]:
    """既知距離比較の合否（要件 (1) / (4)）。"""
    checks = [
        _check("rmse", err.n > 0 and err.rmse_m <= spec.rmse_m_max,
               "<= %.3f m" % spec.rmse_m_max, "%.3f m" % err.rmse_m,
               "RMSE（対 実測距離）"),
        _check("bias", err.n > 0 and abs(err.mean_error_m) <= spec.bias_m_max,
               "|bias| <= %.3f m" % spec.bias_m_max, "%.3f m" % err.mean_error_m,
               "平均誤差（バイアス）"),
        _check("pass_rate", err.n > 0 and err.pass_rate_pct >= spec.pass_rate_pct_min,
               ">= %.1f %%" % spec.pass_rate_pct_min, "%.1f %%" % err.pass_rate_pct,
               "許容誤差 %.3f m 内の割合" % spec.tolerance_m),
    ]
    if err.n == 0:
        checks.insert(0, _check("samples", False, "> 0", "0", "有効サンプル数"))
    ok = all(c["ok"] for c in checks)
    summary = ("n=%d bias=%.3fm RMSE=%.3fm max=%.3fm 合格率=%.1f%%"
               % (err.n, err.mean_error_m, err.rmse_m, err.max_abs_m,
                  err.pass_rate_pct))
    return {
        "name": label,
        "status": STATUS_PASS if ok else STATUS_FAIL,
        "summary": summary,
        "checks": checks,
        "details": {"reference_m": reference_m, "error_stats": err.to_dict()},
    }


def evaluate_crosscheck(err: ErrorStats, spec: AccuracySpec,
                        label: str = "PPK クロスチェック") -> Dict[str, Any]:
    """PPK 後処理結果とのクロスチェック合否（要件 (3) / (4)）。"""
    checks = [
        _check("crosscheck_rmse", err.n > 0 and err.rmse_m <= spec.crosscheck_rmse_m_max,
               "<= %.3f m" % spec.crosscheck_rmse_m_max, "%.3f m" % err.rmse_m,
               "RTK vs PPK の RMSE"),
        _check("crosscheck_bias", err.n > 0 and abs(err.mean_error_m) <= spec.crosscheck_bias_m_max,
               "|bias| <= %.3f m" % spec.crosscheck_bias_m_max, "%.3f m" % err.mean_error_m,
               "RTK vs PPK のバイアス"),
        _check("crosscheck_max_abs", err.n > 0 and err.max_abs_m <= spec.crosscheck_max_abs_m_max,
               "<= %.3f m" % spec.crosscheck_max_abs_m_max, "%.3f m" % err.max_abs_m,
               "RTK vs PPK の最大絶対差"),
    ]
    if err.n == 0:
        checks.insert(0, _check("samples", False, "> 0", "0", "対応サンプル数"))
    ok = all(c["ok"] for c in checks)
    summary = ("n=%d bias=%.3fm RMSE=%.3fm max=%.3fm"
               % (err.n, err.mean_error_m, err.rmse_m, err.max_abs_m))
    return {
        "name": label,
        "status": STATUS_PASS if ok else STATUS_FAIL,
        "summary": summary,
        "checks": checks,
        "details": {"error_stats": err.to_dict()},
    }


__all__ = [
    "STATUS_PASS", "STATUS_FAIL",
    "AccuracySpec", "BaselineStats", "ErrorStats",
    "compute_baseline_stats", "compute_error_stats",
    "compare_to_reference", "compare_series", "crosscheck_baseline",
    "align_series", "evaluate_known_distance", "evaluate_crosscheck",
]
