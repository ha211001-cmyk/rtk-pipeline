#!/usr/bin/env python3
"""test_fix_metrics.py — fix_metrics の単体テスト（ハードウェア不要）。

実行:
    python3 -m unittest gcs.test_fix_metrics
    # または
    python3 gcs/test_fix_metrics.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fix_metrics import (  # noqa: E402
    FIXED,
    FLOAT,
    compute_metrics,
    fix_name,
    iter_transitions,
    ubx_to_fix_type,
)


class TestUbxMapping(unittest.TestCase):
    def test_carr_soln_fixed(self):
        self.assertEqual(ubx_to_fix_type(fix_type=3, carr_soln=2, diff_soln=1), FIXED)

    def test_carr_soln_float(self):
        self.assertEqual(ubx_to_fix_type(fix_type=3, carr_soln=1, diff_soln=1), FLOAT)

    def test_no_carrier_3d(self):
        self.assertEqual(ubx_to_fix_type(fix_type=3, carr_soln=0, diff_soln=1), 3)

    def test_no_carrier_2d(self):
        self.assertEqual(ubx_to_fix_type(fix_type=2, carr_soln=0, diff_soln=0), 2)

    def test_no_fix(self):
        self.assertEqual(ubx_to_fix_type(fix_type=0, carr_soln=0, diff_soln=0), 0)

    def test_bad_input(self):
        self.assertEqual(ubx_to_fix_type(None, None), 0)


class TestMetrics(unittest.TestCase):
    def _series(self):
        return [
            {"t": 0.0, "fix_type": 5},
            {"t": 5.0, "fix_type": 5},
            {"t": 10.0, "fix_type": 6},
            {"t": 15.0, "fix_type": 6},
            {"t": 20.0, "fix_type": 5},
            {"t": 25.0, "fix_type": 6},
            {"t": 30.0, "fix_type": 6},
        ]

    def test_basic(self):
        m = compute_metrics(self._series())
        self.assertEqual(m["total_samples"], 7)
        self.assertAlmostEqual(m["duration_sec"], 30.0)
        self.assertTrue(m["reached_fixed"])
        self.assertAlmostEqual(m["ttff_sec"], 10.0)
        self.assertAlmostEqual(m["fixed_rate_pct"], 50.0)
        self.assertEqual(m["float_transition_count"], 1)
        self.assertEqual(m["fixed_to_float_count"], 1)
        self.assertEqual(m["transition_count"], 3)
        self.assertEqual(m["fixed_samples"], 4)

    def test_transitions(self):
        trs = iter_transitions(self._series())
        self.assertEqual(len(trs), 3)
        self.assertEqual(trs[0]["from"], FLOAT)
        self.assertEqual(trs[0]["to"], FIXED)
        self.assertEqual(trs[1]["from"], FIXED)
        self.assertEqual(trs[1]["to"], FLOAT)

    def test_never_fixed(self):
        series = [{"t": 0.0, "fix_type": 5}, {"t": 10.0, "fix_type": 5}]
        m = compute_metrics(series)
        self.assertFalse(m["reached_fixed"])
        self.assertIsNone(m["ttff_sec"])
        self.assertEqual(m["fixed_rate_pct"], 0.0)

    def test_empty(self):
        m = compute_metrics([])
        self.assertEqual(m["total_samples"], 0)
        self.assertFalse(m["reached_fixed"])

    def test_string_fix_type(self):
        # rover_recorder CSV 等、文字列 fix_type を許容する
        series = [
            {"t": 0.0, "fix_type": "5"},
            {"t": 10.0, "fix_type": "6"},
        ]
        m = compute_metrics(series)
        self.assertTrue(m["reached_fixed"])
        self.assertAlmostEqual(m["ttff_sec"], 10.0)

    def test_fix_name(self):
        self.assertEqual(fix_name(6), "RTK_FIXED")
        self.assertEqual(fix_name(5), "RTK_FLOAT")
        self.assertEqual(fix_name(99), "UNKNOWN(99)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
