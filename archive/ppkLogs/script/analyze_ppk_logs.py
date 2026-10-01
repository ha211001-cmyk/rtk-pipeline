from __future__ import annotations

from pathlib import Path
import json

import matplotlib.pyplot as plt
import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
RESULT_DIR = BASE_DIR / "result"

NAV_FILE = DATA_DIR / "ppk_nav_20260314_144809.csv"
POS_FILE = DATA_DIR / "ppk_pos_20260314_144809.csv"
RAW_FILE = DATA_DIR / "ppk_raw_20260314_144809.csv"


def load_csv_with_time(path: Path, time_col: str = "recv_utc") -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    frame = pd.read_csv(path)
    if time_col in frame.columns:
        frame[time_col] = pd.to_datetime(frame[time_col], errors="coerce", utc=True)
    return frame


def compute_position_quality(pos: pd.DataFrame) -> dict:
    work = pos.copy()
    work = work.dropna(subset=["recv_utc"]).sort_values("recv_utc")

    lat_valid = work["lat_deg"].between(-90, 90, inclusive="both").mean() if len(work) else 0.0
    lon_valid = work["lon_deg"].between(-180, 180, inclusive="both").mean() if len(work) else 0.0

    diffs = work["recv_utc"].diff().dropna().dt.total_seconds()
    interval_median_s = float(diffs.median()) if len(diffs) else None

    lat_span_deg = float(work["lat_deg"].max() - work["lat_deg"].min()) if len(work) else 0.0
    lon_span_deg = float(work["lon_deg"].max() - work["lon_deg"].min()) if len(work) else 0.0

    approx_path_m = ((lat_span_deg * 111_320.0) ** 2 + (lon_span_deg * 90_000.0) ** 2) ** 0.5

    hdop_series = pd.to_numeric(work.get("hdop"), errors="coerce") if "hdop" in work.columns else pd.Series(dtype=float)
    hdop_valid = hdop_series[(hdop_series >= 0) & (hdop_series <= 50)]
    hdop_placeholder_ratio = float((hdop_series >= 90).mean()) if len(hdop_series.dropna()) else None
    num_sv_series = pd.to_numeric(work.get("num_sv"), errors="coerce") if "num_sv" in work.columns else pd.Series(dtype=float)

    return {
        "samples": int(len(work)),
        "start_utc": work["recv_utc"].min().isoformat() if len(work) else None,
        "end_utc": work["recv_utc"].max().isoformat() if len(work) else None,
        "duration_s": float((work["recv_utc"].max() - work["recv_utc"].min()).total_seconds()) if len(work) else 0.0,
        "interval_median_s": interval_median_s,
        "lat_valid_ratio": float(lat_valid),
        "lon_valid_ratio": float(lon_valid),
        "lat_mean": float(work["lat_deg"].mean()) if len(work) else None,
        "lon_mean": float(work["lon_deg"].mean()) if len(work) else None,
        "lat_span_deg": lat_span_deg,
        "lon_span_deg": lon_span_deg,
        "approx_path_span_m": float(approx_path_m),
        "fix_quality_counts": work["fix_quality"].value_counts(dropna=False).to_dict() if "fix_quality" in work.columns else {},
        "num_sv_min": float(num_sv_series.min()) if len(num_sv_series.dropna()) else None,
        "num_sv_max": float(num_sv_series.max()) if len(num_sv_series.dropna()) else None,
        "num_sv_mean": float(num_sv_series.mean()) if len(num_sv_series.dropna()) else None,
        "hdop_min": float(hdop_valid.min()) if len(hdop_valid.dropna()) else None,
        "hdop_max": float(hdop_valid.max()) if len(hdop_valid.dropna()) else None,
        "hdop_mean": float(hdop_valid.mean()) if len(hdop_valid.dropna()) else None,
        "hdop_ge_10_ratio": float((hdop_valid >= 10).mean()) if len(hdop_valid.dropna()) else None,
        "hdop_available_ratio": float(len(hdop_valid.dropna()) / len(hdop_series.dropna())) if len(hdop_series.dropna()) else None,
        "hdop_placeholder_ratio": hdop_placeholder_ratio,
    }


