#!/usr/bin/env python3
"""
rtcm_monitor のユニットテスト（実ハードウェア不要）

実行方法:
    cd ~/EVK-F9P
    python3 -m unittest gcs.test_rtcm_monitor -v
    # または
    python3 gcs/test_rtcm_monitor.py
"""

import json
import struct
import sys
import unittest
from pathlib import Path

# 実行位置に依存しない import（スクリプト自身のディレクトリを sys.path に追加）
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from rtcm_monitor import (  # noqa: E402
    CorrectionMonitor,
    CrcErrorAggregator,
    RtkAgeMonitor,
    Rtcm3StreamParser,
    RxmRtcmMonitor,
    UbxParser,
    parse_rxm_rtcm,
    rtcm3_crc24q,
    rtcm3_frame_msg_type,
    rtcm3_verify_frame,
    ubx_checksum,
    UBX_RXM_RTCM_CLASS,
    UBX_RXM_RTCM_ID,
)


class _Clock:
    """テスト用の注入可能クロック。"""

    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def make_ubx_rxm_rtcm(flags: int = 0x00, ref_station: int = 0,
                      msg_type: int = 1077) -> bytes:
    """UBX-RXM-RTCM フレームを生成する（checksum 付き）。"""
    payload = struct.pack("<BBHHH", 1, flags, 0, ref_station, msg_type)
    header = bytes((UBX_RXM_RTCM_CLASS, UBX_RXM_RTCM_ID,
                    len(payload) & 0xFF, (len(payload) >> 8) & 0xFF))
    return b"\xb5\x62" + header + payload + ubx_checksum(header + payload)


def make_rtcm3_frame(msg_type: int, body_len: int = 10) -> bytes:
    """RTCM3 フレームを生成する（CRC-24Q 付き）。

    メッセージ種別（12bit）はボディ先頭 12bit に配置する。
    """
    if msg_type < 0 or msg_type > 0xFFF:
        raise ValueError("msg_type must be 0..0xFFF")
    body = bytes(((msg_type >> 4) & 0xFF, (msg_type & 0x0F) << 4))
    body += b"\x00" * body_len
    frame_len = len(body)
    header = bytes((0xD3, (frame_len >> 8) & 0x03, frame_len & 0xFF))
    no_crc = header + body
    crc = rtcm3_crc24q(no_crc)
    return no_crc + bytes(((crc >> 16) & 0xFF, (crc >> 8) & 0xFF, crc & 0xFF))


class TestParseRxmRtcm(unittest.TestCase):
    def test_parse_fields(self):
        info = parse_rxm_rtcm(struct.pack("<BBHHH", 1, 0x05, 3, 7, 1077))
        # flags=0x05: bit0=1 (crcFailed), bit2=1 -> msgUsed=(0x05>>1)&3=2
        self.assertEqual(info["crc_failed"], True)
        self.assertEqual(info["msg_used"], 2)
        self.assertEqual(info["sub_type"], 3)
        self.assertEqual(info["ref_station"], 7)
        self.assertEqual(info["msg_type"], 1077)

    def test_parse_no_crc_failed(self):
        info = parse_rxm_rtcm(struct.pack("<BBHHH", 1, 0x04, 0, 0, 1087))
        self.assertEqual(info["crc_failed"], False)
        self.assertEqual(info["msg_used"], 2)

    def test_short_payload(self):
        self.assertIsNone(parse_rxm_rtcm(b"\x01\x00"))


class TestUbxParser(unittest.TestCase):
    def test_split_frame_reassembly(self):
        frame = make_ubx_rxm_rtcm(flags=0x04, ref_station=0, msg_type=1077)
        p = UbxParser()
        self.assertEqual(p.feed(frame[:5]), [])
        out = p.feed(frame[5:])
        self.assertEqual(len(out), 1)
        cls, mid, payload = out[0]
        self.assertEqual(cls, UBX_RXM_RTCM_CLASS)
        self.assertEqual(mid, UBX_RXM_RTCM_ID)
        self.assertEqual(parse_rxm_rtcm(payload)["msg_type"], 1077)

    def test_garbage_skipped(self):
        p = UbxParser()
        frame = make_ubx_rxm_rtcm(msg_type=1087)
        out = p.feed(b"\x00\x01garbage" + frame)
        self.assertEqual(len(out), 1)
        self.assertEqual(parse_rxm_rtcm(out[0][2])["msg_type"], 1087)


class TestRtcm3(unittest.TestCase):
    def test_crc_roundtrip(self):
        frame = make_rtcm3_frame(1077)
        self.assertTrue(rtcm3_verify_frame(frame))
        self.assertEqual(rtcm3_frame_msg_type(frame), 1077)

    def test_corrupted_frame_detected(self):
        frame = bytearray(make_rtcm3_frame(1087))
        frame[4] ^= 0xFF  # ボディを1ビット反転
        self.assertFalse(rtcm3_verify_frame(bytes(frame)))

    def test_stream_parser(self):
        p = Rtcm3StreamParser(verify_crc=True)
        f1 = make_rtcm3_frame(1077)
        f2 = make_rtcm3_frame(1087)
        frames = p.feed(f1 + b"\x24junk" + f2)
        self.assertEqual(len(frames), 2)
        self.assertEqual(p.stats["frames_received"], 2)
        self.assertEqual(p.stats["crc_ok"], 2)
        self.assertEqual(p.stats["crc_failed"], 0)

    def test_real_log_crc(self):
        """実ログ（archive/rtk_base_mavlink/logs）で CRC24Q が通ることを確認する。"""
        repo = Path(__file__).resolve().parent.parent
        files = sorted((repo / "archive" / "rtk_base_mavlink" / "logs").glob("rtcm_raw_*.rtcm3"))
        data = b""
        for f in files:
            b = f.read_bytes()
            if b:
                data = b
                break
        if not data:
            self.skipTest("実ログが見つからないためスキップ")
        p = Rtcm3StreamParser(verify_crc=True)
        frames = p.feed(data)
        self.assertGreater(len(frames), 0)
        self.assertEqual(p.stats["crc_failed"], 0, "実ログは全フレーム CRC OK のはず")


