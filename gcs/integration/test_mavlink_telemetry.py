#!/usr/bin/env python3
"""test_mavlink_telemetry.py — MavlinkTelemetryReader のユニットテスト（実機不要）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.integration.sources import MavlinkTelemetryReader  # noqa: E402


def _make_heartbeat(mav, system_id, vehicle_type, custom_mode,
                    base_mode=None, system_status=4):
    if base_mode is None:
        base_mode = (mav.MAV_MODE_FLAG_SAFETY_ARMED
                     | mav.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED)
    hb = mav.MAVLink_heartbeat_message(
        vehicle_type, mav.MAV_AUTOPILOT_ARDUPILOTMEGA,
        base_mode, custom_mode, system_status, 3)
    hb._header.srcSystem = system_id
    hb._header.srcComponent = 1
    return hb


def _make_gps(mav, system_id, fix_type, sats):
    g = mav.MAVLink_gps_raw_int_message(
        0, fix_type, 360751418, 1362133477, 44800, 5, 7, 0, 0, sats)
    g._header.srcSystem = system_id
    g._header.srcComponent = 1
    return g


def _make_sys_status(mav, system_id, voltage_mv, current_ca, remaining):
    s = mav.MAVLink_sys_status_message(
        0, 0, 0, 0, voltage_mv, current_ca, remaining, 0, 0, 0, 0, 0, 0)
    s._header.srcSystem = system_id
    s._header.srcComponent = 1
    return s


class TestMavlinkTelemetryReader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pymavlink import mavutil
        cls.mav = mavutil.mavlink

    def test_gps_raw_int_classified_by_system_id(self):
        reader = MavlinkTelemetryReader()
        reader.process_message(_make_gps(self.mav, 1, 6, 18))
        reader.process_message(_make_gps(self.mav, 2, 5, 12))
        v1 = reader.get_state(1)
        v2 = reader.get_state(2)
        self.assertEqual(v1["fix_type"], 6)
        self.assertEqual(v1["fix_name"], "RTK_FIXED")
        self.assertEqual(v1["satellites"], 18)
        self.assertEqual(v2["fix_type"], 5)
        self.assertEqual(v2["fix_name"], "RTK_FLOAT")
        self.assertEqual(v2["satellites"], 12)
        self.assertEqual(set(reader.vehicles().keys()), {1, 2})

    def test_heartbeat_flight_mode_and_arm(self):
        reader = MavlinkTelemetryReader()
        reader.process_message(_make_heartbeat(self.mav, 1, 2, 4))  # copter GUIDED
        v = reader.get_state(1)
        self.assertEqual(v["flight_mode"], "GUIDED")
        self.assertTrue(v["armed"])
        self.assertEqual(v["vehicle_type"], 2)
        self.assertEqual(v["vehicle_type_name"], "QUADROTOR")

    def test_rover_mode(self):
        reader = MavlinkTelemetryReader()
        reader.process_message(_make_heartbeat(self.mav, 10, 10, 10))  # rover AUTO
        v = reader.get_state(10)
        self.assertEqual(v["flight_mode"], "AUTO")
        self.assertEqual(v["vehicle_type_name"], "ROVER")

    def test_sys_status_battery(self):
        reader = MavlinkTelemetryReader()
        reader.process_message(_make_sys_status(self.mav, 1, 12500, 500, 80))
        v = reader.get_state(1)
        self.assertAlmostEqual(v["battery_voltage_v"], 12.5)
        self.assertAlmostEqual(v["battery_current_a"], 5.0)
        self.assertEqual(v["battery_remaining_pct"], 80)

    def test_snapshot(self):
        reader = MavlinkTelemetryReader()
        reader.process_message(_make_gps(self.mav, 1, 3, 9))
        snap = reader.snapshot()
        self.assertIn("vehicles", snap)
        self.assertIn(1, snap["vehicles"])
        self.assertIn("stats", snap)
        self.assertGreaterEqual(snap["stats"]["gps_raw_int"], 1)

    def test_get_state_unknown_returns_none(self):
        reader = MavlinkTelemetryReader()
        self.assertIsNone(reader.get_state(999))


if __name__ == "__main__":
    unittest.main(verbosity=2)
