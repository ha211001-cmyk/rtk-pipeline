#!/usr/bin/env python3
"""pairing.py — 複数ローバーの UBX-NAV-RELPOSNED を iTOW でペアリングする中核ロジック

協調搬送に向けた自作 GCS 拡張の中核。複数ローバーがそれぞれ出力する
UBX-NAV-RELPOSNED（基準局からの相対位置）を、**GPS 時刻エポック（iTOW）をキーに**
ペアリングし、両ローバーの差（機体間相対位置）を算出する。

飛行中（協調搬送本番）はエポックのズレがそのまま相対位置誤差として現れるため、
「各ローバーの最新値を単に都度表示する」のではなく、同一 iTOW で揃えてから
差分を取ることが最重要要件となる。

本モジュールは**標準ライブラリのみ**に依存し、通信層（pyserial / pyubx2）とは
独立している。UBX バイト列の読み取りは reader.py が、ライブ表示・CSV 記録は
monitor.py が担当する。

主な機能:
  - iTOW をキーにした最新値バッファリングとペアリング
  - GPS 週跨ぎロールオーバー（604800000 ms）の正しい取り扱い
  - マッチング許容ウィンドウ（許容エポック差）の定義と整合状態の判定
  - accN/accE/accD からの相対位置精度の誤差伝播推定
  - relPosHeading のペアリングと機体間方位（bearing）の算出
  - ペアリング後の相対位置を CSV 行・JSON dict へ変換するヘルパー

Usage:
    from gcs.relpos.pairing import (
        RelposnedSample, PairedRelpos, RelposPairingBuffer,
        itow_diff_ms, compute_relative,
    )

    buf = RelposPairingBuffer(rover_ids=("A", "B"), match_window_ms=200)
    buf.update(sample_a)      # RelposnedSample
    paired = buf.update(sample_b)   # iTOW が揃えば PairedRelpos を返す
"""

from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, Optional, Tuple

# GPS 週 = 604800 秒 = 604800000 ms（iTOW は 0..604799999 でラップする）
ITOW_PER_WEEK_MS = 604_800_000
ITOW_HALF_WEEK_MS = ITOW_PER_WEEK_MS // 2

# 方位の正規化範囲
FULL_TURN_DEG = 360.0


# ---------------------------------------------------------------------------
# iTOW（GPS 時刻エポック）のロールオーバー対応
# ---------------------------------------------------------------------------

def itow_diff_ms(a: int, b: int) -> int:
    """iTOW の符号付き最短差（b - a）を ms で返す。GPS 週跨ぎを考慮する。

    iTOW は 0..604799999 の範囲で、GPS 週の境界で 604799999 → 0 へラップする。
    単純な引き算だと週跨ぎで ±604800000 ms もの誤差になるため、mod 演算で
    最短の符号付き差（-302400000 .. +302400000 ms）へ折り畳む。

    Args:
        a: 基準となる iTOW [ms]
        b: 比較対象の iTOW [ms]

    Returns:
        b - a の符号付き最短差 [ms]。正なら b が a より進んでいる。
    """
    delta = (b - a) % ITOW_PER_WEEK_MS
    if delta > ITOW_HALF_WEEK_MS:
        delta -= ITOW_PER_WEEK_MS
    return delta


def normalize_bearing_deg(deg: float) -> float:
    """方位角を [0, 360) に正規化する（0=北, 90=東, 180=南, 270=西）。"""
    return deg % FULL_TURN_DEG


def signed_heading_delta_deg(a: float, b: float) -> float:
    """方位差（b - a）を [-180, 180) に折り畳む。"""
    d = (b - a) % FULL_TURN_DEG
    if d >= 180.0:
        d -= FULL_TURN_DEG
    return d


def propagate_accuracy(a_m: float, b_m: float) -> float:
    """2 つの独立な 1σ 精度（m）から、差 B-A の 1σ 精度を誤差伝播で推定する。

    独立な誤差を持つ 2 測定値の差の分散は各分散の和になるため、
    σ_Δ = sqrt(σ_A^2 + σ_B^2) となる。
    """
    return math.hypot(a_m, b_m)


