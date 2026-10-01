#!/usr/bin/env python3
"""test_selftest.py — gcs.selftest のユニットテスト（実機不要）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.selftest import (  # noqa: E402
    SYNTH_MSG_TYPE,
    build_rtcm3_frame,
    check_config_schema,
    check_fix_metrics,
    check_rtcm3_parser,
    run_selfcheck,
)


class TestRtcm3Frame(unittest.TestCase):
    def test_build_valid_frame(self):
        frame = build_rtcm3_frame(SYNTH_MSG_TYPE)
        self.assertEqual(frame[0], 0xD3)
        # 0xD3 + 2byte ヘッダ + payload + 3byte CRC
        payload_len = 8
        self.assertEqual(len(frame), 3 + payload_len + 3)

    def test_parser_extracts_and_verifies(self):
        result = check_rtcm3_parser()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["crc_failed"], 0)


class TestFixMetrics(unittest.TestCase):
    def test_synthetic_fixed_reached(self):
        result = check_fix_metrics()
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["reached_fixed"])


class TestConfigSchema(unittest.TestCase):
    def test_bundled_configs_valid(self):
        result = check_config_schema()
        self.assertTrue(result["ok"], result)


class TestSelfcheck(unittest.TestCase):
    def test_all_checks_pass(self):
        summary = run_selfcheck()
        self.assertTrue(summary["ok"], summary)


if __name__ == "__main__":
    unittest.main()
