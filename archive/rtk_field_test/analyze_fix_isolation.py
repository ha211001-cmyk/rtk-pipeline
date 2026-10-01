#!/usr/bin/env python3
"""
analyze_fix_isolation.py — RTK-FLOAT から RTK-FIXED に到達しない原因の切り分け解析

既存ログ（基地局 RTCM / ローバー受信 RTCM / ローバー RTK 状態 CSV）から、
FIXED 未達の原因を下記の観点で切り分ける:

  1. RTCM メッセージ種別・GNSS 別観測状況（MSM7 の衛星数・信号数）
  2. GLONASS 1230（バイアス）の有無
  3. 基地局 ↔ ローバーの RTCM 到達（TOW 整合・欠落率・時間カバレッジ）
  4. L1/L2 位相観測・lock time（cycle slip）・half-cycle ・CNR の評価

※ ローバー自身の観測（衛星リスト）は本データセットには含まれない
   （rtcm_rover_*.rtcm3 は基地局 RTCM の UDP 受信コピー）。共通衛星は
   短基線であることを根拠に「ほぼ同一」と推定するが、確定には
   ローバー側の UBX-NAV-SAT / RXM-RAWX ログが別途必要。

使い方:
    python3 analyze_fix_isolation.py [--log-dir rtk_field_test/logs]
    （pyrtcm が必要: pip install pyrtcm）
"""

import argparse
import csv
import glob
import os
import sys
from collections import Counter, defaultdict

try:
    from pyrtcm import RTCMReader
except ImportError:
    print("エラー: pyrtcm がインストールされていません")
    print("  pip install pyrtcm")
    sys.exit(1)


# GPS週の日曜0時(GPS時)=TOW 0。2026-09-24 は木曜(day4, TOW 345600s 開始)。
# UTC = GPS時 - 18s（うるう秒）、JST = UTC + 9h = +32400s。
# よって JST 時刻 = TOW_s - 18 - 345600 + 32400 = TOW_s - 313218
TOW_JST_OFFSET = 313218.0

# MSM7 メッセージ種別（GNSS 別）
MSM7_TYPES = {
    1077: ("GPS", "G"),
    1087: ("GLONASS", "R"),
    1097: ("Galileo", "E"),
    1117: ("QZSS", "J"),
    1127: ("BeiDou", "C"),
}
MSM7_TYPE_NAMES = {
    1077: "GPS MSM7 (L1C+L2L)",
    1087: "GLONASS MSM7 (L1C+L2C)",
    1097: "Galileo MSM7 (E1C+E5bQ)",
    1117: "QZSS MSM7",
    1127: "BeiDou MSM7 (B1I+B3I)",
}

# 信号ID → 周波数帯の大まかな分類
SIG_BAND = {
    "1C": "L1", "1P": "L1", "1W": "L1", "1S": "L1", "1L": "L1", "1X": "L1",
    "2C": "L2", "2P": "L2", "2W": "L2", "2S": "L2", "2L": "L2", "2X": "L2",
    "5I": "L5", "5Q": "L5", "5X": "L5",
    "6I": "L6", "6Q": "L6", "6X": "L6",
    "7I": "B3/E5b", "7Q": "B3/E5b", "7X": "B3/E5b",
    "8I": "L8", "8Q": "L8", "8X": "L8",
    "1I": "B1", "2I": "B1", "3I": "B3",
}


def jst_hms(tow_ms):
    """GPS TOW(ms) → JST 時刻文字列 (HH:MM:SS.s)"""
    s = tow_ms / 1000.0 - TOW_JST_OFFSET
    s = max(s, 0.0)
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return "%02d:%02d:%05.2f" % (h, m, sec)