# ---------------------------------------------------------------------------
# データ構造（SI 単位に正規化済み）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RelposnedSample:
    """1 ローバー・1 エポック分の NAV-RELPOSNED を SI 単位で保持する。

    reader.py が pyubx2 の解析結果（relPosN 等は cm、accN 等は mm）を
    メートルへ換算して構築する。iTOW は ms、refStationID はそのまま保持する。
    """

    rover_id: str
    itow_ms: int
    ref_station_id: int
    rel_n_m: float          # 北成分（基準局→ローバー）[m]
    rel_e_m: float          # 東成分 [m]
    rel_d_m: float          # 下成分 [m]
    rel_length_m: float     # 3D 基線長 [m]
    rel_heading_deg: float  # ローバー→基準局 の方位 [deg]
    acc_n_m: float          # 北成分精度 1σ [m]
    acc_e_m: float
    acc_d_m: float
    acc_length_m: float
    acc_heading_deg: float
    flags: Dict[str, Any] = field(default_factory=dict)
    wall_ts: float = 0.0    # 受信時刻（time.time()）

    @property
    def rel_pos_valid(self) -> bool:
        return bool(self.flags.get("rel_pos_valid", False))

    @property
    def heading_valid(self) -> bool:
        return bool(self.flags.get("rel_pos_heading_valid", False))


@dataclass(frozen=True)
class PairedRelpos:
    """同一 iTOW にペアリングされた 2 ローバー間の相対位置（B - A）。

    相対位置は RELPOSNED_B - RELPOSNED_A として N/E/D 各軸で算出する。
    誤差は誤差伝播（各軸 σ の二乗和平方根）で推定する。
    """

    itow_ms: int            # ペアリングの基準 iTOW（= itow_a）
    itow_a: int
    itow_b: int
    delta_ms: int           # itow_b - itow_a（符号付き最短差）
    matched: bool           # 許容ウィンドウ内で整合したか
    ref_station_match: bool # 両ローバーの refStationId が一致したか
    ref_station_a: int
    ref_station_b: int
    rel_n_m: float          # B - A 北成分 [m]
    rel_e_m: float          # B - A 東成分 [m]
    rel_d_m: float          # B - A 下成分 [m]
    distance_2d_m: float
    distance_3d_m: float
    bearing_ab_deg: float   # 機体間方位（A→B）[deg]
    heading_a_deg: float    # A の relPosHeading（→基準局）
    heading_b_deg: float    # B の relPosHeading（→基準局）
    heading_valid: bool
    acc_n_m: float
    acc_e_m: float
    acc_d_m: float
    acc_horizontal_m: float
    acc_3d_m: float
    valid: bool             # 両ローバーの relPosValid が立っているか
    wall_ts: float

    @property
    def epoch_status(self) -> str:
        """エポック整合状態の文字列表現。"""
        return "matched" if self.matched else "mismatched"

    def to_dict(self) -> Dict[str, Any]:
        """JSON シリアライズ可能な dict（GCS 統合用）。"""
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def to_csv_row(self, fields: Iterable[str]) -> Dict[str, str]:
        """CSV フィールド名に応じた行 dict を返す（None は空文字）。"""
        d = self.to_dict()
        row: Dict[str, str] = {}
        for f in fields:
            v = d.get(f)
            if v is None:
                row[f] = ""
            elif isinstance(v, bool):
                row[f] = "1" if v else "0"
            elif isinstance(v, float):
                row[f] = "%.6f" % v
            else:
                row[f] = str(v)
        return row


