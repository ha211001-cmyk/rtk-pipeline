#!/usr/bin/env python3
"""test_runner.py — 飛行前セルフテスト ランナー / セッションのユニットテスト（実機不要）。

実行:
    cd <リポジトリルート>
    python3 -m unittest gcs.preflight.test_runner -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.rtcm_monitor import CorrectionMonitor  # noqa: E402
from gcs.preflight.checklist import STATUS_PASS, STATUS_FAIL  # noqa: E402
from gcs.preflight.session import (  # noqa: E402
    TcpSession,
    STATE_DISCONNECTED,
)
from gcs.preflight.runner import PreflightRunner  # noqa: E402


class _FakeThread:
    def is_alive(self) -> bool:
        return True


class _FakeReader:
    def __init__(self):
        self._thread = _FakeThread()

    def sample(self):
        return None


def _make_stale_monitor() -> CorrectionMonitor:
    mon = CorrectionMonitor(age_alert_threshold=10.0, age_warn_threshold=5.0)
    # テスト用クロック: 常に t=20.0（受信時刻 0.0 から 20 秒経過 → stale）
    mon.age_monitor._clock = lambda: 20.0
    mon.age_monitor.mark_received(ts=0.0)
    return mon


def _make_fresh_monitor() -> CorrectionMonitor:
    mon = CorrectionMonitor(age_alert_threshold=10.0, age_warn_threshold=5.0)
    mon.age_monitor._clock = lambda: 1.0
    mon.age_monitor.mark_received(ts=0.0)
    return mon


class TestSessionDisconnectDetection(unittest.TestCase):
    def test_not_connected_is_disconnected(self):
        s = TcpSession("127.0.0.1", 9999)
        self.assertFalse(s.is_connected())
        self.assertTrue(s.is_disconnected())
        self.assertEqual(s.state, STATE_DISCONNECTED)

    def test_stale_linked_to_disconnect(self):
        # リーダーは生存しているが RTK age が stale → 切断扱い（要件 6 の連動）
        mon = _make_stale_monitor()
        s = TcpSession("127.0.0.1", 9999, monitor=mon)
        s._reader = _FakeReader()
        self.assertTrue(s.is_stale())
        self.assertTrue(s.is_disconnected())

    def test_fresh_not_disconnected(self):
        mon = _make_fresh_monitor()
        s = TcpSession("127.0.0.1", 9999, monitor=mon)
        s._reader = _FakeReader()
        self.assertFalse(s.is_stale())
        self.assertFalse(s.is_disconnected())


class TestRunnerOfflineEndToEnd(unittest.TestCase):
    def _config_no_report(self):
        return {"report": {"json": False, "output_dir": None},
                "monitor": {"sample_interval_sec": 0.1}}

    def test_full_pipeline_pass(self):
        runner = PreflightRunner(self._config_no_report())
        report = runner.run(offline=True, duration=2.0, fix_script=[(0.0, 5), (0.3, 6)])
        self.assertEqual(report.overall_status(), STATUS_PASS)
        items = report.to_dict()["items"]
        ids = [it["item_id"] for it in items]
        self.assertEqual(ids, ["item2_config_golden", "item1_fixed_rate",
                               "item3_rtcm_health", "base_rate"])

    def test_fail_when_never_fixed(self):
        runner = PreflightRunner(self._config_no_report())
        report = runner.run(offline=True, duration=1.0, fix_script=[(0.0, 5), (1.0, 5)])
        self.assertEqual(report.overall_status(), STATUS_FAIL)
        self.assertIn("item1_fixed_rate",
                      [it["item_id"] for it in report.to_dict()["items"]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
