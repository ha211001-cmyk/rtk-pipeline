#!/usr/bin/env python3
"""loader.py — 相対測位精度実測の入力データ読み込み（ペアリング CSV / 実測距離 / PPK）

- ``load_relpos_csv``: タスク63504（gcs/relpos/monitor.py）のペアリング後 CSV を読む。
- ``load_measurements``: 既知距離（メジャー実測）を読む（単一値 or JSON マニフェスト）。
- ``load_ppk_baseline_csv``: PPK 後処理で得た基線長 CSV（独立正解値）を読む。
- ``baseline_from_position_files``: 2 ローバーの PPK 位置 CSV から基線長を計算する。

標準ライブラリのみで動作する（pandas / numpy 不要）。
"""

from __future__ import annotations

import bisect
import csv
import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ペアリング CSV の代表カラム名（gcs.relpos.pairing.PAIRED_CSV_FIELDS と一致）
COL_UTC = "utc_time"
COL_ITOW = "itow_ms"
COL_DIST2D = "distance_2d_m"
COL_DIST3D = "distance_3d_m"
COL_ACC3D = "acc_3d_m"
COL_VALID = "valid"
COL_MATCHED = "matched"

# WGS84 回転楕円体
_WGS84_A = 6378137.0
_WGS84_F = 1.0 / 298.257223563
_WGS84_E2 = _WGS84_F * (2.0 - _WGS84_F)