def compute_satellite_quality(raw: pd.DataFrame, nav: pd.DataFrame) -> dict:
    raw_work = raw.copy()
    nav_work = nav.copy()

    raw_work = raw_work.dropna(subset=["recv_utc"]).sort_values("recv_utc")
    nav_work = nav_work.dropna(subset=["recv_utc"]).sort_values("recv_utc")

    raw_unique_sat = (
        raw_work.groupby("recv_utc")["sv_id"].nunique().rename("raw_unique_sv").sort_index() if len(raw_work) else pd.Series(dtype=float)
    )
    nav_unique_sat = (
        nav_work.groupby("recv_utc")["sv_id"].nunique().rename("nav_unique_sv").sort_index() if len(nav_work) else pd.Series(dtype=float)
    )

    raw_1s = raw_unique_sat.resample("1s").max().dropna() if len(raw_unique_sat) else pd.Series(dtype=float)
    nav_1s = nav_unique_sat.resample("1s").max().dropna() if len(nav_unique_sat) else pd.Series(dtype=float)

    raw_by_gnss = raw_work.groupby("gnss")["sv_id"].nunique().sort_values(ascending=False).to_dict() if "gnss" in raw_work.columns else {}
    nav_by_gnss = nav_work.groupby("gnss")["sv_id"].nunique().sort_values(ascending=False).to_dict() if "gnss" in nav_work.columns else {}

    return {
        "raw_rows": int(len(raw_work)),
        "nav_rows": int(len(nav_work)),
        "raw_unique_satellites_total": int(raw_work["sv_id"].nunique()) if len(raw_work) else 0,
        "nav_unique_satellites_total": int(nav_work["sv_id"].nunique()) if len(nav_work) else 0,
        "raw_unique_by_gnss": raw_by_gnss,
        "nav_unique_by_gnss": nav_by_gnss,
        "raw_epoch_sv_min": float(raw_unique_sat.min()) if len(raw_unique_sat) else None,
        "raw_epoch_sv_max": float(raw_unique_sat.max()) if len(raw_unique_sat) else None,
        "raw_epoch_sv_mean": float(raw_unique_sat.mean()) if len(raw_unique_sat) else None,
        "raw_1s_sv_mean": float(raw_1s.mean()) if len(raw_1s) else None,
        "raw_1s_sv_min": float(raw_1s.min()) if len(raw_1s) else None,
        "raw_1s_sv_max": float(raw_1s.max()) if len(raw_1s) else None,
        "nav_epoch_sv_min": float(nav_unique_sat.min()) if len(nav_unique_sat) else None,
        "nav_epoch_sv_max": float(nav_unique_sat.max()) if len(nav_unique_sat) else None,
        "nav_epoch_sv_mean": float(nav_unique_sat.mean()) if len(nav_unique_sat) else None,
    }


