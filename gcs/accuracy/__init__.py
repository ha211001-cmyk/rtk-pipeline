#!/usr/bin/env python3
"""gcs.accuracy — 機体間相対測位精度の実測（Phase 2.5）

タスク63504（gcs/relpos）が出力する RELPOSNED iTOW ペアリング結果（CSV）を
RTK 基線長として読み込み、メジャー実測値（既知距離）との比較と、PPK 後処理
結果（独立正解値）とのクロスチェックを行い、協調搬送が要求する相対測位精度
（想定精度）を満たすかをレポートする。

利用例:
    from gcs.accuracy import (
        AccuracySpec, load_relpos_csv, compute_baseline_stats,
        compare_to_reference,
    )

    spec = AccuracySpec()
    data = load_relpos_csv("gcs/relpos/logs/relpos_YYYYMMDD_HHMMSS.csv")
    stats = compute_baseline_stats(data.dist3d_m)          # RTK 基線長
    err = compare_to_reference(1.003, data.dist3d_m, spec.tolerance_m)  # 実測比較
"""

from .baseline import (  # noqa: F401
    STATUS_PASS,
    STATUS_FAIL,
    AccuracySpec,
    BaselineStats,
    ErrorStats,
    compute_baseline_stats,
    compute_error_stats,
    compare_to_reference,
    compare_series,
    align_series,
    crosscheck_baseline,
    evaluate_known_distance,
    evaluate_crosscheck,
)
from .loader import (  # noqa: F401
    RelposBaseline,
    PpkBaseline,
    Measurement,
    load_relpos_csv,
    load_measurements,
    load_ppk_baseline_csv,
    load_position_csv,
    baseline_from_positions,
    baseline_from_position_files,
    parse_utc_epoch,
)
from .report import AccuracyReport, utc_now_iso  # noqa: F401

__all__ = [
    "STATUS_PASS",
    "STATUS_FAIL",
    "AccuracySpec",
    "BaselineStats",
    "ErrorStats",
    "compute_baseline_stats",
    "compute_error_stats",
    "compare_to_reference",
    "compare_series",
    "align_series",
    "crosscheck_baseline",
    "evaluate_known_distance",
    "evaluate_crosscheck",
    "RelposBaseline",
    "PpkBaseline",
    "Measurement",
    "load_relpos_csv",
    "load_measurements",
    "load_ppk_baseline_csv",
    "load_position_csv",
    "baseline_from_positions",
    "baseline_from_position_files",
    "parse_utc_epoch",
    "AccuracyReport",
    "utc_now_iso",
]