def parse_msm7(parsed):
    """MSM7 メッセージから (衛星PRN, 信号ID) ごとの観測情報を抽出する。"""
    cells = []
    ncell = getattr(parsed, "NCell", 0)
    for c in range(1, ncell + 1):
        prn = getattr(parsed, "CELLPRN_%02d" % c, None)
        sig = getattr(parsed, "CELLSIG_%02d" % c, None)
        lock = getattr(parsed, "DF407_%02d" % c, None)
        cnr = getattr(parsed, "DF408_%02d" % c, None)
        half = getattr(parsed, "DF420_%02d" % c, None)
        cells.append({
            "prn": prn,
            "sig": sig,
            "band": SIG_BAND.get(sig, sig),
            "lock": lock,
            "cnr": cnr,
            "half": half,
        })
    return cells


def analyze_rtcm_file(filepath):
    """1 つの RTCM3 ログを解析し、結果辞書を返す。"""
    msg_types = Counter()
    msm7_by_type = defaultdict(list)  # type -> list of (tow, cells)
    all_tows = []                     # MSM7 の TOW 列（時系列）
    type_order = []                   # MSM7 出現順
    base_station = None

    with open(filepath, "rb") as fh:
        rtr = RTCMReader(fh, quitonerror=0)
        while True:
            try:
                raw, parsed = rtr.read()
            except Exception:
                break
            if raw is None and parsed is None:
                break
            if parsed is None:
                continue
            t = int(parsed.identity)
            msg_types[t] += 1

            if t in (1005, 1006) and base_station is None:
                base_station = {
                    "type": t,
                    "station_id": getattr(parsed, "DF003", None),
                    "ecef_x": getattr(parsed, "DF025", None),
                    "ecef_y": getattr(parsed, "DF026", None),
                    "ecef_z": getattr(parsed, "DF027", None),
                    "gps_ind": getattr(parsed, "DF022", None),
                    "glo_ind": getattr(parsed, "DF023", None),
                    "gal_ind": getattr(parsed, "DF024", None),
                }

            if t in MSM7_TYPES:
                tow = getattr(parsed, "DF004", None)
                cells = parse_msm7(parsed)
                msm7_by_type[t].append((tow, cells))
                if tow is not None:
                    all_tows.append(tow)
                if t not in type_order:
                    type_order.append(t)

    tow_min = min(all_tows) if all_tows else None
    tow_max = max(all_tows) if all_tows else None

    gnss_summary = {}
    for t in type_order:
        msgs = msm7_by_type[t]
        prns = set()
        sig_per_prn = defaultdict(set)
        lock_vals = []
        cnr_vals = []
        half_ones = 0
        for tow, cells in msgs:
            for c in cells:
                if c["prn"]:
                    prns.add(c["prn"])
                    sig_per_prn[c["prn"]].add(c["band"])
                if c["lock"] is not None:
                    lock_vals.append(c["lock"])
                if c["cnr"] is not None:
                    cnr_vals.append(c["cnr"])
                if c["half"] == 1:
                    half_ones += 1

        dual_freq_prns = sorted(p for p, b in sig_per_prn.items() if len(b) >= 2)
        gnss_summary[t] = {
            "name": MSM7_TYPE_NAMES.get(t, str(t)),
            "n_msgs": len(msgs),
            "n_prns": len(prns),
            "prns": sorted(prns),
            "dual_freq": len(dual_freq_prns),
            "dual_freq_prns": dual_freq_prns,
            "lock_min": min(lock_vals) if lock_vals else None,
            "lock_max": max(lock_vals) if lock_vals else None,
            "cnr_min": min(cnr_vals) if cnr_vals else None,
            "cnr_max": max(cnr_vals) if cnr_vals else None,
            "cnr_avg": (sum(cnr_vals) / len(cnr_vals)) if cnr_vals else None,
            "half_ones": half_ones,
        }

    return {
        "file": filepath,
        "size": os.path.getsize(filepath),
        "msg_types": dict(msg_types),
        "base_station": base_station,
        "tow_min": tow_min,
        "tow_max": tow_max,
        "gnss_summary": gnss_summary,
        "msm7_tows": all_tows,
    }