class TestRtkAgeMonitor(unittest.TestCase):
    def test_age_states(self):
        c = _Clock()
        m = RtkAgeMonitor(alert_threshold=10.0, warn_threshold=5.0, clock=c)
        self.assertIsNone(m.age())
        self.assertEqual(m.status()["state"], "no_data")
        self.assertTrue(m.status()["alert"])

        m.mark_received()  # t=1000
        c.t = 1002.0
        self.assertEqual(m.status()["state"], "ok")

        c.t = 1006.0  # age=6
        self.assertEqual(m.status()["state"], "warn")
        self.assertFalse(m.status()["alert"])

        c.t = 1012.0  # age=12
        st = m.status()
        self.assertEqual(st["state"], "stale")
        self.assertTrue(st["alert"])
        self.assertAlmostEqual(st["age_sec"], 12.0)

    def test_invalid_thresholds(self):
        with self.assertRaises(ValueError):
            RtkAgeMonitor(alert_threshold=1.0, warn_threshold=2.0)


class TestCrcErrorAggregator(unittest.TestCase):
    def test_rate(self):
        a = CrcErrorAggregator()
        a.add(False)
        a.add(False)
        a.add(True)
        self.assertEqual(a.total, 3)
        self.assertEqual(a.failed, 1)
        self.assertAlmostEqual(a.rate_pct(), 100.0 / 3, places=3)

    def test_empty_rate_zero(self):
        a = CrcErrorAggregator()
        self.assertEqual(a.rate_pct(), 0.0)


class TestRxmRtcmMonitor(unittest.TestCase):
    def test_aggregation(self):
        m = RxmRtcmMonitor()
        m.add({"msg_type": 1077, "crc_failed": False, "msg_used": 2, "ref_station": 0})
        m.add({"msg_type": 1077, "crc_failed": True, "msg_used": 1, "ref_station": 0})
        m.add({"msg_type": 1087, "crc_failed": False, "msg_used": 2, "ref_station": 1})

        tot = m.totals()
        self.assertEqual(tot["count"], 3)
        self.assertEqual(tot["crc_failed"], 1)
        self.assertEqual(tot["used_counts"][2], 2)
        self.assertEqual(tot["used_counts"][1], 1)
        self.assertEqual(m.ref_station(), 1)

        snap = m.snapshot()
        self.assertEqual(snap["total"], 3)
        self.assertIn("1077", snap["by_msg_type"])
        self.assertIn("1087", snap["by_msg_type"])
        self.assertAlmostEqual(snap["used_ratio_pct"], 200.0 / 3, places=3)


class TestCorrectionMonitor(unittest.TestCase):
    def test_feed_ubx_and_snapshot(self):
        mon = CorrectionMonitor()
        frame = make_ubx_rxm_rtcm(flags=0x04, ref_station=0, msg_type=1077)
        infos = mon.feed_ubx(frame)
        self.assertEqual(len(infos), 1)
        self.assertEqual(infos[0]["msg_type"], 1077)
        self.assertEqual(infos[0]["msg_used"], 2)

        snap = mon.snapshot()
        json.dumps(snap)  # シリアライズ可能であること
        self.assertEqual(snap["rxm_rtcm"]["total"], 1)
        self.assertEqual(snap["rxm_rtcm"]["used_counts"]["2"], 1)

    def test_feed_rtcm3(self):
        mon = CorrectionMonitor()
        frames = mon.feed_rtcm3(make_rtcm3_frame(1077))
        self.assertEqual(len(frames), 1)
        snap = mon.snapshot()
        self.assertEqual(snap["crc"]["rtcm3_frame"]["total"], 1)
        self.assertEqual(snap["crc"]["rtcm3_frame"]["failed"], 0)

    def test_alert_edge_trigger(self):
        calls = []
        mon = CorrectionMonitor(on_alert=lambda a: calls.append(a))
        mon.snapshot()  # rtk_age_no_data が発火
        self.assertEqual([a["code"] for a in calls], ["rtk_age_no_data"])
        mon.snapshot()  # 既にアクティブ → 再発火しない
        self.assertEqual(len(calls), 1)

    def test_rtk_age_recovers(self):
        mon = CorrectionMonitor(age_alert_threshold=10.0, age_warn_threshold=5.0)
        self.assertTrue(any(a["code"] == "rtk_age_no_data"
                            for a in mon.snapshot()["alerts"]))
        mon.feed_ubx(make_ubx_rxm_rtcm(flags=0x04, msg_type=1077))
        codes = [a["code"] for a in mon.snapshot()["alerts"]]
        self.assertNotIn("rtk_age_no_data", codes)
        self.assertNotIn("rtk_age_stale", codes)


if __name__ == "__main__":
    unittest.main(verbosity=2)