# デフォルトの CSV フィールド（ペアリング後相対位置時系列）
PAIRED_CSV_FIELDS = [
    "utc_time", "itow_ms", "itow_a", "itow_b", "delta_ms", "matched",
    "ref_station_match", "ref_station_a", "ref_station_b",
    "rel_n_m", "rel_e_m", "rel_d_m",
    "distance_2d_m", "distance_3d_m", "bearing_ab_deg",
    "heading_a_deg", "heading_b_deg", "heading_valid",
    "acc_n_m", "acc_e_m", "acc_d_m",
    "acc_horizontal_m", "acc_3d_m", "valid",
]


# ---------------------------------------------------------------------------
# 相対位置の算出
# ---------------------------------------------------------------------------

def compute_relative(sample_a: RelposnedSample,
                     sample_b: RelposnedSample,
                     delta_ms: Optional[int] = None,
                     matched: Optional[bool] = None) -> PairedRelpos:
    """2 ローバーの RELPOSNED から機体間相対位置（B - A）を算出する。

    Args:
        sample_a: ローバー A のサンプル
        sample_b: ローバー B のサンプル
        delta_ms: itow_b - itow_a の符号付き差。省略時は itow_diff_ms() で算出。
        matched: 許容ウィンドウ内での整合有無。省略時は False（呼び出し側で判定する）。

    Returns:
        PairedRelpos（相対位置・距離・方位・誤差伝播済み精度）。
    """
    if delta_ms is None:
        delta_ms = itow_diff_ms(sample_a.itow_ms, sample_b.itow_ms)

    rel_n = sample_b.rel_n_m - sample_a.rel_n_m
    rel_e = sample_b.rel_e_m - sample_a.rel_e_m
    rel_d = sample_b.rel_d_m - sample_a.rel_d_m

    distance_2d = math.hypot(rel_n, rel_e)
    distance_3d = math.sqrt(rel_n * rel_n + rel_e * rel_e + rel_d * rel_d)

    # 機体間方位（A→B）: ENU 座標系で atan2(E, N)
    bearing_ab = normalize_bearing_deg(math.degrees(math.atan2(rel_e, rel_n)))

    # 誤差伝播: 差の分散 = 各分散の和
    acc_n = propagate_accuracy(sample_a.acc_n_m, sample_b.acc_n_m)
    acc_e = propagate_accuracy(sample_a.acc_e_m, sample_b.acc_e_m)
    acc_d = propagate_accuracy(sample_a.acc_d_m, sample_b.acc_d_m)
    acc_horizontal = math.hypot(acc_n, acc_e)
    acc_3d = math.sqrt(acc_n * acc_n + acc_e * acc_e + acc_d * acc_d)

    valid = sample_a.rel_pos_valid and sample_b.rel_pos_valid
    heading_valid = sample_a.heading_valid and sample_b.heading_valid

    return PairedRelpos(
        itow_ms=sample_a.itow_ms,
        itow_a=sample_a.itow_ms,
        itow_b=sample_b.itow_ms,
        delta_ms=delta_ms,
        matched=bool(matched) if matched is not None else False,
        ref_station_match=sample_a.ref_station_id == sample_b.ref_station_id,
        ref_station_a=sample_a.ref_station_id,
        ref_station_b=sample_b.ref_station_id,
        rel_n_m=rel_n,
        rel_e_m=rel_e,
        rel_d_m=rel_d,
        distance_2d_m=distance_2d,
        distance_3d_m=distance_3d,
        bearing_ab_deg=bearing_ab,
        heading_a_deg=sample_a.rel_heading_deg,
        heading_b_deg=sample_b.rel_heading_deg,
        heading_valid=heading_valid,
        acc_n_m=acc_n,
        acc_e_m=acc_e,
        acc_d_m=acc_d,
        acc_horizontal_m=acc_horizontal,
        acc_3d_m=acc_3d,
        valid=valid,
        wall_ts=max(sample_a.wall_ts, sample_b.wall_ts),
    )


# ---------------------------------------------------------------------------
# ペアリングバッファ
# ---------------------------------------------------------------------------

