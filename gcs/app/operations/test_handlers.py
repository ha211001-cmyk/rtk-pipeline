#!/usr/bin/env python3
"""test_handlers.py — 操作カタログ・ヘルパー関数のユニットテスト（ハードウェア不要）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.app.operations import handlers  # noqa: E402
from gcs.app.operations.handlers import (  # noqa: E402
    OPERATIONS,
    register_operations,
    _base_llh,
    _verify_summary,
)
from gcs.app.operations.manager import OperationManager  # noqa: E402


class TestCatalog(unittest.TestCase):
    def test_operations_registered(self):
        self.assertEqual(len(OPERATIONS), 14)
        ids = [o["id"] for o in OPERATIONS]
        self.assertEqual(len(ids), len(set(ids)), "operation ids must be unique")

    def test_categories(self):
        allowed = {"設定系", "監視系", "ロギング系", "基地局・注入系"}
        for op in OPERATIONS:
            self.assertIn(op["category"], allowed, op["id"])

    def test_dangerous_ops(self):
        # 危険操作（Flash 書き込み・座標上書き・GLONASS 切替・レート変更・基地局起動）
        dangerous = {o["id"] for o in OPERATIONS if o["dangerous"]}
        self.assertTrue(
            {"f9p_write_verify", "base_tmode3_set", "rtcm_rate_set",
             "glonass_toggle", "base_station_start"} <= dangerous
        )

    def test_services(self):
        services = {o["id"] for o in OPERATIONS if o["mode"] == "service"}
        self.assertEqual(
            services,
            {"forwarder_start", "tcp2serial_start", "base_station_start"},
        )

    def test_register_into_manager(self):
        m = OperationManager()
        register_operations(m)
        cat = m.catalog()
        self.assertEqual(len(cat), 14)
        self.assertTrue(all("handler" not in c for c in cat))


class TestHelpers(unittest.TestCase):
    def test_verify_summary(self):
        v = {"device_alive": True, "all_verified": True, "ok_count": 12,
             "fail_count": 0, "warn_count": 1, "checks": []}
        s = _verify_summary(v)
        self.assertEqual(s["ok_count"], 12)
        self.assertNotIn("checks", s)

    def test_base_llh_defaults(self):
        # params 未指定なら gcs/config/config.yaml の既定値を使う
        lat, lon, alt = _base_llh({})
        self.assertAlmostEqual(lat, 36.0751418, places=5)
        self.assertAlmostEqual(lon, 136.2133477, places=5)
        self.assertAlmostEqual(alt, 44.80, places=2)

    def test_base_llh_override(self):
        lat, lon, alt = _base_llh({"lat": 35.0, "lon": 139.0, "alt": 10.0})
        self.assertAlmostEqual(lat, 35.0)
        self.assertAlmostEqual(lon, 139.0)
        self.assertAlmostEqual(alt, 10.0)

    def test_param_schema(self):
        # 各操作の params は name/label/type を備える
        for op in OPERATIONS:
            for p in op["params"]:
                self.assertIn("name", p)
                self.assertIn("label", p)
                self.assertIn("type", p)


if __name__ == "__main__":
    unittest.main()
