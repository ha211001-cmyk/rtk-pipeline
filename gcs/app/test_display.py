#!/usr/bin/env python3
"""test_display.py — gcs.app.display（表示変換の純関数）のユニットテスト（実機不要）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.app.display import (  # noqa: E402
    fix_name,
    flight_mode_name,
    mode_number,
    severity_name,
    heartbeat_to_display,
    battery_to_display,
    gps_to_display,
    command_state_to_display,
    status_texts_to_display,
    connection_status_to_display,
)


class _Msg:
    def __init__(self, **attrs):
        self.__dict__.update(attrs)


class TestTableLookups(unittest.TestCase):
    def test_fix_name_known(self):
        self.assertEqual(fix_name(6), "RTK_FIXED")
        self.assertEqual(fix_name(5), "RTK_FLOAT")
        self.assertEqual(fix_name(0), "NO_GPS")
        self.assertEqual(fix_name(1), "NO_FIX")

    def test_fix_name_unknown(self):
        self.assertEqual(fix_name(99), "UNKNOWN(99)")

    def test_fix_name_bad_type(self):
        self.assertEqual(fix_name(None), "UNKNOWN(None)")

    def test_flight_mode_name(self):
        self.assertEqual(flight_mode_name(4), "GUIDED")
        self.assertEqual(flight_mode_name(6), "RTH")
        self.assertEqual(flight_mode_name(99), "MODE_99")

    def test_mode_number_roundtrip(self):
        self.assertEqual(mode_number("GUIDED"), 4)
        self.assertEqual(mode_number("guided"), 4)
        self.assertIsNone(mode_number("NOPE"))

    def test_severity_name(self):
        self.assertEqual(severity_name(0), "EMERGENCY")
        self.assertEqual(severity_name(7), "DEBUG")
        self.assertEqual(severity_name(99), "UNKNOWN")


class TestFormatters(unittest.TestCase):
    def test_heartbeat_none(self):
        self.assertEqual(
            heartbeat_to_display(None),
            {"armed": False, "mode": "N/A", "base_mode": 0, "custom_mode": -1},
        )

    def test_heartbeat_armed(self):
        out = heartbeat_to_display(_Msg(base_mode=0x81, custom_mode=4))
        self.assertTrue(out["armed"])
        self.assertEqual(out["mode"], "GUIDED")
        self.assertEqual(out["custom_mode"], 4)

    def test_heartbeat_disarmed(self):
        out = heartbeat_to_display(_Msg(base_mode=0x01, custom_mode=6))
        self.assertFalse(out["armed"])
        self.assertEqual(out["mode"], "RTH")

    def test_battery_none(self):
        self.assertEqual(
            battery_to_display(None),
            {"voltage": None, "current": None, "remaining": None},
        )

    def test_battery_values(self):
        out = battery_to_display(
            _Msg(voltage_battery=12500, current_battery=500, battery_remaining=80)
        )
        self.assertEqual(out["voltage"], 12.5)
        self.assertEqual(out["current"], 5.0)
        self.assertEqual(out["remaining"], 80)

    def test_battery_remaining_invalid(self):
        out = battery_to_display(
            _Msg(voltage_battery=12500, current_battery=500, battery_remaining=-1)
        )
        self.assertIsNone(out["remaining"])

    def test_gps_none(self):
        out = gps_to_display(None, None)
        self.assertEqual(out["fix_type"], -1)
        self.assertEqual(out["fix_name"], "N/A")

    def test_gps_fixed(self):
        gps_raw = _Msg(fix_type=6, satellites_visible=18, eph=50)
        gpos = _Msg(lat=360751418, lon=1362133477, alt=44800)
        out = gps_to_display(gps_raw, gpos)
        self.assertEqual(out["fix_type"], 6)
        self.assertEqual(out["fix_name"], "RTK_FIXED")
        self.assertEqual(out["satellites"], 18)
        self.assertEqual(out["hdop"], 0.5)
        self.assertAlmostEqual(out["lat"], 36.0751418, places=6)
        self.assertAlmostEqual(out["lon"], 136.2133477, places=6)
        self.assertAlmostEqual(out["alt"], 44.8)

    def test_command_state_empty(self):
        self.assertEqual(
            command_state_to_display([]),
            {"pending_count": 0, "last_ack": None},
        )

    def test_command_state_last_ack(self):
        pending = [
            {"status": "pending", "description": "ARM"},
            {"status": "acked", "description": "TAKEOFF"},
        ]
        out = command_state_to_display(pending)
        self.assertEqual(out["pending_count"], 2)
        self.assertEqual(out["last_ack"], {"command": "TAKEOFF", "status": "acked"})

    def test_status_texts(self):
        out = status_texts_to_display([
            {"text": "hello", "severity": 3, "name": "x", "time": 1.0},
        ])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["severity_name"], "ERROR")
        self.assertEqual(out[0]["text"], "hello")

    def test_connection_status_none(self):
        self.assertEqual(
            connection_status_to_display(None),
            {"is_connected": False, "type": "unknown"},
        )

    def test_connection_status_values(self):
        out = connection_status_to_display({
            "is_connected": True,
            "connection_type": "udp",
            "packet_received": 10,
            "packet_loss": 1,
            "last_error": None,
        })
        self.assertTrue(out["is_connected"])
        self.assertEqual(out["type"], "udp")
        self.assertEqual(out["packets_received"], 10)
        self.assertEqual(out["packet_loss"], 1)
        self.assertIsNone(out["last_error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