def make_plots(pos: pd.DataFrame, raw: pd.DataFrame, nav: pd.DataFrame) -> None:
    pos_work = pos.dropna(subset=["recv_utc"]).sort_values("recv_utc").copy()
    raw_work = raw.dropna(subset=["recv_utc"]).sort_values("recv_utc").copy()
    nav_work = nav.dropna(subset=["recv_utc"]).sort_values("recv_utc").copy()

    raw_unique_sat = raw_work.groupby("recv_utc")["sv_id"].nunique().rename("raw_unique_sv") if len(raw_work) else pd.Series(dtype=float)
    raw_1s = raw_unique_sat.resample("1s").max().dropna() if len(raw_unique_sat) else pd.Series(dtype=float)

    nav_unique_sat = nav_work.groupby("recv_utc")["sv_id"].nunique().rename("nav_unique_sv") if len(nav_work) else pd.Series(dtype=float)
    nav_1s = nav_unique_sat.resample("1s").max().dropna() if len(nav_unique_sat) else pd.Series(dtype=float)

    fig, axes = plt.subplots(2, 2, figsize=(16, 10), constrained_layout=True)

    ax1 = axes[0, 0]
    if len(pos_work):
        ax1.plot(pos_work["recv_utc"], pd.to_numeric(pos_work["num_sv"], errors="coerce"), label="POS num_sv", linewidth=1.2)
    if len(raw_1s):
        ax1.plot(raw_1s.index, raw_1s.values, label="RAW unique sv (1s max)", linewidth=1.0)
    if len(nav_1s):
        ax1.plot(nav_1s.index, nav_1s.values, label="NAV unique sv (1s max)", linewidth=1.0)
    ax1.set_title("Satellite Count Over Time")
    ax1.set_xlabel("UTC")
    ax1.set_ylabel("satellites")
    ax1.grid(alpha=0.3)
    ax1.legend(loc="best")

    ax2 = axes[0, 1]
    if len(pos_work):
        ax2.plot(pos_work["recv_utc"], pd.to_numeric(pos_work["hdop"], errors="coerce"), color="tab:orange", linewidth=1.2, label="HDOP")
        ax2.set_ylabel("HDOP")
    ax2b = ax2.twinx()
    if len(pos_work):
        ax2b.plot(pos_work["recv_utc"], pd.to_numeric(pos_work["fix_quality"], errors="coerce"), color="tab:green", linewidth=1.0, label="Fix quality")
    ax2.set_title("Position Quality (HDOP / Fix quality)")
    ax2.set_xlabel("UTC")
    ax2.grid(alpha=0.3)

    lines_1, labels_1 = ax2.get_legend_handles_labels()
    lines_2, labels_2 = ax2b.get_legend_handles_labels()
    ax2.legend(lines_1 + lines_2, labels_1 + labels_2, loc="best")

    ax3 = axes[1, 0]
    if len(pos_work):
        ax3.scatter(pos_work["lon_deg"], pos_work["lat_deg"], s=8, alpha=0.6)
    ax3.set_title("Latitude / Longitude Scatter")
    ax3.set_xlabel("Longitude [deg]")
    ax3.set_ylabel("Latitude [deg]")
    ax3.grid(alpha=0.3)

    ax4 = axes[1, 1]
    if len(raw_work):
        raw_counts = raw_work.groupby("gnss")["sv_id"].nunique().sort_values(ascending=False)
        ax4.bar(raw_counts.index.astype(str), raw_counts.values, alpha=0.8, label="RAW unique SV")
    if len(nav_work):
        nav_counts = nav_work.groupby("gnss")["sv_id"].nunique().sort_values(ascending=False)
        ax4.plot(nav_counts.index.astype(str), nav_counts.values, color="tab:red", marker="o", linewidth=1.2, label="NAV unique SV")
    ax4.set_title("Unique Satellites by GNSS")
    ax4.set_xlabel("GNSS")
    ax4.set_ylabel("satellites")
    ax4.grid(alpha=0.3)
    ax4.legend(loc="best")

    fig.suptitle("PPK Log Analysis", fontsize=14)
    fig.savefig(RESULT_DIR / "ppk_summary_plots.png", dpi=150)
    plt.close(fig)


def save_timeseries(pos: pd.DataFrame, raw: pd.DataFrame, nav: pd.DataFrame) -> None:
    pos_work = pos.dropna(subset=["recv_utc"]).sort_values("recv_utc").copy()
    raw_work = raw.dropna(subset=["recv_utc"]).sort_values("recv_utc").copy()
    nav_work = nav.dropna(subset=["recv_utc"]).sort_values("recv_utc").copy()

    out = pd.DataFrame(index=pos_work["recv_utc"]) if len(pos_work) else pd.DataFrame()
    if len(pos_work):
        out["pos_num_sv"] = pd.to_numeric(pos_work["num_sv"], errors="coerce").values
        out["lat_deg"] = pd.to_numeric(pos_work["lat_deg"], errors="coerce").values
        out["lon_deg"] = pd.to_numeric(pos_work["lon_deg"], errors="coerce").values
        out["hdop"] = pd.to_numeric(pos_work["hdop"], errors="coerce").values
        out["fix_quality"] = pd.to_numeric(pos_work["fix_quality"], errors="coerce").values

    if len(raw_work):
        raw_1s = raw_work.groupby("recv_utc")["sv_id"].nunique().resample("1s").max()
        out = out.join(raw_1s.rename("raw_unique_sv_1s"), how="outer")
    if len(nav_work):
        nav_1s = nav_work.groupby("recv_utc")["sv_id"].nunique().resample("1s").max()
        out = out.join(nav_1s.rename("nav_unique_sv_1s"), how="outer")

    out = out.sort_index()
    out.index.name = "recv_utc"
    out.to_csv(RESULT_DIR / "ppk_timeseries_summary.csv")


