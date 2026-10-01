#!/usr/bin/env python3
"""test_reader.py — reader.from_pyubx2 の単位換算を検証するテスト

pyubx2 で NAV-RELPOSNED フレームを実際にパースし、reader.py が正しく
cm→m / 0.1mm→m へ換算できていることを検証する（実ハードウェア不要）。

実行:
    cd ~/EVK-F9P
    python3 -m unittest gcs.relpos.test_reader -v
"""

from __future__ import annotations

import io
import struct
import sys
import unittest
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent.parent
for _p in (_SCRIPT_DIR, _REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from gcs.relpos.reader import from_pyubx2  # noqa: E402

try:
    from pyubx2 import UBXReader  # noqa: E402
    HAS_PYUBX2 = True
except ImportError:
    HAS_PYUBX2 = False


def _make_relposned_frame(rel_pos=(100, -250, -30), heading_raw=90000000,
                          acc=(50, 60, 70), ref_station=1234, itow=500000,
                          flags=0x0006) -> bytes:
    """NAV-RELPOSNED（version 0x01）フレームを生成する。"""
    payload = struct.pack("<BBHI", 0x01, 0x00, ref_station, itow)
    payload += struct.pack("<iiii", rel_pos[0], rel_pos[1], rel_pos[2],
                           int((rel_pos[0] ** 2 + rel_pos[1] ** 2 +
                                rel_pos[2] ** 2) ** 0.5))
    payload += struct.pack("<i", heading_raw)
    payload += struct.pack("<I", 0)              # reserved1
    payload += struct.pack("<bbbb", 0, 0, 0, 0)  # high precision
    payload += struct.pack("<IIIII", acc[0], acc[1], acc[2], 0, 0)
    payload += struct.pack("<I", 0)              # reserved2
    payload += struct.pack("<I", flags)
    cls, mid = 0x01, 0x3C
    length = len(payload)
    header = bytes((cls, mid, length & 0xFF, (length >> 8) & 0xFF))
    ck_a = ck_b = 0
    for b in header + payload:
        ck_a = (ck_a + b) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return b"\xb5\x62" + header + payload + bytes((ck_a, ck_b))


@unittest.skipUnless(HAS_PYUBX2, "pyubx2 がインストールされていないためスキップ")
class TestFromPyubx2(unittest.TestCase):
    def test_unit_conversion(self):
        parsed = UBXReader(io.BytesIO(_make_relposned_frame())).read()[1]
        s = from_pyubx2(parsed, "A")
        self.assertEqual(s.rover_id, "A")
        self.assertEqual(s.itow_ms, 500000)
        self.assertEqual(s.ref_station_id, 1234)
        # cm → m
        self.assertAlmostEqual(s.rel_n_m, 1.00, places=4)
        self.assertAlmostEqual(s.rel_e_m, -2.50, places=4)
        self.assertAlmostEqual(s.rel_d_m, -0.30, places=4)
        # 1e-5 deg → deg
        self.assertAlmostEqual(s.rel_heading_deg, 900.0, places=6)
        # 0.1mm → m
        self.assertAlmostEqual(s.acc_n_m, 0.005, places=9)
        self.assertAlmostEqual(s.acc_e_m, 0.006, places=9)
        self.assertAlmostEqual(s.acc_d_m, 0.007, places=9)

    def test_flags(self):
        parsed = UBXReader(io.BytesIO(_make_relposned_frame(flags=0x0006))).read()[1]
        s = from_pyubx2(parsed, "A")
        self.assertTrue(s.flags["rel_pos_valid"])
        self.assertTrue(s.flags["diff_soln"])
        self.assertFalse(s.flags["gnss_fix_ok"])
        self.assertTrue(s.rel_pos_valid)

    def test_heading_valid_flag(self):
        # flags bit8 = relPosHeadingValid
        parsed = UBXReader(io.BytesIO(_make_relposned_frame(flags=0x0100))).read()[1]
        s = from_pyubx2(parsed, "A")
        self.assertTrue(s.flags["rel_pos_heading_valid"])
        self.assertTrue(s.heading_valid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
