#!/usr/bin/env python3
"""test_metrics.py — gcs/flight_test/metrics.py のユニットテスト（実機不要）。

実行:
    cd <リポジトリルート>
    python3 -m unittest gcs.flight_test.test_metrics -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.flight_test.metrics import (  # noqa: E402
    STATUS_PASS,
    STATUS_FAIL,
    FlightSpec,
    compute_ekf_consistency,
    detect_degradations,
    classify_failsafe_text,
    confirm_failsafe,
    next_phase_issues,
)
from gcs.flight_test.runner import evaluate_flight  # noqa: E402

_EKF_HEALTHY = 0x001 | 0x002 | 0x004 | 0x010 | 0x020  # 姿勢+速度+位置 健全


def _row(t, ft, flags=_EKF_HEALTHY, hdop=0.8, horiz=0.02, vert=0.04):
    return {
        "t": float(t), "ts": "",
        "fix_type": ft,
        "hdop": hdop, "vdop": 1.2, "sats": 22,
        "ekf_flags": flags,
        "ekf_pos_horiz_m": horiz, "ekf_pos_vert_m": vert,
        "ekf_vel_var": 0.01,
    }


def _series(fix_types, flags=None):
    return [_row(i, ft, _EKF_HEALTHY if flags is None else flags)
            for i, ft in enumerate(fix_types)]


class TestClassifyFailsafeText(unittest.TestCase):
    def test_gps(self):
        self.assertEqual(classify_failsafe_text("GPS glitch detected"), "gps")

    def test_ekf(self):
        self.assertEqual(classify_failsafe_text("EKF variance"), "ekf")

    def test_gcs(self):
        self.assertEqual(classify_failsafe_text("GCS failsafe"), "gcs")

    def test_none(self):
        self.assertIsNone(classify_failsafe_text("Battery low"))


class TestComputeEkfConsistency(unittest.TestCase):
    def test_consistency(self):
        ekf = compute_ekf_consistency(_series([6, 6, 6, 6]))
        self.assertEqual(ekf["fixed_samples"], 4)
        self.assertEqual(ekf["fixed_ekf_consistency_pct"], 100.0)
        self.assertTrue(ekf["has_accuracy"])

    def test_no_ekf_flags(self):
        series = [{"t": 0.0, "fix_type": 6, "hdop": 0.8}]
        ekf = compute_ekf_consistency(series)
        self.assertFalse(ekf["has_ekf_flags"])
        self.assertIsNone(ekf["fixed_ekf_consistency_pct"])


class TestDetectDegradations(unittest.TestCase):
    def test_rtk_loss(self):
        d = detect_degradations(_series([6, 6, 3, 3]))
        self.assertEqual(d["rtk_loss_count"], 1)
        self.assertEqual(d["severe_count"], 0)

    def test_gps_loss_is_severe(self):
        d = detect_degradations(_series([6, 0, 6]))
        self.assertEqual(d["gps_loss_count"], 1)
        self.assertEqual(d["severe_count"], 1)

    def test_ekf_unhealthy_is_severe(self):
        series = [_row(0, 6, _EKF_HEALTHY), _row(1, 6, 0x000)]
        d = detect_degradations(series)
        self.assertEqual(d["ekf_unhealthy_count"], 1)
        self.assertEqual(d["severe_count"], 1)

    def test_hdop_high(self):
        series = [_row(0, 6, hdop=0.8), _row(1, 6, hdop=3.0)]
        d = detect_degradations(series, FlightSpec(hdop_max_m=1.4))
        self.assertEqual(d["hdop_high_count"], 1)

class TestConfirmFailsafe(unittest.TestCase):
    def test_no_severe_passes(self):
        r = confirm_failsafe(_series([5, 6, 6]), failsafe_ok=True)
        self.assertTrue(r["ok"])
        self.assertEqual(r["severe_count"], 0)
        self.assertIn("failsafe_not_needed", [c["name"] for c in r["checks"]])

    def test_failsafe_golden_off_fails(self):
        r = confirm_failsafe(_series([5, 6, 6]), failsafe_ok=False)
        self.assertFalse(r["ok"])

    def test_severe_without_evidence_fails(self):
        r = confirm_failsafe(_series([6, 0, 6]), failsafe_ok=True)
        self.assertFalse(r["ok"])

    def test_severe_with_evidence_passes(self):
        ev = [{"t": 1.0, "ts": "", "kind": "gps", "text": "GPS glitch"}]
        r = confirm_failsafe(_series([6, 0, 6]), failsafe_ok=True,
                             failsafe_events=ev)
        self.assertTrue(r["ok"])
        self.assertTrue(r["fs_triggered"])

    def test_evidence_not_required(self):
        spec = FlightSpec(require_failsafe_evidence=False)
        r = confirm_failsafe(_series([6, 0, 6]), failsafe_ok=True, spec=spec)
        self.assertTrue(r["ok"])


class TestNextPhaseIssues(unittest.TestCase):
    def test_clean_flight(self):
        rep = evaluate_flight(_series([5, 6, 6, 6]), failsafe_ok=True)
        self.assertTrue(any(i["category"] == "検討項目" for i in rep.issues))
        self.assertFalse(any(i["severity"] == "high" for i in rep.issues))

    def test_fixed_not_maintained_raises_issue(self):
        series = _series([5, 6, 5, 5, 6])
        rtk = {"reached_fixed": True, "fixed_rate_after_first_pct": 50.0,
               "float_transition_count": 2, "fixed_to_float_count": 1}
        ekf = {"fixed_ekf_consistency_pct": 100.0, "fixed_horiz_err_max_m": 0.02}
        degrad = {"events": [], "severe_count": 0}
        failsafe = {"ok": True, "severe_count": 0, "summary": ""}
        issues = next_phase_issues(series, rtk, ekf, degrad, failsafe,
                                   FlightSpec())
        self.assertTrue(any("維持率" in i["title"] for i in issues))


class TestEvaluateFlight(unittest.TestCase):
    def test_clean_pass(self):
        rep = evaluate_flight(_series([5, 6, 6, 6]), failsafe_ok=True)
        self.assertEqual(rep.overall(), STATUS_PASS)

    def test_never_fixed_fail(self):
        rep = evaluate_flight(_series([5, 5, 5]), failsafe_ok=True)
        self.assertEqual(rep.overall(), STATUS_FAIL)

    def test_degradation_fail(self):
        rep = evaluate_flight(_series([6, 6, 0, 6]), failsafe_ok=True)
        self.assertEqual(rep.overall(), STATUS_FAIL)

    def test_report_markdown(self):
        rep = evaluate_flight(_series([5, 6, 6]), failsafe_ok=True)
        md = rep.format_markdown()
        self.assertIn("次フェーズへの課題整理", md)
        self.assertIn("総合判定", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)

