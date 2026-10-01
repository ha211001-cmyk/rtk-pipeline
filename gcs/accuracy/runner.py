#!/usr/bin/env python3
"""runner.py — Phase 2.5 機体間相対測位精度の実測レポート CLI

タスク63504（gcs/relpos）が出力したペアリング後 CSV を読み込み、
  (1) 既知距離（メジャー実測）との比較
  (2) RTK 基線長の算出
  (3) PPK 後処理結果（独立正解値）とのクロスチェック
  (4) 協調搬送の要求精度（想定精度）の合否判定
を一括レポートし、JSON / テキストを出力する。

Usage:
    python3 gcs/accuracy/runner.py --relpos-csv gcs/relpos/logs/relpos_*.csv \\
        --distance 1.003

    python3 gcs/accuracy/runner.py --relpos-csv ... \\
        --measurements measurements.json --ppk-baseline-csv ppk_baseline.csv

    python3 gcs/accuracy/runner.py --relpos-csv ... --distance 1.003 \\
        --ppk-pos-a ppk_a.csv --ppk-pos-b ppk_b.csv

    python3 gcs/accuracy/runner.py --selftest
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 実行位置に依存しない import（リポジトリルート + 本パッケージ）
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent.parent
for _p in (_SCRIPT_DIR, _REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from gcs.accuracy.baseline import (  # noqa: E402
    STATUS_PASS,
    STATUS_FAIL,
    AccuracySpec,
    compute_baseline_stats,
    compare_to_reference,
    align_series,
    crosscheck_baseline,
    evaluate_known_distance,
    evaluate_crosscheck,
)
from gcs.accuracy.loader import (  # noqa: E402
    PpkBaseline,
    load_relpos_csv,
    load_measurements,
    load_ppk_baseline_csv,
    baseline_from_position_files,
    parse_utc_epoch,
)
from gcs.accuracy.report import (  # noqa: E402
    STATUS_SKIP,
    AccuracyReport,
    utc_now_iso,
)

DEFAULT_REPORT_DIR = _SCRIPT_DIR / "reports"


def build_spec(args: argparse.Namespace) -> AccuracySpec:
    """CLI 引数から想定精度（AccuracySpec）を構築する。"""
    kw: Dict[str, Any] = {}
    if args.tolerance is not None:
        kw["tolerance_m"] = args.tolerance
    if args.pass_rate is not None:
        kw["pass_rate_pct_min"] = args.pass_rate
    if args.rmse_max is not None:
        kw["rmse_m_max"] = args.rmse_max
    if args.bias_max is not None:
        kw["bias_m_max"] = args.bias_max
    if args.crosscheck_rmse_max is not None:
        kw["crosscheck_rmse_m_max"] = args.crosscheck_rmse_max
    if args.crosscheck_bias_max is not None:
        kw["crosscheck_bias_m_max"] = args.crosscheck_bias_max
    if args.crosscheck_max_abs_max is not None:
        kw["crosscheck_max_abs_m_max"] = args.crosscheck_max_abs_max
    return AccuracySpec(**kw)


def _select_samples(times: List[float], values: List[float],
                    start_utc: Optional[str],
                    end_utc: Optional[str]) -> Tuple[List[float], List[float]]:
    """既知距離の時間範囲でサンプルを切り出す（範囲未指定なら全件）。"""
    if start_utc is None and end_utc is None:
        return list(times), list(values)
    s = parse_utc_epoch(start_utc) if start_utc else None
    e = parse_utc_epoch(end_utc) if end_utc else None
    sel_t: List[float] = []
    sel_v: List[float] = []
    for t, v in zip(times, values):
        if s is not None and t < s:
            continue
        if e is not None and t > e:
            continue
        sel_t.append(t)
        sel_v.append(v)
    return sel_t, sel_v


def run(relpos_csv: str,
        distance: Optional[float] = None,
        measurements: Optional[str] = None,
        ppk_baseline_csv: Optional[str] = None,
        ppk_pos_a: Optional[str] = None,
        ppk_pos_b: Optional[str] = None,
        spec: Optional[AccuracySpec] = None,
        require_valid: bool = True,
        require_matched: bool = True,
        align_tolerance_s: float = 1.0) -> AccuracyReport:
    """実測データを読み込み、4 要件のレポートを組立てる。"""
    spec = spec or AccuracySpec()
    started_at = utc_now_iso()

    inputs = {
        "relpos_csv": relpos_csv,
        "distance_m": distance,
        "measurements": measurements,
        "ppk_baseline_csv": ppk_baseline_csv,
        "ppk_pos_a": ppk_pos_a,
        "ppk_pos_b": ppk_pos_b,
    }

    r = load_relpos_csv(relpos_csv, require_valid=require_valid,
                        require_matched=require_matched)
    if r.n() == 0:
        sections = [{
            "name": "RTK基線長の読込",
            "status": STATUS_FAIL,
            "summary": "有効なサンプルがありません（valid/matched で除外された可能性）",
            "checks": [],
            "details": {"total_rows": r.total_rows,
                        "skipped_invalid": r.skipped_invalid,
                        "skipped_unmatched": r.skipped_unmatched},
        }]
        return AccuracyReport(started_at=started_at, spec=asdict(spec),
                              inputs=inputs, sections=sections,
                              overall_status=STATUS_FAIL,
                              summary="RTK基線長のサンプルが 0 件")

    # (2) RTK 基線長の算出（63504 ペアリング結果）
    b3 = compute_baseline_stats(r.dist3d_m)
    b2 = compute_baseline_stats(r.dist2d_m)
    mean_acc3d = (sum(r.acc3d_m) / len(r.acc3d_m)) if r.acc3d_m else 0.0
    baseline_section = {
        "name": "② RTK基線長の算出（63504 ペアリング結果）",
        "status": STATUS_PASS,
        "summary": "n=%d mean=%.4fm median=%.4fm std=%.4fm span=%.4fm"
                   % (b3.n, b3.mean_m, b3.median_m, b3.std_m, b3.span_m),
        "checks": [],
        "details": {
            "baseline_3d": b3.to_dict(),
            "baseline_2d": b2.to_dict(),
            "total_rows": r.total_rows,
            "skipped_invalid": r.skipped_invalid,
            "skipped_unmatched": r.skipped_unmatched,
            "mean_acc_3d_m": mean_acc3d,
        },
    }

    # (1) 既知距離（メジャー実測）との比較
    known_sections: List[Dict[str, Any]] = []
    meas = load_measurements(measurements, distance)
    if not meas:
        known_sections.append({
            "name": "① 既知距離との比較",
            "status": STATUS_FAIL,
            "summary": "--distance または --measurements を指定してください",
            "checks": [],
            "details": {},
        })
    for m in meas:
        times, vals = _select_samples(r.utc_epoch, r.dist3d_m,
                                      m.start_utc, m.end_utc)
        err = compare_to_reference(m.distance_m, vals, spec.tolerance_m)
        label = "① 既知距離との比較"
        if m.label:
            label = "① 既知距離との比較 (%s)" % m.label
        known_sections.append(evaluate_known_distance(
            err, spec, reference_m=m.distance_m, label=label))

    # (3) PPK 後処理結果とのクロスチェック
    ppk: Optional[PpkBaseline] = None
    if ppk_baseline_csv:
        ppk = load_ppk_baseline_csv(ppk_baseline_csv)
    elif ppk_pos_a and ppk_pos_b:
        ppk = baseline_from_position_files(ppk_pos_a, ppk_pos_b, align_tolerance_s)

    if ppk is None:
        crosscheck_section: Dict[str, Any] = {
            "name": "③ PPK クロスチェック",
            "status": STATUS_SKIP,
            "summary": "--ppk-baseline-csv / --ppk-pos-a+--ppk-pos-b 未指定のためスキップ",
            "checks": [],
            "details": {},
        }
    elif ppk.n() == 0:
        crosscheck_section = {
            "name": "③ PPK クロスチェック",
            "status": STATUS_FAIL,
            "summary": "PPK 基線長のサンプルが 0 件",
            "checks": [],
            "details": {"source": ppk.source},
        }
    else:
        ppk_aligned, rtk_aligned, deltas = align_series(
            ppk.utc_epoch, ppk.baseline_m, r.utc_epoch, r.dist3d_m,
            align_tolerance_s)
        err = crosscheck_baseline(ppk_aligned, rtk_aligned)
        crosscheck_section = evaluate_crosscheck(
            err, spec, label="③ PPK クロスチェック")
        crosscheck_section["details"]["ppk_baseline_stats"] = \
            compute_baseline_stats(ppk.baseline_m).to_dict()
        crosscheck_section["details"]["n_aligned"] = len(ppk_aligned)
        crosscheck_section["details"]["mean_align_delta_s"] = \
            (sum(deltas) / len(deltas)) if deltas else 0.0
        crosscheck_section["details"]["source"] = ppk.source

    sections = known_sections + [baseline_section, crosscheck_section]
    statuses = [s.get("status") for s in sections]
    overall = STATUS_FAIL if STATUS_FAIL in statuses else STATUS_PASS
    summary = ("協調搬送の要求精度を満たします"
               if overall == STATUS_PASS else "要求精度を満たしません（不合格セクションあり）")
    return AccuracyReport(started_at=started_at, spec=asdict(spec),
                          inputs=inputs, sections=sections,
                          overall_status=overall, summary=summary)


# ---------------------------------------------------------------------------
# 自己検証用の合成データ生成
# ---------------------------------------------------------------------------

_REL_FIELDS = [
    "utc_time", "itow_ms", "itow_a", "itow_b", "delta_ms", "matched",
    "ref_station_match", "ref_station_a", "ref_station_b",
    "rel_n_m", "rel_e_m", "rel_d_m", "distance_2d_m", "distance_3d_m",
    "bearing_ab_deg", "heading_a_deg", "heading_b_deg", "heading_valid",
    "acc_n_m", "acc_e_m", "acc_d_m", "acc_horizontal_m", "acc_3d_m", "valid",
]


def _write_synthetic_relpos(path: Path, n: int = 60, center: float = 1.0,
                            noise: float = 0.01) -> None:
    t0 = datetime(2026, 9, 27, 10, 0, 0, tzinfo=timezone.utc)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_REL_FIELDS)
        w.writeheader()
        for i in range(n):
            ts = t0 + timedelta(seconds=i)
            d = center + random.gauss(0.0, noise)
            row = {
                "utc_time": ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
                "itow_ms": 100000 + i * 1000,
                "itow_a": 100000 + i * 1000,
                "itow_b": 100000 + i * 1000,
                "delta_ms": 0, "matched": 1,
                "ref_station_match": 1, "ref_station_a": 0, "ref_station_b": 0,
                "rel_n_m": d, "rel_e_m": 0.0, "rel_d_m": 0.0,
                "distance_2d_m": d, "distance_3d_m": d, "bearing_ab_deg": 0.0,
                "heading_a_deg": 0.0, "heading_b_deg": 0.0, "heading_valid": 1,
                "acc_n_m": 0.005, "acc_e_m": 0.005, "acc_d_m": 0.008,
                "acc_horizontal_m": 0.007, "acc_3d_m": 0.011, "valid": 1,
            }
            w.writerow({k: row[k] for k in _REL_FIELDS})


def _write_synthetic_ppk(path: Path, n: int = 60, center: float = 1.001,
                         noise: float = 0.005) -> None:
    t0 = datetime(2026, 9, 27, 10, 0, 0, tzinfo=timezone.utc)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["utc_time", "baseline_length_m"])
        for i in range(n):
            ts = t0 + timedelta(seconds=i)
            w.writerow([ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
                        "%.6f" % (center + random.gauss(0.0, noise))])


def self_test() -> int:
    """合成データでフルパイプライン（PASS と FAIL の両方）を検証する。"""
    import tempfile
    random.seed(0)
    with tempfile.TemporaryDirectory() as d:
        rel = Path(d) / "relpos.csv"
        ppk = Path(d) / "ppk.csv"
        _write_synthetic_relpos(rel)
        _write_synthetic_ppk(ppk)

        rep_ok = run(str(rel), distance=1.000, ppk_baseline_csv=str(ppk))
        rep_ng = run(str(rel), distance=10.0, ppk_baseline_csv=str(ppk))

    ok = rep_ok.overall() == STATUS_PASS
    ng = rep_ng.overall() == STATUS_FAIL
    print("runner self-test: %s" % ("OK" if (ok and ng) else "FAILED"))
    if not ok:
        print("  [FAIL] 既知距離 1.000m の比較が PASS になりませんでした")
    if not ng:
        print("  [FAIL] 既知距離 10.0m の比較が FAIL になりませんでした")
    return 0 if (ok and ng) else 1


# ---------------------------------------------------------------------------
# コマンドライン
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Phase 2.5 機体間相対測位精度の実測レポート",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--relpos-csv", default=None,
                   help="タスク63504 ペアリング後 CSV（distance_3d_m を含む）")
    p.add_argument("--distance", type=float, default=None,
                   help="既知距離（メジャー実測）[m]")
    p.add_argument("--measurements", default=None,
                   help="既知距離マニフェスト JSON（複数配置時）")
    p.add_argument("--ppk-baseline-csv", default=None,
                   help="PPK 基線長 CSV（独立正解値）")
    p.add_argument("--ppk-pos-a", default=None, help="ローバーA の PPK 位置 CSV")
    p.add_argument("--ppk-pos-b", default=None, help="ローバーB の PPK 位置 CSV")
    p.add_argument("--no-require-valid", action="store_true",
                   help="relPosValid が立っていない行も対象に含める")
    p.add_argument("--no-require-matched", action="store_true",
                   help="エポック不整合行も対象に含める")
    p.add_argument("--align-tolerance", type=float, default=1.0,
                   help="PPK 時刻対応の許容差 [s]")
    p.add_argument("--tolerance", type=float, default=None,
                   help="許容絶対誤差 [m]（既定 %.3f）" % AccuracySpec().tolerance_m)
    p.add_argument("--pass-rate", type=float, default=None, help="合格率下限 [%%]")
    p.add_argument("--rmse-max", type=float, default=None, help="RMSE 上限 [m]")
    p.add_argument("--bias-max", type=float, default=None, help="バイアス上限 [m]")
    p.add_argument("--crosscheck-rmse-max", type=float, default=None,
                   help="RTK vs PPK の RMSE 上限 [m]")
    p.add_argument("--crosscheck-bias-max", type=float, default=None,
                   help="RTK vs PPK のバイアス上限 [m]")
    p.add_argument("--crosscheck-max-abs-max", type=float, default=None,
                   help="RTK vs PPK の最大絶対差上限 [m]")
    p.add_argument("--output-dir", default=None,
                   help="レポート出力先（既定: gcs/accuracy/reports）")
    p.add_argument("--selftest", action="store_true",
                   help="合成データでフルパイプラインを自己検証")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.selftest:
        return self_test()

    if not args.relpos_csv:
        print("[ERROR] --relpos-csv を指定してください（--selftest で自己検証可）")
        return 2

    spec = build_spec(args)
    try:
        report = run(
            args.relpos_csv,
            distance=args.distance,
            measurements=args.measurements,
            ppk_baseline_csv=args.ppk_baseline_csv,
            ppk_pos_a=args.ppk_pos_a,
            ppk_pos_b=args.ppk_pos_b,
            spec=spec,
            require_valid=not args.no_require_valid,
            require_matched=not args.no_require_matched,
            align_tolerance_s=args.align_tolerance,
        )
    except FileNotFoundError as e:
        print("[ERROR] ファイルが見つかりません: %s" % e)
        return 2

    print(report.format_text())

    out_dir = Path(args.output_dir) if args.output_dir else DEFAULT_REPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / ("accuracy_report_%s.json" % ts)
    txt_path = out_dir / ("accuracy_report_%s.txt" % ts)
    json_path.write_text(report.to_json(), encoding="utf-8")
    txt_path.write_text(report.format_text(), encoding="utf-8")
    print("\n[LOG] JSON: %s" % json_path)
    print("[LOG] TXT : %s" % txt_path)

    return 0 if report.overall() == STATUS_PASS else 1


if __name__ == "__main__":
    sys.exit(main())
