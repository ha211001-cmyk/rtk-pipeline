#!/usr/bin/env python3
"""test_runner.py — GCS バックエンドコア（GcsBackend）と GUI 表示変換のユニットテスト。

実行:
    cd <リポジトリルート>
    python3 -m unittest gcs.integration.test_runner -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.integration.runner import GcsBackend, _parse_dest, _status_lines  # noqa: E402
from gcs.integration.display import format_vehicle_rows  # noqa: E402


class _FakeReader:
    def __init__(self, vehicles=None):
        self._running = False
        self.stats = {"packets": 1, "gps_raw_int": 1, "heartbeat": 1,
                      "sys_status": 1, "other": 0}
        self._vehicles = vehicles or {}

    def start(self):
        self._running = True
        return True

    def stop(self):
        self._running = False

    def is_running(self):
        return self._running

    def vehicles(self):
        return {sid: dict(st) for sid, st in self._vehicles.items()}


class _FakeCaster:
    def __init__(self):
        self._running = False
        self.stats = {"bytes_read": 10, "frames_read": 2, "frames_sent": 2,
                      "bytes_sent": 60, "destinations": 1, "send_errors": 0}
        self._destinations = []

    def add_destination(self, host, port):
        self._destinations.append((host, port))
        self.stats["destinations"] = len(self._destinations)
        return True

    def destinations(self):
        return list(self._destinations)

    def start(self):
        self._running = True
        return True

    def stop(self):
        self._running = False

    def is_running(self):
        return self._running


def _sample_vehicle(system_id=1):
    return {
        "system_id": system_id, "component_id": 1, "vehicle_type": 10,
        "vehicle_type_name": "ROVER", "fix_type": 6, "fix_name": "RTK_FIXED",
        "satellites": 18, "lat": 36.0751418, "lon": 136.2133477,
        "alt_m": 44.8, "flight_mode": "AUTO", "custom_mode": 10,
        "base_mode": 129, "system_status": 4, "armed": True,
        "battery_voltage_v": 12.5, "battery_current_a": 2.0,
        "battery_remaining_pct": 80, "last_update": 1000.0,
        "last_message": "GPS_RAW_INT",
        "messages": {"GPS_RAW_INT": 1, "HEARTBEAT": 1, "SYS_STATUS": 1},
    }


class TestParseDest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(_parse_dest("192.168.1.10:14550"),
                         ("192.168.1.10", 14550))

    def test_invalid(self):
        with self.assertRaises(ValueError):
            _parse_dest("no-port")


class TestGcsBackend(unittest.TestCase):
    def test_snapshot_shape(self):
        reader = _FakeReader(vehicles={1: _sample_vehicle()})
        caster = _FakeCaster()
        caster.add_destination("192.168.1.10", 14550)
        backend = GcsBackend(reader=reader, caster=caster)
        snap = backend.snapshot()
        self.assertIn("vehicles", snap)
        self.assertIn(1, snap["vehicles"])
        self.assertEqual(snap["vehicles"][1]["fix_name"], "RTK_FIXED")
        self.assertIn("mavlink", snap)
        self.assertIn("rtcm", snap)
        self.assertEqual(snap["rtcm_destinations"], [["192.168.1.10", 14550]])

    def test_start_stop_runs_both_threads(self):
        reader = _FakeReader(vehicles={1: _sample_vehicle()})
        caster = _FakeCaster()
        backend = GcsBackend(reader=reader, caster=caster)
        self.assertTrue(backend.start())
        self.assertTrue(reader.is_running())
        self.assertTrue(caster.is_running())
        self.assertTrue(backend.is_running())
        backend.stop()
        self.assertFalse(reader.is_running())
        self.assertFalse(caster.is_running())

    def test_status_lines(self):
        reader = _FakeReader(vehicles={1: _sample_vehicle()})
        caster = _FakeCaster()
        caster.add_destination("192.168.1.10", 14550)
        backend = GcsBackend(reader=reader, caster=caster)
        text = "\n".join(_status_lines(backend))
        self.assertIn("system_id=1", text)
        self.assertIn("RTK_FIXED", text)
        self.assertIn("AUTO", text)
        self.assertIn("12.5V", text)
        self.assertIn("dests=1", text)


class TestFormatVehicleRows(unittest.TestCase):
    def test_rows(self):
        rows = format_vehicle_rows({1: _sample_vehicle()}, now=1001.0)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row[0], 1)
        self.assertEqual(row[2], "RTK_FIXED")
        self.assertEqual(row[3], 18)
        self.assertEqual(row[4], "AUTO")
        self.assertEqual(row[5], "12.5V/80%")
        self.assertEqual(row[6], "ARM")
        self.assertEqual(row[7], "1.0s")

    def test_empty(self):
        self.assertEqual(format_vehicle_rows({}), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
