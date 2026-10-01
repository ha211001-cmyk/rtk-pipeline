#!/usr/bin/env python3
"""
plot_rtk_histogram.py — RTKのログ(CSV)から測位誤差のヒストグラムを作成

サポート形式:
  1. rtk_data_collector.py の出力 (horizontal_error_m, delta_alt_m を含む)
  2. mavlink_bridge.py の出力 (lat, lon, alt を含む) ※RTK_FIXED時の重心からの距離を誤差とする

使い方:
  python3 gcs/rtk_tools/plot_rtk_histogram.py logs/rtk_error.csv
"""

import argparse
import csv
import sys
import math
from pathlib import Path
try:
    import matplotlib.pyplot as plt
    import numpy as np
except ImportError:
    print("エラー: matplotlib と numpy が必要です。")
    print("pip install matplotlib numpy を実行してください。")
    sys.exit(1)

METERS_PER_DEG_LAT = 111320.0

def _lon_scale(lat_deg: float) -> float:
    return METERS_PER_DEG_LAT * math.cos(math.radians(lat_deg))

def plot_histogram(csv_path: Path):
    if not csv_path.exists():
        print(f"エラー: ファイルが見つかりません - {csv_path}")
        sys.exit(1)

    h_errors = []
    v_errors = []
    
    with open(csv_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        rows = list(reader)

    if "horizontal_error_m" in fields and "delta_alt_m" in fields:
        # 形式1: rtk_data_collector.py
        for row in rows:
            try:
                h_errors.append(float(row["horizontal_error_m"]))
                v_errors.append(float(row["delta_alt_m"]))
            except (ValueError, KeyError):
                continue
    elif "lat" in fields and "lon" in fields and "alt" in fields:
        # 形式2: mavlink_bridge.py
        # RTK_FIXED のみ抽出（または全点）
        fixed_rows = [r for r in rows if r.get("fix_name") == "RTK_FIXED" or r.get("fix_type") == "6"]
        if not fixed_rows:
            print("警告: RTK_FIXED のデータが見つからないため、全点を使用します。")
            fixed_rows = rows
        
        lats = []
        lons = []
        alts = []
        for r in fixed_rows:
            try:
                lats.append(float(r["lat"]))
                lons.append(float(r["lon"]))
                alts.append(float(r["alt"]))
            except ValueError:
                continue
                
        if not lats:
            print("エラー: 有効な座標データが見つかりませんでした。")
            sys.exit(1)
            
        mean_lat = sum(lats) / len(lats)
        mean_lon = sum(lons) / len(lons)
        mean_alt = sum(alts) / len(alts)
        
        for lat, lon, alt in zip(lats, lons, alts):
            dlat = (lat - mean_lat) * METERS_PER_DEG_LAT
            dlon = (lon - mean_lon) * _lon_scale(mean_lat)
            h_dist = math.sqrt(dlat**2 + dlon**2)
            dalt = alt - mean_alt
            
            h_errors.append(h_dist)
            v_errors.append(dalt)
    else:
        print("エラー: 未対応のCSV形式です。")
        sys.exit(1)

    if not h_errors:
        print("エラー: 誤差データを計算できませんでした。")
        sys.exit(1)

    h_errors = np.array(h_errors)
    v_errors = np.array(v_errors)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # 水平誤差ヒストグラム
    ax1.hist(h_errors, bins=50, color='blue', alpha=0.7, edgecolor='black')
    ax1.set_title(f"Horizontal Error Distribution (n={len(h_errors)})")
    ax1.set_xlabel("Horizontal Error [m]")
    ax1.set_ylabel("Frequency")
    ax1.grid(True, linestyle='--', alpha=0.7)
    
    # 垂直誤差ヒストグラム
    ax2.hist(v_errors, bins=50, color='green', alpha=0.7, edgecolor='black')
    ax2.set_title(f"Vertical Error Distribution (n={len(v_errors)})")
    ax2.set_xlabel("Vertical Error [m] (Error from Mean)")
    ax2.set_ylabel("Frequency")
    ax2.grid(True, linestyle='--', alpha=0.7)

    plt.suptitle(f"RTK Positioning Error Histogram\n{csv_path.name}")
    plt.tight_layout()
    
    # 画像として保存
    out_img = csv_path.with_suffix(".png")
    plt.savefig(out_img, dpi=300)
    print(f"ヒストグラム画像を保存しました: {out_img}")

def main():
    p = argparse.ArgumentParser(description="測位誤差のヒストグラムを作成")
    p.add_argument("csv_path", help="CSVファイル (rtk_data_collector または mavlink_bridge 出力)")
    args = p.parse_args()

    plot_histogram(Path(args.csv_path))

if __name__ == "__main__":
    main()
