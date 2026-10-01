#!/usr/bin/env python3
"""test_checklist.py — 飛行前セルフテストの Item 判定ロジックのユニットテスト（実機不要）。

実行:
    cd <リポジトリルート>
    python3 -m unittest gcs.preflight.test_checklist -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.fix_metrics import compute_metrics  # noqa: E402
from gcs.rtcm_monitor import CorrectionMonitor  # noqa: E402
from gcs.integration import sources  # noqa: E402

from gcs.preflight.checklist import (  # noqa: E402
    STATUS_PASS, STATUS_FAIL,
    GO, NO_GO,
    ITEM1, ITEM2, ITEM3, BASE_RATE,
    PreflightReport,
    evaluate_item1, evaluate_item2, evaluate_item3, evaluate_base_rate,
)


class TestItem2Evaluation(unittest.TestCase):
    def test_pass(self):
        r = evaluate_item2({"status": "PASS", "summary": "OK",
                            "checked": {"CFG_NAVHPG_DGNSSMODE":
                                        {"key_display": "CFG-NAVHPG-DGNSSMODE",
                                         "expected": 3, "actual": 3, "ok": True}}})
        self.assertEqual(r.item_id, ITEM2)
        self.assertEqual(r.status, STATUS_PASS)
        self.assertTrue(r.is_pass())

    def test_fixed_counts_as_pass(self):
        r = evaluate_item2({"status": "FIXED", "summary": "fixed", "checked": {}})
        self.assertEqual(r.status, STATUS_PASS)

    def test_fail(self):
        r = evaluate_item2({"status": "FAIL", "summary": "ng", "checked": {}})
        self.assertEqual(r.status, STATUS_FAIL)


class TestItem1Evaluation(unittest.TestCase):
    CRITERIA = {"fixed_rate_pct_min": 80.0, "max_float_transitions": 5,
                "ttff_sec_max": 120.0}

    def test_pass(self):
        series = [{"t": 0.0, "fix_type": 5}, {"t": 1.0, "fix_type": 6},
                  {"t": 10.0, "fix_type": 6}]
        r = evaluate_item1(compute_metrics(series), self.CRITERIA)
        self.assertEqual(r.item_id, ITEM1)
        self.assertEqual(r.status, STATUS_PASS)

    def test_fail_not_reached(self):
        m = compute_metrics([{"t": 0.0, "fix_type": 5}, {"t": 10.0, "fix_type": 5}])
        r = evaluate_item1(m, self.CRITERIA)
        self.assertEqual(r.status, STATUS_FAIL)


class TestItem3Evaluation(unittest.TestCase):
    CRITERIA = {"crc_alert_rate_pct": 5.0, "used_alert_ratio_pct": 50.0}

    def test_pass_healthy(self):
        mon = CorrectionMonitor()
        mon.feed_ubx(sources.make_ubx_rxm_rtcm())
        mon.feed_rtcm3(sources.make_rtcm3_frame())
        r = evaluate_item3(mon.snapshot(), self.CRITERIA)
        self.assertEqual(r.item_id, ITEM3)
        self.assertEqual(r.status, STATUS_PASS)

    def test_fail_no_data(self):
        mon = CorrectionMonitor()
        r = evaluate_item3(mon.snapshot(), self.CRITERIA)
        self.assertEqual(r.status, STATUS_FAIL)


class TestBaseRateEvaluation(unittest.TestCase):
    CRITERIA = {"base_rate_min_fps": 1.0}

    def test_pass(self):
        mon = CorrectionMonitor()
        for _ in range(10):
            mon.feed_ubx(sources.make_ubx_rxm_rtcm())
        r = evaluate_base_rate(mon.snapshot(), 5.0, self.CRITERIA)
        self.assertEqual(r.item_id, BASE_RATE)
        self.assertEqual(r.status, STATUS_PASS)
        self.assertAlmostEqual(r.details["rate_fps"], 2.0, places=4)

    def test_fail_no_msgs(self):
        mon = CorrectionMonitor()
        r = evaluate_base_rate(mon.snapshot(), 5.0, self.CRITERIA)
        self.assertEqual(r.status, STATUS_FAIL)


class TestPreflightReport(unittest.TestCase):
    def _make_report(self):
        item2 = evaluate_item2({"status": "PASS", "summary": "ok", "checked": {}})
        m = compute_metrics([{"t": 0.0, "fix_type": 6}, {"t": 10.0, "fix_type": 6}])
        item1 = evaluate_item1(m, {"fixed_rate_pct_min": 80.0, "max_float_transitions": 5,
                                   "ttff_sec_max": 120.0})
        mon = CorrectionMonitor()
        for _ in range(10):
            mon.feed_ubx(sources.make_ubx_rxm_rtcm())
        item3 = evaluate_item3(mon.snapshot(), {"crc_alert_rate_pct": 5.0,
                                                "used_alert_ratio_pct": 50.0})
        base = evaluate_base_rate(mon.snapshot(), 5.0, {"base_rate_min_fps": 1.0})
        return PreflightReport([item2, item1, item3, base],
                               connection={"host": "192.168.1.100", "port": 5001})

    def test_overall_pass_and_verdict(self):
        rep = self._make_report()
        self.assertEqual(rep.overall_status(), STATUS_PASS)
        self.assertEqual(rep.verdict(), GO)

    def test_to_dict_and_json(self):
        rep = self._make_report()
        d = rep.to_dict()
        self.assertEqual(d["overall"]["status"], STATUS_PASS)
        self.assertEqual(d["overall"]["verdict"], GO)
        self.assertEqual(len(d["items"]), 4)
        json.loads(rep.to_json())

    def test_checklist_format(self):
        rep = self._make_report()
        text = rep.format_checklist()
        self.assertIn("飛行前セルフテスト", text)
        self.assertIn("GO（飛行可）", text)
        self.assertIn("[PASS]", text)

    def test_overall_fail_if_any_fail(self):
        item2 = evaluate_item2({"status": "PASS", "summary": "ok", "checked": {}})
        item1 = evaluate_item1(
            compute_metrics([{"t": 0.0, "fix_type": 5}, {"t": 10.0, "fix_type": 5}]),
            {"fixed_rate_pct_min": 80.0, "max_float_transitions": 5, "ttff_sec_max": 120.0})
        rep = PreflightReport([item2, item1])
        self.assertEqual(rep.overall_status(), STATUS_FAIL)
        self.assertEqual(rep.verdict(), NO_GO)


if __name__ == "__main__":
    unittest.main(verbosity=2)
