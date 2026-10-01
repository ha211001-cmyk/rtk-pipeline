#!/usr/bin/env python3
"""fix_metrics.py — RTK fix_type 時系列の定量指標を計算する（標準ライブラリのみ）

Phase 1 ゴール「地上で安定して RTK-FIXED を定量判定」のため、fix_type 時系列から
下記を集計する:

  - FIXED 維持率 (%)
  - FLOAT 遷移回数（FIXED→FLOAT の脱落回数を含む）
  - 遷移タイムスタンプ一覧
  - TTFF (Time To First Fix = 記録開始から最初の RTK_FIXED までの秒数)

fix_type は MAVLink の GPS_FIX_TYPE（0..6）に正規化した値を用いる:
    0/1 = NO_FIX, 2 = 2D_FIX, 3 = 3D_FIX, 4 = DGPS, 5 = RTK_FLOAT, 6 = RTK_FIXED

本モジュールは外部ライブラリに依存せず、ライブログ（fix_type_logger.py）と
後処理（analyze_fix_log.py）の両方から import して再利用される。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional

# MAVLink GPS_RAW_INT.fix_type と同一の正規化マッピング。
# （archive/rtk_field_test/analyze_status.py の FIX_NAMES と同値。独立定義しつつ値は一致させる）
FIX_NAMES = {
    0: "NO_FIX",
    1: "NO_FIX",
    2: "2D_FIX",
    3: "3D_FIX",
    4: "DGPS",
    5: "RTK_FLOAT",
    6: "RTK_FIXED",
}

FIXED = 6
FLOAT = 5


def _num(v: Any, default: Optional[float] = None) -> Optional[float]:
    """文字列/None を float に変換（失敗時は default）。"""
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _int(v: Any, default: int = 0) -> int:
    f = _num(v)
    return int(f) if f is not None else default


def fix_name(fix_type: int) -> str:
    return FIX_NAMES.get(fix_type, "UNKNOWN(%s)" % fix_type)


def ubx_to_fix_type(fix_type: int, carr_soln: int, diff_soln: Optional[int] = None) -> int:
    """UBX-NAV-PVT の fixType / carrSoln / diffSoln を正規化 fix_type（0..6）へ変換する。

    UBX-NAV-PVT の定義:
      - fixType: 0=no fix, 1=dead reckoning, 2=2D, 3=3D, 4=GNSS+DR, 5=time only
      - flags.carrSoln: 0=no carrier phase, 1=float, 2=fixed
      - flags.diffSoln: 0=no differential, 1=differential applied

    RTK の真偽は carrSoln が最も直接的なので優先する。
    """
    try:
        carr_soln = int(carr_soln)
    except (TypeError, ValueError):
        carr_soln = 0
    try:
        fix_type = int(fix_type)
    except (TypeError, ValueError):
        fix_type = 0

    if carr_soln == 2:
        return FIXED            # RTK_FIXED
    if carr_soln == 1:
        return FLOAT            # RTK_FLOAT
    if fix_type >= 3:
        return 3                # 3D_FIX
    if fix_type == 2:
        return 2                # 2D_FIX
    return 0                    # NO_FIX


def _sample_t(row: Dict[str, Any], index: int) -> Optional[float]:
    """行から elapsed 秒を取得（t / elapsed_sec / index にフォールバック）。"""
    for key in ("t", "elapsed_sec", "elapsed"):
        v = _num(row.get(key))
        if v is not None:
            return v
    return float(index)


def iter_transitions(series: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """fix_type の遷移を検出し、一覧（リスト）を返す。

    series の各行は 'fix_type'（int, 0..6）を含むこと。't'（秒）と 'ts'（壁時計文字列）は
    あれば遷移タイムスタンプに利用される。

    返り値の各要素:
        {'t': 遷移時刻(秒 or None), 'ts': 壁時計(文字列 or None),
         'from': 遷移前 fix_type, 'to': 遷移後 fix_type,
         'from_name': ..., 'to_name': ...}
    """
    transitions: List[Dict[str, Any]] = []
    prev: Optional[int] = None
    for i, row in enumerate(series):
        cur = _int(row.get("fix_type"))
        if prev is None:
            prev = cur
            continue
        if cur != prev:
            transitions.append({
                "t": _sample_t(row, i),
                "ts": row.get("ts") or row.get("timestamp") or row.get("utc_time"),
                "from": prev,
                "to": cur,
                "from_name": fix_name(prev),
                "to_name": fix_name(cur),
            })
            prev = cur
    return transitions


def compute_metrics(series: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """fix_type 時系列から定量指標を計算する。

    Args:
        series: 'fix_type' を含む行のイテラブル。't'（elapsed 秒）があれば時間加重、
                なければサンプル数比で集計する。

    Returns:
        dict:
          total_samples / duration_sec / counts_by_fix / duration_by_fix
          transitions / transition_count / float_transition_count
          fixed_to_float_count / fixed_samples / fixed_rate_pct
          fixed_rate_after_first_pct / ttff_sec / first_fixed_t
          first_fixed_ts / reached_fixed
    """
    rows = list(series)
    n = len(rows)
    if n == 0:
        return {
            "total_samples": 0, "duration_sec": 0.0, "counts_by_fix": {},
            "duration_by_fix": {}, "transitions": [], "transition_count": 0,
            "float_transition_count": 0, "fixed_to_float_count": 0,
            "fixed_samples": 0, "fixed_rate_pct": 0.0,
            "fixed_rate_after_first_pct": 0.0, "ttff_sec": None,
            "first_fixed_t": None, "first_fixed_ts": None, "reached_fixed": False,
        }

    ts = [_sample_t(r, i) for i, r in enumerate(rows)]
    fixes = [_int(r.get("fix_type")) for r in rows]

    counts_by_fix: Dict[int, int] = defaultdict(int)
    for f in fixes:
        counts_by_fix[f] += 1

    transitions = iter_transitions(rows)

    # --- 時間加重（'t' が全行に存在する場合） ---
    has_time = all(t is not None for t in ts)
    duration_sec = 0.0
    duration_by_fix: Dict[int, float] = defaultdict(float)
    if has_time and n >= 2:
        t_min = min(ts)
        t_max = max(ts)
        duration_sec = t_max - t_min
        # 各区間（連続した同一 fix）の継続時間を足し合わせる
        prev_t = ts[0]
        prev_fix = fixes[0]
        for i in range(1, n):
            cur_t = ts[i]
            if fixes[i] == prev_fix:
                continue
            duration_by_fix[prev_fix] += (cur_t - prev_t)
            prev_t = cur_t
            prev_fix = fixes[i]
        duration_by_fix[prev_fix] += (t_max - prev_t)

    fixed_duration = duration_by_fix.get(FIXED, 0.0)
    fixed_rate_pct = (fixed_duration / duration_sec * 100.0) if duration_sec > 0 else 0.0

    # --- FLOAT 遷移回数 ---
    float_transition_count = sum(1 for tr in transitions if tr["to"] == FLOAT)
    fixed_to_float_count = sum(
        1 for tr in transitions if tr["from"] == FIXED and tr["to"] == FLOAT
    )

    # --- TTFF / 初回 FIXED ---
    first_fixed_t: Optional[float] = None
    first_fixed_ts: Optional[str] = None
    for i, r in enumerate(rows):
        if fixes[i] == FIXED:
            first_fixed_t = ts[i]
            first_fixed_ts = r.get("ts") or r.get("timestamp") or r.get("utc_time")
            break

    ttff_sec: Optional[float] = None
    if first_fixed_t is not None and has_time:
        ttff_sec = first_fixed_t - min(ts)
    elif first_fixed_t is not None:
        ttff_sec = first_fixed_t

    # 初回 FIXED 以降の維持率（安定度）
    fixed_rate_after_first_pct = 0.0
    if first_fixed_t is not None and has_time:
        t_max = max(ts)
        after_duration = t_max - first_fixed_t
        if after_duration > 0:
            after_fixed_duration = 0.0
            prev_t = None
            for i in range(n):
                t = ts[i]
                if t is None or t < first_fixed_t:
                    continue
                if prev_t is not None and fixes[i - 1] == FIXED:
                    after_fixed_duration += (t - prev_t)
                prev_t = t
            fixed_rate_after_first_pct = (after_fixed_duration / after_duration * 100.0)

    return {
        "total_samples": n,
        "duration_sec": duration_sec,
        "counts_by_fix": dict(counts_by_fix),
        "duration_by_fix": dict(duration_by_fix),
        "transitions": transitions,
        "transition_count": len(transitions),
        "float_transition_count": float_transition_count,
        "fixed_to_float_count": fixed_to_float_count,
        "fixed_samples": counts_by_fix.get(FIXED, 0),
        "fixed_rate_pct": fixed_rate_pct,
        "fixed_rate_after_first_pct": fixed_rate_after_first_pct,
        "ttff_sec": ttff_sec,
        "first_fixed_t": first_fixed_t,
        "first_fixed_ts": first_fixed_ts,
        "reached_fixed": first_fixed_t is not None,
    }


def format_metrics(m: Dict[str, Any]) -> str:
    """集計結果を人間可読な文字列に整形する（ライブログ・後処理で共用）。"""
    lines: List[str] = []
    lines.append("=" * 60)
    lines.append("RTK FIXED 定量指標")
    lines.append("=" * 60)
    lines.append("サンプル数     : %d" % m["total_samples"])
    lines.append("記録時間       : %.1f 秒" % m["duration_sec"])

    dur_by_fix = m.get("duration_by_fix", {})
    if dur_by_fix:
        lines.append("--- FIX 別 継続時間 ---")
        for f in sorted(dur_by_fix):
            d = dur_by_fix[f]
            lines.append("  %-10s: %8.1f 秒" % (fix_name(f), d))

    lines.append("--- RTK FIXED 定量判定 ---")
    if m["reached_fixed"]:
        lines.append("  ✅ RTK_FIXED 到達")
        lines.append("  TTFF（初回FIXED） : %.1f 秒" % (m["ttff_sec"] or 0.0))
        lines.append("  FIXED 維持率      : %.1f %% (全期間)" % m["fixed_rate_pct"])
        lines.append("  FIXED 維持率      : %.1f %% (初回FIXED以降)" % m["fixed_rate_after_first_pct"])
    else:
        lines.append("  ❌ RTK_FIXED 未到達")
        lines.append("  TTFF              : n/a")

    lines.append("  FLOAT 遷移回数    : %d 回" % m["float_transition_count"])
    lines.append("  FIXED→FLOAT 脱落  : %d 回" % m["fixed_to_float_count"])
    lines.append("  総遷移回数        : %d 回" % m["transition_count"])

    lines.append("--- 遷移タイムスタンプ一覧 ---")
    if m["transitions"]:
        for tr in m["transitions"]:
            t = "t=%s" % (("%.1f" % tr["t"]) if tr.get("t") is not None else "?")
            ts = tr.get("ts") or ""
            lines.append("  %-8s %s  %s → %s" % (
                t, ts, tr["from_name"], tr["to_name"]))
    else:
        lines.append("  （遷移なし）")
    lines.append("=" * 60)
    return "\n".join(lines)


def self_test() -> bool:
    """合成時系列で compute_metrics の期待値を検証する。"""
    series = [
        {"t": 0.0, "fix_type": 5},    # FLOAT
        {"t": 5.0, "fix_type": 5},
        {"t": 10.0, "fix_type": 6},   # → FIXED
        {"t": 15.0, "fix_type": 6},
        {"t": 20.0, "fix_type": 5},   # → FLOAT（脱落）
        {"t": 25.0, "fix_type": 6},   # → FIXED
        {"t": 30.0, "fix_type": 6},
    ]
    m = compute_metrics(series)
    checks = [
        ("total_samples == 7", m["total_samples"] == 7),
        ("duration_sec == 30", abs(m["duration_sec"] - 30.0) < 1e-9),
        ("ttff == 10", m["ttff_sec"] is not None and abs(m["ttff_sec"] - 10.0) < 1e-9),
        ("reached_fixed", m["reached_fixed"]),
        ("float_transition_count == 1", m["float_transition_count"] == 1),
        ("fixed_to_float_count == 1", m["fixed_to_float_count"] == 1),
        ("transition_count == 3", m["transition_count"] == 3),
        ("fixed_rate_pct == 50", abs(m["fixed_rate_pct"] - 50.0) < 1e-9),
    ]
    ok = True
    for name, passed in checks:
        if not passed:
            ok = False
            print("[FAIL] %s" % name)
    return ok


if __name__ == "__main__":
    if self_test():
        print("fix_metrics self-test: OK")
    else:
        print("fix_metrics self-test: FAILED")
        raise SystemExit(1)