def parse_utc_epoch(s: Optional[str]) -> Optional[float]:
    """UTC 時刻文字列を UNIX epoch 秒へ変換する。解釈不能なら None。"""
    if s is None or s == "":
        return None
    try:
        text = str(s).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _f(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _f0(v: Any) -> float:
    return _f(v) if _f(v) is not None else 0.0


@dataclass
class RelposBaseline:
    """タスク63504 のペアリング後 CSV から読み込んだ RTK 基線長時系列。"""

    source: str = ""
    utc_epoch: List[float] = field(default_factory=list)
    itow_ms: List[int] = field(default_factory=list)
    dist2d_m: List[float] = field(default_factory=list)
    dist3d_m: List[float] = field(default_factory=list)
    acc3d_m: List[float] = field(default_factory=list)
    total_rows: int = 0
    skipped_invalid: int = 0
    skipped_unmatched: int = 0

    def n(self) -> int:
        return len(self.dist3d_m)


@dataclass
class PpkBaseline:
    """PPK 後処理結果の基線長時系列（独立正解値）。"""

    source: str = ""
    utc_epoch: List[float] = field(default_factory=list)
    baseline_m: List[float] = field(default_factory=list)

    def n(self) -> int:
        return len(self.baseline_m)


@dataclass
class Measurement:
    """既知距離（メジャー実測）1 点。時間範囲は任意（省略時は全系列を対象）。"""

    label: str = ""
    distance_m: float = 0.0
    uncertainty_m: float = 0.0
    start_utc: Optional[str] = None
    end_utc: Optional[str] = None


def load_relpos_csv(path: str, require_valid: bool = True,
                    require_matched: bool = True) -> RelposBaseline:
    """タスク63504 のペアリング後 CSV を読み込む。

    require_valid=True のとき relPosValid が立っていない行（valid != "1"）を、
    require_matched=True のときエポック不整合行（matched != "1"）を除外する。
    """
    p = Path(path)
    out = RelposBaseline(source=str(p))
    with open(p, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out.total_rows += 1
            if require_valid and row.get(COL_VALID, "1") != "1":
                out.skipped_invalid += 1
                continue
            if require_matched and row.get(COL_MATCHED, "1") != "1":
                out.skipped_unmatched += 1
                continue
            d3 = _f(row.get(COL_DIST3D))
            if d3 is None:
                out.skipped_invalid += 1
                continue
            out.utc_epoch.append(parse_utc_epoch(row.get(COL_UTC)) or 0.0)
            itow = row.get(COL_ITOW, "")
            out.itow_ms.append(int(float(itow)) if itow not in ("", None) else 0)
            out.dist3d_m.append(d3)
            out.dist2d_m.append(_f0(row.get(COL_DIST2D)))
            out.acc3d_m.append(_f0(row.get(COL_ACC3D)))
    return out


def load_measurements(manifest_path: Optional[str] = None,
                      distance_m: Optional[float] = None) -> List[Measurement]:
    """既知距離を読み込む。distance_m 指定時は単一実測として扱う。"""
    if distance_m is not None:
        d = float(distance_m)
        return [Measurement(label="D=%.4f m" % d, distance_m=d)]
    if manifest_path is None:
        return []
    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("measurements", data if isinstance(data, list) else [])
    out: List[Measurement] = []
    for it in items:
        out.append(Measurement(
            label=it.get("label", ""),
            distance_m=float(it.get("distance_m", 0.0)),
            uncertainty_m=float(it.get("uncertainty_m", 0.0)),
            start_utc=it.get("start_utc"),
            end_utc=it.get("end_utc"),
        ))
    return out


def load_ppk_baseline_csv(path: str) -> PpkBaseline:
    """PPK 後処理結果の基線長 CSV を読み込む。

    カラム名の揺れ（utc_time/time/datetime/recv_utc/timestamp と
    baseline_length_m/baseline_m/distance_3d_m/dist3d_m/length_m）を吸収する。
    """
    p = Path(path)
    out = PpkBaseline(source=str(p))
    with open(p, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        time_col: Optional[str] = None
        base_col: Optional[str] = None
        for c in (reader.fieldnames or []):
            cl = c.strip().lower()
            if cl in ("utc_time", "time", "datetime", "recv_utc", "timestamp") \
                    and time_col is None:
                time_col = c
            if cl in ("baseline_length_m", "baseline_m", "distance_3d_m",
                      "dist3d_m", "length_m") and base_col is None:
                base_col = c
        for row in reader:
            b = _f(row.get(base_col)) if base_col else None
            if b is None:
                continue
            out.baseline_m.append(b)
            out.utc_epoch.append(
                parse_utc_epoch(row.get(time_col) if time_col else None) or 0.0)
    return out


# ---------------------------------------------------------------------------
# 位置（lat/lon/alt）からの基線長算出（PPK 位置 CSV の組み合わせ用）
# ---------------------------------------------------------------------------

def _enu_between(lat_ref: float, lon_ref: float, lat: float, lon: float
                 ) -> Tuple[float, float]:
    """基準点から見たローカル ENU（北・東）平面距離 [m]（回転楕円体近似）。"""
    la0, lo0 = math.radians(lat_ref), math.radians(lon_ref)
    la, lo = math.radians(lat), math.radians(lon)
    sin0, cos0 = math.sin(la0), math.cos(la0)
    rn = _WGS84_A / math.sqrt(1.0 - _WGS84_E2 * sin0 * sin0)
    rm = _WGS84_A * (1.0 - _WGS84_E2) / ((1.0 - _WGS84_E2 * sin0 * sin0) ** 1.5)
    dn = (la - la0) * rm
    de = (lo - lo0) * cos0 * rn
    return dn, de


def baseline_from_positions(lat_a: float, lon_a: float, alt_a: float,
                            lat_b: float, lon_b: float, alt_b: float) -> float:
    """2 地点（WGS84 緯度経度＋楕円体高）間の 3D 基線長 [m] を算出する。"""
    dn, de = _enu_between(lat_a, lon_a, lat_b, lon_b)
    du = float(alt_b) - float(alt_a)
    return math.sqrt(dn * dn + de * de + du * du)


def load_position_csv(path: str) -> List[Tuple[float, float, float, float]]:
    """位置 CSV を読み込み (utc_epoch, lat_deg, lon_deg, alt_m) のリストを返す。

    カラム名の揺れ（utc_time/recv_utc/time、lat_deg/lat、lon_deg/lon、
    alt_m/alt/height_m）を吸収する。PPK 位置は CSV ヘッダ付きを想定。
    """
    p = Path(path)
    rows: List[Tuple[float, float, float, float]] = []
    with open(p, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols = list(reader.fieldnames or [])
        time_col = next((c for c in cols if c.strip().lower()
                         in ("utc_time", "time", "datetime", "recv_utc",
                             "timestamp")), None)
        lat_col = next((c for c in cols if c.strip().lower()
                        in ("lat_deg", "lat", "latitude")), None)
        lon_col = next((c for c in cols if c.strip().lower()
                        in ("lon_deg", "lon", "longitude")), None)
        alt_col = next((c for c in cols if c.strip().lower()
                        in ("alt_m", "alt", "height_m", "height")), None)
        for row in reader:
            t = parse_utc_epoch(row.get(time_col) if time_col else None)
            la = _f(row.get(lat_col)) if lat_col else None
            lo = _f(row.get(lon_col)) if lon_col else None
            al = _f(row.get(alt_col)) if alt_col else 0.0
            if t is None or la is None or lo is None:
                continue
            rows.append((t, la, lo, al or 0.0))
    return rows


def baseline_from_position_files(path_a: str, path_b: str,
                                 tolerance_s: float = 1.0) -> PpkBaseline:
    """2 ローバーの PPK 位置 CSV から、時刻対応させて基線長時系列を算出する。"""
    a = load_position_csv(path_a)
    b = sorted(load_position_csv(path_b))
    b_t = [x[0] for x in b]

    out = PpkBaseline(source="%s / %s" % (path_a, path_b))
    for (t, la, lo, al) in a:
        idx = bisect.bisect_left(b_t, t)
        best: Optional[Tuple[float, float, float, float]] = None
        best_dt: Optional[float] = None
        for j in (idx - 1, idx):
            if 0 <= j < len(b):
                dt = abs(b[j][0] - t)
                if dt <= tolerance_s and (best_dt is None or dt < best_dt):
                    best_dt = dt
                    best = b[j]
        if best is not None:
            _, lb, lob, alb = best
            out.baseline_m.append(
                baseline_from_positions(la, lo, al, lb, lob, alb))
            out.utc_epoch.append(t)
    return out


__all__ = [
    "parse_utc_epoch",
    "RelposBaseline", "PpkBaseline", "Measurement",
    "load_relpos_csv", "load_measurements", "load_ppk_baseline_csv",
    "load_position_csv", "baseline_from_positions",
    "baseline_from_position_files",
]