def compare_tows(base_tows, rover_tows):
    """基地局とローバーの MSM7 TOW 列を比較し、エポック単位の欠落率を算出する。"""
    base_epochs = set(base_tows)
    rover_epochs = set(rover_tows)
    base_only = base_epochs - rover_epochs
    n_base = len(base_epochs)
    missing = len(base_only)
    loss_pct = (missing / n_base * 100.0) if n_base else 0.0
    return {
        "n_base_epochs": n_base,
        "n_rover_epochs": len(rover_epochs),
        "missing_epochs": missing,
        "loss_pct": loss_pct,
    }


def analyze_status_csv(csv_path):
    rows = []
    with open(csv_path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    if not rows:
        return None

    def fnum(r, k):
        v = r.get(k, "").strip()
        try:
            return float(v) if v else None
        except ValueError:
            return None

    transitions = []
    prev = None
    for r in rows:
        ft = r.get("fix_type")
        if ft != prev:
            transitions.append((fnum(r, "elapsed_sec"), ft,
                                r.get("fix_name"), r.get("utc_time")))
            prev = ft

    rtcm_vals = [fnum(r, "rtcm_elapsed_sec") for r in rows]
    rtcm_vals = [v for v in rtcm_vals if v is not None]
    rtcm_active = [v for v in rtcm_vals if v <= 1.0]
    rtcm_idle = [v for v in rtcm_vals if v > 1.0]

    sats = [int(r["sats"]) for r in rows if r.get("sats", "").strip()]
    nsats_vals = Counter(r.get("nsats", "0") for r in rows)

    return {
        "file": csv_path,
        "n_rows": len(rows),
        "transitions": transitions,
        "n_rtcm_active": len(rtcm_active),
        "n_rtcm_idle": len(rtcm_idle),
        "rtcm_max_gap": max(rtcm_vals) if rtcm_vals else None,
        "sats": {"min": min(sats), "max": max(sats),
                 "avg": sum(sats) / len(sats)} if sats else None,
        "nsats_vals": dict(nsats_vals),
    }


def main():
    p = argparse.ArgumentParser(description="RTK-FIXED未達の原因切り分け解析")
    p.add_argument("--log-dir", default=None,
                   help="ログディレクトリ（省略時: 本スクリプトと同階層の logs/）")
    p.add_argument("--csv", default=None, help="RTK状態CSV（省略時: 自動検出）")
    args = p.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = args.log_dir or os.path.join(script_dir, "logs")

    base_files = sorted(glob.glob(os.path.join(log_dir, "rtcm_base_*.rtcm3")))
    rover_files = sorted(glob.glob(os.path.join(log_dir, "rtcm_rover_*.rtcm3")))
    csv_files = sorted(glob.glob(os.path.join(log_dir, "rtk_status_*.csv")))

    print("=" * 74)
    print(" RTK-FIXED 未達の原因切り分け解析（既存ログ）")
    print("=" * 74)
    print("ログディレクトリ: %s" % log_dir)
    print()

    base_results = [analyze_rtcm_file(f) for f in base_files]
    rover_results = [analyze_rtcm_file(f) for f in rover_files]

    print("[1] RTCM メッセージ種別・時間カバレッジ")
    print("-" * 74)
    for r in base_results + rover_results:
        fn = os.path.basename(r["file"])
        tmin = jst_hms(r["tow_min"]) if r["tow_min"] is not None else "?"
        tmax = jst_hms(r["tow_max"]) if r["tow_max"] is not None else "?"
        kinds = ", ".join("%d:%d" % (k, v) for k, v in sorted(r["msg_types"].items()))
        print("  %-42s %s ~ %s" % (fn, tmin, tmax))
        print("      (%s)" % kinds)

    print()
    print("[2] GLONASS 出力（1087 MSM7 / 1230 バイアス）の有無")
    print("-" * 74)
    for r in base_results + rover_results:
        fn = os.path.basename(r["file"])
        has_1087 = 1087 in r["msg_types"]
        has_1230 = 1230 in r["msg_types"]
        print("  %-42s 1087(GLONASS MSM7)=%s  1230(GLO bias)=%s"
              % (fn, "あり" if has_1087 else "なし", "あり" if has_1230 else "なし"))

    print()
    print("[3] GNSS 別 MSM7 観測状況（基地局・ローバー受信）")
    print("-" * 74)
    for r in base_results + rover_results:
        fn = os.path.basename(r["file"])
        print("  [%s]" % fn)
        for t in sorted(r["gnss_summary"]):
            g = r["gnss_summary"][t]
            lock = ("lock=%s~%s" % (g["lock_min"], g["lock_max"])
                    if g["lock_min"] is not None else "lock=n/a")
            cnr = ("CNR=%.0f~%.0f(avg %.0f)dBHz"
                   % (g["cnr_min"], g["cnr_max"], g["cnr_avg"])
                   if g["cnr_avg"] is not None else "CNR=n/a")
            print("    Type %4d %-26s 衛星=%2d うち2周波=%2d  %s %s half-cycle=%d"
                  % (t, g["name"], g["n_prns"], g["dual_freq"], lock, cnr,
                     g["half_ones"]))
            print("          PRN: %s" % " ".join(g["prns"]))

    print()
    print("[4] 基地局 ARP（1005/1006）座標")
    print("-" * 74)
    for r in base_results:
        bs = r["base_station"]
        if bs:
            print("  [%s] Type=%d 局ID=%s GPS_ind=%s GLO_ind=%s GAL_ind=%s"
                  % (os.path.basename(r["file"]), bs["type"], bs["station_id"],
                     bs["gps_ind"], bs["glo_ind"], bs["gal_ind"]))
            if bs["ecef_x"] is not None:
                print("         ECEF X=%.3f Y=%.3f Z=%.3f m"
                      % (bs["ecef_x"], bs["ecef_y"], bs["ecef_z"]))

    print()
    print("[5] 基地局↔ローバーの RTCM 到達比較（TOW 整合）")
    print("-" * 74)
    for rr in rover_results:
        for br in base_results:
            if (br["tow_min"] is not None and rr["tow_min"] is not None
                    and br["tow_min"] <= rr["tow_max"]
                    and rr["tow_min"] <= br["tow_max"]):
                cmp = compare_tows(br["msm7_tows"], rr["msm7_tows"])
                print("  基地局 %s  vs ローバー %s"
                      % (os.path.basename(br["file"]), os.path.basename(rr["file"])))
                print("    基地局エポック数=%d ローバー受信=%d 欠落=%d (%.3f%%)"
                      % (cmp["n_base_epochs"], cmp["n_rover_epochs"],
                         cmp["missing_epochs"], cmp["loss_pct"]))

    print()
    print("[6] ローバー RTK 状態 CSV")
    print("-" * 74)
    csv_path = args.csv or (csv_files[0] if csv_files else None)
    if csv_path:
        cs = analyze_status_csv(csv_path)
        print("  ファイル: %s (%d 行)" % (os.path.basename(csv_path), cs["n_rows"]))
        print("  FIX 遷移:")
        for sec, ft, fn, ts in cs["transitions"]:
            print("    t=%s (%s) -> fix_type=%s %s" % (sec, ts, ft, fn))
        print("  RTCM 到達サンプル: 流れている(<=1s)=%d, 途絶(>1s)=%d, 最大途絶=%.1fs"
              % (cs["n_rtcm_active"], cs["n_rtcm_idle"], cs["rtcm_max_gap"]))
        if cs["sats"]:
            print("  捕捉衛星数 sats: min=%d avg=%.1f max=%d"
                  % (cs["sats"]["min"], cs["sats"]["avg"], cs["sats"]["max"]))
        print("  RTK使用衛星 nsats の値分布: %s" % cs["nsats_vals"])
    else:
        print("  CSV が見つかりません")

    print()
    print("=" * 74)
    print("解析完了")
    print("=" * 74)


if __name__ == "__main__":
    main()


