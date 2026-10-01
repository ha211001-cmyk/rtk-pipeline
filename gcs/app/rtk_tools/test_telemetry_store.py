#!/usr/bin/env python3
"""test_telemetry_store.py — TelemetryStore のユニットテスト（実機不要）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.app.rtk_tools.telemetry_store import TelemetryStore  # noqa: E402


class _Msg:
    def __init__(self, **attrs):
        self.__dict__.update(attrs)


class TestTelemetryStore(unittest.TestCase):
    def test_update_and_get(self):
        store = TelemetryStore()
        store.update(1, "HEARTBEAT", _Msg(base_mode=0x81, custom_mode=4))
        hb = store.get(1, "HEARTBEAT")
        self.assertIsNotNone(hb)
        self.assertEqual(hb.custom_mode, 4)

    def test_get_all_drone_ids(self):
        store = TelemetryStore()
        store.update(1, "HEARTBEAT", _Msg())
        store.update(2, "GPS_RAW_INT", _Msg())
        self.assertEqual(sorted(store.get_all_drone_ids()), [1, 2])

    def test_last_seen(self):
        store = TelemetryStore()
        self.assertIsNone(store.get_last_seen(1))
        store.update(1, "HEARTBEAT", _Msg())
        self.assertIsNotNone(store.get_last_seen(1))
        self.assertIn(1, store.get_last_seen_all())

    def test_get_gps_and_sys_status(self):
        store = TelemetryStore()
        store.update(1, "GPS_RAW_INT", _Msg(fix_type=6, satellites_visible=18))
        store.update(1, "SYS_STATUS", _Msg(voltage_battery=12500, battery_remaining=80))
        self.assertEqual(store.get_gps_raw(1).fix_type, 6)
        self.assertEqual(store.get_sys_status(1).voltage_battery, 12500)
        self.assertIsNone(store.get_gps_raw(999))

    def test_status_text_ring_buffer(self):
        store = TelemetryStore()
        for i in range(60):
            store.add_status_text(1, f"msg {i}", 4)
        texts = store.get_status_texts(1)
        self.assertEqual(len(texts), 50)  # 最大 50 件
        self.assertEqual(texts[-1]["text"], "msg 59")
        self.assertEqual(texts[0]["text"], "msg 10")

    def test_status_text_count(self):
        store = TelemetryStore()
        store.add_status_text(1, "a", 3)
        store.add_status_text(1, "b", 4)
        self.assertEqual(len(store.get_status_texts(1, count=1)), 1)
        self.assertEqual(store.get_status_texts(1, count=1)[0]["text"], "b")

    def test_named_value_float_history(self):
        store = TelemetryStore()
        store.update(1, "NAMED_VALUE_FLOAT", _Msg(name="alt", value=1.5, time_usec=100))
        store.update(1, "NAMED_VALUE_FLOAT", _Msg(name="alt", value=2.5, time_usec=200))
        hist = store.get_named_value_float_history(1)
        self.assertEqual(len(hist["alt"]), 2)
        latest = store.get_named_value_float_latest(1)
        self.assertEqual(latest["alt"].value, 2.5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
