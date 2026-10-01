#!/usr/bin/env python3
"""test_server.py — FastAPI バックエンド（REST + WebSocket ペイロード生成）のスモークテスト。

実ハードウェア不要。fastapi / httpx（TestClient）が無い環境では自動スキップする。

実行:
    python3 -m unittest gcs.app.test_server -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from fastapi.testclient import TestClient
    from gcs.app.server import app
    _HAS_FASTAPI = True
except Exception:  # pragma: no cover - fastapi/httpx 未導入環境
    _HAS_FASTAPI = False


@unittest.skipUnless(_HAS_FASTAPI, "fastapi / httpx がインストールされていません")
class TestFastAPI(unittest.TestCase):
    def setUp(self):
        # ログ出力先を一時ディレクトリへ退避（startup イベントの副作用を抑止）
        self._tmp = tempfile.TemporaryDirectory()
        self._prev = os.environ.get("GCS_LOG_DIR")
        os.environ["GCS_LOG_DIR"] = self._tmp.name

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("GCS_LOG_DIR", None)
        else:
            os.environ["GCS_LOG_DIR"] = self._prev
        self._tmp.cleanup()

    def test_health(self):
        with TestClient(app) as client:
            r = client.get("/api/health")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["status"], "ok")

    def test_drones_not_initialized(self):
        with TestClient(app) as client:
            r = client.get("/api/drones")
            self.assertEqual(r.status_code, 503)

    def test_status(self):
        with TestClient(app) as client:
            r = client.get("/api/status")
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertIn("connection", body)
            self.assertFalse(body["connection"]["is_connected"])

    def test_root(self):
        with TestClient(app) as client:
            r = client.get("/")
            self.assertEqual(r.status_code, 200)

    def test_ws_route_registered(self):
        paths = {getattr(r, "path", None) for r in app.routes}
        self.assertIn("/ws/telemetry", paths)


@unittest.skipUnless(_HAS_FASTAPI, "fastapi / httpx がインストールされていません")
class TestWebSocketPayloadBuilders(unittest.TestCase):
    """websocket の payload 生成（純関数）を直接検証する。"""

    def test_build_payload_requires_store(self):
        from gcs.app.api.websocket import _build_payload
        self.assertIsNone(_build_payload(None, None, None))

    def test_build_payload_shape(self):
        from gcs.app.api.websocket import _build_payload
        from gcs.app.rtk_tools.telemetry_store import TelemetryStore

        store = TelemetryStore()

        class _Hb:
            base_mode = 0x81
            custom_mode = 4

        class _Gps:
            fix_type = 6
            satellites_visible = 18
            eph = 50

        class _Gpos:
            lat = 360751418
            lon = 1362133477
            alt = 44800

        class _Sys:
            voltage_battery = 12500
            current_battery = 500
            battery_remaining = 80

        store.update(1, "HEARTBEAT", _Hb())
        store.update(1, "GPS_RAW_INT", _Gps())
        store.update(1, "GLOBAL_POSITION_INT", _Gpos())
        store.update(1, "SYS_STATUS", _Sys())

        payload = _build_payload(store, None, None)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["type"], "telemetry")
        self.assertIn("1", payload["drones"])
        drone = payload["drones"]["1"]
        self.assertEqual(drone["gps"]["fix_name"], "RTK_FIXED")
        self.assertEqual(drone["battery"]["voltage"], 12.5)
        self.assertEqual(drone["heartbeat"]["mode"], "GUIDED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
