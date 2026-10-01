#!/usr/bin/env python3
"""analyze_intervals.py — 測位ログ CSV から 5分・20分・60分（任意区間）を切り出して精度比較サマリーを出力するツール"""

import argparse
import csv
import math
import os
import sys

FIX_NAMES = {
    0: "NO_GPS",
    1: "NO_FIX",
    2: "2D_FIX",
    3: "3D_FIX",
    4: "DGPS",
    5: "RTK_FLOAT",
    6: "RTK_FIXED",
}
METERS_PER_DEG_LAT = 111320.0

def analyze_slice(rows, label="全区間"):
    """特定区間のデータを解析して辞書で返す"""
    if not rows:
        return None

    def _f(v):
        try:
            return float(v) if v is not None and v != "" else None
        except Exception:
            return None

    def _i(v):
        try:
            return int(float(v)) if v is not None and v != "" else 0
        except Exception:
            return 0

    secs = [_f(r.get("elapsed_sec")) for r in rows]
    fixes = [_i(r.get("fix_type")) for r in rows]
    lats = [_f(r.get("lat")) for r in rows]
    lons = [_f(r.get("lon")) for r in rows]
    alts = [_f(r.get("alt")) for r in rows]

    total_pts = len(rows)
    valid_secs = [s for s in secs if s is not None]
    duration = (max(valid_secs) - min(valid_secs)) if len(valid_secs) >= 2 else float(total_pts)

    fixed_count = sum(1 for fix in fixes if fix == 6)
    fixed_ratio = (fixed_count / total_pts * 100.0) if total_pts > 0 else 0.0

    # RTK_FIXED 区間の位置計算（なければ全体）
    fixed_idx = [i for i, fix in enumerate(fixes) if fix == 6]
    target_idx = fixed_idx if len(fixed_idx) >= 3 else [i for i, la in enumerate(lats) if la is not None]

    pts = [(lats[i], lons[i], alts[i]) for i in target_idx if lats[i] is not None and lons[i] is not None]

    if len(pts) < 3:
        return {
            "label": label,
            "pts": total_pts,
            "duration": duration,
            "fixed_pts": fixed_count,
            "fixed_ratio": fixed_ratio,
            "std_horiz_cm": None,
            "std_lat_cm": None,
            "std_lon_cm": None,
            "std_alt_cm": None,
            "max_dev_cm": None,
            "mean_lat": None,
            "mean_lon": None,
            "mean_alt": None,
        }

    la_ok = [p[0] for p in pts]
    lo_ok = [p[1] for p in pts]
    al_ok = [p[2] for p in pts if p[2] is not None]

    mean_lat = sum(la_ok) / len(la_ok)
    mean_lon = sum(lo_ok) / len(lo_ok)
    mean_alt = sum(al_ok) / len(al_ok) if al_ok else 0.0

    def std(vals, mean):
        return math.sqrt(sum((v - mean) ** 2 for v in vals) / (len(vals) - 1))

    cos_lat = math.cos(math.radians(mean_lat))
    std_lat_m = std(la_ok, mean_lat) * METERS_PER_DEG_LAT
    std_lon_m = std(lo_ok, mean_lon) * (METERS_PER_DEG_LAT * cos_lat)
    std_horiz_m = math.sqrt(std_lat_m ** 2 + std_lon_m ** 2)
    std_alt_m = std(al_ok, mean_alt) if len(al_ok) >= 3 else 0.0

    max_horiz_err = 0.0
    for la, lo, _ in pts:
        dx = (lo - mean_lon) * METERS_PER_DEG_LAT * cos_lat
        dy = (la - mean_lat) * METERS_PER_DEG_LAT
        max_horiz_err = max(max_horiz_err, math.hypot(dx, dy))

    return {
        "label": label,
        "pts": total_pts,
        "duration": duration,
        "fixed_pts": fixed_count,
        "fixed_ratio": fixed_ratio,
        "std_horiz_cm": std_horiz_m * 100.0,
        "std_lat_cm": std_lat_m * 100.0,
        "std_lon_cm": std_lon_m * 100.0,
        "std_alt_cm": std_alt_m * 100.0,
        "max_dev_cm": max_horiz_err * 100.0,
        "mean_lat": mean_lat,
        "mean_lon": mean_lon,
        "mean_alt": mean_alt,
    }

def main():
    parser = argparse.ArgumentParser(description="測位ログ CSV から 5分・20分・60分の区間比較を出力するツール")
    parser.add_argument("csv_path", help="rtk_status_*.csv のファイルパス")
    parser.add_argument("--intervals", nargs="+", type=int, default=[300, 1200, 3600],
                        help="切り出し秒数のリスト (既定: 300 1200 3600)")
    args = parser.parse_args()

    if not os.path.exists(args.csv_path):
        print(f"[ERROR] ファイルが存在しません: {args.csv_path}")
        sys.exit(1)

    rows = []
    with open(args.csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    if not rows:
        print("[ERROR] 記録行がありません。")
        sys.exit(1)

    def _f(v):
        try:
            return float(v) if v is not None and v != "" else None
        except Exception:
            return None

    # 各インターバルごとにスライス
    results = []
    for sec_limit in args.intervals:
        mins = sec_limit // 60
        sliced = [r for r in rows if _f(r.get("elapsed_sec")) is not None and _f(r.get("elapsed_sec")) <= sec_limit]
        if sliced:
            res = analyze_slice(sliced, label=f"最初の {mins} 分 ({sec_limit}s)")
            results.append(res)

    # 全区間も追加
    all_res = analyze_slice(rows, label=f"全区間 ({len(rows)}点)")
    results.append(all_res)

    print("\n" + "=" * 78)
    print(" 📊 RTK 測位ログ 観測時間別 精度比較サマリー")
    print("=" * 78)
    print(f" 対象ログ: {args.csv_path}")
    print("-" * 78)
    print(f"{'区分':<18} | {'時間':>7} | {'FIX率':>7} | {'水平1σ(cm)':>10} | {'垂直1σ(cm)':>10} | {'最大偏位(cm)':>10}")
    print("-" * 78)

    for r in results:
        if r is None or r.get("std_horiz_cm") is None:
            continue
        dur_str = f"{r['duration']:.0f}s"
        fix_str = f"{r['fixed_ratio']:.1f}%"
        h_str = f"{r['std_horiz_cm']:.2f}"
        v_str = f"{r['std_alt_cm']:.2f}"
        m_str = f"{r['max_dev_cm']:.2f}"
        print(f"{r['label']:<18} | {dur_str:>7} | {fix_str:>7} | {h_str:>10} | {v_str:>10} | {m_str:>10}")

    print("=" * 78 + "\n")

if __name__ == "__main__":
    main()
