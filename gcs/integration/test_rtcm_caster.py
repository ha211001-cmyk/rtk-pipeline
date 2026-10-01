#!/usr/bin/env python3
"""test_rtcm_caster.py — RtcmCaster のユニットテスト（実機不要）。"""

from __future__ import annotations

import socket
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.integration.rtcm_caster import RtcmCaster  # noqa: E402
from gcs.integration.sources import make_rtcm3_frame  # noqa: E402


def _free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestRtcmCasterDestinations(unittest.TestCase):
    def test_add_remove_destinations(self):
        caster = RtcmCaster()
        self.assertTrue(caster.add_destination("192.168.1.10", 14550))
        self.assertFalse(caster.add_destination("192.168.1.10", 14550))  # dup
        self.assertTrue(caster.add_destination("192.168.1.11", 14550))
        self.assertEqual(caster.destinations(),
                         [("192.168.1.10", 14550), ("192.168.1.11", 14550)])
        self.assertTrue(caster.remove_destination("192.168.1.10", 14550))
        self.assertFalse(caster.remove_destination("192.168.1.10", 14550))
        self.assertEqual(caster.destinations(), [("192.168.1.11", 14550)])


class TestRtcmCasterBroadcast(unittest.TestCase):
    def test_feed_broadcasts_frame_to_destination(self):
        port = _free_udp_port()
        recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        recv.bind(("127.0.0.1", port))
        recv.settimeout(2.0)
        try:
            caster = RtcmCaster()
            caster.add_destination("127.0.0.1", port)
            frame = make_rtcm3_frame(1077)
            caster.feed(frame)
            data, addr = recv.recvfrom(2048)
            self.assertEqual(data, frame)
            self.assertEqual(caster.stats["frames_read"], 1)
            self.assertEqual(caster.stats["frames_sent"], 1)
        finally:
            recv.close()
            caster.stop()

    def test_broadcast_with_no_destinations(self):
        caster = RtcmCaster()
        self.assertEqual(caster.broadcast(make_rtcm3_frame()), 0)
        self.assertEqual(caster.stats["frames_sent"], 0)


class TestRtcmCasterStartStop(unittest.TestCase):
    def test_start_stop_without_serial(self):
        caster = RtcmCaster()  # source_port=None → 手動投入モード
        self.assertTrue(caster.start())
        self.assertTrue(caster.is_running())
        caster.stop()
        self.assertFalse(caster.is_running())


if __name__ == "__main__":
    unittest.main(verbosity=2)
