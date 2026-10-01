#!/usr/bin/env python3
"""test_baseline.py — gcs.accuracy のユニットテスト（実ハードウェア不要）

実行:
    cd <リポジトリルート>
    python3 -m unittest gcs.accuracy.test_baseline -v
    # または
    python3 gcs/accuracy/test_baseline.py
"""

from __future__ import annotations

import math
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT,):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from gcs.accuracy.baseline import (  # noqa: E402
    STATUS_PASS,
    STATUS_FAIL,
    AccuracySpec,
    compute_baseline_stats,
    compute_error_stats,
    compare_to_reference,
    align_series,
    crosscheck_baseline,
    evaluate_known_distance,
    evaluate_crosscheck,
)
from gcs.accuracy.loader import (  # noqa: E402
    load_relpos_csv,
    load_measurements,
    load_ppk_baseline_csv,
    baseline_from_positions,
    baseline_from_position_files,
    parse_utc_epoch,
)
from gcs.accuracy.report import AccuracyReport  # noqa: E402


class TestParseUtc(unittest.TestCase):
    def test_z_suffix(self):
        self.assertIsNotNone(parse_utc_epoch("2026-09-27T10:00:00.123Z"))

    def test_invalid(self):
        self.assertIsNone(parse_utc_epoch("not-a-time"))
        self.assertIsNone(parse_utc_epoch(""))


class TestBaselineStats(unittest.TestCase):
    def test_stats(self):
        s = compute_baseline_stats([1.0, 2.0, 3.0, 4.0])
        self.assertEqual(s.n, 4)
        self.assertAlmostEqual(s.mean_m, 2.5)
        self.assertAlmostEqual(s.min_m, 1.0)
        self.assertAlmostEqual(s.max_m, 4.0)
        self.assertAlmostEqual(s.span_m, 3.0)
        self.assertAlmostEqual(s.median_m, 2.5)

    def test_empty(self):
        self.assertEqual(compute_baseline_stats([]).n, 0)


class TestErrorStats(unittest.TestCase):
    def test_rmse_and_pass(self):
        e = compute_error_stats([0.0, 0.1], tolerance_m=0.1)
        self.assertAlmostEqual(e.rmse_m, math.sqrt(0.01 / 2.0), places=12)
        self.assertEqual(e.pass_count, 2)
        self.assertAlmostEqual(e.pass_rate_pct, 100.0)

    def test_compare_reference_bias(self):
        e = compare_to_reference(1.0, [1.0, 1.02, 0.98], tolerance_m=0.05)
        self.assertAlmostEqual(e.mean_error_m, 0.0, places=12)
        self.assertAlmostEqual(e.max_abs_m, 0.02)


class TestAlignSeries(unittest.TestCase):
    def test_nearest_within_tolerance(self):
        a_t = [10.0, 11.0, 12.0]
        a_v = [1.0, 2.0, 3.0]
        b_t = [10.2, 11.2, 12.2]
        b_v = [100.0, 200.0, 300.0]
        ra, rb, deltas = align_series(a_t, a_v, b_t, b_v, tolerance_s=1.0)
        self.assertEqual(ra, [1.0, 2.0, 3.0])
        self.assertEqual(rb, [100.0, 200.0, 300.0])
        self.assertTrue(all(d <= 0.2 for d in deltas))

    def test_tolerance_excludes(self):
        ra, _, _ = align_series([10.0], [1.0], [20.0], [9.0], tolerance_s=1.0)
        self.assertEqual(ra, [])


class TestCrosscheck(unittest.TestCase):
    def test_crosscheck(self):
        e = crosscheck_baseline([1.0, 1.0], [1.01, 1.02])
        self.assertAlmostEqual(e.mean_error_m, 0.015)


class TestEvaluate(unittest.TestCase):
    def test_known_distance_pass(self):
        err = compare_to_reference(1.0, [1.0, 1.01, 0.99], 0.1)
        r = evaluate_known_distance(err, AccuracySpec(), reference_m=1.0)
        self.assertEqual(r["status"], STATUS_PASS)

    def test_known_distance_fail(self):
        err = compare_to_reference(1.0, [1.5, 1.6], 0.1)
        r = evaluate_known_distance(err, AccuracySpec(), reference_m=1.0)
        self.assertEqual(r["status"], STATUS_FAIL)

    def test_crosscheck_pass(self):
        err = crosscheck_baseline([1.0, 1.0], [1.005, 1.006])
        r = evaluate_crosscheck(err, AccuracySpec())
        self.assertEqual(r["status"], STATUS_PASS)


