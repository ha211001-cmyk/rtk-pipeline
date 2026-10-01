#!/usr/bin/env python3
"""test_pairing.py — gcs.relpos.pairing のユニットテスト（ハードウェア不要）

実行:
    cd ~/EVK-F9P
    python3 -m unittest gcs.relpos.test_pairing -v
    # または
    python3 gcs/relpos/test_pairing.py
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent.parent
for _p in (_SCRIPT_DIR, _REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from gcs.relpos.pairing import (  # noqa: E402
    ITOW_PER_WEEK_MS,
    PAIRED_CSV_FIELDS,
    RelposPairingBuffer,
    compute_relative,
    itow_diff_ms,
    normalize_bearing_deg,
    propagate_accuracy,
    signed_heading_delta_deg,
)


def _mk(rover_id: str, itow: int, n: float, e: float, d: float,
        ref_station: int = 0, acc: float = 0.01) -> object:
    from gcs.relpos.pairing import RelposnedSample
    length = math.sqrt(n * n + e * e + d * d)
    return RelposnedSample(
        rover_id=rover_id, itow_ms=itow, ref_station_id=ref_station,
        rel_n_m=n, rel_e_m=e, rel_d_m=d, rel_length_m=length,
        rel_heading_deg=45.0,
        acc_n_m=acc, acc_e_m=acc, acc_d_m=acc, acc_length_m=acc,
        acc_heading_deg=0.001,
        flags={"rel_pos_valid": True, "rel_pos_heading_valid": True,
               "gnss_fix_ok": True, "diff_soln": True, "carr_soln": 2},
        wall_ts=0.0,
    )


class TestItowDiff(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(itow_diff_ms(1000, 1200), 200)
        self.assertEqual(itow_diff_ms(1200, 1000), -200)

    def test_rollover_positive(self):
        # A=604799990, B=10 → 20ms 進んでいる
        self.assertEqual(itow_diff_ms(604799990, 10), 20)

    def test_rollover_negative(self):
        self.assertEqual(itow_diff_ms(10, 604799990), -20)

    def test_half_week_boundary(self):
        # ちょうど半週は符号の曖昧性があるが、正側へ折り畳まれる
        self.assertEqual(itow_diff_ms(0, ITOW_PER_WEEK_MS // 2),
                         ITOW_PER_WEEK_MS // 2)


class TestBearing(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_bearing_deg(0.0), 0.0)
        self.assertEqual(normalize_bearing_deg(360.0), 0.0)
        self.assertEqual(normalize_bearing_deg(-90.0), 270.0)

    def test_signed_delta(self):
        self.assertAlmostEqual(signed_heading_delta_deg(350.0, 10.0), 20.0)
        self.assertAlmostEqual(signed_heading_delta_deg(10.0, 350.0), -20.0)


class TestPropagateAccuracy(unittest.TestCase):
    def test_propagate(self):
        self.assertAlmostEqual(propagate_accuracy(0.03, 0.04), 0.05, places=12)


class TestComputeRelative(unittest.TestCase):
    def test_difference_b_minus_a(self):
        a = _mk("A", 1000, n=1.0, e=0.0, d=0.5)
        b = _mk("B", 1000, n=4.0, e=3.0, d=1.5)
        p = compute_relative(a, b, delta_ms=0, matched=True)
        self.assertAlmostEqual(p.rel_n_m, 3.0)
        self.assertAlmostEqual(p.rel_e_m, 3.0)
        self.assertAlmostEqual(p.rel_d_m, 1.0)
        self.assertAlmostEqual(p.distance_3d_m, math.sqrt(3 ** 2 + 3 ** 2 + 1.0))
        self.assertAlmostEqual(p.bearing_ab_deg, 45.0, places=6)

    def test_ref_station_mismatch(self):
        a = _mk("A", 1000, n=0.0, e=0.0, d=0.0, ref_station=7)
        b = _mk("B", 1000, n=1.0, e=0.0, d=0.0, ref_station=8)
        p = compute_relative(a, b, delta_ms=0, matched=True)
        self.assertFalse(p.ref_station_match)

    def test_csv_row(self):
        a = _mk("A", 1000, n=0.0, e=0.0, d=0.0)
        b = _mk("B", 1000, n=1.0, e=2.0, d=0.0)
        p = compute_relative(a, b, delta_ms=0, matched=True)
        row = p.to_csv_row(PAIRED_CSV_FIELDS)
        self.assertEqual(row["matched"], "1")
        self.assertIn("itow_ms", row)


class TestPairingBuffer(unittest.TestCase):
    def test_pair_on_match(self):
        buf = RelposPairingBuffer(rover_ids=("A", "B"), match_window_ms=200)
        self.assertIsNone(buf.update(_mk("A", 1000, n=0, e=0, d=0)))
        p = buf.update(_mk("B", 1000, n=3, e=4, d=0))
        self.assertIsNotNone(p)
        self.assertTrue(p.matched)

    def test_mismatch_flagged(self):
        buf = RelposPairingBuffer(rover_ids=("A", "B"), match_window_ms=50)
        buf.update(_mk("A", 1000, n=0, e=0, d=0))
        p = buf.update(_mk("B", 1200, n=3, e=4, d=0))
        self.assertIsNotNone(p)
        self.assertFalse(p.matched)
        self.assertEqual(p.delta_ms, 200)

    def test_rollover_pairing(self):
        buf = RelposPairingBuffer(rover_ids=("A", "B"), match_window_ms=50)
        buf.update(_mk("A", ITOW_PER_WEEK_MS - 10, n=0, e=0, d=0))
        p = buf.update(_mk("B", 10, n=3, e=4, d=0))
        self.assertIsNotNone(p)
        self.assertTrue(p.matched)
        self.assertEqual(p.delta_ms, 20)

    def test_history_best_match(self):
        # B が少し先行して受信 → 履歴から最良の iTOW を選ぶ
        buf = RelposPairingBuffer(rover_ids=("A", "B"), match_window_ms=30)
        buf.update(_mk("B", 1005, n=3, e=4, d=0))
        p = buf.update(_mk("A", 1000, n=0, e=0, d=0))
        self.assertIsNotNone(p)
        self.assertTrue(p.matched)
        self.assertEqual(p.delta_ms, 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