class RelposPairingBuffer:
    """iTOW をキーに各ローバーの最新 RELPOSNED をバッファリングしペアリングする。

    各ローバーごとに直近 N サンプルの履歴（iTOW 順）を保持し、``update()``
    ごとに両ローバーの履歴から iTOW 差（週跨ぎ対応）が最小の組み合わせを探す。
    その差が ``match_window_ms`` 以内なら「一致エポック」としてペアリングする。

    エポックが揃わない場合も ``matched=False`` の best-effort 結果を返すため、
    呼び出し側は ``paired.matched`` / ``paired.delta_ms`` で警告表示できる。
    """

    def __init__(self,
                 rover_ids: Tuple[str, ...] = ("A", "B"),
                 match_window_ms: int = 200,
                 history_len: int = 32):
        if len(rover_ids) < 2:
            raise ValueError("rover_ids は 2 機以上必要です")
        self.rover_ids = tuple(rover_ids)
        self.match_window_ms = match_window_ms
        self._latest: Dict[str, RelposnedSample] = {}
        self._history: Dict[str, deque] = {
            rid: deque(maxlen=history_len) for rid in self.rover_ids
        }
        self.stats: Dict[str, int] = {
            "updates": 0,
            "paired": 0,
            "matched": 0,
            "mismatched": 0,
            "ref_station_mismatch": 0,
        }

    def update(self, sample: RelposnedSample) -> Optional[PairedRelpos]:
        """ローバーのサンプルを投入し、ペアリング結果（あれば）を返す。"""
        if sample.rover_id not in self.rover_ids:
            raise ValueError("未知の rover_id: %s" % sample.rover_id)
        self._latest[sample.rover_id] = sample
        self._history[sample.rover_id].append(sample)
        self.stats["updates"] += 1
        return self.pair()

    def has_all(self) -> bool:
        return all(rid in self._latest for rid in self.rover_ids)

    def pair(self) -> Optional[PairedRelpos]:
        """現在のバッファから最良のペアを 1 つ返す（全ローバー未着なら None）。"""
        if not self.has_all():
            return None

        # 先頭 2 機（rover_ids の順）を対象に、iTOW 差が最小の組み合わせを探索
        rid_a, rid_b = self.rover_ids[0], self.rover_ids[1]
        best: Optional[Tuple[RelposnedSample, RelposnedSample]] = None
        best_diff: Optional[int] = None
        for a in self._history[rid_a]:
            for b in self._history[rid_b]:
                diff = itow_diff_ms(a.itow_ms, b.itow_ms)
                if best_diff is None or abs(diff) < abs(best_diff):
                    best = (a, b)
                    best_diff = diff

        if best is None or best_diff is None:
            return None

        a, b = best
        matched = abs(best_diff) <= self.match_window_ms
        paired = compute_relative(a, b, delta_ms=best_diff, matched=matched)

        self.stats["paired"] += 1
        if paired.matched:
            self.stats["matched"] += 1
        else:
            self.stats["mismatched"] += 1
        if not paired.ref_station_match:
            self.stats["ref_station_mismatch"] += 1
        return paired


# ---------------------------------------------------------------------------
# 自己検証
# ---------------------------------------------------------------------------

def _mk_sample(rover_id: str, itow: int, n: float, e: float, d: float,
               ref_station: int = 0, acc: float = 0.01,
               heading: float = 45.0, rel_pos_valid: bool = True,
               heading_valid: bool = True) -> RelposnedSample:
    """テスト・自己検証用のサンプル生成ヘルパー。"""
    length = math.sqrt(n * n + e * e + d * d)
    return RelposnedSample(
        rover_id=rover_id,
        itow_ms=itow,
        ref_station_id=ref_station,
        rel_n_m=n, rel_e_m=e, rel_d_m=d, rel_length_m=length,
        rel_heading_deg=heading,
        acc_n_m=acc, acc_e_m=acc, acc_d_m=acc, acc_length_m=acc,
        acc_heading_deg=0.001,
        flags={
            "rel_pos_valid": rel_pos_valid,
            "rel_pos_heading_valid": heading_valid,
            "gnss_fix_ok": True,
            "diff_soln": True,
            "carr_soln": 2,
        },
        wall_ts=0.0,
    )