class TestLoader(unittest.TestCase):
    def test_load_relpos_csv_filters(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "rel.csv"
            p.write_text(
                "utc_time,itow_ms,matched,valid,distance_2d_m,distance_3d_m,acc_3d_m\n"
                "2026-09-27T10:00:00.000Z,1000,1,1,1.0,1.0,0.01\n"
                "2026-09-27T10:00:01.000Z,2000,0,1,2.0,2.0,0.01\n"
                "2026-09-27T10:00:02.000Z,3000,1,0,3.0,3.0,0.01\n"
                "2026-09-27T10:00:03.000Z,4000,1,1,4.0,4.0,0.01\n",
                encoding="utf-8")
            r = load_relpos_csv(str(p))
            self.assertEqual(r.total_rows, 4)
            self.assertEqual(r.n(), 2)  # matched=0 と valid=0 を除外
            self.assertEqual(r.dist3d_m, [1.0, 4.0])

    def test_load_ppk_baseline_csv(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "ppk.csv"
            p.write_text("utc_time,baseline_length_m\n"
                         "2026-09-27T10:00:00.000Z,1.001\n"
                         "2026-09-27T10:00:01.000Z,1.002\n", encoding="utf-8")
            ppk = load_ppk_baseline_csv(str(p))
            self.assertEqual(ppk.n(), 2)
            self.assertAlmostEqual(ppk.baseline_m[0], 1.001)

    def test_load_measurements_single(self):
        m = load_measurements(distance_m=2.5)
        self.assertEqual(len(m), 1)
        self.assertAlmostEqual(m[0].distance_m, 2.5)

    def test_baseline_from_positions(self):
        d = baseline_from_positions(36.0, 136.0, 100.0, 36.00001, 136.0, 100.0)
        self.assertGreater(d, 1.0)
        self.assertLess(d, 1.2)

    def test_baseline_from_position_files(self):
        with tempfile.TemporaryDirectory() as d:
            a = Path(d) / "a.csv"
            b = Path(d) / "b.csv"
            a.write_text("utc_time,lat_deg,lon_deg,alt_m\n"
                         "2026-09-27T10:00:00.000Z,36.0,136.0,100.0\n",
                         encoding="utf-8")
            b.write_text("utc_time,lat_deg,lon_deg,alt_m\n"
                         "2026-09-27T10:00:00.000Z,36.00001,136.0,100.0\n",
                         encoding="utf-8")
            ppk = baseline_from_position_files(str(a), str(b))
            self.assertEqual(ppk.n(), 1)
            self.assertGreater(ppk.baseline_m[0], 1.0)


class TestReport(unittest.TestCase):
    def test_json_roundtrip(self):
        rep = AccuracyReport(sections=[{"name": "x", "status": STATUS_PASS,
                                        "summary": "", "checks": [], "details": {}}])
        d = rep.to_dict()
        self.assertEqual(d["overall"]["status"], STATUS_PASS)
        self.assertEqual(d["title"], "Phase 2.5 機体間相対測位精度 実測レポート")

    def test_text(self):
        rep = AccuracyReport(sections=[{"name": "x", "status": STATUS_PASS,
                                        "summary": "s", "checks": [], "details": {}}])
        self.assertIn("総合判定: PASS", rep.format_text())


class TestRunnerEndToEnd(unittest.TestCase):
    def test_pass_and_fail(self):
        from gcs.accuracy.runner import run, _write_synthetic_relpos, _write_synthetic_ppk
        import random
        random.seed(0)
        with tempfile.TemporaryDirectory() as d:
            rel = Path(d) / "relpos.csv"
            ppk = Path(d) / "ppk.csv"
            _write_synthetic_relpos(rel)
            _write_synthetic_ppk(ppk)
            ok = run(str(rel), distance=1.000, ppk_baseline_csv=str(ppk))
            ng = run(str(rel), distance=10.0, ppk_baseline_csv=str(ppk))
        self.assertEqual(ok.overall(), STATUS_PASS)
        self.assertEqual(ng.overall(), STATUS_FAIL)


if __name__ == "__main__":
    unittest.main(verbosity=2)
