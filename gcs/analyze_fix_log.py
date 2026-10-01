#!/usr/bin/env python3
"""analyze_fix_log.py — fix_type 時系列 CSV の後処理解析

fix_type_logger.py が出力した CSV（または rover_recorder.py の rtk_status CSV）を
読み込み、FIXED 維持率・FLOAT 遷移回数・遷移タイムスタンプ・TTFF を集計表示する。

集計ロジックは fix_metrics.py を再利用する。あわせて既存資産を import で再利用する:
  - archive/rtk_field_test/analyze_status.py      … FIX_NAMES（状態名の正規化）
  - archive/rtk_field_test/analyze_fix_isolation.py … analyze_status_csv()（RTCM到達・衛星数等）

使い方:
    python3 analyze_fix_log.py gcs/logs/fix_type_YYYYMMDD_HHMMSS.csv
    python3 analyze_fix_log.py archive/rtk_field_test/logs/rtk_status_YYYYMMDD_HHMMSS.csv
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_GCS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _GCS_DIR.parent
sys.path.insert(0, str(_GCS_DIR))

from fix_metrics import (  # noqa: E402
    compute_metrics,
    fix_name,
    format_metrics,
    _int,
    _num,
)

_ANALYZE_STATUS = _REPO_ROOT / "archive" / "rtk_field_test" / "analyze_status.py"
_ANALYZE_ISOLATION = _REPO_ROOT / "archive" / "rtk_field_test" / "analyze_fix_isolation.py"


def _load_module(name: str, path: Path):
    """ファイルパスから既存モジュールを import する（既存ファイルを改変しない再利用）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_reused_modules():
    """既存資産を import で読み込む。失敗時は None を返して継続させる。"""
    analyze_status = None
    analyze_iso = None

    if _ANALYZE_STATUS.is_file():
        try:
            analyze_status = _load_module("analyze_status_reused", _ANALYZE_STATUS)
        except Exception as e:  # noqa: BLE001
            print("[WARN] analyze_status.py を import できません: %s" % e)
    else:
        print("[WARN] analyze_status.py が見つかりません: %s" % _ANALYZE_STATUS)

    if _ANALYZE_ISOLATION.is_file():
        try:
            analyze_iso = _load_module("analyze_fix_isolation_reused", _ANALYZE_ISOLATION)
        except Exception as e:  # noqa: BLE001
            print("[WARN] analyze_fix_isolation.py を import できません: %s" % e)
    else:
        print("[WARN] analyze_fix_isolation.py が見つかりません: %s" % _ANALYZE_ISOLATION)

    return analyze_status, analyze_iso


def read_series(csv_path: str) -> List[Dict[str, Any]]:
    """fix_type 時系列 CSV を読み、fix_metrics 用の行リストへ変換する。

    gcs 形式（merged_fix_type）と rover_recorder 形式（fix_type）の両方に対応。
    """
    rows: List[Dict[str, Any]] = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        raw_rows = list(reader)

    fix_key = "merged_fix_type" if "merged_fix_type" in fields else "fix_type"
    for i, r in enumerate(raw_rows):
        ft = _int(r.get(fix_key))
        t = _num(r.get("elapsed_sec"))
        if t is None:
            t = _num(r.get("t"))
        if t is None:
            t = float(i)
        ts = r.get("timestamp") or r.get("utc_time") or r.get("ts")
        rows.append({"t": t, "ts": ts, "fix_type": ft})
    return rows


def main() -> int:
    p = argparse.ArgumentParser(description="fix_type 時系列 CSV の後処理解析")
    p.add_argument("csv_path", help="fix_type_logger.py / rover_recorder.py の CSV")
    p.add_argument("--json", default=None, help="集計結果を JSON としても出力（省略時は標準出力のみ）")
    args = p.parse_args()

    series = read_series(args.csv_path)
    if not series:
        print("[ERROR] データがありません: %s" % args.csv_path)
        return 1

    m = compute_metrics(series)
    print("ファイル: %s" % args.csv_path)
    print()
    print(format_metrics(m))

    # rover_recorder 形式なら、analyze_fix_isolation.py の再利用で RTCM 到達等も表示
    with open(args.csv_path, newline="") as f:
        fields = csv.DictReader(f).fieldnames or []
    _, analyze_iso = load_reused_modules()
    if analyze_iso is not None and "fix_type" in fields and "merged_fix_type" not in fields:
        try:
            cs = analyze_iso.analyze_status_csv(args.csv_path)
            if cs:
                print()
                print("--- 追加（analyze_fix_isolation.analyze_status_csv 再利用） ---")
                print("  RTCM 到達: 流れている(<=1s)=%d, 途絶(>1s)=%d, 最大途絶=%.1fs"
                      % (cs["n_rtcm_active"], cs["n_rtcm_idle"], cs["rtcm_max_gap"] or 0.0))
                if cs.get("sats"):
                    print("  捕捉衛星数 sats: min=%d avg=%.1f max=%d"
                          % (cs["sats"]["min"], cs["sats"]["avg"], cs["sats"]["max"]))
                print("  RTK使用衛星 nsats 分布: %s" % cs.get("nsats_vals"))
        except Exception as e:  # noqa: BLE001
            print("[WARN] analyze_status_csv の実行に失敗: %s" % e)

    if args.json:
        import json  # noqa: PLC0415
        with open(args.json, "w") as f:
            json.dump(m, f, ensure_ascii=False, indent=2, default=str)
        print("[LOG] JSON: %s" % args.json)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
