#!/usr/bin/env python3
"""test_rtk_state.py — gcs.app.api.rtk_state のユニットテスト（実機不要・FastAPI 非依存）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.app.api import rtk_state  # noqa: E402


def _reset():
    with rtk_state._fix_lock:
        rtk_state._fix_state = {}
    with rtk_state._forwarder_lock:
        rtk_state._forwarder_stats = {}


class TestFixState(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_update_and_get(self):
        rtk_state.update_fix_state({"carrSoln": 2, "fixType": 4, "numSV": 20})
        state = rtk_state.get_fix_state()
        self.assertIsNotNone(state)
        self.assertEqual(state["carrSoln"], 2)
        self.assertIn("last_update", state)

    def test_clear(self):
        rtk_state.update_fix_state({"carrSoln": 2})
        self.assertIsNotNone(rtk_state.get_fix_state())
        rtk_state.update_fix_state(None)
        self.assertIsNone(rtk_state.get_fix_state())

    def test_get_never_set_returns_none(self):
        self.assertIsNone(rtk_state.get_fix_state())


class TestForwarderStats(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_update_and_get(self):
        rtk_state.update_forwarder_stats({"total_packets": 10, "total_bytes": 200})
        stats = rtk_state.get_forwarder_stats()
        self.assertEqual(stats["total_packets"], 10)
        self.assertIn("last_update", stats)

    def test_get_never_set_returns_none(self):
        self.assertIsNone(rtk_state.get_forwarder_stats())


if __name__ == "__main__":
    unittest.main(verbosity=2)
