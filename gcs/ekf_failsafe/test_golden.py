#!/usr/bin/env python3
"""test_golden.py — golden.py のユニットテスト（標準ライブラリのみ・実機不要）。

実行:
    cd <リポジトリルート>
    python3 -m unittest gcs.ekf_failsafe.test_golden -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gcs.ekf_failsafe.golden import (  # noqa: E402
    ALL_PARAM_NAMES,
    GOLDEN_PARAMS,
    LABELS,
    PARAM_TYPES,
    PARAM_GROUPS,
    GROUP_EKF_SOURCES,
    GROUP_FAILSAFE,
    GNSS_MODE_BITS,
    decode_gnss_mode,
    group_of,
    values_equal,
    is_float_param,
    param_value_repr,
    synthetic_guard_result,
)


class TestGoldenIntegrity(unittest.TestCase):
    def test_all_params_have_type_and_label(self):
        for name in GOLDEN_PARAMS:
            self.assertIn(name, PARAM_TYPES, name)
            self.assertIn(name, LABELS, name)

    def test_groups_cover_all_params(self):
        grouped = set()
        for names in PARAM_GROUPS.values():
            grouped.update(names)
        self.assertEqual(grouped, set(GOLDEN_PARAMS.keys()))

    def test_order_matches_groups(self):
        self.assertEqual(ALL_PARAM_NAMES, [n for ns in PARAM_GROUPS.values() for n in ns])

    def test_gps_type_is_dronecan(self):
        self.assertEqual(GOLDEN_PARAMS["GPS_TYPE"], 9)

    def test_ekf_sources_use_gps(self):
        self.assertEqual(GOLDEN_PARAMS["EK3_SRC1_POSXY"], 3)
        self.assertEqual(GOLDEN_PARAMS["EK3_SRC1_POSZ"], 3)
        self.assertEqual(GOLDEN_PARAMS["EK3_SRC1_VELXY"], 3)
        self.assertEqual(GOLDEN_PARAMS["EK3_SRC1_VELZ"], 3)

    def test_glonass_bit_disabled_in_golden(self):
        mode = int(GOLDEN_PARAMS["GPS_GNSS_MODE"])
        self.assertEqual((mode >> 6) & 1, 0, "GLONASS(bit6) は無効であること")


class TestValuesEqual(unittest.TestCase):
    def test_int_equal(self):
        self.assertTrue(values_equal(3, 3, "EK3_SRC1_POSXY"))
        self.assertFalse(values_equal(3, 1, "EK3_SRC1_POSXY"))

    def test_none_is_not_equal(self):
        self.assertFalse(values_equal(3, None, "EK3_SRC1_POSXY"))

    def test_float_within_tolerance(self):
        self.assertTrue(values_equal(0.8, 0.80001, "FS_EKF_THRESH"))
        self.assertFalse(values_equal(0.8, 1.0, "FS_EKF_THRESH"))

    def test_int_rounded_compare(self):
        # PARAM_VALUE は float で返るため丸めて整数比較する
        self.assertTrue(values_equal(140, 140.0, "GPS_HDOP_GOOD"))


class TestGnssMode(unittest.TestCase):
    def test_decode_47(self):
        s = decode_gnss_mode(47)
        self.assertIn("GPS", s)
        self.assertIn("Galileo", s)
        self.assertNotIn("GLONASS", s)

    def test_decode_zero(self):
        self.assertIn("デフォルト", decode_gnss_mode(0))

    def test_decode_none(self):
        self.assertEqual(decode_gnss_mode(None), "n/a")

    def test_bits_mapping(self):
        self.assertEqual(GNSS_MODE_BITS[6], "GLONASS")


class TestHelpers(unittest.TestCase):
    def test_group_of(self):
        self.assertEqual(group_of("EK3_SRC1_POSXY"), GROUP_EKF_SOURCES)
        self.assertEqual(group_of("FS_GCS_ENABLE"), GROUP_FAILSAFE)
        self.assertIsNone(group_of("UNKNOWN"))

    def test_is_float_param(self):
        self.assertTrue(is_float_param("FS_EKF_THRESH"))
        self.assertFalse(is_float_param("GPS_TYPE"))

    def test_param_value_repr(self):
        s = param_value_repr("GPS_GNSS_MODE", 47)
        self.assertNotIn("GLONASS", s)
        self.assertIn("GPS", s)
        self.assertNotIn("0b0b", s)  # bin() の 0b が重複しないこと
        self.assertEqual(param_value_repr("GPS_TYPE", 9), "9")
        self.assertEqual(param_value_repr("FS_EKF_THRESH", 0.8), "0.800")


class TestSyntheticGuardResult(unittest.TestCase):
    def test_pass_all_ok(self):
        r = synthetic_guard_result()
        self.assertEqual(r["status"], "PASS")
        self.assertTrue(all(v["ok"] for v in r["checked"].values()))
        self.assertEqual(set(r["checked"].keys()), set(GOLDEN_PARAMS.keys()))

    def test_mismatch_fail(self):
        r = synthetic_guard_result(mismatches=["FS_GCS_ENABLE"], status="FAIL")
        self.assertEqual(r["status"], "FAIL")
        self.assertFalse(r["checked"]["FS_GCS_ENABLE"]["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
