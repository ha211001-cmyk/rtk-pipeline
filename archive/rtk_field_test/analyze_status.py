#!/usr/bin/env python3
"""
analyze_status.py — rover_recorder.py が出力した RTK 状態 CSV を解析する

FIX 到達有無・FLOAT 継続時間・衛星数・基線長・位置の標準偏差/最大誤差を集計表示する。

使い方:
    python3 analyze_status.py logs/rtk_status_20260924_120000.csv
"""

import argparse
import csv
import math
from collections import defaultdict

FIX_NAMES = {0: "NO_FIX", 1: "NO_FIX", 2: "2D_FIX", 3: "3D_FIX",
             4: "DGPS", 5: "RTK_FLOAT", 6: "RTK_FIXED"}
METERS_PER_DEG_LAT = 111320.0


def _f(v):
    """文字列/None を float に変換（失敗時 None）。"""
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v, default=0):
    f = _f(v)
    return int(f) if f is not None else default


def main() -> None:
    p = argparse.ArgumentParser(description="RTK状態CSVの解析")
    p.add_argument("csv_path", help="rover_recorder.py が出力した RTK 状態 CSV")
    args = p.parse_args()

    rows = []
    with open(args.csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    if not rows:
        print("[ERROR] データがありません")
        return

    secs = [_f(r.get("elapsed_sec")) for r in rows]
    fixes = [_i(r.get("fix_type")) for r in rows]
    sats = [_i(r.get("sats")) for r in rows]
    nsats = [_i(r.get("nsats")) for r in rows]
    baselines = [_f(r.get("baseline_m")) for r in rows]
    lats = [_f(r.get("lat")) for r in rows]
    lons = [_f(r.get("lon")) for r in rows]

    secs_ok = [s for s in secs if s is not None]
    duration = (max(secs_ok) - min(secs_ok)) if len(secs_ok) >= 2 else 0.0

    print("=" * 66)
    print("RTK 状態ログ解析サマリー")
    print("=" * 66)
    print("ファイル       : %s" % args.csv_path)
    print("サンプル数     : %d" % len(rows))
    print("記録時間       : %.1f 秒（%.2f 分）" % (duration, duration / 60.0))

    # ---- FIX 状態遷移（連続した同一 FIX を1区間にまとめる）----
    runs = []          # (fix, start_sec, end_sec)
    transitions = []   # (sec, fix, utc_time)
    cur_fix = None
    cur_start = None
    last_sec = None
    for i, r in enumerate(rows):
        fix = fixes[i]
        sec = secs[i] if secs[i] is not None else float(i)
        if fix != cur_fix:
            if cur_fix is not None:
                runs.append((cur_fix, cur_start, last_sec))
            cur_fix = fix
            cur_start = sec
            transitions.append((sec, fix, r.get("utc_time")))
        last_sec = sec
    if cur_fix is not None:
        runs.append((cur_fix, cur_start, last_sec))

    print("\n--- FIX 状態遷移 ---")
    for sec, fix, ts in transitions:
        print("  t=%7.1fs (%s)  →  %s" % (sec, ts, FIX_NAMES.get(fix, str(fix))))

    # ---- FIX 別 継続時間 ----
    dur_by_fix = defaultdict(float)
    for fix, s, e in runs:
        if s is not None and e is not None:
            dur_by_fix[fix] += (e - s)

    print("\n--- FIX 別 継続時間 ---")
    for fix in sorted(dur_by_fix):
        d = dur_by_fix[fix]
        print("  %-10s: %8.1f 秒（%.2f 分）" % (FIX_NAMES.get(fix, str(fix)), d, d / 60.0))

    # ---- RTK FIXED 判定 ----
    first_fixed = next((sec for sec, fix, _ts in transitions if fix == 6), None)
    print("\n--- RTK FIXED 判定 ---")
    if first_fixed is not None:
        print("  ✅ RTK_FIXED 到達（開始から %.1f 秒後）" % first_fixed)
    else:
        print("  ❌ RTK_FIXED 未到達")

    # ---- 衛星数・基線長 ----
    def stats_str(vals):
        ok = [v for v in vals if v is not None]
        if not ok:
            return "n/a"
        return "min=%g avg=%.1f max=%g" % (min(ok), sum(ok) / len(ok), max(ok))

    print("\n--- 衛星数 / 基線長 ---")
    print("  捕捉衛星数 sats : %s" % stats_str(sats))
    print("  RTK使用 nsats   : %s" % stats_str(nsats))
    print("  基線長 base(m)  : %s" % stats_str(baselines))

    # ---- 位置の安定性 ----
    latlon = [(la, lo) for la, lo in zip(lats, lons) if la is not None and lo is not None]
    if len(latlon) >= 2:
        la_ok = [x[0] for x in latlon]
        lo_ok = [x[1] for x in latlon]
        mean_lat = sum(la_ok) / len(la_ok)
        mean_lon = sum(lo_ok) / len(lo_ok)

        def std(vals, mean):
            return math.sqrt(sum((v - mean) ** 2 for v in vals) / (len(vals) - 1))

        std_lat_m = std(la_ok, mean_lat) * METERS_PER_DEG_LAT
        std_lon_m = std(lo_ok, mean_lon) * (METERS_PER_DEG_LAT * math.cos(math.radians(mean_lat)))

        cos_lat = math.cos(math.radians(mean_lat))
        max_err = 0.0
        for la, lo in latlon:
            dx = (lo - mean_lon) * METERS_PER_DEG_LAT * cos_lat
            dy = (la - mean_lat) * METERS_PER_DEG_LAT
            max_err = max(max_err, math.hypot(dx, dy))

        print("\n--- 位置の安定性 ---")
        print("  平均位置      : %.7f, %.7f" % (mean_lat, mean_lon))
        print("  標準偏差      : 緯度 %.3f m / 経度 %.3f m" % (std_lat_m, std_lon_m))
        print("  最大水平誤差  : %.3f m" % max_err)
        print("  位置サンプル  : %d 件" % len(latlon))
    else:
        print("\n--- 位置の安定性 ---")
        print("  有効な位置データが不足しています")

    print()


if __name__ == "__main__":
    main()