def self_test() -> bool:
    """合成データでペアリング・ロールオーバー・誤差伝播を検証する。"""
    checks = []

    # 1. iTOW 差（通常）
    checks.append(("itow_diff 基本", itow_diff_ms(1000, 1200) == 200))
    checks.append(("itow_diff 負", itow_diff_ms(1200, 1000) == -200))

    # 2. 週跨ぎロールオーバー
    # A=604799990, B=10 は 20ms の差（10 - 604799990 = -604799980 → +20）
    checks.append(("ロールオーバー(+20ms)", itow_diff_ms(604799990, 10) == 20))
    # 逆方向: A=10, B=604799990 は -20ms
    checks.append(("ロールオーバー(-20ms)", itow_diff_ms(10, 604799990) == -20))

    # 3. 相対位置（B - A）
    a = _mk_sample("A", 1000, n=1.0, e=0.0, d=0.0)
    b = _mk_sample("B", 1000, n=3.0, e=4.0, d=0.0)
    p = compute_relative(a, b, delta_ms=0, matched=True)
    checks.append(("relN = B-A", abs(p.rel_n_m - 2.0) < 1e-9))
    checks.append(("relE = B-A", abs(p.rel_e_m - 4.0) < 1e-9))
    checks.append(("distance_2d", abs(p.distance_2d_m - math.hypot(2.0, 4.0)) < 1e-9))
    checks.append(("bearing", abs(p.bearing_ab_deg
                                  - math.degrees(math.atan2(4, 2))) < 1e-6))

    # 4. 誤差伝播: σ_Δ = sqrt(0.01^2 + 0.01^2)
    checks.append(("誤差伝播", abs(p.acc_n_m - math.hypot(0.01, 0.01)) < 1e-12))

    # 5. refStationId 一致
    checks.append(("refStation 一致", p.ref_station_match is True))
    c = _mk_sample("B", 1000, n=3.0, e=4.0, d=0.0, ref_station=99)
    p2 = compute_relative(a, c, delta_ms=0, matched=True)
    checks.append(("refStation 不一致", p2.ref_station_match is False))

    # 6. ペアリングバッファ（一致エポック）
    buf = RelposPairingBuffer(rover_ids=("A", "B"), match_window_ms=200)
    assert buf.update(a) is None
    res = buf.update(b)
    checks.append(("バッファ: ペア生成", res is not None))
    checks.append(("バッファ: matched", res is not None and res.matched))

    # 7. ペアリングバッファ（エポック不整合 → 警告状態）
    buf2 = RelposPairingBuffer(rover_ids=("A", "B"), match_window_ms=50)
    buf2.update(_mk_sample("A", 1000, n=1.0, e=0.0, d=0.0))
    res2 = buf2.update(_mk_sample("B", 1200, n=3.0, e=4.0, d=0.0))
    checks.append(("バッファ: 不整合", res2 is not None and not res2.matched))
    checks.append(("バッファ: delta=200ms",
                   res2 is not None and res2.delta_ms == 200))

    # 8. 週跨ぎでのペアリング（バッファ）
    buf3 = RelposPairingBuffer(rover_ids=("A", "B"), match_window_ms=50)
    buf3.update(_mk_sample("A", 604799990, n=1.0, e=0.0, d=0.0))
    res3 = buf3.update(_mk_sample("B", 10, n=3.0, e=4.0, d=0.0))
    checks.append(("バッファ: 週跨ぎマッチ", res3 is not None and res3.matched))
    checks.append(("バッファ: 週跨ぎ delta=20ms",
                   res3 is not None and res3.delta_ms == 20))

    ok = True
    for name, passed in checks:
        if not passed:
            ok = False
            print("[FAIL] %s" % name)
    return ok


if __name__ == "__main__":
    if self_test():
        print("pairing self-test: OK")
    else:
        print("pairing self-test: FAILED")
        raise SystemExit(1)
