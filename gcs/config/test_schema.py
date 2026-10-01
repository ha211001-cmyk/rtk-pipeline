#!/usr/bin/env python3
"""test_schema.py — gcs.config.schema のユニットテスト（実機不要）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.config.schema import (  # noqa: E402
    validate_bundled_configs,
    validate_config_file,
    validate_gcs_config,
    validate_rtk_forwarder_config,
    validate_tcp2serial_config,
)


class TestGcsConfig(unittest.TestCase):
    def test_valid_minimal_udp(self):
        errors = validate_gcs_config({"connection_type": "udp", "udp_listen_port": 14550})
        self.assertEqual(errors, [])

    def test_invalid_connection_type(self):
        errors = validate_gcs_config({"connection_type": "i2c"})
        self.assertTrue(any("connection_type" in e for e in errors))

    def test_invalid_port(self):
        errors = validate_gcs_config({"udp_listen_port": 99999})
        self.assertTrue(any("udp_listen_port" in e for e in errors))

    def test_drones_mapping(self):
        cfg = {
            "drones": {
                "drone1": {"system_id": 1, "endpoint": "127.0.0.1:14550"},
                "drone2": {"system_id": "two", "endpoint": "127.0.0.1:14551"},
            }
        }
        errors = validate_gcs_config(cfg)
        self.assertTrue(any("drones.drone2.system_id" in e for e in errors))

    def test_env_ref_allowed_in_port(self):
        errors = validate_gcs_config({"connection_type": "udp", "udp_listen_port": "${GCS_PORT}"})
        self.assertEqual(errors, [])


class TestRtkForwarderConfig(unittest.TestCase):
    def test_valid(self):
        cfg = {
            "source": {"source_type": "tcp", "host": "127.0.0.1", "port": 2101},
            "forward": {"type": "serial", "serial_port": "/dev/ttyAMA4", "baudrate": 115200},
        }
        self.assertEqual(validate_rtk_forwarder_config(cfg), [])

    def test_ntrip_env_refs(self):
        cfg = {
            "source": {
                "source_type": "ntrip",
                "host": "${NTRIP_HOST}",
                "port": "${NTRIP_PORT}",
                "username": "${NTRIP_USER}",
                "password": "${NTRIP_PASSWORD}",
            },
            "forward": {"type": "serial", "serial_port": "/dev/ttyAMA4", "baudrate": 115200},
        }
        self.assertEqual(validate_rtk_forwarder_config(cfg), [])

    def test_missing_source(self):
        errors = validate_rtk_forwarder_config({"forward": {"type": "serial"}})
        self.assertTrue(any("source" in e for e in errors))

    def test_invalid_source_type(self):
        cfg = {
            "source": {"source_type": "http"},
            "forward": {"type": "serial"},
        }
        errors = validate_rtk_forwarder_config(cfg)
        self.assertTrue(any("source.source_type" in e for e in errors))


class TestTcp2SerialConfig(unittest.TestCase):
    def test_valid(self):
        cfg = {
            "bind_host": "0.0.0.0",
            "bind_port": 2102,
            "serial_device": "/dev/ttyAMA4",
            "baudrate": 115200,
        }
        self.assertEqual(validate_tcp2serial_config(cfg), [])

    def test_missing_required(self):
        errors = validate_tcp2serial_config({"bind_host": "0.0.0.0"})
        self.assertTrue(any("bind_port" in e for e in errors))
        self.assertTrue(any("serial_device" in e for e in errors))


class TestBundledConfigs(unittest.TestCase):
    def test_all_bundled_configs_valid(self):
        results = validate_bundled_configs()
        self.assertIn("gcs.yml", results)
        for filename, result in results.items():
            self.assertEqual(result["errors"], [], f"{filename} に検証エラーがあります")

    def test_validate_config_file_kind(self):
        import tempfile
        import os

        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
            f.write("bind_host: 0.0.0.0\nbind_port: 2102\nserial_device: /dev/ttyAMA4\n")
            path = f.name
        try:
            _, errors = validate_config_file(path, "tcp2serial")
            self.assertEqual(errors, [])
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
