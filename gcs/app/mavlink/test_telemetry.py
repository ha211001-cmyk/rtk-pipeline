#!/usr/bin/env python3
"""test_telemetry.py — gcs.app.mavlink.telemetry（正典抽出ロジック）のユニットテスト（実機不要）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.app.mavlink.telemetry import (  # noqa: E402
    VehicleStateStore,
    apply_message,
    new_stats,
    new_vehicle_state,
)


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


class TestApplyMessage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pymavlink import mavutil
        cls.mav = mavutil.mavlink

    def test_gps_raw_int(self):
        state = new_vehicle_state(1)
        stats = new_stats()
        apply_message(state, _make_gps(self.mav, 1, 6, 18), stats)
        self.assertEqual(state["fix_type"], 6)
        self.assertEqual(state["fix_name"], "RTK_FIXED")
        self.assertEqual(state["satellites"], 18)
        self.assertAlmostEqual(state["lat"], 36.0751418, places=6)
        self.assertAlmostEqual(state["lon"], 136.2133477, places=6)
        self.assertAlmostEqual(state["alt_m"], 44.8)
        self.assertEqual(stats["gps_raw_int"], 1)

    def test_heartbeat(self):
        state = new_vehicle_state(1)
        stats = new_stats()
        apply_message(state, _make_heartbeat(self.mav, 1, 2, 4), stats)
        self.assertEqual(state["flight_mode"], "GUIDED")
        self.assertTrue(state["armed"])
        self.assertEqual(state["vehicle_type"], 2)
        self.assertEqual(state["vehicle_type_name"], "QUADROTOR")
        self.assertEqual(stats["heartbeat"], 1)

    def test_rover_mode(self):
        state = new_vehicle_state(10)
        stats = new_stats()
        apply_message(state, _make_heartbeat(self.mav, 10, 10, 10), stats)
        self.assertEqual(state["flight_mode"], "AUTO")
        self.assertEqual(state["vehicle_type_name"], "ROVER")

    def test_sys_status_battery(self):
        state = new_vehicle_state(1)
        stats = new_stats()
        apply_message(state, _make_sys_status(self.mav, 1, 12500, 500, 80), stats)
        self.assertAlmostEqual(state["battery_voltage_v"], 12.5)
        self.assertAlmostEqual(state["battery_current_a"], 5.0)
        self.assertEqual(state["battery_remaining_pct"], 80)

    def test_other_message(self):
        class _Stub:
            def get_type(self):
                return "ATTITUDE"

            def get_srcComponent(self):
                return 1

        state = new_vehicle_state(1)
        stats = new_stats()
        apply_message(state, _Stub(), stats)
        self.assertEqual(stats["other"], 1)


class TestVehicleStateStore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pymavlink import mavutil
        cls.mav = mavutil.mavlink

    def test_classified_by_system_id(self):
        store = VehicleStateStore()
        store.apply(_make_gps(self.mav, 1, 6, 18))
        store.apply(_make_gps(self.mav, 2, 5, 12))
        self.assertEqual(store.get_state(1)["fix_type"], 6)
        self.assertEqual(store.get_state(2)["fix_name"], "RTK_FLOAT")
        self.assertEqual(set(store.vehicles().keys()), {1, 2})

    def test_get_state_unknown_returns_none(self):
        store = VehicleStateStore()
        self.assertIsNone(store.get_state(999))

    def test_snapshot(self):
        store = VehicleStateStore()
        store.apply(_make_gps(self.mav, 1, 3, 9))
        snap = store.snapshot()
        self.assertIn("vehicles", snap)
        self.assertIn(1, snap["vehicles"])
        self.assertIn("stats", snap)
        self.assertGreaterEqual(snap["stats"]["gps_raw_int"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
