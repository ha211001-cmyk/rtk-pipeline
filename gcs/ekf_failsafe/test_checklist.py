#!/usr/bin/env python3
"""test_checklist.py — checklist.py のユニットテスト（実機不要）。

実行:
    cd <リポジトリルート>
    python3 -m unittest gcs.ekf_failsafe.test_checklist -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.ekf_failsafe.golden import synthetic_guard_result  # noqa: E402
from gcs.ekf_failsafe.checklist import (  # noqa: E402
    ITEM_F9P_GOLDEN,
    ITEM_EKF_SRC,
    ITEM_FAILSAFE,
    ITEM_RTK_LOSS,
    STATUS_PASS,
    STATUS_FAIL,
    GO,
    NO_GO,
    Phase3Report,
    evaluate_f9p_golden,
    evaluate_ekf_sources,
    evaluate_failsafe,
    evaluate_rtk_loss_behavior,
)

_EKF_HEALTHY = 0x001 | 0x002 | 0x004 | 0x010 | 0x020  # 姿勢+速度+位置 健全


def _series(fix_types, flags=_EKF_HEALTHY):
    return [{"t": float(i), "ts": "", "fix_type": ft, "ekf_flags": flags}
            for i, ft in enumerate(fix_types)]


class TestEvaluateF9pGolden(unittest.TestCase):
    def test_remaps_item_id(self):
        r = evaluate_f9p_golden({"status": "PASS", "summary": "OK", "checked": {}})
        self.assertEqual(r.item_id, ITEM_F9P_GOLDEN)
        self.assertEqual(r.status, STATUS_PASS)

    def test_fail(self):
        r = evaluate_f9p_golden({"status": "FAIL", "summary": "ng", "checked": {}})
        self.assertEqual(r.status, STATUS_FAIL)


class TestEvaluateEkfSources(unittest.TestCase):
    def test_pass(self):
        r = evaluate_ekf_sources(synthetic_guard_result())
        self.assertEqual(r.item_id, ITEM_EKF_SRC)
        self.assertEqual(r.status, STATUS_PASS)
        self.assertTrue(r.is_pass())

    def test_fail_on_mismatch(self):
        r = evaluate_ekf_sources(
            synthetic_guard_result(mismatches=["EK3_SRC1_POSXY"], status="FAIL"))
        self.assertEqual(r.status, STATUS_FAIL)


class TestEvaluateFailsafe(unittest.TestCase):
    def test_pass(self):
        r = evaluate_failsafe(synthetic_guard_result())
        self.assertEqual(r.item_id, ITEM_FAILSAFE)
        self.assertEqual(r.status, STATUS_PASS)
        self.assertIn("gnss_mode", r.details)

    def test_gnss_restore_check_present(self):
        r = evaluate_failsafe(synthetic_guard_result())
        names = [c["name"] for c in r.checks]
        self.assertIn("gps_gnss_mode_restored", names)

    def test_fail(self):
        r = evaluate_failsafe(synthetic_guard_result(mismatches=["FS_GCS_ENABLE"], status="FAIL"))
        self.assertEqual(r.status, STATUS_FAIL)


class TestEvaluateRtkLossBehavior(unittest.TestCase):
    def test_pass_no_dropout(self):
        series = _series([5, 6, 6, 6])
        r = evaluate_rtk_loss_behavior(series, failsafe_ok=True)
        self.assertEqual(r.item_id, ITEM_RTK_LOSS)
        self.assertEqual(r.status, STATUS_PASS)

    def test_pass_with_recovered_dropout(self):
        # FLOAT → FIXED → 3D(喪失) → FLOAT → FIXED（1回の喪失、すぐ復帰）
        series = _series([5, 6, 3, 5, 6])
        r = evaluate_rtk_loss_behavior(series, failsafe_ok=True)
        self.assertEqual(r.status, STATUS_PASS)
        self.assertEqual(r.details["rtk_dropout_count"], 1)

    def test_fail_never_fixed(self):
        series = _series([5, 5, 5])
        r = evaluate_rtk_loss_behavior(series, failsafe_ok=True)
        self.assertEqual(r.status, STATUS_FAIL)

    def test_fail_failsafe_not_armed(self):
        series = _series([5, 6, 6])
        r = evaluate_rtk_loss_behavior(series, failsafe_ok=False)
        self.assertEqual(r.status, STATUS_FAIL)

    def test_fail_too_many_dropouts(self):
        # RTK → 3D を3回繰り返す（上限2を超える）
        series = _series([5, 3, 5, 3, 5, 3, 6])
        r = evaluate_rtk_loss_behavior(series, failsafe_ok=True,
                                       criteria={"max_rtk_dropouts": 2, "max_dropout_sec": 30.0})
        self.assertEqual(r.status, STATUS_FAIL)
        self.assertEqual(r.details["rtk_dropout_count"], 3)

    def test_ekf_unhealthy_fails(self):
        series = [{"t": 0.0, "ts": "", "fix_type": 6, "ekf_flags": 0x000},
                  {"t": 1.0, "ts": "", "fix_type": 6, "ekf_flags": 0x000}]
        r = evaluate_rtk_loss_behavior(series, failsafe_ok=True)
        self.assertEqual(r.status, STATUS_FAIL)

    def test_no_ekf_flags_skips_check(self):
        # ekf_flags が無い時系列でも fix_type だけで判定できる
        series = [{"t": 0.0, "ts": "", "fix_type": 6, "ekf_flags": None}]
        r = evaluate_rtk_loss_behavior(series, failsafe_ok=True)
        self.assertEqual(r.status, STATUS_PASS)


class TestPhase3Report(unittest.TestCase):
    def _make_report(self):
        f9p = evaluate_f9p_golden({"status": "PASS", "summary": "OK", "checked": {}})
        ekf = evaluate_ekf_sources(synthetic_guard_result())
        fs = evaluate_failsafe(synthetic_guard_result())
        loss = evaluate_rtk_loss_behavior(_series([5, 6, 6]), failsafe_ok=True)
        return Phase3Report([f9p, ekf, fs, loss], connection={"connection": "(test)"})

    def test_overall_pass(self):
        rep = self._make_report()
        self.assertEqual(rep.overall_status(), STATUS_PASS)
        self.assertEqual(rep.verdict(), GO)

    def test_to_dict_and_json(self):
        rep = self._make_report()
        d = rep.to_dict()
        self.assertEqual(d["overall"]["status"], STATUS_PASS)
        self.assertEqual(len(d["items"]), 4)
        json.loads(rep.to_json())

    def test_checklist_format(self):
        rep = self._make_report()
        text = rep.format_checklist()
        self.assertIn("RTK→EKF", text)
        self.assertIn("GO（飛行可）", text)

    def test_overall_fail_if_any_fail(self):
        fs = evaluate_failsafe(synthetic_guard_result(mismatches=["FS_GCS_ENABLE"], status="FAIL"))
        loss = evaluate_rtk_loss_behavior(_series([5, 6, 6]), failsafe_ok=fs.is_pass())
        rep = Phase3Report([fs, loss])
        self.assertEqual(rep.overall_status(), STATUS_FAIL)
        self.assertEqual(rep.verdict(), NO_GO)


if __name__ == "__main__":
    unittest.main(verbosity=2)