def evaluate_overall(pos_q: dict, sat_q: dict) -> list[str]:
    comments: list[str] = []

    hdop_mean = pos_q.get("hdop_mean")
    hdop_bad_ratio = pos_q.get("hdop_ge_10_ratio")
    hdop_available_ratio = pos_q.get("hdop_available_ratio")
    hdop_placeholder_ratio = pos_q.get("hdop_placeholder_ratio")
    num_sv_mean = pos_q.get("num_sv_mean")
    path_span = pos_q.get("approx_path_span_m")

    if hdop_available_ratio is not None and hdop_available_ratio < 0.3:
        comments.append("HDOPの有効値が少なく、受信機がHDOPを出力していない可能性が高い。")
    elif hdop_mean is not None:
        if hdop_mean <= 2.5:
            comments.append("HDOP平均は良好で、幾何学的な測位条件は比較的安定。")
        elif hdop_mean <= 6:
            comments.append("HDOP平均は中程度で、測位条件は許容範囲。")
        else:
            comments.append("HDOP平均が高く、測位幾何は不安定。")

    if hdop_bad_ratio is not None and (hdop_available_ratio is not None and hdop_available_ratio >= 0.3):
        if hdop_bad_ratio > 0.5:
            comments.append("HDOP>=10の比率が高く、精度面で問題が大きい。")
        elif hdop_bad_ratio > 0.1:
            comments.append("HDOP>=10の期間が一部あり、品質の揺らぎに注意。")
        else:
            comments.append("HDOP>=10の期間は少なく、品質は比較的安定。")

    if hdop_placeholder_ratio is not None and hdop_placeholder_ratio > 0.7:
        comments.append("HDOPに99.xxのプレースホルダ値が多く、HDOP指標は信頼できない。")

    if num_sv_mean is not None:
        if num_sv_mean >= 10:
            comments.append("POSの平均衛星数は十分。")
        elif num_sv_mean >= 6:
            comments.append("POSの平均衛星数は最低限を確保。")
        else:
            comments.append("POSの平均衛星数が少なく、Fix品質悪化の可能性。")

    raw_mean = sat_q.get("raw_1s_sv_mean")
    if raw_mean is not None:
        if raw_mean >= 12:
            comments.append("RAW観測では衛星取得数が多く、観測自体は良好。")
        elif raw_mean >= 8:
            comments.append("RAW観測の衛星取得数は中程度。")
        else:
            comments.append("RAW観測の衛星取得数が少ない。")

    if path_span is not None:
        if path_span < 2.0:
            comments.append("緯度経度の変動が非常に小さく、受信機はほぼ静止。")
        elif path_span < 20.0:
            comments.append("緯度経度変動は小さく、緩やかな移動またはノイズ範囲。")
        else:
            comments.append("緯度経度の変動が大きく、実移動または不安定挙動の可能性。")

    fix_counts = pos_q.get("fix_quality_counts", {})
    if fix_counts:
        dominant_fix = max(fix_counts.items(), key=lambda x: x[1])[0]
        comments.append(f"Fix qualityの最頻値は {dominant_fix}。")

    if not comments:
        comments.append("評価に十分なデータが取得できませんでした。")

    return comments


def main() -> None:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    pos = load_csv_with_time(POS_FILE)
    raw = load_csv_with_time(RAW_FILE)
    nav = load_csv_with_time(NAV_FILE)

    pos_quality = compute_position_quality(pos)
    sat_quality = compute_satellite_quality(raw, nav)
    comments = evaluate_overall(pos_quality, sat_quality)

    make_plots(pos, raw, nav)
    save_timeseries(pos, raw, nav)

    report = {
        "input_files": {
            "pos": str(POS_FILE),
            "raw": str(RAW_FILE),
            "nav": str(NAV_FILE),
        },
        "position_quality": pos_quality,
        "satellite_quality": sat_quality,
        "evaluation": comments,
    }

    report_json = RESULT_DIR / "ppk_quality_report.json"
    with report_json.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    report_txt = RESULT_DIR / "ppk_quality_report.txt"
    with report_txt.open("w", encoding="utf-8") as f:
        f.write("PPKログ品質評価\n")
        f.write("=" * 40 + "\n")
        f.write("入力ファイル:\n")
        f.write(f"- POS: {POS_FILE}\n")
        f.write(f"- RAW: {RAW_FILE}\n")
        f.write(f"- NAV: {NAV_FILE}\n\n")

        f.write("位置品質サマリ:\n")
        for key, value in pos_quality.items():
            f.write(f"- {key}: {value}\n")

        f.write("\n衛星品質サマリ:\n")
        for key, value in sat_quality.items():
            f.write(f"- {key}: {value}\n")

        f.write("\n評価:\n")
        for comment in comments:
            f.write(f"- {comment}\n")

    print("解析完了")
    print(f"- グラフ: {RESULT_DIR / 'ppk_summary_plots.png'}")
    print(f"- 時系列: {RESULT_DIR / 'ppk_timeseries_summary.csv'}")
    print(f"- レポート(JSON): {report_json}")
    print(f"- レポート(TXT): {report_txt}")


if __name__ == "__main__":
    main()
